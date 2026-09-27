from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class SectionBoundary:
    raw_time_ms: int
    final_time_ms: int
    confidence: float
    reason: str
    supporting_feature_changes: dict[str, float]
    snapped: bool
    snapped_to: str | None = None
    snap_distance_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rawTimeMs": self.raw_time_ms,
            "finalTimeMs": self.final_time_ms,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "supportingFeatureChanges": {
                key: round(value, 4)
                for key, value in sorted(self.supporting_feature_changes.items())
            },
            "snapped": self.snapped,
        }
        if self.snapped_to:
            payload["snappedTo"] = self.snapped_to
        if self.snap_distance_ms is not None:
            payload["snapDistanceMs"] = self.snap_distance_ms
        return payload


@dataclass(frozen=True)
class SongSection:
    id: int
    start_ms: int
    end_ms: int
    duration_ms: int
    label: str
    confidence: float
    average_energy: float
    energy_trend: str
    beat_density: float
    onset_density: float
    rhythm_complexity: float
    repetition_group: int | None
    energy_class: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "durationMs": self.duration_ms,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "averageEnergy": round(self.average_energy, 4),
            "energyTrend": self.energy_trend,
            "beatDensity": round(self.beat_density, 4),
            "onsetDensity": round(self.onset_density, 4),
            "rhythmComplexity": round(self.rhythm_complexity, 4),
            "repetitionGroup": self.repetition_group,
            "energyClass": self.energy_class,
        }
        return payload


@dataclass(frozen=True)
class SectionAnalysis:
    version: int
    audio_path: str
    duration_ms: int
    configuration: dict[str, Any]
    sections: list[SongSection]
    boundaries: list[SectionBoundary]
    summary: dict[str, Any]
    input_signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "audio": {
                "path": self.audio_path,
                "durationMs": self.duration_ms,
            },
            "configuration": self.configuration,
            "inputSignature": self.input_signature,
            "sections": [section.to_dict() for section in self.sections],
            "boundaries": [boundary.to_dict() for boundary in self.boundaries],
            "summary": self.summary,
        }


@dataclass(frozen=True)
class SectionIssue:
    code: str
    severity: str
    message: str
    measured_value: float | None = None
    allowed_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.measured_value is not None:
            payload["measuredValue"] = round(self.measured_value, 4)
        if self.allowed_value is not None:
            payload["allowedValue"] = round(self.allowed_value, 4)
        return payload


@dataclass(frozen=True)
class SectionState:
    object_id: int | None
    time_ms: int | None
    x: float | None
    y: float | None
    direction_deg: float | None
    cursor_speed_pps: float | None
    gap_ms: int | None
    density: float | None
    region: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "timeMs": self.time_ms,
            "x": _round(self.x),
            "y": _round(self.y),
            "directionDeg": _round(self.direction_deg),
            "cursorSpeedPps": _round(self.cursor_speed_pps),
            "gapMs": self.gap_ms,
            "density": _round(self.density),
            "region": self.region,
        }


@dataclass(frozen=True)
class SectionScores:
    structural: float
    timing: float
    rhythm: float
    movement: float
    readability: float
    spatial_balance: float
    repetition: float
    density_consistency: float
    difficulty_consistency: float
    transition_readiness: float
    overall: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "structural": round(self.structural, 3),
            "timing": round(self.timing, 3),
            "rhythm": round(self.rhythm, 3),
            "movement": round(self.movement, 3),
            "readability": round(self.readability, 3),
            "spatialBalance": round(self.spatial_balance, 3),
            "repetition": round(self.repetition, 3),
            "densityConsistency": round(self.density_consistency, 3),
            "difficultyConsistency": round(self.difficulty_consistency, 3),
            "transitionReadiness": round(self.transition_readiness, 3),
            "overall": round(self.overall, 3),
        }


@dataclass(frozen=True)
class SectionMetrics:
    object_count: int
    objects_per_second: float
    average_object_gap_ms: float
    minimum_object_gap_ms: int
    maximum_object_gap_ms: int
    average_jump_distance: float
    maximum_jump_distance: float
    average_cursor_speed: float
    maximum_cursor_speed: float
    timing_confidence: float
    beat_alignment: float
    onset_alignment: float
    spatial_coverage: float
    center_usage: float
    edge_usage: float
    repetition_count: int
    stacking_count: int
    warning_count: int
    error_count: int
    local_difficulty_behavior: str
    energy_to_density_ratio: float
    entry_direction_deg: float | None
    exit_direction_deg: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectCount": self.object_count,
            "objectsPerSecond": round(self.objects_per_second, 4),
            "averageObjectGapMs": round(self.average_object_gap_ms, 4),
            "minimumObjectGapMs": self.minimum_object_gap_ms,
            "maximumObjectGapMs": self.maximum_object_gap_ms,
            "averageJumpDistance": round(self.average_jump_distance, 4),
            "maximumJumpDistance": round(self.maximum_jump_distance, 4),
            "averageCursorSpeed": round(self.average_cursor_speed, 4),
            "maximumCursorSpeed": round(self.maximum_cursor_speed, 4),
            "timingConfidence": round(self.timing_confidence, 4),
            "beatAlignment": round(self.beat_alignment, 4),
            "onsetAlignment": round(self.onset_alignment, 4),
            "spatialCoverage": round(self.spatial_coverage, 4),
            "centerUsage": round(self.center_usage, 4),
            "edgeUsage": round(self.edge_usage, 4),
            "repetitionCount": self.repetition_count,
            "stackingCount": self.stacking_count,
            "warningCount": self.warning_count,
            "errorCount": self.error_count,
            "localDifficultyBehavior": self.local_difficulty_behavior,
            "energyToDensityRatio": round(self.energy_to_density_ratio, 4),
            "entryDirectionDeg": _round(self.entry_direction_deg),
            "exitDirectionDeg": _round(self.exit_direction_deg),
        }


