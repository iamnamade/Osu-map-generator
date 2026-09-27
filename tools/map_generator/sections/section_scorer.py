from __future__ import annotations

import math
from dataclasses import dataclass

from ..analysis_io import load_analysis_json
from ..config import DifficultyPreset
from ..models import AudioAnalysis
from ..utils import average, clamp
from .section_config import SectionEvaluationConfig
from .section_models import (
    MapObject,
    SectionIssue,
    SectionMetrics,
    SectionScores,
    SectionState,
    SongSection,
)


@dataclass(frozen=True)
class SectionScoreResult:
    metrics: SectionMetrics
    scores: SectionScores
    issues: list[SectionIssue]
    entry_state: SectionState
    exit_state: SectionState


def evaluate_section_window(
    *,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    section: SongSection,
    all_objects: list[MapObject],
    evaluation_config: SectionEvaluationConfig,
) -> SectionScoreResult:
    local_objects = [
        item for item in all_objects if section.start_ms <= item.time < section.end_ms
    ]
    context_objects = [
        item
        for item in all_objects
        if section.start_ms - evaluation_config.boundary_context_ms
        <= item.time
        < section.end_ms + evaluation_config.boundary_context_ms
    ]
    # Objects that carry valid x/y spatial coordinates (circles and sliders).
    # Spinners lack positional data and would pollute spatial metrics with
    # synthetic (0,0) coordinates injected by the normaliser.
    positioned_local = [obj for obj in local_objects if obj.x != 0 or obj.y != 0]
    positioned_context = [obj for obj in context_objects if obj.x != 0 or obj.y != 0]
    # Fall back to all local objects when every entry is non-positional
    # (e.g. an all-spinner section) so that timing metrics still compute.
    if not positioned_local:
        positioned_local = local_objects
    if not positioned_context:
        positioned_context = context_objects
    issues: list[SectionIssue] = []
    if not local_objects:
        issues.append(
            SectionIssue(
                code="empty-section",
                severity="error",
                message="No hit objects fall inside this section.",
            )
        )
        empty_metrics = SectionMetrics(
            object_count=0,
            objects_per_second=0.0,
            average_object_gap_ms=section.duration_ms,
            minimum_object_gap_ms=section.duration_ms,
            maximum_object_gap_ms=section.duration_ms,
            average_jump_distance=0.0,
            maximum_jump_distance=0.0,
            average_cursor_speed=0.0,
            maximum_cursor_speed=0.0,
            timing_confidence=0.0,
            beat_alignment=0.0,
            onset_alignment=0.0,
            spatial_coverage=0.0,
            center_usage=0.0,
            edge_usage=0.0,
            repetition_count=0,
            stacking_count=0,
            warning_count=0,
            error_count=1,
            local_difficulty_behavior="underfilled",
            energy_to_density_ratio=0.0,
            entry_direction_deg=None,
            exit_direction_deg=None,
        )
        empty_scores = SectionScores(
            structural=82.0,
            timing=10.0,
            rhythm=8.0,
            movement=78.0,
            readability=88.0,
            spatial_balance=12.0,
            repetition=90.0,
            density_consistency=6.0,
            difficulty_consistency=25.0,
            transition_readiness=18.0,
            overall=24.0,
        )
        blank_state = SectionState(None, None, None, None, None, None, None, None, None)
        return SectionScoreResult(
            metrics=empty_metrics,
            scores=empty_scores,
            issues=issues,
            entry_state=blank_state,
            exit_state=blank_state,
        )

    distances, speeds, directions, gaps = _movement_sequences(positioned_context)
    local_duration_ms = max(1, section.duration_ms)
    objects_per_second = len(local_objects) * 1000 / local_duration_ms
    # Temporal gaps use ALL objects (including spinners) for density counting.
    local_gaps = [right.time - left.time for left, right in zip(local_objects, local_objects[1:])]
    # Spatial distances use ONLY positioned objects to avoid synthetic (0,0) bias.
    local_distances = [
        math.hypot(right.x - left.x, right.y - left.y)
        for left, right in zip(positioned_local, positioned_local[1:])
    ]
    local_speeds = [
        distance * 1000 / max(1, gap)
        for distance, gap in zip(local_distances, local_gaps[: len(local_distances)])
    ]
    beat_alignment = average(
        max(0.0, 1.0 - _nearest_delta_ms(item.time, analysis.beats) / 90.0)
        for item in local_objects
    )
    onset_alignment = average(
        max(0.0, 1.0 - _nearest_delta_ms(item.time, analysis.onsets) / 90.0)
        for item in local_objects
    )
    timing_confidence = (beat_alignment + onset_alignment) / 2

    # Spatial metrics use only positioned objects so spinners at (0,0) don't
    # inflate coverage, center/edge usage, or create phantom repetitions.
    coverage_cells = {
        _grid_region(item.x, item.y)
        for item in positioned_local
    }
    center_usage = (
        sum(1 for item in positioned_local if 156 <= item.x <= 356 and 108 <= item.y <= 276)
        / len(positioned_local)
    )
    edge_usage = (
        sum(
            1
            for item in positioned_local
            if item.x <= 76 or item.x >= 436 or item.y <= 56 or item.y >= 328
        )
        / len(positioned_local)
    )
    spatial_coverage = len(coverage_cells) / 12
    repetition_count = _repetition_count(positioned_local)
    stacking_count = sum(
        1
        for distance in local_distances
        if distance <= max(10, preset.circle_radius * 0.45)
    )

    if local_gaps and min(local_gaps) < preset.min_gap_ms:
        issues.append(
            SectionIssue(
                code="tight-gap",
                severity="warning",
                message="Section contains gaps tighter than the target difficulty minimum.",
                measured_value=float(min(local_gaps)),
                allowed_value=float(preset.min_gap_ms),
            )
        )
    if local_speeds and max(local_speeds, default=0) > preset.max_cursor_speed:
        issues.append(
            SectionIssue(
                code="cursor-speed",
                severity="error",
                message="Section requires cursor speed above the difficulty safety target.",
                measured_value=max(local_speeds),
                allowed_value=preset.max_cursor_speed,
            )
        )
    if section.label in {"quiet", "intro-like", "break-like"} and objects_per_second > 1.55:
        issues.append(
            SectionIssue(
                code="too-dense-for-quiet",
                severity="warning",
                message="Density is high for a quiet or recovery section.",
                measured_value=objects_per_second,
                allowed_value=1.55,
            )
        )

    energy_to_density_ratio = (
        section.average_energy / max(0.15, objects_per_second) if objects_per_second else 0.0
    )
    local_difficulty_behavior = _difficulty_behavior(
        objects_per_second=objects_per_second,
        average_speed=average(local_speeds) if local_speeds else 0.0,
        preset=preset,
    )
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    error_count = sum(1 for issue in issues if issue.severity in {"error", "critical"})
    metrics = SectionMetrics(
        object_count=len(local_objects),
        objects_per_second=objects_per_second,
        average_object_gap_ms=average(local_gaps) if local_gaps else float(local_duration_ms),
        minimum_object_gap_ms=min(local_gaps) if local_gaps else local_duration_ms,
        maximum_object_gap_ms=max(local_gaps) if local_gaps else local_duration_ms,
        average_jump_distance=average(local_distances),
        maximum_jump_distance=max(local_distances) if local_distances else 0.0,
        average_cursor_speed=average(local_speeds),
        maximum_cursor_speed=max(local_speeds) if local_speeds else 0.0,
        timing_confidence=timing_confidence,
        beat_alignment=beat_alignment,
        onset_alignment=onset_alignment,
        spatial_coverage=spatial_coverage,
        center_usage=center_usage,
        edge_usage=edge_usage,
        repetition_count=repetition_count,
        stacking_count=stacking_count,
        warning_count=warning_count,
        error_count=error_count,
        local_difficulty_behavior=local_difficulty_behavior,
        energy_to_density_ratio=energy_to_density_ratio,
        entry_direction_deg=directions[0] if directions else None,
        exit_direction_deg=directions[-1] if directions else None,
    )
    scores = _score_metrics(
        preset=preset,
        section=section,
        metrics=metrics,
        issues=issues,
    )
    entry_state, exit_state = _build_boundary_states(section, positioned_local, gaps, speeds, directions)
    return SectionScoreResult(
        metrics=metrics,
        scores=scores,
        issues=issues,
        entry_state=entry_state,
        exit_state=exit_state,
    )


