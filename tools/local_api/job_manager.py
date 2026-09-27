from __future__ import annotations

import json
import uuid
from threading import Lock, Thread

from .artifact_service import ArtifactService
from .errors import LocalApiConflictError, LocalApiNotFoundError
from .job_models import JobRecord, JobRuntimeState, utc_now
from .workspace_manager import WorkspaceManager


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
