from __future__ import annotations

from dataclasses import dataclass

from ..config import DifficultyPreset
from ..utils import clamp
from .models import ScoreCategories, ValidationIssue, ValidationMetrics

SCORE_WEIGHTS = {
    "structural": 0.15,
    "timing": 0.20,
    "rhythm": 0.15,
    "movement": 0.15,
    "readability": 0.10,
    "spatialBalance": 0.05,
    "repetition": 0.05,
    "densityConsistency": 0.10,
    "difficultyConsistency": 0.05,
}

ISSUE_SEVERITY_PENALTIES = {
    "info": 1.5,
    "warning": 5.0,
    "error": 11.0,
    "critical": 28.0,
}

CATEGORY_MODIFIERS = {
    "structural": 1.2,
    "timing": 1.0,
    "rhythm": 1.0,
    "movement": 1.05,
    "readability": 1.0,
    "spatialBalance": 0.9,
    "repetition": 0.9,
    "densityConsistency": 1.0,
    "difficultyConsistency": 1.0,
}


@dataclass(frozen=True)
class QualityScoreResult:
    scores: ScoreCategories
    interpretation: str


def calculate_quality_scores(
    *,
    metrics: ValidationMetrics,
    issues: list[ValidationIssue],
    preset: DifficultyPreset,
) -> QualityScoreResult:
    structural = _category_score("structural", metrics, issues, preset)
    timing = _category_score("timing", metrics, issues, preset)
    rhythm = _category_score("rhythm", metrics, issues, preset)
    movement = _category_score("movement", metrics, issues, preset)
    readability = _category_score("readability", metrics, issues, preset)
    spatial_balance = _category_score("spatialBalance", metrics, issues, preset)
    repetition = _category_score("repetition", metrics, issues, preset)
    density_consistency = _category_score("densityConsistency", metrics, issues, preset)
    difficulty_consistency = _category_score("difficultyConsistency", metrics, issues, preset)

    overall = (
        structural * SCORE_WEIGHTS["structural"]
        + timing * SCORE_WEIGHTS["timing"]
        + rhythm * SCORE_WEIGHTS["rhythm"]
        + movement * SCORE_WEIGHTS["movement"]
        + readability * SCORE_WEIGHTS["readability"]
        + spatial_balance * SCORE_WEIGHTS["spatialBalance"]
        + repetition * SCORE_WEIGHTS["repetition"]
        + density_consistency * SCORE_WEIGHTS["densityConsistency"]
        + difficulty_consistency * SCORE_WEIGHTS["difficultyConsistency"]
    )

    if any(issue.severity == "critical" and issue.category == "structural" for issue in issues):
        overall = min(overall, 20.0)

    overall = clamp(overall, 0.0, 100.0)
    scores = ScoreCategories(
        structural=structural,
        timing=timing,
        rhythm=rhythm,
        movement=movement,
        readability=readability,
        spatial_balance=spatial_balance,
        repetition=repetition,
        density_consistency=density_consistency,
        difficulty_consistency=difficulty_consistency,
        overall=overall,
    )
    return QualityScoreResult(scores=scores, interpretation=_interpret_score(overall))


def _category_score(
    category: str,
    metrics: ValidationMetrics,
    issues: list[ValidationIssue],
    preset: DifficultyPreset,
) -> float:
    issue_penalty = sum(
        ISSUE_SEVERITY_PENALTIES[issue.severity] * CATEGORY_MODIFIERS[category]
        for issue in issues
        if issue.category == category
    )
    metric_penalty = _metric_penalty(category=category, metrics=metrics, preset=preset)
    return clamp(100.0 - issue_penalty - metric_penalty, 0.0, 100.0)


def _metric_penalty(
    *,
    category: str,
    metrics: ValidationMetrics,
    preset: DifficultyPreset,
) -> float:
    if category == "structural":
        structural = metrics.structural
        return (
            structural.duplicate_id_count * 8
            + structural.duplicate_timestamp_count * 6
            + structural.non_finite_value_count * 12
            + max(0, structural.object_count - structural.valid_object_count) * 4
        )

    if category == "timing":
        timing = metrics.timing
        return (
            timing.mistimed_count * 8
            + timing.weak_alignment_count * 2
            + max(0.0, timing.average_anchor_delta_ms - 25) / 3
        )

    if category == "rhythm":
        rhythm = metrics.rhythm
        minimum_gap_penalty = max(0.0, (preset.min_gap_ms - rhythm.min_gap_ms) / max(1, preset.min_gap_ms) * 35)
        return (
            minimum_gap_penalty
            + rhythm.long_empty_space_count * 5
            + rhythm.rapid_sequence_count * 4
            + rhythm.repeated_equal_gap_runs * 2
        )

    if category == "movement":
        movement = metrics.movement
        return (
            movement.speed_violation_count * 16
            + movement.near_limit_run_count * 5
            + movement.large_isolated_jump_count * 4
            + max(0.0, movement.highest_cursor_speed - preset.max_cursor_speed) / 35
        )

    if category == "readability":
        movement = metrics.movement
        return (
            movement.exact_stacking_count * 14
            + movement.near_stacking_count * 6
            + movement.overlap_count * 8
        )

    if category == "spatialBalance":
        spatial = metrics.spatial
        return (
            max(0.0, 45 - spatial.playfield_coverage_percent) * 0.45
            + max(0.0, spatial.left_right_balance - 20) * 0.35
            + max(0.0, spatial.top_bottom_balance - 20) * 0.35
            + max(0.0, spatial.center_usage_percent - 55) * 0.18
            + max(0.0, spatial.edge_usage_percent - 50) * 0.15
        )

    if category == "repetition":
        repetition = metrics.repetition
        return (
            repetition.repeated_two_point_loops * 12
            + repetition.repeated_coordinate_pairs * 4
            + repetition.repeated_three_object_shapes * 4
            + repetition.repeated_gap_sequences * 3
            + max(0, repetition.longest_repetition_run - 3) * 2
        )

    if category == "densityConsistency":
        density = metrics.density
        return (
            density.high_density_low_energy_windows * 7
            + density.low_density_high_energy_windows * 7
            + density.abrupt_density_spikes * 5
            + density.flat_density_despite_energy_change * 2
            + max(0.0, density.ending_gap_ms - (preset.end_padding_ms + 250)) / 120
        )

    difficulty = metrics.difficulty
    behavior_penalty = {
        "within-target": 0.0,
        "easier-than-target": 8.0,
        "harder-than-target": 10.0,
        "inconsistent": 16.0,
    }[difficulty.estimated_behavior]
    return (
        behavior_penalty
        + abs(difficulty.density_ratio - 1.0) * 12
        + abs(difficulty.jump_ratio - 1.0) * 10
        + abs(difficulty.speed_ratio - 1.0) * 10
        + abs(difficulty.timing_complexity_ratio - 1.0) * 7
        + abs(difficulty.spatial_variation_ratio - 1.0) * 7
    )


def _interpret_score(value: float) -> str:
    if value >= 90:
        return "Excellent foundation"
    if value >= 80:
        return "Strong map with minor issues"
    if value >= 70:
        return "Playable but needs refinement"
    if value >= 60:
        return "Noticeable quality problems"
    if value >= 40:
        return "Major revision required"
    return "Invalid or severely unplayable"