def _movement_sequences(
    objects: list[MapObject],
) -> tuple[list[float], list[float], list[float], list[int]]:
    distances: list[float] = []
    speeds: list[float] = []
    directions: list[float] = []
    gaps: list[int] = []
    for left, right in zip(objects, objects[1:]):
        gap_ms = right.time - left.time
        distance_px = math.hypot(right.x - left.x, right.y - left.y)
        angle_deg = math.degrees(math.atan2(right.y - left.y, right.x - left.x))
        distances.append(distance_px)
        gaps.append(gap_ms)
        speeds.append(distance_px * 1000 / max(1, gap_ms))
        directions.append(angle_deg)
    return distances, speeds, directions, gaps


def _grid_region(x: int, y: int) -> str:
    column = min(3, max(0, int(x / (512 / 4))))
    row = min(2, max(0, int(y / (384 / 3))))
    return f"r{row + 1}c{column + 1}"


def _repetition_count(objects: list[MapObject]) -> int:
    repetitions = 0
    for left, right in zip(objects, objects[1:]):
        if abs(left.x - right.x) <= 8 and abs(left.y - right.y) <= 8:
            repetitions += 1
    return repetitions


def _nearest_delta_ms(time_ms: int, markers: list[object]) -> float:
    best = min((abs(getattr(marker, "time_ms") - time_ms) for marker in markers), default=1000)
    return float(best)


