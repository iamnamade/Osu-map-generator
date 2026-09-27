from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Condition, Thread

from .models import JobEvent, JobResultSummary, JobStateResponse


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
        self.updated_at = utc_now()

    def to_response(self, *, include_events: bool = True) -> JobStateResponse:
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
            events=self.events if include_events else [],
            result=self.result,
        )


@dataclass
class JobRecord:
    state: JobRuntimeState
    condition: Condition = field(default_factory=Condition)
    thread: Thread | None = None
