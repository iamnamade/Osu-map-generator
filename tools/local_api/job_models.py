from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Condition, Thread

from .models import JobEvent, JobResultSummary, JobStateResponse, StageTiming

# P3.4 (Phase 6 roadmap): job events live in a bounded ring buffer. A long
# generation emits a log line per stage/candidate/warning; without a cap the
# in-memory list (and every SSE payload derived from it) grows without bound
# for the lifetime of the process. The newest 200 events are kept; older
# entries are dropped and remain unretrievable (``index`` stays monotonic so
# ``?since=`` tailing keeps working across trims).
MAX_JOB_EVENTS = 200


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobRuntimeState:
    job_id: str
    workspace_id: str
    status: str = "queued"
    current_stage: str | None = None
    current_stage_label: str | None = None
    completed_stages: int = 0
    total_stages: int = 0
    overall_progress_percent: int = 0
    current_difficulty: str | None = None
    current_candidate: int | None = None
    candidates_completed: int | None = None
    candidates_total: int | None = None
    latest_message: str = "Job queued."
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    technical_details: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    events: list[JobEvent] = field(default_factory=list)
    stage_timings: list[StageTiming] = field(default_factory=list)
    cancel_requested: bool = False
    result: JobResultSummary | None = None
    next_event_index: int = 1

    def append_event(self, level: str, message: str) -> None:
        self.events.append(
            JobEvent(
                index=self.next_event_index,
                timestamp=utc_now(),
                level=level,
                message=message,
            )
        )
        self.next_event_index += 1
        overflow = len(self.events) - MAX_JOB_EVENTS
        if overflow > 0:
            del self.events[:overflow]
        self.updated_at = utc_now()

    def events_since(self, since: int) -> list[JobEvent]:
        """P3.4: tailing view — only events with ``index > since``.

        ``index`` is monotonic even after ring-buffer trims, so a client can
        poll with the highest index it has already seen and receive only new
        events, regardless of how many old ones were evicted.
        """
        if since <= 0:
            return list(self.events)
        return [event for event in self.events if event.index > since]

    def to_response(
        self,
        *,
        include_events: bool = True,
        since: int = 0,
    ) -> JobStateResponse:
        return JobStateResponse(
            jobId=self.job_id,
            workspaceId=self.workspace_id,
            status=self.status,
            currentStage=self.current_stage,
            currentStageLabel=self.current_stage_label,
            completedStages=self.completed_stages,
            totalStages=self.total_stages,
            overallProgressPercent=self.overall_progress_percent,
            currentDifficulty=self.current_difficulty,
            currentCandidate=self.current_candidate,
            candidatesCompleted=self.candidates_completed,
            candidatesTotal=self.candidates_total,
            latestMessage=self.latest_message,
            warnings=self.warnings,
            errors=self.errors,
            artifactIds=self.artifact_ids,
            technicalDetails=self.technical_details,
            startedAt=self.started_at,
            updatedAt=self.updated_at,
            finishedAt=self.finished_at,
            events=(self.events_since(since) if include_events else []),
            stageTimings=self.stage_timings,
            result=self.result,
        )


@dataclass
class JobRecord:
    state: JobRuntimeState
    condition: Condition = field(default_factory=Condition)
    thread: Thread | None = None
