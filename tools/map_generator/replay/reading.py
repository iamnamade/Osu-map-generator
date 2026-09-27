from __future__ import annotations

import math

from ..difficulty.common import clamp, mean, standard_deviation
from ..difficulty.loader import LoadedDifficultyMap
from .models import ReadingSimulation


def simulate_reading(beatmap: LoadedDifficultyMap) -> ReadingSimulation:
    """Estimate reading complexity for a human player.

    Considers object spacing, time spacing (irregular timing is harder to
    read), angle variation, pattern repetition (repetition eases reading), and
    visual clutter (objects close in space and time). Produces a 0..100
    reading difficulty score where 100 means trivially readable.
    """
    positioned = [item for item in beatmap.objects if item.is_positioned]
    if len(positioned) < 2:
        return ReadingSimulation(
            score=100.0,
            spacing=0.0,
            time_spacing=0.0,
            angle_variation=0.0,
            pattern_repetition=0.0,
            visual_clutter=0.0,
        )

    gaps = [right.time - left.time for left, right in zip(positioned, positioned[1:], strict=False)]
    distances = [
        math.hypot(
            float(right.x) - float(left.x),
            float(right.y) - float(left.y),
        )
        for left, right in zip(positioned, positioned[1:], strict=False)
    ]
    turn_angles = _turn_angles(positioned)

    spacing_demand = clamp(mean(distances) / 380.0, 0.0, 1.0)
    average_gap = mean([float(gap) for gap in gaps])
    gap_cv = standard_deviation([float(gap) for gap in gaps]) / max(1e-6, average_gap)
    time_demand = clamp(1.0 - average_gap / 600.0, 0.0, 1.0) * 0.6
    time_demand += clamp(gap_cv * 0.9, 0.0, 1.0) * 0.4

    angle_demand = (
        clamp(standard_deviation(turn_angles) / 90.0, 0.0, 1.0)
        if turn_angles
        else 0.0
    )

    repetition = _pattern_repetition(gaps, turn_angles)
    repetition_ease = clamp(repetition * 2.0, 0.0, 1.0)

    clutter = _visual_clutter(positioned, distances, gaps, beatmap.circle_radius)

    reading_difficulty = clamp(
        spacing_demand * 0.30
        + time_demand * 0.22
        + angle_demand * 0.18
        + clutter * 0.18
        + (1.0 - repetition_ease) * 0.12,
        0.0,
        1.0,
    )
    score = 100.0 * (1.0 - reading_difficulty)
    return ReadingSimulation(
        score=round(score, 2),
        spacing=round(spacing_demand, 4),
        time_spacing=round(time_demand, 4),
        angle_variation=round(angle_demand, 4),
        pattern_repetition=round(repetition, 4),
        visual_clutter=round(clutter, 4),
    )


def _turn_angles(positioned) -> list[float]:
    angles: list[float] = []
    for left, mid, right in zip(positioned, positioned[1:], positioned[2:], strict=False):
        first = math.degrees(
            math.atan2(float(mid.y) - float(left.y), float(mid.x) - float(left.x))
        )
        second = math.degrees(
            math.atan2(float(right.y) - float(mid.y), float(right.x) - float(mid.x))
        )
        delta = abs((second - first + 180.0) % 360.0 - 180.0)
        angles.append(delta)
    return angles


def _pattern_repetition(gaps: list[int], turn_angles: list[float]) -> float:
    """Fraction of adjacent (gap, angle) pairs that repeat nearby."""
    if not gaps or not turn_angles:
        return 0.0
    pairs = [
        (round(gap / 20.0), round(angle / 15.0))
        for gap, angle in zip(gaps, turn_angles, strict=False)
    ]
    repeated = 0
    for index, pair in enumerate(pairs):
        if pair in pairs[max(0, index - 5) : index]:
            repeated += 1
    return repeated / len(pairs)


def _visual_clutter(positioned, distances, gaps, circle_radius: int) -> float:
    """Fraction of object pairs that are spatially close and temporally close."""
    if len(positioned) < 2:
        return 0.0
    radius = max(1, circle_radius)
    cluttered = 0
    total = 0
    for left, right, distance, gap in zip(
        positioned,
        positioned[1:],
        distances,
        gaps,
        strict=False,
    ):
        total += 1
        if distance < 2.5 * radius and abs(gap) < 300:
            cluttered += 1
    return cluttered / max(1, total)