def _difficulty_behavior(
    *,
    objects_per_second: float,
    average_speed: float,
    preset: DifficultyPreset,
) -> str:
    density_ratio = objects_per_second / max(0.25, 1000 / preset.target_gap_ms)
    speed_ratio = average_speed / max(1.0, preset.max_cursor_speed)
    if density_ratio < 0.78 and speed_ratio < 0.72:
        return "underfilled"
    if density_ratio > 1.32 or speed_ratio > 1.12:
        return "overstretched"
    return "balanced"


def _score_metrics(
    *,
    preset: DifficultyPreset,
    section: SongSection,
    metrics: SectionMetrics,
    issues: list[SectionIssue],
) -> SectionScores:
    structural = max(75.0, 100.0 - metrics.error_count * 9.0)
    timing = clamp(
        100.0 * (0.55 * metrics.beat_alignment + 0.45 * metrics.onset_alignment)
        - metrics.warning_count * 3.0
        - metrics.error_count * 10.0,
        0.0,
        100.0,
    )
    rhythm = clamp(
        100.0
        - abs(metrics.average_object_gap_ms - preset.target_gap_ms) / max(1.0, preset.target_gap_ms) * 28.0
        - metrics.warning_count * 2.0,
        0.0,
        100.0,
    )
    movement = clamp(
        100.0
        - max(0.0, metrics.maximum_cursor_speed - preset.max_cursor_speed) / max(1.0, preset.max_cursor_speed) * 110.0
        - max(0.0, metrics.maximum_jump_distance - preset.max_jump_distance) / max(1.0, preset.max_jump_distance) * 80.0
        - metrics.stacking_count * 4.0,
        0.0,
        100.0,
    )
    readability = clamp(
        100.0
        - metrics.stacking_count * 10.0
        - metrics.edge_usage * 16.0
        - metrics.warning_count * 2.5,
        0.0,
        100.0,
    )
    spatial_balance = clamp(
        58.0 + metrics.spatial_coverage * 42.0 - abs(metrics.center_usage - 0.34) * 28.0,
        0.0,
        100.0,
    )
    repetition = clamp(100.0 - metrics.repetition_count * 8.0, 0.0, 100.0)

    expected_density = _expected_density(section.label)
    density_consistency = clamp(
        100.0
        - abs(metrics.objects_per_second - expected_density) / max(0.35, expected_density) * 30.0
        - abs(metrics.energy_to_density_ratio - _expected_ratio(section.label)) * 24.0,
        0.0,
        100.0,
    )
    difficulty_consistency = clamp(
        100.0
        - (0.0 if metrics.local_difficulty_behavior == "balanced" else 18.0)
        - max(0.0, metrics.maximum_cursor_speed / max(1.0, preset.max_cursor_speed) - 1.0) * 40.0,
        0.0,
        100.0,
    )
    transition_readiness = clamp(
        100.0
        - metrics.stacking_count * 5.0
        - max(0.0, metrics.maximum_cursor_speed / max(1.0, preset.max_cursor_speed) - 0.94) * 56.0
        - metrics.error_count * 8.0,
        0.0,
        100.0,
    )

    if section.label in {"quiet", "intro-like", "break-like"}:
        density_consistency += max(0.0, 1.1 - metrics.objects_per_second) * 10.0
        movement += max(0.0, 0.9 - metrics.average_cursor_speed / max(1.0, preset.max_cursor_speed)) * 8.0
    elif section.label in {"build-up"}:
        density_consistency += max(0.0, metrics.objects_per_second - 0.9) * 4.0
    elif section.label in {"chorus-like", "drop-like"}:
        movement += max(0.0, metrics.maximum_jump_distance / max(1.0, preset.preferred_jump_distance) - 0.85) * 12.0
        rhythm += metrics.timing_confidence * 4.0

    overall = clamp(
        structural * 0.10
        + timing * 0.17
        + rhythm * 0.14
        + movement * 0.14
        + readability * 0.10
        + spatial_balance * 0.09
        + repetition * 0.07
        + density_consistency * 0.09
        + difficulty_consistency * 0.06
        + transition_readiness * 0.04,
        0.0,
        100.0,
    )
    return SectionScores(
        structural=clamp(structural, 0.0, 100.0),
        timing=timing,
        rhythm=rhythm,
        movement=movement,
        readability=readability,
        spatial_balance=spatial_balance,
        repetition=repetition,
        density_consistency=clamp(density_consistency, 0.0, 100.0),
        difficulty_consistency=difficulty_consistency,
        transition_readiness=transition_readiness,
        overall=overall,
    )


