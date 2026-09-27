from __future__ import annotations

from ..config import DifficultyPreset
from .candidate_config import StabilitySettings
from .candidate_models import CandidateMetrics, StabilitySummary


def analyze_stability(
    *,
    original_report: object,
    improved_report: object,
    candidate_metrics: CandidateMetrics,
    preset: DifficultyPreset,
    settings: StabilitySettings,
) -> StabilitySummary:
    speed_margin_ratio = max(
        0.0,
        (preset.max_cursor_speed - improved_report.metrics.movement.highest_cursor_speed)
        / max(preset.max_cursor_speed, 1.0),
    )
    gap_margin_ratio = max(
        0.0,
        (improved_report.metrics.rhythm.min_gap_ms - preset.min_gap_ms)
        / max(preset.min_gap_ms, 1.0),
    )
    near_threshold_warnings = (
        improved_report.metrics.movement.near_limit_run_count
        + improved_report.metrics.movement.speed_violation_count
        + improved_report.summary.warnings
    )
    accepted_correction_magnitude = (
        candidate_metrics.max_coordinate_shift_px * 0.6
        + candidate_metrics.max_timing_adjustment_ms * 0.4
        + candidate_metrics.destructive_corrections * 14.0
    )
    quality_swing = abs(improved_report.scores.overall - original_report.scores.overall)
    severe_section_count = sum(
        1
        for issue in improved_report.issues
        if issue.severity in {"error", "critical"} and issue.start_time_ms is not None
    )

    score = 100.0
    if speed_margin_ratio < 1.0 - settings.near_limit_speed_ratio:
        score -= (1.0 - settings.near_limit_speed_ratio - speed_margin_ratio) * 140
    if gap_margin_ratio < settings.near_limit_gap_ratio - 1.0:
        score -= (settings.near_limit_gap_ratio - 1.0 - gap_margin_ratio) * 130
    score -= near_threshold_warnings * 1.8
    score -= candidate_metrics.reverted_corrections * 2.5
    score -= accepted_correction_magnitude * 0.05
    score -= quality_swing * 0.65
    score -= severe_section_count * 4.0
    score -= improved_report.summary.errors * 5.0
    score -= improved_report.summary.critical * 18.0
    score = max(0.0, min(100.0, score))

    return StabilitySummary(
        score=score,
        label=_stability_label(score),
        speed_margin_ratio=speed_margin_ratio,
        gap_margin_ratio=gap_margin_ratio,
        near_threshold_warnings=near_threshold_warnings,
        reverted_corrections=candidate_metrics.reverted_corrections,
        accepted_correction_magnitude=accepted_correction_magnitude,
        quality_swing=quality_swing,
        severe_section_count=severe_section_count,
    )


def _stability_label(score: float) -> str:
    if score >= 90:
        return "Very stable"
    if score >= 80:
        return "Stable"
    if score >= 70:
        return "Mostly stable"
    if score >= 60:
        return "Borderline"
    return "Fragile"
