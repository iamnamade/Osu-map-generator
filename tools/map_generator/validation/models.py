from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["info", "warning", "error", "critical"]
IssueCategory = Literal[
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
EstimatedBehavior = Literal[
    "easier-than-target",
    "within-target",
    "harder-than-target",
    "inconsistent",
]
AnchorType = Literal["beat", "onset", "none"]

SEVERITY_ORDER: dict[Severity, int] = {
    "critical": 3,
    "error": 2,
    "warning": 1,
    "info": 0,
}


def _rounded(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class ParsedBeatmapObject:
    id: int
    type: str
    time: int
    x: float | None = None
    y: float | None = None
    end_time: int | None = None
    path_type: str | None = None
    control_points: list[dict[str, float]] = field(default_factory=list)
    repeats: int | None = None
    pixel_length: float | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "time": self.time,
        }

        if self.x is not None:
            payload["x"] = round(self.x, 3)
        if self.y is not None:
            payload["y"] = round(self.y, 3)
        if self.end_time is not None:
            payload["endTime"] = self.end_time
        if self.path_type is not None:
            payload["pathType"] = self.path_type
        if self.control_points:
            payload["controlPoints"] = [
                {"x": round(point["x"], 3), "y": round(point["y"], 3)}
                for point in self.control_points
            ]
        if self.repeats is not None:
            payload["repeats"] = self.repeats
        if self.pixel_length is not None:
            payload["pixelLength"] = round(self.pixel_length, 3)

        payload.update(self.extra_fields)
        return payload


@dataclass(frozen=True)
class ParsedBeatmap:
    path: str
    title: str
    artist: str
    audio: str
    approach_time: float
    circle_radius: float
    objects: list[ParsedBeatmapObject]
    generator: dict[str, Any] | None = None

    @property
    def object_count(self) -> int:
        return len(self.objects)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    category: IssueCategory
    object_ids: list[int] = field(default_factory=list)
    start_time_ms: int | None = None
    end_time_ms: int | None = None
    measured_value: float | None = None
    allowed_value: float | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "category": self.category,
            "objectIds": self.object_ids,
        }

        if self.start_time_ms is not None:
            payload["startTimeMs"] = self.start_time_ms
        if self.end_time_ms is not None:
            payload["endTimeMs"] = self.end_time_ms
        if self.measured_value is not None:
            payload["measuredValue"] = round(self.measured_value, 4)
        if self.allowed_value is not None:
            payload["allowedValue"] = round(self.allowed_value, 4)
        if self.suggestion:
            payload["suggestion"] = self.suggestion

        return payload


@dataclass(frozen=True)
class TimingObjectDiagnostic:
    object_id: int
    time_ms: int
    nearest_beat_delta_ms: int | None
    nearest_onset_delta_ms: int | None
    anchor_type: AnchorType
    anchor_strength: float
    local_energy: float
    confidence: float
    signed_delta_ms: int | None


@dataclass(frozen=True)
class MovementPairDiagnostic:
    from_object_id: int
    to_object_id: int
    from_time_ms: int
    to_time_ms: int
    distance_px: float
    time_gap_ms: int
    cursor_speed_pps: float
    angle_deg: float
    direction_change_deg: float | None
    edge_distance_px: float
    center_distance_px: float


@dataclass(frozen=True)
class DensityWindowDiagnostic:
    start_ms: int
    end_ms: int
    objects_per_second: float
    object_count: int
    average_event_strength: float
    average_audio_energy: float
    average_jump_distance: float
    average_cursor_speed: float
    timing_confidence: float
    issue_count: int = 0

    def with_issue_count(self, issue_count: int) -> "DensityWindowDiagnostic":
        return DensityWindowDiagnostic(
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            objects_per_second=self.objects_per_second,
            object_count=self.object_count,
            average_event_strength=self.average_event_strength,
            average_audio_energy=self.average_audio_energy,
            average_jump_distance=self.average_jump_distance,
            average_cursor_speed=self.average_cursor_speed,
            timing_confidence=self.timing_confidence,
            issue_count=issue_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "objectsPerSecond": round(self.objects_per_second, 4),
            "objectCount": self.object_count,
            "averageEventStrength": round(self.average_event_strength, 4),
            "averageAudioEnergy": round(self.average_audio_energy, 4),
            "averageJumpDistance": round(self.average_jump_distance, 4),
            "averageCursorSpeed": round(self.average_cursor_speed, 4),
            "timingConfidence": round(self.timing_confidence, 4),
            "issueCount": self.issue_count,
        }


