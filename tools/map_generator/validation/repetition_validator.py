from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .models import MovementPairDiagnostic, ParsedBeatmap, RepetitionMetrics, ValidationIssue


@dataclass(frozen=True)
class RepetitionValidationResult:
    metrics: RepetitionMetrics
    issues: list[ValidationIssue]


def validate_repetition(
    beatmap: ParsedBeatmap,
    pair_diagnostics: list[MovementPairDiagnostic],
    gaps_ms: list[int],
) -> RepetitionValidationResult:
    issues: list[ValidationIssue] = []
    repeated_coordinate_pairs = _count_repeated_coordinate_pairs(beatmap)
    repeated_two_point_loops = _count_two_point_loops(beatmap)
    repeated_three_object_shapes = _count_repeated_three_object_shapes(beatmap)
    repeated_distance_patterns = _count_sequence_repetitions(
        [int(round(item.distance_px / 12)) for item in pair_diagnostics]
    )
    repeated_angle_patterns = _count_sequence_repetitions(
        [int(round(((item.direction_change_deg or 0.0)) / 15)) for item in pair_diagnostics[1:]]
    )
    repeated_gap_sequences = _count_sequence_repetitions(
        [int(round(gap / 10)) for gap in gaps_ms]
    )
    longest_repetition_run = _find_longest_repetition_run(
        [int(round(gap / 10)) for gap in gaps_ms]
    )

    if repeated_coordinate_pairs >= 2:
        issues.append(
            ValidationIssue(
                code="REPETITION_COORDINATE_PAIR_REUSE",
                severity="warning",
                message="The same coordinate-pair movement appears repeatedly.",
                category="repetition",
                measured_value=float(repeated_coordinate_pairs),
                allowed_value=1.0,
                suggestion="Vary the placement pattern instead of replaying the same pair.",
            )
        )

    if repeated_two_point_loops >= 2:
        issues.append(
            ValidationIssue(
                code="REPETITION_TWO_POINT_LOOP",
                severity="error",
                message="A two-point back-and-forth loop repeats too many times.",
                category="repetition",
                measured_value=float(repeated_two_point_loops),
                allowed_value=1.0,
                suggestion="Break the loop with a third position or a direction change.",
            )
        )

    if repeated_three_object_shapes >= 2:
        issues.append(
            ValidationIssue(
                code="REPETITION_SHAPE_MOTIF_OVERUSE",
                severity="warning",
                message="The same three-object shape repeats frequently.",
                category="repetition",
                measured_value=float(repeated_three_object_shapes),
                allowed_value=1.0,
                suggestion="Introduce a few alternate local shapes to reduce repetition fatigue.",
            )
        )

    if repeated_gap_sequences >= 2 and repeated_angle_patterns >= 2:
        issues.append(
            ValidationIssue(
                code="REPETITION_IDENTICAL_PATTERN_SEQUENCE",
                severity="warning",
                message="Short rhythm and movement sequences repeat with little variation.",
                category="repetition",
                measured_value=float(repeated_gap_sequences + repeated_angle_patterns),
                allowed_value=2.0,
                suggestion="Keep the motif, but add slight timing or angle variation.",
            )
        )

    metrics = RepetitionMetrics(
        repeated_coordinate_pairs=repeated_coordinate_pairs,
        repeated_two_point_loops=repeated_two_point_loops,
        repeated_three_object_shapes=repeated_three_object_shapes,
        repeated_distance_patterns=repeated_distance_patterns,
        repeated_angle_patterns=repeated_angle_patterns,
        repeated_gap_sequences=repeated_gap_sequences,
        longest_repetition_run=longest_repetition_run,
    )
    return RepetitionValidationResult(metrics=metrics, issues=issues)


def _positioned(beatmap: ParsedBeatmap) -> list[Any]:
    """Return objects that carry x/y coordinates (spinners have none)."""
    return [obj for obj in beatmap.objects if obj.x is not None and obj.y is not None]


def _count_repeated_coordinate_pairs(beatmap: ParsedBeatmap) -> int:
    positioned = _positioned(beatmap)
    if len(positioned) < 2:
        return 0

    counter: Counter[tuple[int, int, int, int]] = Counter()
    for left, right in zip(positioned, positioned[1:], strict=False):
        counter[
            (
                int(round(left.x / 16)),
                int(round(left.y / 16)),
                int(round(right.x / 16)),
                int(round(right.y / 16)),
            )
        ] += 1
    return sum(count - 1 for count in counter.values() if count >= 2)


def _count_two_point_loops(beatmap: ParsedBeatmap) -> int:
    positioned = _positioned(beatmap)
    if len(positioned) < 4:
        return 0

    count = 0
    for index in range(len(positioned) - 3):
        first = positioned[index]
        second = positioned[index + 1]
        third = positioned[index + 2]
        fourth = positioned[index + 3]
        if _points_close(first.x, first.y, third.x, third.y, tolerance=10) and _points_close(
            second.x,
            second.y,
            fourth.x,
            fourth.y,
            tolerance=10,
        ):
            count += 1
    return count


def _count_repeated_three_object_shapes(beatmap: ParsedBeatmap) -> int:
    positioned = _positioned(beatmap)
    if len(positioned) < 3:
        return 0

    counter: Counter[tuple[int, int, int, int]] = Counter()
    for index in range(len(positioned) - 2):
        first = positioned[index]
        second = positioned[index + 1]
        third = positioned[index + 2]
        counter[
            (
                int(round((second.x - first.x) / 14)),
                int(round((second.y - first.y) / 14)),
                int(round((third.x - second.x) / 14)),
                int(round((third.y - second.y) / 14)),
            )
        ] += 1
    return sum(count - 1 for count in counter.values() if count >= 2)


def _count_sequence_repetitions(values: list[int], window_size: int = 3) -> int:
    if len(values) < window_size:
        return 0

    counter: Counter[tuple[int, ...]] = Counter(
        tuple(values[index : index + window_size])
        for index in range(len(values) - window_size + 1)
    )
    return sum(count - 1 for count in counter.values() if count >= 2)


def _find_longest_repetition_run(values: list[int]) -> int:
    longest = 0
    current = 0
    previous: int | None = None
    for value in values:
        if value == previous:
            current += 1
        else:
            longest = max(longest, current)
            current = 1
            previous = value
    return max(longest, current) if values else 0


def _points_close(left_x: float, left_y: float, right_x: float, right_y: float, *, tolerance: float) -> bool:
    return abs(left_x - right_x) <= tolerance and abs(left_y - right_y) <= tolerance
