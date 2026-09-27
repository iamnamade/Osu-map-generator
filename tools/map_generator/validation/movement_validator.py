from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ..config import DifficultyPreset
from ..models import AudioAnalysis
from ..position_generator import PLAYFIELD_CENTER, PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from ..utils import shortest_angle_delta
from .models import (
    MovementMetrics,
    MovementPairDiagnostic,
    ParsedBeatmap,
    ParsedBeatmapObject,
    SpatialMetrics,
    ValidationIssue,
)

GRID_COLUMNS = 4
GRID_ROWS = 3


@dataclass(frozen=True)
class MovementValidationResult:
    movement_metrics: MovementMetrics
    spatial_metrics: SpatialMetrics
    issues: list[ValidationIssue]
    pair_diagnostics: list[MovementPairDiagnostic]


def validate_movement(
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
) -> MovementValidationResult:
    issues: list[ValidationIssue] = []
    pair_diagnostics: list[MovementPairDiagnostic] = []
    distances: list[float] = []
    speeds: list[float] = []
    exact_stacking_count = 0
    near_stacking_count = 0
    overlap_count = 0
    speed_violation_count = 0
    near_limit_run_count = 0
    large_isolated_jump_count = 0

    near_limit_run_length = 0
    tiny_jump_run_start: int | None = None
    reversal_run_length = 0
    straight_run_length = 1
    direction_bins: list[int] = []
    previous_angle_radians: float | None = None
    previous_direction_bin: int | None = None
    same_direction_run = 1

    # Spinners have no coordinates, so movement pairs only consider positioned
    # objects. The spinner validator handles entry/exit transition safety.
    positioned_objects = [
        item for item in beatmap.objects if item.x is not None and item.y is not None
    ]

    for index, (left, right) in enumerate(
        zip(positioned_objects, positioned_objects[1:], strict=False)
    ):
        pair = _build_pair_diagnostic(
            left=left,
            right=right,
            previous_angle_radians=previous_angle_radians,
        )
        pair_diagnostics.append(pair)
        distances.append(pair.distance_px)
        speeds.append(pair.cursor_speed_pps)

        direction_bin = _quantize_angle(pair.angle_deg)
        direction_bins.append(direction_bin)
        target_energy = analysis.energy_at(right.time)

        if pair.distance_px < 1.0:
            exact_stacking_count += 1
            issues.append(
                ValidationIssue(
                    code="READABILITY_EXACT_STACKING",
                    severity="error" if pair.time_gap_ms < int(preset.approach_time_ms * 0.6) else "warning",
                    message="Two consecutive circles occupy the exact same coordinate.",
                    category="readability",
                    object_ids=[left.id, right.id],
                    start_time_ms=left.time,
                    end_time_ms=right.time,
                    measured_value=pair.distance_px,
                    allowed_value=1.0,
                    suggestion="Separate the positions or increase the time gap.",
                )
            )
        elif pair.distance_px < max(8.0, preset.min_jump_distance * 0.4):
            near_stacking_count += 1

        if pair.distance_px < beatmap.circle_radius * 1.65 and pair.time_gap_ms < int(beatmap.approach_time * 0.62):
            overlap_count += 1
            issues.append(
                ValidationIssue(
                    code="READABILITY_APPROACH_OVERLAP",
                    severity="warning",
                    message="Approach-circle visuals are likely to overlap in this short jump.",
                    category="readability",
                    object_ids=[left.id, right.id],
                    start_time_ms=left.time,
                    end_time_ms=right.time,
                    measured_value=pair.distance_px,
                    allowed_value=beatmap.circle_radius * 1.65,
                    suggestion="Increase spacing or give the player more time between notes.",
                )
            )

        if pair.cursor_speed_pps > preset.max_cursor_speed:
            speed_violation_count += 1
            issues.append(
                ValidationIssue(
                    code="MOVEMENT_SPEED_EXCEEDED",
                    severity="critical" if pair.cursor_speed_pps > preset.max_cursor_speed * 1.25 else "error",
                    message="Required cursor speed exceeds the configured difficulty limit.",
                    category="movement",
                    object_ids=[left.id, right.id],
                    start_time_ms=left.time,
                    end_time_ms=right.time,
                    measured_value=pair.cursor_speed_pps,
                    allowed_value=preset.max_cursor_speed,
                    suggestion="Reduce the jump distance or allow more time between these objects.",
                )
            )

        if pair.cursor_speed_pps >= preset.max_cursor_speed * 0.88:
            near_limit_run_length += 1
        else:
            if near_limit_run_length >= 2:
                near_limit_run_count += 1
                issues.append(
                    ValidationIssue(
                        code="MOVEMENT_NEAR_LIMIT_RUN",
                        severity="warning",
                        message="Multiple consecutive jumps stay close to the speed limit.",
                        category="movement",
                        measured_value=float(near_limit_run_length),
                        allowed_value=1.0,
                        suggestion="Ease one or two transitions to create a recovery point.",
                    )
                )
            near_limit_run_length = 0

        if pair.distance_px <= max(12.0, preset.min_jump_distance * 0.55):
            tiny_jump_run_start = index if tiny_jump_run_start is None else tiny_jump_run_start
        elif tiny_jump_run_start is not None:
            if index - tiny_jump_run_start >= 2:
                issues.append(
                    ValidationIssue(
                        code="READABILITY_TINY_JUMP_RUN",
                        severity="warning",
                        message="Several tiny jumps are chained together in a short section.",
                        category="readability",
                        object_ids=[positioned_objects[tiny_jump_run_start].id, left.id, right.id],
                        start_time_ms=positioned_objects[tiny_jump_run_start].time,
                        end_time_ms=right.time,
                        measured_value=float(index - tiny_jump_run_start + 1),
                        allowed_value=2.0,
                        suggestion="Add more spacing or vary the pattern to improve readability.",
                    )
                )
            tiny_jump_run_start = None

        if pair.edge_distance_px < beatmap.circle_radius * 0.25:
            issues.append(
                ValidationIssue(
                    code="READABILITY_TOO_CLOSE_TO_EDGE",
                    severity="warning",
                    message="An object sits very close to the edge of the playfield.",
                    category="readability",
                    object_ids=[right.id],
                    start_time_ms=right.time,
                    measured_value=pair.edge_distance_px,
                    allowed_value=beatmap.circle_radius * 0.25,
                    suggestion="Pull the object slightly inward for better visibility.",
                )
            )

        if (
            pair.edge_distance_px < beatmap.circle_radius + preset.safe_margin + 8
            and _edge_distance(left) < beatmap.circle_radius + preset.safe_margin + 8
            and pair.distance_px > preset.max_jump_distance * 0.82
            and pair.time_gap_ms < preset.target_gap_ms
        ):
            issues.append(
                ValidationIssue(
                    code="MOVEMENT_EDGE_TO_EDGE_RUSH",
                    severity="error",
                    message="A long edge-to-edge jump does not leave enough time to react.",
                    category="movement",
                    object_ids=[left.id, right.id],
                    start_time_ms=left.time,
                    end_time_ms=right.time,
                    measured_value=pair.cursor_speed_pps,
                    allowed_value=preset.max_cursor_speed,
                    suggestion="Shorten the jump or move one object away from the edge.",
                )
            )

        if target_energy < preset.high_energy_threshold * 0.72 and pair.distance_px > preset.preferred_jump_distance * 1.28:
            issues.append(
                ValidationIssue(
                    code="MOVEMENT_LARGE_JUMP_LOW_ENERGY",
                    severity="warning",
                    message="A large movement spike appears during a low-energy moment.",
                    category="movement",
                    object_ids=[left.id, right.id],
                    start_time_ms=left.time,
                    end_time_ms=right.time,
                    measured_value=pair.distance_px,
                    allowed_value=preset.preferred_jump_distance * 1.28,
                    suggestion="Reserve larger jumps for stronger moments in the audio.",
                )
            )

        if index > 0 and index < len(positioned_objects) - 2:
            neighbor_average = (distances[index - 1] + _distance_between(right, positioned_objects[index + 2])) / 2
            if (
                neighbor_average > 0
                and pair.distance_px > neighbor_average * 1.6
                and target_energy < preset.high_energy_threshold
            ):
                large_isolated_jump_count += 1
                issues.append(
                    ValidationIssue(
                        code="MOVEMENT_ISOLATED_JUMP_SPIKE",
                        severity="warning",
                        message="This jump is much larger than the surrounding movement pattern.",
                        category="movement",
                        object_ids=[left.id, right.id],
                        start_time_ms=left.time,
                        end_time_ms=right.time,
                        measured_value=pair.distance_px,
                        allowed_value=neighbor_average * 1.6,
                        suggestion="Blend the jump back into the local spacing pattern.",
                    )
                )

        if pair.direction_change_deg is not None:
            if pair.direction_change_deg >= 165:
                reversal_run_length += 1
            else:
                if reversal_run_length >= 2:
                    issues.append(
                        ValidationIssue(
                            code="MOVEMENT_REPEATED_REVERSAL",
                            severity="warning",
                            message="Several consecutive jumps repeatedly reverse direction.",
                            category="movement",
                            measured_value=float(reversal_run_length),
                            allowed_value=1.0,
                            suggestion="Add a continuation or arc to break the back-and-forth pattern.",
                        )
                    )
                reversal_run_length = 0

            if pair.direction_change_deg <= 12:
                straight_run_length += 1
            else:
                if straight_run_length >= 4:
                    issues.append(
                        ValidationIssue(
                            code="MOVEMENT_OVERLY_STRAIGHT_SEQUENCE",
                            severity="info",
                            message="Movement follows nearly the same direction for an extended run.",
                            category="movement",
                            measured_value=float(straight_run_length),
                            allowed_value=3.0,
                        )
                    )
                straight_run_length = 1

            if pair.direction_change_deg >= 135 and pair.cursor_speed_pps >= preset.max_cursor_speed * 0.85:
                issues.append(
                    ValidationIssue(
                        code="MOVEMENT_SHARP_HIGH_SPEED_TURN",
                        severity="error",
                        message="A sharp direction change is paired with a very fast jump.",
                        category="movement",
                        object_ids=[left.id, right.id],
                        start_time_ms=left.time,
                        end_time_ms=right.time,
                        measured_value=pair.direction_change_deg,
                        allowed_value=134.0,
                        suggestion="Reduce either the turn sharpness or the movement speed.",
                    )
                )

        if previous_direction_bin is not None and direction_bin == previous_direction_bin:
            same_direction_run += 1
        else:
            if same_direction_run >= 4:
                issues.append(
                    ValidationIssue(
                        code="MOVEMENT_REPEATED_DIRECTION",
                        severity="info",
                        message="The same movement direction repeats many times in a row.",
                        category="movement",
                        measured_value=float(same_direction_run),
                        allowed_value=3.0,
                    )
                )
            same_direction_run = 1
        previous_direction_bin = direction_bin
        previous_angle_radians = math.radians(pair.angle_deg)

    if near_limit_run_length >= 2:
        near_limit_run_count += 1

    if tiny_jump_run_start is not None and len(pair_diagnostics) - tiny_jump_run_start >= 2:
        issues.append(
            ValidationIssue(
                code="READABILITY_TINY_JUMP_RUN",
                severity="warning",
                message="Several tiny jumps are chained together in a short section.",
                category="readability",
                object_ids=[positioned_objects[tiny_jump_run_start].id, positioned_objects[-1].id],
                start_time_ms=positioned_objects[tiny_jump_run_start].time,
                end_time_ms=positioned_objects[-1].time,
                measured_value=float(len(pair_diagnostics) - tiny_jump_run_start + 1),
                allowed_value=2.0,
                suggestion="Add more spacing or vary the pattern to improve readability.",
            )
        )

    if reversal_run_length >= 2:
        issues.append(
            ValidationIssue(
                code="MOVEMENT_REPEATED_REVERSAL",
                severity="warning",
                message="Several consecutive jumps repeatedly reverse direction.",
                category="movement",
                measured_value=float(reversal_run_length),
                allowed_value=1.0,
                suggestion="Add a continuation or arc to break the back-and-forth pattern.",
            )
        )

    if straight_run_length >= 4:
        issues.append(
            ValidationIssue(
                code="MOVEMENT_OVERLY_STRAIGHT_SEQUENCE",
                severity="info",
                message="Movement follows nearly the same direction for an extended run.",
                category="movement",
                measured_value=float(straight_run_length),
                allowed_value=3.0,
            )
        )

    spatial_metrics, spatial_issues = _build_spatial_metrics(beatmap, preset, distances)
    issues.extend(spatial_issues)

    movement_metrics = MovementMetrics(
        min_jump_distance=min(distances) if distances else 0.0,
        max_jump_distance=max(distances) if distances else 0.0,
        average_jump_distance=(sum(distances) / len(distances)) if distances else 0.0,
        highest_cursor_speed=max(speeds) if speeds else 0.0,
        average_cursor_speed=(sum(speeds) / len(speeds)) if speeds else 0.0,
        speed_violation_count=speed_violation_count,
        near_limit_run_count=near_limit_run_count,
        exact_stacking_count=exact_stacking_count,
        near_stacking_count=near_stacking_count,
        overlap_count=overlap_count,
        large_isolated_jump_count=large_isolated_jump_count,
    )

    return MovementValidationResult(
        movement_metrics=movement_metrics,
        spatial_metrics=spatial_metrics,
        issues=issues,
        pair_diagnostics=pair_diagnostics,
    )


