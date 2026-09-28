from __future__ import annotations

import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Lock, Thread

from .artifact_service import ArtifactService
from .errors import LocalApiConflictError, LocalApiNotFoundError
from .job_models import JobRecord, JobRuntimeState, utc_now
from .workspace_manager import WorkspaceManager

_logger = logging.getLogger(__name__)


class LocalApiStageTimeoutError(LocalApiConflictError):
    """Raised when a pipeline stage exceeds the P0.2 execution watchdog."""

    status_code = 500
    error_code = "STAGE_TIMEOUT"

# P0.2 (Phase 6 roadmap): per-stage execution watchdog. A stage that exceeds
# this budget fails the job instead of hanging the worker thread forever.
# Override with PULSE_LOCAL_API_STAGE_TIMEOUT_SECONDS (<= 0 disables).
def _default_stage_timeout_seconds() -> float:
    try:
        value = float(os.getenv("PULSE_LOCAL_API_STAGE_TIMEOUT_SECONDS", "1800"))
    except ValueError:
        return 1800.0
    return value

# P0.2: rough address-space guard for stage execution. Python cannot hard-stop
# a thread, but a worker-side soft limit keeps runaway allocations from taking
# the whole process down on platforms that support resource limits.
_STAGE_MAX_ADDRESS_SPACE_BYTES = 6 * 1024 * 1024 * 1024  # 6 GiB