@dataclass(frozen=True)
class StructuralMetrics:
    object_count: int
    valid_object_count: int
    duplicate_id_count: int
    duplicate_timestamp_count: int
    non_finite_value_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectCount": self.object_count,
            "validObjectCount": self.valid_object_count,
            "duplicateIdCount": self.duplicate_id_count,
            "duplicateTimestampCount": self.duplicate_timestamp_count,
            "nonFiniteValueCount": self.non_finite_value_count,
        }


@dataclass(frozen=True)
class TimingMetrics:
    average_anchor_delta_ms: float
    average_beat_delta_ms: float
    average_onset_delta_ms: float
    excellent_alignment_count: int
    good_alignment_count: int
    acceptable_alignment_count: int
    weak_alignment_count: int
    mistimed_count: int
    early_bias_count: int
    late_bias_count: int
    anchor_usage: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "averageAnchorDeltaMs": round(self.average_anchor_delta_ms, 4),
            "averageBeatDeltaMs": round(self.average_beat_delta_ms, 4),
            "averageOnsetDeltaMs": round(self.average_onset_delta_ms, 4),
            "excellentAlignmentCount": self.excellent_alignment_count,
            "goodAlignmentCount": self.good_alignment_count,
            "acceptableAlignmentCount": self.acceptable_alignment_count,
            "weakAlignmentCount": self.weak_alignment_count,
            "mistimedCount": self.mistimed_count,
            "earlyBiasCount": self.early_bias_count,
            "lateBiasCount": self.late_bias_count,
            "anchorUsage": self.anchor_usage,
        }


@dataclass(frozen=True)
class RhythmMetrics:
    min_gap_ms: int
    max_gap_ms: int
    average_gap_ms: float
    median_gap_ms: float
    gap_standard_deviation_ms: float
    gap_percentiles_ms: dict[str, float]
    rapid_sequence_count: int
    long_empty_space_count: int
    repeated_equal_gap_runs: int
    common_rhythm_intervals_ms: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "minGapMs": self.min_gap_ms,
            "maxGapMs": self.max_gap_ms,
            "averageGapMs": round(self.average_gap_ms, 4),
            "medianGapMs": round(self.median_gap_ms, 4),
            "gapStandardDeviationMs": round(self.gap_standard_deviation_ms, 4),
            "gapPercentilesMs": {
                key: round(value, 4) for key, value in self.gap_percentiles_ms.items()
            },
            "rapidSequenceCount": self.rapid_sequence_count,
            "longEmptySpaceCount": self.long_empty_space_count,
            "repeatedEqualGapRuns": self.repeated_equal_gap_runs,
            "commonRhythmIntervalsMs": self.common_rhythm_intervals_ms,
        }


@dataclass(frozen=True)
class MovementMetrics:
    min_jump_distance: float
    max_jump_distance: float
    average_jump_distance: float
    highest_cursor_speed: float
    average_cursor_speed: float
    speed_violation_count: int
    near_limit_run_count: int
    exact_stacking_count: int
    near_stacking_count: int
    overlap_count: int
    large_isolated_jump_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "minJumpDistance": round(self.min_jump_distance, 4),
            "maxJumpDistance": round(self.max_jump_distance, 4),
            "averageJumpDistance": round(self.average_jump_distance, 4),
            "highestCursorSpeed": round(self.highest_cursor_speed, 4),
            "averageCursorSpeed": round(self.average_cursor_speed, 4),
            "speedViolationCount": self.speed_violation_count,
            "nearLimitRunCount": self.near_limit_run_count,
            "exactStackingCount": self.exact_stacking_count,
            "nearStackingCount": self.near_stacking_count,
            "overlapCount": self.overlap_count,
            "largeIsolatedJumpCount": self.large_isolated_jump_count,
        }


@dataclass(frozen=True)
class SpatialMetrics:
    grid_columns: int
    grid_rows: int
    region_counts: dict[str, int]
    playfield_coverage_percent: float
    center_usage_percent: float
    edge_usage_percent: float
    corner_usage_percent: float
    left_right_balance: float
    top_bottom_balance: float
    most_used_region: str
    least_used_region: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gridColumns": self.grid_columns,
            "gridRows": self.grid_rows,
            "regionCounts": self.region_counts,
            "playfieldCoveragePercent": round(self.playfield_coverage_percent, 4),
            "centerUsagePercent": round(self.center_usage_percent, 4),
            "edgeUsagePercent": round(self.edge_usage_percent, 4),
            "cornerUsagePercent": round(self.corner_usage_percent, 4),
            "leftRightBalance": round(self.left_right_balance, 4),
            "topBottomBalance": round(self.top_bottom_balance, 4),
            "mostUsedRegion": self.most_used_region,
            "leastUsedRegion": self.least_used_region,
        }


