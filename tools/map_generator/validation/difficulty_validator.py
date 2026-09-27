from __future__ import annotations

from dataclasses import dataclass

from ..config import DifficultyPreset
from .models import (
    DifficultyMetrics,
    MovementMetrics,
    ParsedBeatmap,
    RhythmMetrics,
    SpatialMetrics,
    TimingMetrics,
    ValidationIssue,
)

EXPECTED_SPATIAL_COVERAGE = {
    "easy": 48.0,
    "normal": 62.0,
    "hard": 74.0,
}

EXPECTED_TIMING_COMPLEXITY = {
    "easy": 0.62,
    "normal": 1.0,
    "hard": 1.28,
}


@dataclass(frozen=True)
class DifficultyValidationResult:
    metrics: DifficultyMetrics
    issues: list[ValidationIssue]


def validate_difficulty(
    beatmap: ParsedBeatmap,
    preset: DifficultyPreset,
    timing_metrics: TimingMetrics,
    rhythm_metrics: RhythmMetrics,
    movement_metrics: MovementMetrics,
    spatial_metrics: SpatialMetrics,
) -> DifficultyValidationResult:
    issues: list[ValidationIssue] = []
    active_duration_ms = max(1, beatmap.objects[-1].time - beatmap.objects[0].time) if beatmap.objects else 1
    actual_density = len(beatmap.objects) / (active_duration_ms / 1000) if beatmap.objects else 0.0
    target_density = 1000 / preset.target_gap_ms if preset.target_gap_ms > 0 else 0.0
    density_ratio = actual_density / target_density if target_density > 0 else 0.0
    jump_ratio = movement_metrics.average_jump_distance / preset.preferred_jump_distance if preset.preferred_jump_distance > 0 else 0.0
    speed_ratio = max(
        (movement_metrics.highest_cursor_speed / preset.max_cursor_speed) if preset.max_cursor_speed > 0 else 0.0,
        (movement_metrics.average_cursor_speed / (preset.max_cursor_speed * 0.55)) if preset.max_cursor_speed > 0 else 0.0,
    )
    onset_share = timing_metrics.anchor_usage.get("onset", 0) / max(1, sum(timing_metrics.anchor_usage.values()))
    rapid_share = rhythm_metrics.rapid_sequence_count / max(1, len(beatmap.objects) - 1)
    raw_timing_complexity = 0.55 + onset_share + rapid_share * 1.3 + max(0.0, 1 - (rhythm_metrics.average_gap_ms / max(1.0, preset.target_gap_ms))) * 0.4
    timing_complexity_ratio = raw_timing_complexity / EXPECTED_TIMING_COMPLEXITY[preset.name]
    spatial_variation_ratio = (
        (spatial_metrics.playfield_coverage_percent / EXPECTED_SPATIAL_COVERAGE[preset.name]) * 0.65
        + jump_ratio * 0.35
    )
    ratio_values = [density_ratio, jump_ratio, speed_ratio, timing_complexity_ratio, spatial_variation_ratio]
    ratio_average = sum(ratio_values) / len(ratio_values)
    ratio_spread = max(ratio_values) - min(ratio_values)
    estimated_behavior = "within-target"

    if ratio_spread > 0.9 or movement_metrics.speed_violation_count > 0:
        estimated_behavior = "inconsistent"
    elif ratio_average < 0.8:
        estimated_behavior = "easier-than-target"
    elif ratio_average > 1.22:
        estimated_behavior = "harder-than-target"

    if abs(beatmap.approach_time - preset.approach_time_ms) > max(25.0, preset.approach_time_ms * 0.08):
        issues.append(
            ValidationIssue(
                code="DIFFICULTY_APPROACH_TIME_MISMATCH",
                severity="error",
                message="Approach time does not match the selected difficulty expectation.",
                category="difficultyConsistency",
                measured_value=beatmap.approach_time,
                allowed_value=float(preset.approach_time_ms),
                suggestion="Keep validation difficulty aligned with the map's intended preset.",
            )
        )

    if abs(beatmap.circle_radius - preset.circle_radius) > max(2.0, preset.circle_radius * 0.08):
        issues.append(
            ValidationIssue(
                code="DIFFICULTY_CIRCLE_RADIUS_MISMATCH",
                severity="error",
                message="Circle radius does not match the selected difficulty expectation.",
                category="difficultyConsistency",
                measured_value=beatmap.circle_radius,
                allowed_value=float(preset.circle_radius),
            )
        )

    if estimated_behavior == "harder-than-target":
        issues.append(
            ValidationIssue(
                code="DIFFICULTY_BEHAVIOR_TOO_HARD",
                severity="warning",
                message="The map behaves harder than the selected preset in aggregate.",
                category="difficultyConsistency",
                measured_value=ratio_average,
                allowed_value=1.22,
                suggestion="Reduce density, speed, or spacing spikes in the hardest sections.",
            )
        )
    elif estimated_behavior == "easier-than-target":
        issues.append(
            ValidationIssue(
                code="DIFFICULTY_BEHAVIOR_TOO_EASY",
                severity="warning",
                message="The map behaves easier than the selected preset overall.",
                category="difficultyConsistency",
                measured_value=ratio_average,
                allowed_value=0.8,
                suggestion="Add a little more rhythmic or spatial challenge for this preset.",
            )
        )
    elif estimated_behavior == "inconsistent":
        issues.append(
            ValidationIssue(
                code="DIFFICULTY_BEHAVIOR_INCONSISTENT",
                severity="error",
                message="The map's local challenge swings too far from one metric to another.",
                category="difficultyConsistency",
                measured_value=ratio_spread,
                allowed_value=0.9,
                suggestion="Smooth out the largest density, spacing, or speed spikes.",
            )
        )

    metrics = DifficultyMetrics(
        estimated_behavior=estimated_behavior,
        density_ratio=density_ratio,
        jump_ratio=jump_ratio,
        speed_ratio=speed_ratio,
        timing_complexity_ratio=timing_complexity_ratio,
        spatial_variation_ratio=spatial_variation_ratio,
    )
    return DifficultyValidationResult(metrics=metrics, issues=issues)