def _build_boundary_states(
    section: SongSection,
    objects: list[MapObject],
    gaps: list[int],
    speeds: list[float],
    directions: list[float],
) -> tuple[SectionState, SectionState]:
    first = objects[0]
    last = objects[-1]
    entry_density = len(objects) * 1000 / max(1, section.duration_ms)
    entry_state = SectionState(
        object_id=first.id,
        time_ms=first.time,
        x=first.x,
        y=first.y,
        direction_deg=directions[0] if directions else None,
        cursor_speed_pps=speeds[0] if speeds else None,
        gap_ms=gaps[0] if gaps else None,
        density=entry_density,
        region=_grid_region(first.x, first.y),
    )
    exit_state = SectionState(
        object_id=last.id,
        time_ms=last.time,
        x=last.x,
        y=last.y,
        direction_deg=directions[-1] if directions else None,
        cursor_speed_pps=speeds[-1] if speeds else None,
        gap_ms=gaps[-1] if gaps else None,
        density=entry_density,
        region=_grid_region(last.x, last.y),
    )
    return entry_state, exit_state


def _expected_density(label: str) -> float:
    if label in {"quiet", "intro-like", "break-like"}:
        return 0.75
    if label == "build-up":
        return 1.05
    if label in {"chorus-like", "drop-like"}:
        return 1.45
    if label == "outro-like":
        return 0.82
    return 1.0


def _expected_ratio(label: str) -> float:
    if label in {"quiet", "break-like"}:
        return 0.34
    if label in {"chorus-like", "drop-like"}:
        return 0.48
    return 0.42