def _build_pair_diagnostic(
    *,
    left: ParsedBeatmapObject,
    right: ParsedBeatmapObject,
    previous_angle_radians: float | None,
) -> MovementPairDiagnostic:
    delta_x = right.x - left.x
    delta_y = right.y - left.y
    distance = math.hypot(delta_x, delta_y)
    time_gap = max(1, right.time - left.time)
    angle_radians = math.atan2(delta_y, delta_x)
    angle_deg = math.degrees(angle_radians)
    direction_change_deg: float | None = None
    if previous_angle_radians is not None:
        direction_change_deg = abs(math.degrees(shortest_angle_delta(previous_angle_radians, angle_radians)))

    return MovementPairDiagnostic(
        from_object_id=left.id,
        to_object_id=right.id,
        from_time_ms=left.time,
        to_time_ms=right.time,
        distance_px=distance,
        time_gap_ms=time_gap,
        cursor_speed_pps=distance / (time_gap / 1000),
        angle_deg=angle_deg,
        direction_change_deg=direction_change_deg,
        edge_distance_px=_edge_distance(right),
        center_distance_px=math.hypot(right.x - PLAYFIELD_CENTER[0], right.y - PLAYFIELD_CENTER[1]),
    )


def _edge_distance(hit_object: ParsedBeatmapObject) -> float:
    return min(hit_object.x, PLAYFIELD_WIDTH - hit_object.x, hit_object.y, PLAYFIELD_HEIGHT - hit_object.y)