class JobManager:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        artifact_service: ArtifactService,
        pipeline_runner,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.artifact_service = artifact_service
        self.pipeline_runner = pipeline_runner
        self._jobs: dict[str, JobRecord] = {}
        self._active_by_workspace: dict[str, str] = {}
        self._lock = Lock()

    def create_job(self, workspace_id: str):
        with self._lock:
            active_job_id = self._active_by_workspace.get(workspace_id)
            if active_job_id is not None:
                active_record = self._jobs.get(active_job_id)
                if active_record and active_record.state.status in {"queued", "running"}:
                    raise LocalApiConflictError(
                        f"Workspace {workspace_id} already has an active generation job."
                    )

            job_id = str(uuid.uuid4())
            state = JobRuntimeState(job_id=job_id, workspace_id=workspace_id)
            state.append_event("info", "Job queued.")
            record = JobRecord(state=state)
            self._jobs[job_id] = record
            self._active_by_workspace[workspace_id] = job_id
            manifest = self.workspace_manager.load_manifest(workspace_id)
            manifest = manifest.model_copy(update={"job_status": "queued"}, deep=True)
            self.workspace_manager.save_manifest(manifest)

        thread = Thread(
            target=self._run_job,
            args=(job_id, workspace_id),
            daemon=True,
            name=f"generator-job-{job_id}",
        )
        record.thread = thread
        thread.start()
        return state.to_response()

    def reconcile_orphaned_running_jobs(self, workspace_ids: list[str]) -> list[str]:
        """Mark workspaces whose manifests claim a live job but have none.

        P0.2 (Phase 6 roadmap): job records live in memory only, so after an
        API restart any manifest still flagged ``queued``/``running`` is a
        zombie. This flips those manifests to ``failed`` with an explanatory
        event so cleanup tooling can remove them again.
        Returns the list of reconciled workspace IDs.
        """
        if not workspace_ids:
            return []
        with self._lock:
            live_workspace_ids = {
                workspace_id
                for workspace_id, job_id in self._active_by_workspace.items()
                if (record := self._jobs.get(job_id)) is not None
                and record.state.status in {"queued", "running"}
            }
        reconciled: list[str] = []
        for workspace_id in workspace_ids:
            if workspace_id in live_workspace_ids:
                continue
            try:
                manifest = self.workspace_manager.load_manifest(workspace_id)
            except Exception:
                continue
            if manifest.job_status not in {"queued", "running"}:
                continue
            reconciled_manifest = manifest.model_copy(
                update={"job_status": "failed"},
                deep=True,
            )
            try:
                self.workspace_manager.save_manifest(reconciled_manifest)
            except Exception:
                continue
            reconciled.append(workspace_id)
            _logger.warning(
                "Reconciled orphaned running workspace %s to failed after restart.",
                workspace_id,
            )
        return reconciled

    def get_job(self, job_id: str):
        return self._get_record(job_id).state.to_response()

    def set_total_stages(self, job_id: str, total_stages: int) -> None:
        self._mutate(job_id, lambda state: setattr(state, "total_stages", total_stages))

    def begin_stage(
        self,
        job_id: str,
        *,
        stage_number: int,
        stage_code: str,
        stage_label: str,
        difficulty: str | None,
    ) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.status = "running"
            state.current_stage = stage_code
            state.current_stage_label = stage_label
            state.current_difficulty = difficulty
            state.current_candidate = None
            state.candidates_completed = None
            state.candidates_total = None
            state.latest_message = stage_label
            state.overall_progress_percent = self._progress_percent(
                state.completed_stages,
                state.total_stages,
            )
            state.append_event("info", stage_label)

        self._mutate(job_id, mutate)
        manifest = self.workspace_manager.load_manifest(self._get_record(job_id).state.workspace_id)
        manifest = manifest.model_copy(update={"job_status": "running"}, deep=True)
        self.workspace_manager.save_manifest(manifest)

    def complete_stage(self, job_id: str, stage_label: str) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.completed_stages += 1
            state.latest_message = f"{stage_label} complete."
            state.overall_progress_percent = self._progress_percent(
                state.completed_stages,
                state.total_stages,
            )
            state.candidates_completed = None
            state.candidates_total = None
            state.current_candidate = None
            state.append_event("info", f"{stage_label} complete.")

        self._mutate(job_id, mutate)

    def update_candidate_progress(
        self,
        job_id: str,
        *,
        difficulty: str,
        current_candidate: int,
        candidates_completed: int,
        candidates_total: int,
        message: str,
    ) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.current_difficulty = difficulty
            state.current_candidate = current_candidate
            state.candidates_completed = candidates_completed
            state.candidates_total = candidates_total
            state.latest_message = message
            state.updated_at = utc_now()

        self._mutate(job_id, mutate)

    def log(self, job_id: str, level: str, message: str) -> None:
        def mutate(state: JobRuntimeState) -> None:
            if level == "warning":
                state.warnings.append(message)
            elif level == "error":
                state.errors.append(message)
            state.latest_message = message
            state.append_event(level, message)

        self._mutate(job_id, mutate)

    def request_cancel(self, job_id: str):
        def mutate(state: JobRuntimeState) -> None:
            state.cancel_requested = True
            state.latest_message = "Cancellation requested. Waiting for the current stage to finish."
            state.append_event("warning", state.latest_message)

        self._mutate(job_id, mutate)
        return self.get_job(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        return self._get_record(job_id).state.cancel_requested

    def complete(self, job_id: str, *, artifact_ids: list[str], result) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.status = "completed"
            state.latest_message = "Generation complete."
            state.artifact_ids = artifact_ids
            state.result = result
            state.current_stage = None
            state.current_stage_label = None
            state.finished_at = utc_now()
            state.overall_progress_percent = 100
            state.append_event("info", "Generation complete.")

        self._mutate(job_id, mutate)
        workspace_id = self._get_record(job_id).state.workspace_id
        with self._lock:
            self._active_by_workspace.pop(workspace_id, None)

    def fail(
        self,
        job_id: str,
        message: str,
        *,
        technical_details: str,
        artifact_ids: list[str],
    ) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.status = "failed"
            state.latest_message = message
            state.errors.append(message)
            state.technical_details = technical_details
            state.artifact_ids = artifact_ids
            state.finished_at = utc_now()
            state.append_event("error", message)

        self._mutate(job_id, mutate)
        workspace_id = self._get_record(job_id).state.workspace_id
        with self._lock:
            self._active_by_workspace.pop(workspace_id, None)

    def cancel(self, job_id: str, *, artifact_ids: list[str]) -> None:
        def mutate(state: JobRuntimeState) -> None:
            state.status = "cancelled"
            state.latest_message = "Generation cancelled."
            state.artifact_ids = artifact_ids
            state.current_stage = None
            state.current_stage_label = None
            state.finished_at = utc_now()
            state.append_event("warning", "Generation cancelled.")

        self._mutate(job_id, mutate)
        workspace_id = self._get_record(job_id).state.workspace_id
        with self._lock:
            self._active_by_workspace.pop(workspace_id, None)

    def stream_events(self, job_id: str):
        record = self._get_record(job_id)
        last_emitted_index = 0
        # Emit the initial state (all events so far)
        initial = record.state.to_response()
        yield self._format_sse_payload(initial)
        if initial.events:
            last_emitted_index = initial.events[-1].index
        if initial.status in {"completed", "failed", "cancelled"}:
            return
        while True:
            with record.condition:
                record.condition.wait(timeout=1.0)
                full_response = record.state.to_response()
            # Only emit events newer than the last one we sent
            new_events = [
                evt for evt in full_response.events
                if evt.index > last_emitted_index
            ]
            if new_events:
                last_emitted_index = new_events[-1].index
                # Build a slimmed-down payload with only new events
                payload = full_response.model_copy(
                    update={"events": new_events},
                    deep=False,
                )
                yield self._format_sse_payload(payload)
            elif full_response.status != record.state.status:
                # Status changed but no new events — emit status-only update
                yield self._format_sse_payload(full_response)
            if full_response.status in {"completed", "failed", "cancelled"}:
                break

    def _run_job(self, job_id: str, workspace_id: str) -> None:
        self.pipeline_runner.run_job(self, job_id, workspace_id)

    def run_stage_with_watchdog(self, job_id: str, label: str, action) -> None:
        """Run one pipeline stage under the P0.2 execution watchdog.

        The stage action executes in a worker thread pool with a wall-clock
        budget (``PULSE_LOCAL_API_STAGE_TIMEOUT_SECONDS``, default 1800 s).
        On expiry the job is failed with a readable event; the underlying
        thread cannot be hard-killed (CPython limitation) but the job record
        and workspace status are released instead of hanging forever.
        """
        timeout_seconds = _default_stage_timeout_seconds()
        if timeout_seconds <= 0:
            action()
            return
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"stage-watchdog-{job_id}",
        )
        try:
            future = executor.submit(self._run_stage_with_memory_guard, action)
            future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            _logger.error(
                "Stage %r exceeded the %.0f s watchdog budget (job %s).",
                label,
                timeout_seconds,
                job_id,
            )
            raise LocalApiStageTimeoutError(
                f"Stage '{label}' exceeded the {timeout_seconds:.0f} s execution watchdog."
            )
        finally:
            # Do not wait for a hung worker; shutdown lets finished workers
            # exit and leaks at most one idle thread per timeout event.
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _run_stage_with_memory_guard(action) -> None:
        """Apply a best-effort address-space guard around stage execution.

        Hard RLIMIT_AS enforcement is unavailable on Windows (and interferes
        with some native decoders), so the guard is a soft boundary: when
        ``resource`` is available the limit applies, otherwise the stage runs
        unguarded. This bounds runaway allocations on POSIX platforms while
        keeping cross-platform behavior unchanged.
        """
        try:
            import resource  # noqa: F401  (POSIX only)
        except ImportError:
            action()
            return
        limit_bytes = _STAGE_MAX_ADDRESS_SPACE_BYTES
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            target = min(limit_bytes, hard) if hard != resource.RLIM_INFINITY else limit_bytes
            if soft == resource.RLIM_INFINITY or soft > target:
                resource.setrlimit(resource.RLIMIT_AS, (target, hard))
        except (OSError, ValueError):
            pass
        action()

    def _get_record(self, job_id: str) -> JobRecord:
        record = self._jobs.get(job_id)
        if record is None:
            raise LocalApiNotFoundError("Job was not found.")
        return record

    def _mutate(self, job_id: str, operation) -> None:
        record = self._get_record(job_id)
        with record.condition:
            operation(record.state)
            record.state.updated_at = utc_now()
            record.condition.notify_all()

    def _progress_percent(self, completed_stages: int, total_stages: int) -> int:
        if total_stages <= 0:
            return 0
        return int(round((completed_stages / total_stages) * 100))

    def _format_sse_payload(self, response) -> str:
        payload = response.model_dump_json(by_alias=True, exclude_none=True)
        return f"data: {payload}\n\n"
