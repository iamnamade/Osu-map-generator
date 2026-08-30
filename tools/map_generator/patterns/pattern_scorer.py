from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..config import DifficultyPreset
from ..utils import clamp, shortest_angle_delta
from .flow_engine import evaluate_flow
from .pattern_models import (
    PatternPlacement,
    PatternScore,
    PatternType,
    PlayfieldHeatmap,
)
from .transition_engine import score_transition
from .spacing_model import (
    PLAYFIELD_CENTER,
    PLAYFIELD_HEIGHT,
    PLAYFIELD_WIDTH,
    anti_center_bias,
    playfield_boundary_bonus,
)


@dataclass(frozen=True)
class ScorerConfig:
    """Weights for pattern scoring components."""

    flow_weight: float = 0.25
    spacing_weight: float = 0.15
    comfort_weight: float = 0.15
    readability_weight: float = 0.15
    difficulty_weight: float = 0.10
    novelty_weight: float = 0.10
    transition_weight: float = 0.10


DEFAULT_SCORER_CONFIG = ScorerConfig()


def score_pattern_placement(
    x: float,
    y: float,
    previous_x: float,
    previous_y: float,
    time_gap_ms: int,
    previous_angle: float | None,
    previous_speed: float | None,
    event_energy: float,
    is_emphasis: bool,
    pattern_type: PatternType,
    previous_pattern_type: PatternType | None,
    heatmap: PlayfieldHeatmap,
    recent_types: list[PatternType],
    preset: DifficultyPreset,
    scorer_config: ScorerConfig = DEFAULT_SCORER_CONFIG,
    kiai_confidence: float = 0.0,
    object_index: int = 0,
    total_objects: int = 0,
) -> PatternScore:
    """Score a single pattern placement candidate.

    Returns a comprehensive PatternScore with all sub-scores.
    """
    # 1. Flow score
    flow_score, _, direction_change, speed = evaluate_flow(
        from_x=previous_x, from_y=previous_y,
        to_x=x, to_y=y,
        time_gap_ms=time_gap_ms,
        previous_angle=previous_angle,
        previous_speed=previous_speed,
        preset=preset,
    )

    # 2. Spacing score
    distance = math.hypot(x - previous_x, y - previous_y)
    preferred = preset.preferred_jump_distance
    spacing_deviation = abs(distance - preferred) / max(1.0, preferred)
    spacing_score = max(0.0, 100.0 - spacing_deviation * 40.0)

    # 3. Comfort score
    comfort = flow_score  # flow is a proxy for comfort
    
    # Speed comfort
    gap_seconds = max(0.001, time_gap_ms / 1000.0)
    cursor_speed = distance / gap_seconds
    speed_ratio = cursor_speed / max(1.0, preset.max_cursor_speed)
    if speed_ratio > 0.9:
        comfort -= (speed_ratio - 0.9) * 60
    elif speed_ratio < 0.1:
        comfort -= 15  # too slow is uncomfortable

    # 4. Readability score
    readability = 100.0
    
    # Penalize edge proximity
    edge_x = min(x, PLAYFIELD_WIDTH - x)
    edge_y = min(y, PLAYFIELD_HEIGHT - y)
    edge_dist = min(edge_x, edge_y)
    if edge_dist < preset.circle_radius + 5:
        readability -= (preset.circle_radius + 5 - edge_dist) * 3

    # Penalize stacking (very close to previous)
    if distance < max(8.0, preset.min_jump_distance * 0.35):
        readability -= 25

    # 5. Difficulty score (matches target)
    if preset.name == "easy":
        target_speed_ratio = 0.35
    elif preset.name == "hard":
        target_speed_ratio = 0.65
    else:
        target_speed_ratio = 0.5

    difficulty_deviation = abs(speed_ratio - target_speed_ratio)
    difficulty_score = max(0.0, 100.0 - difficulty_deviation * 120.0)

    # 6. Novelty score (avoid repeating same pattern)
    novelty = 100.0
    if recent_types:
        same_count = sum(1 for t in recent_types[-4:] if t == pattern_type)
        novelty -= same_count * 15

    # 7. Transition quality
    transition_quality = 60.0
    if previous_pattern_type is not None:
        transition_quality = score_transition(
            from_type=previous_pattern_type,
            to_type=pattern_type,
            from_distance=distance,
            to_distance=distance,
            angle_change_deg=direction_change,
            preset=preset,
        )

    # 8. Anti-center-stacking penalty
    center_penalty = anti_center_bias(x, y, heatmap, preset.name)

    # 9. Playfield boundary bonus for full grid usage
    boundary_bonus = playfield_boundary_bonus(x, y, total_objects, object_index)

    # 10. Kiai section bonus: reward higher quality during chorus
    kiai_bonus = 0.0
    if kiai_confidence > 0.0 and event_energy >= preset.high_energy_threshold:
        kiai_bonus = kiai_confidence * 8.0

    # Overall weighted score
    overall = (
        flow_score * scorer_config.flow_weight
        + spacing_score * scorer_config.spacing_weight
        + comfort * scorer_config.comfort_weight
        + readability * scorer_config.readability_weight
        + difficulty_score * scorer_config.difficulty_weight
        + novelty * scorer_config.novelty_weight
        + transition_quality * scorer_config.transition_weight
        - center_penalty
        + boundary_bonus
        + kiai_bonus
    )

    return PatternScore(
        flow=max(0.0, min(100.0, flow_score)),
        spacing=max(0.0, min(100.0, spacing_score)),
        comfort=max(0.0, min(100.0, comfort)),
        readability=max(0.0, min(100.0, readability)),
        difficulty=max(0.0, min(100.0, difficulty_score)),
        novelty=max(0.0, min(100.0, novelty)),
        transition_quality=max(0.0, min(100.0, transition_quality)),
        overall=max(0.0, min(100.0, overall)),
    )


def score_pattern_set(
    placements: list[PatternPlacement],
    preset: DifficultyPreset,
) -> float:
    """Score an entire set of pattern placements.

    Returns overall quality score (0-100).
    """
    if not placements:
        return 0.0

    total_flow = sum(p.flow_score for p in placements)
    avg_flow = total_flow / len(placements)

    # Check variety
    types_used = set(p.pattern_type for p in placements)
    variety_bonus = min(len(types_used) * 5, 25)

    return min(100.0, avg_flow + variety_bonus)
