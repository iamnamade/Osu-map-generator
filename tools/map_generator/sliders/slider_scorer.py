from __future__ import annotations

import math
from typing import Any

from ..config import DifficultyPreset
from ..utils import clamp
from .slider_geometry import evaluate_path_smoothness, compute_slider_length, path_start_direction, path_end_direction
from .slider_models import ControlPoint, SliderPathType, SliderQualityScore, SliderShape


# Phase 21: expressive shapes add difficulty (loop/zigzag > wave > hook/arc).
_SHAPE_DIFFICULTY: dict[str, float] = {
    "linear": 0.0,
    "arc": 0.6,
    "hook": 0.8,
    "wave": 1.4,
    "zigzag": 1.8,
    "loop": 2.4,
}


def score_slider_candidate(
    *,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    control_points: list[ControlPoint],
    path_type: SliderPathType,
    repeats: int,
    pixel_length: float,
    sustained_score: float,
    energy: float,
    previous_distance: float,
    previous_angle: float | None,
    entry_angle_deg: float,
    exit_angle_deg: float,
    preset: DifficultyPreset,
    shape: SliderShape | None = None,
    flow_in_deg: float | None = None,
    flow_out_deg: float | None = None,
) -> SliderQualityScore:
    """Score a slider candidate on multiple quality axes.

    Returns a SliderQualityScore with 0-100 scores for each metric.
    Phase 21 adds flow-continuity (path tangents aligned with the incoming/
    outgoing cursor flow) and shape-aware difficulty. New parameters are
    optional so legacy callers keep identical behavior.
    """
    # 1. Musical match: how well the slider fits the audio
    musical_match = _score_musical_match(sustained_score, energy)

    # 2. Flow: cursor flow into and out of the slider
    flow = _score_flow(
        entry_angle_deg, exit_angle_deg,
        previous_angle, previous_distance,
    )

    # Phase 21: path tangent continuity with the surrounding cursor flow.
    continuity = _score_flow_continuity(
        control_points, start_x, start_y, path_type,
        flow_in_deg=flow_in_deg,
        flow_out_deg=flow_out_deg,
    )
    flow = flow * 0.7 + continuity * 0.3

    # 3. Shape quality: path smoothness and curvature
    smoothness = evaluate_path_smoothness(control_points, start_x, start_y, path_type)
    shape_quality = smoothness * 0.8 + _score_curvature(control_points, path_type) * 0.2

    # 4. Comfort: cursor comfort during slider follow
    comfort = _score_comfort(
        pixel_length, repeats, flow, smoothness, preset
    )

    # 5. Spacing: appropriate spacing relative to difficulty
    spacing = _score_spacing(
        start_x, start_y, end_x, end_y,
        pixel_length, previous_distance, preset,
    )

    # 6. Difficulty match (shape-aware in Phase 21)
    difficulty = _score_difficulty(
        pixel_length, repeats, path_type, preset,
        shape=shape,
    )

    # 7. Transition quality
    transition_quality = _score_transition(
        flow, spacing, comfort, previous_distance, preset
    )

    # Overall (weighted)
    overall = (
        musical_match * 0.20
        + flow * 0.20
        + shape_quality * 0.12
        + comfort * 0.16
        + spacing * 0.12
        + difficulty * 0.08
        + transition_quality * 0.12
    )

    return SliderQualityScore(
        musical_match=clamp(musical_match, 0, 100),
        flow=clamp(flow, 0, 100),
        shape_quality=clamp(shape_quality, 0, 100),
        comfort=clamp(comfort, 0, 100),
        spacing=clamp(spacing, 0, 100),
        difficulty=clamp(difficulty, 0, 100),
        transition_quality=clamp(transition_quality, 0, 100),
        overall=clamp(overall, 0, 100),
    )


def _score_musical_match(sustained_score: float, energy: float) -> float:
    """Score musical match based on sustained content and energy.

    Higher sustained score + moderate-high energy = good slider candidate.
    Percussive content (low sustained) = poor slider candidate.
    """
    base = sustained_score * 80.0
    if sustained_score > 0.4:
        base += energy * 20.0
    elif sustained_score > 0.2:
        base += energy * 10.0
    else:
        # Low sustained content - penalize
        base *= 0.3
    return base


def _score_flow_continuity(
    control_points: list[ControlPoint],
    start_x: int,
    start_y: int,
    path_type: SliderPathType,
    *,
    flow_in_deg: float | None,
    flow_out_deg: float | None,
) -> float:
    """Score how well the slider path continues the surrounding cursor flow.

    The path's starting tangent should follow the incoming flow and its
    ending tangent should point toward the outgoing flow. No flow context
    (or no measurable tangent) scores neutral 70 so phrase-less maps are
    unaffected.
    """
    if flow_in_deg is None and flow_out_deg is None:
        return 70.0

    start_tangent = path_start_direction(start_x, start_y, control_points, path_type)
    end_tangent = path_end_direction(start_x, start_y, control_points, path_type)
    contributions: list[float] = []

    if start_tangent is not None and flow_in_deg is not None:
        contributions.append(_flow_alignment(start_tangent, flow_in_deg))
    if end_tangent is not None and flow_out_deg is not None:
        contributions.append(_flow_alignment(end_tangent, flow_out_deg))

    if not contributions:
        return 70.0
    # Neutral 70; each aligned tangent pushes toward 100, each misaligned one
    # pushes toward 0 (alignment of 50 = no penalty).
    score = 70.0 + sum(contribution - 50.0 for contribution in contributions) / len(contributions)
    return max(0.0, min(100.0, score))