@dataclass(frozen=True)
class RepetitionMetrics:
    repeated_coordinate_pairs: int
    repeated_two_point_loops: int
    repeated_three_object_shapes: int
    repeated_distance_patterns: int
    repeated_angle_patterns: int
    repeated_gap_sequences: int
    longest_repetition_run: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "repeatedCoordinatePairs": self.repeated_coordinate_pairs,
            "repeatedTwoPointLoops": self.repeated_two_point_loops,
            "repeatedThreeObjectShapes": self.repeated_three_object_shapes,
            "repeatedDistancePatterns": self.repeated_distance_patterns,
            "repeatedAnglePatterns": self.repeated_angle_patterns,
            "repeatedGapSequences": self.repeated_gap_sequences,
            "longestRepetitionRun": self.longest_repetition_run,
        }


@dataclass(frozen=True)
class DensityMetrics:
    windows: list[DensityWindowDiagnostic]
    high_density_low_energy_windows: int
    low_density_high_energy_windows: int
    abrupt_density_spikes: int
    flat_density_despite_energy_change: int
    ending_gap_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [window.to_dict() for window in self.windows],
            "highDensityLowEnergyWindows": self.high_density_low_energy_windows,
            "lowDensityHighEnergyWindows": self.low_density_high_energy_windows,
            "abruptDensitySpikes": self.abrupt_density_spikes,
            "flatDensityDespiteEnergyChange": self.flat_density_despite_energy_change,
            "endingGapMs": self.ending_gap_ms,
        }


@dataclass(frozen=True)
class DifficultyMetrics:
    estimated_behavior: EstimatedBehavior
    density_ratio: float
    jump_ratio: float
    speed_ratio: float
    timing_complexity_ratio: float
    spatial_variation_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimatedBehavior": self.estimated_behavior,
            "densityRatio": round(self.density_ratio, 4),
            "jumpRatio": round(self.jump_ratio, 4),
            "speedRatio": round(self.speed_ratio, 4),
            "timingComplexityRatio": round(self.timing_complexity_ratio, 4),
            "spatialVariationRatio": round(self.spatial_variation_ratio, 4),
        }


@dataclass(frozen=True)
class ValidationMetrics:
    structural: StructuralMetrics
    timing: TimingMetrics
    rhythm: RhythmMetrics
    movement: MovementMetrics
    spatial: SpatialMetrics
    density: DensityMetrics
    repetition: RepetitionMetrics
    difficulty: DifficultyMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "structural": self.structural.to_dict(),
            "timing": self.timing.to_dict(),
            "rhythm": self.rhythm.to_dict(),
            "movement": self.movement.to_dict(),
            "spatial": self.spatial.to_dict(),
            "density": self.density.to_dict(),
            "repetition": self.repetition.to_dict(),
            "difficulty": self.difficulty.to_dict(),
        }


@dataclass(frozen=True)
class ScoreCategories:
    structural: float
    timing: float
    rhythm: float
    movement: float
    readability: float
    spatial_balance: float
    repetition: float
    density_consistency: float
    difficulty_consistency: float
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
            "overall": round(self.overall, 3),
        }


@dataclass(frozen=True)
class ReportSummary:
    critical: int
    errors: int
    warnings: int
    info: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical": self.critical,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }


@dataclass(frozen=True)
class ReportMapInfo:
    path: str
    title: str
    artist: str
    difficulty: str
    object_count: int
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "artist": self.artist,
            "difficulty": self.difficulty,
            "objectCount": self.object_count,
            "durationMs": self.duration_ms,
        }


@dataclass(frozen=True)
class ValidationReport:
    version: int
    map_info: ReportMapInfo
    valid: bool
    playable: bool
    scores: ScoreCategories
    interpretation: str
    summary: ReportSummary
    metrics: ValidationMetrics
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "map": self.map_info.to_dict(),
            "valid": self.valid,
            "playable": self.playable,
            "scores": self.scores.to_dict(),
            "interpretation": self.interpretation,
            "summary": self.summary.to_dict(),
            "metrics": self.metrics.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }
