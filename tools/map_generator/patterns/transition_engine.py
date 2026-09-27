from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import DifficultyPreset
from .pattern_models import PatternType


@dataclass(frozen=True)
class TransitionConfig:
    """Tunable parameters for pattern transitions."""

    # Transition compatibility scores (0=poor, 1=excellent)
    jump_to_stream_compatibility: float = 0.7
    stream_to_burst_compatibility: float = 0.8
    burst_to_triangle_compatibility: float = 0.6
    triangle_to_arc_compatibility: float = 0.75
    arc_to_jump_compatibility: float = 0.65
    stream_to_jump_compatibility: float = 0.5
    jump_to_jump_compatibility: float = 0.4  # penalize consecutive jumps
    stream_to_stream_compatibility: float = 0.5  # penalize long streams without change

    max_angle_jump_deg: float = 120.0


DEFAULT_TRANSITION_CONFIG = TransitionConfig()

# Pre-defined transition compatibility matrix
_TRANSITION_SCORES: dict[tuple[PatternType, PatternType], float] = {
    ("single", "single"): 0.7,
    ("single", "double"): 0.8,
    ("single", "jump"): 0.75,
    ("single", "stream"): 0.65,
    ("single", "burst"): 0.7,
    ("single", "arc"): 0.65,
    ("single", "center_recovery"): 0.9,
    ("double", "burst"): 0.75,
    ("double", "single"): 0.8,
    ("double", "jump"): 0.7,
    ("burst", "stream"): 0.7,
    ("burst", "single"): 0.75,
    ("burst", "double"): 0.7,
    ("burst", "triangle"): 0.6,
    ("stream", "burst"): 0.8,
    ("stream", "single"): 0.65,
    ("stream", "arc"): 0.7,
    ("stream", "staircase"): 0.75,
    ("stream", "wave"): 0.7,
    ("jump", "single"): 0.75,
    ("jump", "double"): 0.65,
    ("jump", "arc"): 0.65,
    ("jump", "triangle"): 0.6,
    ("jump", "center_recovery"): 0.85,
    ("triangle", "single"): 0.6,
    ("triangle", "jump"): 0.55,
    ("triangle", "arc"): 0.75,
    ("arc", "single"): 0.7,
    ("arc", "jump"): 0.65,
    ("arc", "wave"): 0.8,
    ("arc", "fan"): 0.75,
    ("zigzag", "single"): 0.6,
    ("zigzag", "staircase"): 0.7,
    ("wave", "stream"): 0.75,
    ("wave", "arc"): 0.8,
    ("wave", "single"): 0.65,
    ("staircase", "stream"): 0.7,
    ("staircase", "zigzag"): 0.7,
    ("fan", "single"): 0.65,
    ("fan", "arc"): 0.7,
    ("spiral", "single"): 0.6,
    ("spiral", "fan"): 0.7,
    ("center_recovery", "single"): 0.85,
    ("center_recovery", "jump"): 0.8,
    ("center_recovery", "stream"): 0.7,
    ("back_and_forth", "single"): 0.6,
    ("back_and_forth", "jump"): 0.55,
    ("back_and_forth", "staircase"): 0.7,
}


def score_transition(
    from_type: PatternType,
    to_type: PatternType,
    from_distance: float,
    to_distance: float,
    angle_change_deg: float | None,
    preset: DifficultyPreset,
    config: TransitionConfig = DEFAULT_TRANSITION_CONFIG,
) -> float:
    """Score the quality of a transition between two patterns.

    Returns 0-100 score. Higher is better.
    """
    score = 60.0  # base score

    # Compatibility bonus
    key = (from_type, to_type)
    compat = _TRANSITION_SCORES.get(key, 0.5)
    score += compat * 30

    # Distance continuity: penalize large distance changes
    if from_distance > 0 and to_distance > 0:
        distance_ratio = max(from_distance, to_distance) / max(1.0, min(from_distance, to_distance))
        if distance_ratio > 2.5:
            score -= 15
        elif distance_ratio > 1.8:
            score -= 8

    # Angle continuity penalty
    if angle_change_deg is not None and angle_change_deg > config.max_angle_jump_deg:
        score -= (angle_change_deg - config.max_angle_jump_deg) * 0.5

    # Penalize switching to the same pattern repeatedly
    if from_type == to_type:
        if from_type in ("jump", "cross_jump", "wide_jump"):
            score -= 15  # consecutive same-type jumps are boring
        elif from_type in ("stream",):
            score -= 10  # long streams without change
        elif from_type in ("single",):
            score -= 5

    return max(0.0, min(100.0, score))


def evaluate_transition_set(
    pattern_sequence: list[PatternType],
    distances: list[float],
    angle_changes: list[float | None],
    preset: DifficultyPreset,
) -> float:
    """Evaluate the overall transition quality of a pattern sequence."""
    if len(pattern_sequence) < 2:
        return 100.0

    total_score = 0.0
    for i in range(len(pattern_sequence) - 1):
        angle = angle_changes[i] if i < len(angle_changes) else None
        from_d = distances[i] if i < len(distances) else 0
        to_d = distances[i + 1] if i + 1 < len(distances) else 0
        score = score_transition(
            from_type=pattern_sequence[i],
            to_type=pattern_sequence[i + 1],
            from_distance=from_d,
            to_distance=to_d,
            angle_change_deg=angle,
            preset=preset,
        )
        total_score += score

    return total_score / max(1, len(pattern_sequence) - 1)