def _flow_alignment(actual_deg: float, expected_deg: float) -> float:
    """Return 0-100 alignment between two angles (180 = worst, 0 = best)."""
    difference = abs((actual_deg - expected_deg + 180.0) % 360.0 - 180.0)
    return max(0.0, 100.0 - difference * (100.0 / 120.0))


def _score_flow(
    entry_angle_deg: float,
    exit_angle_deg: float,
    previous_angle: float | None,
    previous_distance: float,
) -> float:
    """Score cursor flow into and out of the slider.

    Smooth entry/exit angles produce better flow.
    Sharp angles (>120 degrees) are penalized.
    """
    score = 80.0

    # Entry angle penalty
    if entry_angle_deg > 120:
        score -= (entry_angle_deg - 120) * 0.8
    elif entry_angle_deg < 20:
        score -= 10  # too shallow is also awkward

    # Exit angle penalty
    if exit_angle_deg > 120:
        score -= (exit_angle_deg - 120) * 0.6
    elif exit_angle_deg < 20:
        score -= 5

    # Large distance penalty
    if previous_distance > 200:
        score -= 10

    return max(0.0, score)


def _score_curvature(
    control_points: list[ControlPoint],
    path_type: SliderPathType,
) -> float:
    """Score the curvature quality of a slider path.

    Avoids: tiny curves, extreme bends, meaningless wiggles.
    """
    if path_type == "linear":
        return 80.0  # Linear is always fine
    if path_type == "perfect":
        return 85.0  # Perfect curves are smooth by nature
    if path_type == "bezier":
        if len(control_points) <= 2:
            return 75.0
        return max(60.0, 80.0 - (len(control_points) - 2) * 5.0)
    if path_type == "catmull":
        if len(control_points) <= 3:
            return 70.0
        return max(50.0, 75.0 - (len(control_points) - 3) * 8.0)
    return 70.0


def _score_comfort(
    pixel_length: float,
    repeats: int,
    flow: float,
    smoothness: float,
    preset: DifficultyPreset,
) -> float:
    """Score cursor comfort when following the slider.

    Very long sliders with many repeats are uncomfortable.
    Sharp paths are uncomfortable.
    """
    score = 70.0

    # Length penalty
    if pixel_length > 150:
        score -= (pixel_length - 150) * 0.15
    if pixel_length > 300:
        score -= (pixel_length - 300) * 0.2

    # Repeats penalty
    if repeats > 2:
        score -= (repeats - 2) * 12
    if repeats > 4:
        score = max(10.0, score - 20)

    # Flow bonus
    score += (flow - 50) * 0.3

    # Smoothness bonus
    score += (smoothness - 50) * 0.2

    return max(10.0, min(100.0, score))


def _score_spacing(
    start_x: int, start_y: int,
    end_x: int, end_y: int,
    pixel_length: float,
    previous_distance: float,
    preset: DifficultyPreset,
) -> float:
    """Score spacing appropriateness.

    Sliders should have appropriate spacing relative to difficulty.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)

    preferred = preset.preferred_jump_distance * 1.2
    deviation = abs(distance - preferred) / max(1.0, preferred)

    if deviation < 0.3:
        score = 100.0 - deviation * 50.0
    elif deviation < 0.6:
        score = 85.0 - (deviation - 0.3) * 80.0
    else:
        score = max(20.0, 61.0 - (deviation - 0.6) * 60.0)

    return score


def _score_difficulty(
    pixel_length: float,
    repeats: int,
    path_type: SliderPathType,
    preset: DifficultyPreset,
    shape: SliderShape | None = None,
) -> float:
    """Score difficulty appropriateness for the target difficulty."""
    if preset.name == "easy":
        ideal_length = 60.0
        ideal_repeats = 1
        simple_bonus = 1.0 if path_type == "linear" else 0.6
    elif preset.name == "normal":
        ideal_length = 90.0
        ideal_repeats = 1
        simple_bonus = 1.0 if path_type in ("linear", "perfect") else 0.8
    else:  # hard
        ideal_length = 120.0
        ideal_repeats = 2
        simple_bonus = 1.0

    # Phase 21: expressive shapes are inappropriate for easy maps and are a
    # plus on hard maps.
    shape_difficulty = _SHAPE_DIFFICULTY.get(shape or "linear", 0.0)
    if preset.name == "easy" and shape_difficulty > 0.8:
        simple_bonus *= max(0.2, 1.0 - shape_difficulty * 0.3)
    elif preset.name == "hard" and shape_difficulty > 0.0:
        simple_bonus = min(1.0, simple_bonus + shape_difficulty * 0.05)

    length_ratio = min(pixel_length, ideal_length * 2) / max(1.0, ideal_length)
    length_score = max(0.0, 100.0 - abs(length_ratio - 1.0) * 80.0)

    repeat_score = max(0.0, 100.0 - abs(repeats - ideal_repeats) * 20.0)

    return (length_score * 0.5 + repeat_score * 0.3) * simple_bonus + 10.0


def _score_transition(
    flow: float,
    spacing: float,
    comfort: float,
    previous_distance: float,
    preset: DifficultyPreset,
) -> float:
    """Score overall transition quality."""
    base = (flow * 0.4 + spacing * 0.3 + comfort * 0.3)

    if previous_distance > preset.max_jump_distance * 0.8:
        base -= 10.0

    return base