def _distance_between(left: ParsedBeatmapObject, right: ParsedBeatmapObject) -> float:
    return math.hypot(right.x - left.x, right.y - left.y)


def _quantize_angle(angle_deg: float) -> int:
    normalized = int(round((angle_deg % 360) / 15)) * 15
    return normalized % 360


def _build_spatial_metrics(
    beatmap: ParsedBeatmap,
    preset: DifficultyPreset,
    distances: list[float],
) -> tuple[SpatialMetrics, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    region_counts = {f"r{row + 1}c{column + 1}": 0 for row in range(GRID_ROWS) for column in range(GRID_COLUMNS)}
    used_regions = set[str]()
    left_count = 0
    top_count = 0
    center_count = 0
    edge_count = 0
    corner_count = 0

    positioned_objects = [
        item for item in beatmap.objects if item.x is not None and item.y is not None
    ]

    for hit_object in positioned_objects:
        column = min(GRID_COLUMNS - 1, int(hit_object.x / (PLAYFIELD_WIDTH / GRID_COLUMNS)))
        row = min(GRID_ROWS - 1, int(hit_object.y / (PLAYFIELD_HEIGHT / GRID_ROWS)))
        label = f"r{row + 1}c{column + 1}"
        region_counts[label] += 1
        used_regions.add(label)

        if hit_object.x < PLAYFIELD_WIDTH / 2:
            left_count += 1
        if hit_object.y < PLAYFIELD_HEIGHT / 2:
            top_count += 1

        if PLAYFIELD_WIDTH * 0.3 <= hit_object.x <= PLAYFIELD_WIDTH * 0.7 and PLAYFIELD_HEIGHT * 0.3 <= hit_object.y <= PLAYFIELD_HEIGHT * 0.7:
            center_count += 1

        edge_distance = _edge_distance(hit_object)
        if edge_distance < beatmap.circle_radius + preset.safe_margin + 12:
            edge_count += 1

        if (hit_object.x <= PLAYFIELD_WIDTH * 0.25 or hit_object.x >= PLAYFIELD_WIDTH * 0.75) and (
            hit_object.y <= PLAYFIELD_HEIGHT * 0.25 or hit_object.y >= PLAYFIELD_HEIGHT * 0.75
        ):
            corner_count += 1

    object_count = max(1, len(positioned_objects))
    coverage_percent = len(used_regions) / len(region_counts) * 100
    center_usage_percent = center_count / object_count * 100
    edge_usage_percent = edge_count / object_count * 100
    corner_usage_percent = corner_count / object_count * 100
    left_right_balance = abs(left_count - (object_count - left_count)) / object_count * 100
    top_bottom_balance = abs(top_count - (object_count - top_count)) / object_count * 100
    most_used_region = min(
        sorted(region_counts),
        key=lambda label: (-region_counts[label], label),
    )
    least_used_region = min(
        sorted(region_counts),
        key=lambda label: (region_counts[label], label),
    )

    if coverage_percent < 35 and len(positioned_objects) >= 6:
        issues.append(
            ValidationIssue(
                code="SPATIAL_LOW_COVERAGE",
                severity="warning",
                message="The map uses only a small fraction of the playfield regions.",
                category="spatialBalance",
                measured_value=coverage_percent,
                allowed_value=35.0,
                suggestion="Expand the pattern into more of the playfield.",
            )
        )

    if left_right_balance > 45:
        issues.append(
            ValidationIssue(
                code="SPATIAL_LEFT_RIGHT_IMBALANCE",
                severity="warning",
                message="Object placement leans heavily to one side of the playfield.",
                category="spatialBalance",
                measured_value=left_right_balance,
                allowed_value=45.0,
            )
        )

    if top_bottom_balance > 45:
        issues.append(
            ValidationIssue(
                code="SPATIAL_TOP_BOTTOM_IMBALANCE",
                severity="warning",
                message="Object placement leans heavily toward either the top or bottom.",
                category="spatialBalance",
                measured_value=top_bottom_balance,
                allowed_value=45.0,
            )
        )

    if center_usage_percent > 72:
        issues.append(
            ValidationIssue(
                code="SPATIAL_CENTER_CLUSTERING",
                severity="warning",
                message="Too many objects cluster near the center of the playfield.",
                category="spatialBalance",
                measured_value=center_usage_percent,
                allowed_value=72.0,
                suggestion="Use more lateral and diagonal placements.",
            )
        )

    if edge_usage_percent > 58:
        issues.append(
            ValidationIssue(
                code="SPATIAL_EDGE_DEPENDENCE",
                severity="warning",
                message="Objects rely on edge placement more often than expected.",
                category="spatialBalance",
                measured_value=edge_usage_percent,
                allowed_value=58.0,
            )
        )

    if corner_usage_percent > 42:
        issues.append(
            ValidationIssue(
                code="SPATIAL_CORNER_OVERUSE",
                severity="warning",
                message="Corner placements appear too frequently for the current spacing pattern.",
                category="spatialBalance",
                measured_value=corner_usage_percent,
                allowed_value=42.0,
            )
        )

    trapped_area_windows = 0
    for window_start in range(0, max(0, len(positioned_objects) - 5)):
        window = positioned_objects[window_start : window_start + 6]
        width = max(item.x for item in window) - min(item.x for item in window)
        height = max(item.y for item in window) - min(item.y for item in window)
        if width < PLAYFIELD_WIDTH * 0.28 and height < PLAYFIELD_HEIGHT * 0.28:
            trapped_area_windows += 1

    if trapped_area_windows >= 2:
        issues.append(
            ValidationIssue(
                code="SPATIAL_LOCAL_TRAPPING",
                severity="warning",
                message="Several recent-object windows stay trapped in a very small area.",
                category="spatialBalance",
                measured_value=float(trapped_area_windows),
                allowed_value=1.0,
                suggestion="Spread the local movement farther across the playfield.",
            )
        )

    average_jump_distance = sum(distances) / len(distances) if distances else 0.0
    if preset.name == "easy" and coverage_percent > 85 and average_jump_distance > preset.preferred_jump_distance * 1.15:
        issues.append(
            ValidationIssue(
                code="SPATIAL_EASY_MAP_TOO_CHAOTIC",
                severity="warning",
                message="This easy map uses almost the full playfield with surprisingly large jumps.",
                category="spatialBalance",
                measured_value=coverage_percent,
                allowed_value=85.0,
                suggestion="Reduce coverage or tame jump distances for easier reading.",
            )
        )

    spatial_metrics = SpatialMetrics(
        grid_columns=GRID_COLUMNS,
        grid_rows=GRID_ROWS,
        region_counts=region_counts,
        playfield_coverage_percent=coverage_percent,
        center_usage_percent=center_usage_percent,
        edge_usage_percent=edge_usage_percent,
        corner_usage_percent=corner_usage_percent,
        left_right_balance=left_right_balance,
        top_bottom_balance=top_bottom_balance,
        most_used_region=most_used_region,
        least_used_region=least_used_region,
    )
    return spatial_metrics, issues
