from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..config import DifficultyPreset
from ..models import AudioAnalysis

CorrectionActionType = Literal[
    "move_object",
    "adjust_time",
    "remove_object",
    "insert_object",
]
ProcessingStage = Literal[
    "structural_safety",
    "timing_corrections",
    "movement_corrections",
    "stacking_corrections",
    "density_corrections",
    "repetition_corrections",
    "difficulty_corrections",
    "local_optimization",
]
ExpectedCategory = Literal[
    "structural",
    "timing",
    "rhythm",
    "movement",
    "readability",
    "spatialBalance",
    "repetition",
    "densityConsistency",
    "difficultyConsistency",
]

STAGE_ORDER: tuple[ProcessingStage, ...] = (
    "structural_safety",
    "timing_corrections",
    "movement_corrections",
    "stacking_corrections",
    "density_corrections",
    "repetition_corrections",
    "difficulty_corrections",
    "local_optimization",
)


def _rounded(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _to_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, float):
            snapshot[key] = round(item, 4)
        else:
            snapshot[key] = item
    return snapshot


@dataclass(frozen=True)
class CorrectionAction:
    action_id: str
    stage: ProcessingStage
    action_type: CorrectionActionType
    reason_code: str
    object_ids: list[int]
    before: dict[str, Any]
    after: dict[str, Any]
    confidence: float
    expected_categories: list[ExpectedCategory]
    expected_score_impact: float
    actual_score_impact: float = 0.0
    accepted: bool = False
    rejection_reason: str | None = None

    def with_result(
        self,
        *,
        accepted: bool,
        actual_score_impact: float,
        rejection_reason: str | None = None,
    ) -> "CorrectionAction":
        return CorrectionAction(
            action_id=self.action_id,
            stage=self.stage,
            action_type=self.action_type,
            reason_code=self.reason_code,
            object_ids=self.object_ids,
            before=self.before,
            after=self.after,
            confidence=self.confidence,
            expected_categories=self.expected_categories,
            expected_score_impact=self.expected_score_impact,
            actual_score_impact=actual_score_impact,
            accepted=accepted,
            rejection_reason=rejection_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "stage": self.stage,
            "actionType": self.action_type,
            "reasonCode": self.reason_code,
            "objectIds": self.object_ids,
            "before": _to_snapshot(self.before),
            "after": _to_snapshot(self.after),
            "confidence": _rounded(self.confidence),
            "expectedCategories": self.expected_categories,
            "expectedScoreImpact": _rounded(self.expected_score_impact),
            "actualScoreImpact": _rounded(self.actual_score_impact),
            "accepted": self.accepted,
        }
        if self.rejection_reason:
            payload["rejectionReason"] = self.rejection_reason
        return payload


@dataclass(frozen=True)
class ScoreSnapshot:
    overall_score: float
    playable: bool
    critical: int
    errors: int
    warnings: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "overallScore": _rounded(self.overall_score, 3),
            "playable": self.playable,
            "critical": self.critical,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ScoreChanges:
    overall: float
    structural: float
    timing: float
    rhythm: float
    movement: float
    readability: float
    spatial_balance: float
    repetition: float
    density_consistency: float
    difficulty_consistency: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": _rounded(self.overall, 3),
            "structural": _rounded(self.structural, 3),
            "timing": _rounded(self.timing, 3),
            "rhythm": _rounded(self.rhythm, 3),
            "movement": _rounded(self.movement, 3),
            "readability": _rounded(self.readability, 3),
            "spatialBalance": _rounded(self.spatial_balance, 3),
            "repetition": _rounded(self.repetition, 3),
            "densityConsistency": _rounded(self.density_consistency, 3),
            "difficultyConsistency": _rounded(self.difficulty_consistency, 3),
        }


@dataclass(frozen=True)
class CorrectionSummary:
    planned_actions: int
    accepted_actions: int
    reverted_actions: int
    moved_objects: int
    timing_adjustments: int
    removed_objects: int
    inserted_objects: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plannedActions": self.planned_actions,
            "acceptedActions": self.accepted_actions,
            "revertedActions": self.reverted_actions,
            "movedObjects": self.moved_objects,
            "timingAdjustments": self.timing_adjustments,
            "removedObjects": self.removed_objects,
            "insertedObjects": self.inserted_objects,
        }


@dataclass(frozen=True)
class CorrectionReport:
    version: int
    source_map: str
    output_map: str
    difficulty: str
    seed: int
    accepted: bool
    before: ScoreSnapshot
    after: ScoreSnapshot
    score_changes: ScoreChanges
    summary: CorrectionSummary
    actions: list[CorrectionAction]
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "sourceMap": self.source_map,
            "outputMap": self.output_map,
            "difficulty": self.difficulty,
            "seed": self.seed,
            "accepted": self.accepted,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "scoreChanges": self.score_changes.to_dict(),
            "summary": self.summary.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
        }
        if self.rejection_reason:
            payload["rejectionReason"] = self.rejection_reason
        return payload


@dataclass(frozen=True)
class PlannedIssue:
    stage: ProcessingStage
    priority: float
    confidence: float
    code: str
    severity: str
    category: str
    object_ids: list[int]
    start_time_ms: int | None = None
    end_time_ms: int | None = None
    measured_value: float | None = None
    allowed_value: float | None = None


@dataclass(frozen=True)
class CorrectionPlan:
    issues_by_stage: dict[ProcessingStage, list[PlannedIssue]]


@dataclass(frozen=True)
class ActionEvaluation:
    action: CorrectionAction
    accepted: bool
    rejection_reason: str | None
    target_category_delta: float
    overall_delta: float
    issue_count_delta: int
    candidate_map: dict[str, Any]
    report: Any


@dataclass(frozen=True)
class PostprocessLimits:
    max_candidates_per_object: int = 12
    max_total_corrected_objects_ratio: float = 0.25
    max_timing_adjusted_ratio: float = 0.15
    max_removed_ratio: float = 0.08
    max_inserted_ratio: float = 0.08
    max_correction_passes: int = 3
    min_target_category_gain: float = 0.3
    min_confidence: float = 0.62
    overall_score_tolerance: float = 0.2
    required_overall_gain: float = 0.1
    max_timing_adjustment_ms_by_difficulty: dict[str, int] = field(
        default_factory=lambda: {
            "easy": 70,
            "normal": 55,
            "hard": 40,
        }
    )

    def max_total_corrected_objects(self, object_count: int) -> int:
        return max(1, int(round(object_count * self.max_total_corrected_objects_ratio)))

    def max_timing_adjusted_objects(self, object_count: int) -> int:
        return max(1, int(round(object_count * self.max_timing_adjusted_ratio)))

    def max_removed_objects(self, object_count: int) -> int:
        return max(1, int(round(object_count * self.max_removed_ratio)))

    def max_inserted_objects(self, object_count: int) -> int:
        return max(1, int(round(object_count * self.max_inserted_ratio)))


@dataclass(frozen=True)
class PostprocessContext:
    source_map_path: Path
    analysis_path: Path
    original_report_path: Path
    output_map_path: Path
    output_report_path: Path
    changes_output_path: Path
    difficulty: str
    preset: DifficultyPreset
    seed: int
    source_map_label: str
    output_map_label: str
    analysis: AudioAnalysis
    limits: PostprocessLimits