@dataclass(frozen=True)
class CandidateSectionEvaluation:
    section_id: int
    start_ms: int
    end_ms: int
    label: str
    source_candidate: int
    scores: SectionScores
    metrics: SectionMetrics
    issues: list[SectionIssue]
    entry_state: SectionState
    exit_state: SectionState

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "label": self.label,
            "sourceCandidate": self.source_candidate,
            "scores": self.scores.to_dict(),
            "metrics": self.metrics.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "entryState": self.entry_state.to_dict(),
            "exitState": self.exit_state.to_dict(),
        }


@dataclass(frozen=True)
class CandidateSectionReport:
    version: int
    candidate_index: int
    difficulty: str
    input_signature: str
    status: dict[str, Any]
    summary: dict[str, Any]
    sections: list[CandidateSectionEvaluation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "candidateIndex": self.candidate_index,
            "difficulty": self.difficulty,
            "inputSignature": self.input_signature,
            "status": self.status,
            "summary": self.summary,
            "sections": [section.to_dict() for section in self.sections],
        }


@dataclass(frozen=True)
class HybridSectionSelection:
    section_id: int
    start_ms: int
    end_ms: int
    label: str
    source_candidate: int
    section_score: float
    selection_reason: str
    lock_state: str = "unlocked"
    transition_status_before: str | None = None
    transition_status_after: str | None = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "label": self.label,
            "sourceCandidate": self.source_candidate,
            "sectionScore": round(self.section_score, 3),
            "selectionReason": self.selection_reason,
            "lockState": self.lock_state,
            "transitionStatusBefore": self.transition_status_before,
            "transitionStatusAfter": self.transition_status_after,
            "issues": self.issues,
        }


@dataclass(frozen=True)
class HybridTransition:
    boundary_index: int
    from_section_id: int
    to_section_id: int
    from_candidate: int
    to_candidate: int
    classification: str
    score: float
    metrics: dict[str, float | int | str | bool | None]
    issues: list[str]
    corrections: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for key, value in sorted(self.metrics.items()):
            if isinstance(value, float):
                metrics[key] = round(value, 4)
            else:
                metrics[key] = value
        return {
            "boundaryIndex": self.boundary_index,
            "fromSectionId": self.from_section_id,
            "toSectionId": self.to_section_id,
            "fromCandidate": self.from_candidate,
            "toCandidate": self.to_candidate,
            "classification": self.classification,
            "score": round(self.score, 3),
            "metrics": metrics,
            "issues": self.issues,
            "corrections": self.corrections,
        }


@dataclass(frozen=True)
class HybridScores:
    section_quality: float
    transition_quality: float
    style_consistency: float
    final_python_quality: float
    overall_hybrid_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionQuality": round(self.section_quality, 3),
            "transitionQuality": round(self.transition_quality, 3),
            "styleConsistency": round(self.style_consistency, 3),
            "finalPythonQuality": round(self.final_python_quality, 3),
            "overallHybridScore": round(self.overall_hybrid_score, 3),
        }


@dataclass(frozen=True)
class HybridPromotionStatus:
    promoted: bool
    reason: str
    champion_quality: float | None
    hybrid_python_quality: float
    hybrid_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "promoted": self.promoted,
            "reason": self.reason,
            "championQuality": _round(self.champion_quality),
            "hybridPythonQuality": round(self.hybrid_python_quality, 3),
            "hybridScore": round(self.hybrid_score, 3),
        }


@dataclass(frozen=True)
class HybridAssemblyReport:
    version: int
    difficulty: str
    input_signature: str
    sections: list[HybridSectionSelection]
    transitions: list[HybridTransition]
    scores: HybridScores
    source_usage: dict[str, int]
    corrections: dict[str, int]
    valid: bool
    playable: bool
    promotion: HybridPromotionStatus
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "difficulty": self.difficulty,
            "inputSignature": self.input_signature,
            "sections": [section.to_dict() for section in self.sections],
            "transitions": [transition.to_dict() for transition in self.transitions],
            "scores": self.scores.to_dict(),
            "sourceUsage": self.source_usage,
            "corrections": self.corrections,
            "valid": self.valid,
            "playable": self.playable,
            "promotion": self.promotion.to_dict(),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class MapObject:
    id: int
    x: int
    y: int
    time: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "circle",
            "x": self.x,
            "y": self.y,
            "time": self.time,
        }
