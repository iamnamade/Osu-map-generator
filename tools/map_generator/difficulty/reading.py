from __future__ import annotations

import math

from .common import clamp, coefficient_of_variation, mean, normalize
from .loader import LoadedDifficultyMap
from .metrics import compute_pair_diagnostics
from .models import ReadingMetrics


def analyze_reading(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    approach_time_ms: int,
) -> ReadingMetrics:
    """Estimate reading complexity: spacing, stacking, overlap, clutter,
    approach timing, direction ambiguity, and pattern recognition demand."""
    objects = beatmap.objects
    if not objects:
        return ReadingMetrics(
            spacing_complexity=0.0,
            stacking_count=0,
            overlap_count=0,
            visual_clutter=0.0,
            approach_timing_ratio=0.0,
            direction_ambiguity=0.0,
            pattern_recognition_demand=0.0,
            score=0.0,
        )

    positioned = [item for item in objects if item.is_positioned]
    pairs = compute_pair_diagnostics(beatmap)
    circle_radius = float(beatmap.circle_radius)
    overlap_threshold_px = circle_radius * 1.7
    stacking_threshold_px = circle_radius * 0.35

    stacking_count = 0
    overlap_count = 0
    for pair in pairs:
        distance = float(pair["distancePx"])
        time_gap = int(pair["timeGapMs"])
        if distance <= stacking_threshold_px:
            stacking_count += 1
        if distance <= overlap_threshold_px and time_gap <= approach_time_ms * 0.8:
            overlap_count += 1

    # Visual clutter: how many objects appear within one approach window.
    times = [item.time for item in positioned]
    clutter_counts: list[float] = []
    for index, time in enumerate(times):
        window_start = time - approach_time_ms
        window_end = time
        count = sum(
            1
            for other_index, other_time in enumerate(times)
            if other_index != index and window_start <= other_time <= window_end
        )
        clutter_counts.append(float(count))
    visual_clutter = mean(clutter_counts) if clutter_counts else 0.0

    # Approach timing ratio: how much time players have relative to AR.
    approach_timing_ratio = (
        metrics.average_reaction_time_ms / max(1.0, approach_time_ms)
        if approach_time_ms > 0
        else 0.0
    )

    # Direction ambiguity: large fraction of mid-range turn angles.
    turn_angles = _turn_angles(positioned)
    ambiguous_turns = [
        angle
        for angle in turn_angles
        if 45.0 <= angle <= 135.0
    ]
    direction_ambiguity = (
        len(ambiguous_turns) / max(1, len(turn_angles)) if turn_angles else 0.0
    )

    # Pattern recognition demand: repeated distance patterns reduce surprise.
    pattern_recognition_demand = clamp(metrics.pattern_variation, 0.0, 1.0)

    spacing_complexity = clamp(
        coefficient_of_variation(
            [float(pair["distancePx"]) for pair in pairs]
        ),
        0.0,
        1.5,
    )

    reading_score = 0.0
    if pairs:
        reading_score = (
            normalize(spacing_complexity, 0.9) * 0.22
            + normalize(visual_clutter, 4.0) * 0.22
            + normalize(max(0.0, 1.0 - approach_timing_ratio * 1.2), 1.0) * 0.18
            + direction_ambiguity * 0.18
            + normalize(overlap_count / max(1, len(pairs)), 0.25) * 0.12
            + normalize(stacking_count / max(1, len(pairs)), 0.2) * 0.08
        )
        reading_score = clamp(reading_score, 0.0, 1.0)

    return ReadingMetrics(
        spacing_complexity=clamp(spacing_complexity, 0.0, 1.5),
        stacking_count=stacking_count,
        overlap_count=overlap_count,
        visual_clutter=round(visual_clutter, 3),
        approach_timing_ratio=round(approach_timing_ratio, 3),
        direction_ambiguity=round(direction_ambiguity, 3),
        pattern_recognition_demand=round(pattern_recognition_demand, 3),
        score=reading_score,
    )


def _turn_angles(positioned) -> list[float]:
    angles: list[float] = []
    for left, middle, right in zip(positioned, positioned[1:], positioned[2:], strict=False):
        if (
            left.x is None
            or left.y is None
            or middle.x is None
            or middle.y is None
            or right.x is None
            or right.y is None
        ):
            continue
        vector_a = (middle.x - left.x, middle.y - left.y)
        vector_b = (right.x - middle.x, right.y - middle.y)
        magnitude_a = math.hypot(*vector_a)
        magnitude_b = math.hypot(*vector_b)
        if magnitude_a <= 0 or magnitude_b <= 0:
            continue
        dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
        cosine = clamp(dot / (magnitude_a * magnitude_b), -1.0, 1.0)
        angles.append(math.degrees(math.acos(cosine)))
    return angles
