from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .config import DifficultyPreset
from .models import GeneratedHitObject, SelectedEvent
from .utils import clamp, shortest_angle_delta
from .variation import PositionVariation

PLAYFIELD_WIDTH = 512
PLAYFIELD_HEIGHT = 384
PLAYFIELD_CENTER = (PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2)


@dataclass(frozen=True)
class PositionGenerationResult:
    objects: list[GeneratedHitObject]
    rejected_candidates: int


@dataclass(frozen=True)
class _Point:
    x: float
    y: float


def generate_positions(
    events: list[SelectedEvent],
    preset: DifficultyPreset,
    seed: int,
    *,
    variation: PositionVariation | None = None,
    pattern_config: Any | None = None,
    analysis: Any | None = None,
) -> PositionGenerationResult:
    """Generate positions for hit objects.

    When pattern intelligence is enabled in the preset, delegates to the
    Pattern Intelligence Engine for more variety and higher-quality patterns.
    Otherwise, uses the classic deterministic placement algorithm.
    """
    if pattern_config is not None:
        from .patterns.pattern_pipeline import generate_pattern_positions
        return generate_pattern_positions(
            events=events,
            preset=preset,
            seed=seed,
            variation=variation,
            pattern_config=pattern_config,
            analysis=analysis,
        )

    if preset.pattern_intelligence_enabled:
        from .patterns.pattern_pipeline import (
            DEFAULT_PATTERN_CONFIG,
            generate_pattern_positions,
        )
        return generate_pattern_positions(
            events=events,
            preset=preset,
            seed=seed,
            variation=variation,
            pattern_config=DEFAULT_PATTERN_CONFIG,
            analysis=analysis,
        )

    # Classic fallback
    rng = random.Random(seed)
    profile = variation or PositionVariation()
    objects: list[GeneratedHitObject] = []
    points: list[_Point] = []
    rejected_candidates = 0

    for index, event in enumerate(events):
        if index == 0:
            point = _first_point(event, preset, rng)
        else:
            point, local_rejections = _next_point(
                event=event,
                event_index=index,
                preset=preset,
                profile=profile,
                rng=rng,
                points=points,
                objects=objects,
            )
            rejected_candidates += local_rejections

        point = _clamp_point(point, preset)
        points.append(point)
        objects.append(
            GeneratedHitObject(
                id=index + 1,
                type="circle",
                x=int(round(point.x)),
                y=int(round(point.y)),
                time=event.time_ms,
            )
        )

    return PositionGenerationResult(objects=objects, rejected_candidates=rejected_candidates)


def _first_point(event: SelectedEvent, preset: DifficultyPreset, rng: random.Random) -> _Point:
    spread_x = 64 + event.energy * 42
    spread_y = 52 + event.energy * 34
    return _Point(
        x=PLAYFIELD_CENTER[0] + rng.uniform(-spread_x, spread_x),
        y=PLAYFIELD_CENTER[1] + rng.uniform(-spread_y, spread_y),
    )


def _next_point(
    event: SelectedEvent,
    event_index: int,
    preset: DifficultyPreset,
    profile: PositionVariation,
    rng: random.Random,
    points: list[_Point],
    objects: list[GeneratedHitObject],
) -> tuple[_Point, int]:
    previous = points[-1]
    previous_event_time = objects[-1].time
    delta_ms = max(1, event.time_ms - previous_event_time)
    delta_seconds = delta_ms / 1000

    previous_angle = _base_angle(points, rng)
    center_angle = math.atan2(PLAYFIELD_CENTER[1] - previous.y, PLAYFIELD_CENTER[0] - previous.x)
    max_distance_by_speed = preset.max_cursor_speed * delta_seconds
    distance_scale = clamp(delta_ms / preset.target_gap_ms, 0.65, 1.85)
    energy_scale = 0.85 + event.energy * 0.38 * profile.energy_influence_multiplier
    strength_scale = 0.92 + event.strength * 0.24 * profile.strength_influence_multiplier
    preferred_distance = preset.preferred_jump_distance * profile.preferred_jump_distance_multiplier

    target_distance = clamp(
        preferred_distance * distance_scale * energy_scale * strength_scale,
        preset.min_jump_distance,
        min(preset.max_jump_distance, max_distance_by_speed),
    )
    target_distance = min(target_distance, max_distance_by_speed)

    candidates = _build_candidates(
        previous=previous,
        previous_angle=previous_angle,
        center_angle=center_angle,
        target_distance=target_distance,
        event=event,
        event_index=event_index,
        preset=preset,
        profile=profile,
        rng=rng,
    )

    best_point: _Point | None = None
    best_score = float("-inf")
    rejected = 0

    for candidate in candidates:
        score = _score_candidate(
            candidate=candidate,
            previous=previous,
            points=points,
            delta_seconds=delta_seconds,
            target_distance=target_distance,
            previous_angle=previous_angle,
            center_angle=center_angle,
            event=event,
            preset=preset,
            profile=profile,
        )

        if score is None:
            rejected += 1
            continue

        if score > best_score:
            best_point = candidate
            best_score = score

    if best_point is None:
        fallback = _fallback_point(previous, center_angle, target_distance, preset)
        return fallback, rejected

    return best_point, rejected


def _build_candidates(
    previous: _Point,
    previous_angle: float,
    center_angle: float,
    target_distance: float,
    event: SelectedEvent,
    event_index: int,
    preset: DifficultyPreset,
    profile: PositionVariation,
    rng: random.Random,
) -> list[_Point]:
    variation = clamp(preset.pattern_variation * profile.pattern_variation_multiplier, 0.05, 1.25)
    turn_sign = 1 if rng.random() >= 0.5 else -1

    if _needs_center_recovery(previous, preset):
        selected_modes = ["center_recover"]
    else:
        mode_scores = {
            "continue": 1.0 + profile.continuation_bias + (0.08 if event_index % 2 == 1 else 0.0),
            "arc": 0.66 + profile.arc_bias + (0.34 if event.is_emphasis and variation > 0.28 else 0.0),
            "alternate": 0.86 + profile.alternation_bias + (0.16 if event_index % 2 == 0 else -0.04),
            "triangle": 0.48 + profile.triangle_bias + (0.26 if event_index % 5 == 0 and variation > 0.46 else 0.0),
        }
        selected_modes = [
            item[0]
            for item in sorted(mode_scores.items(), key=lambda item: (-item[1], item[0]))[:2]
        ]

    angle_sets = {
        "continue": [previous_angle, previous_angle + turn_sign * 0.28, previous_angle - turn_sign * 0.22],
        "arc": [previous_angle + turn_sign * 0.72, previous_angle + turn_sign * 0.52, previous_angle + turn_sign * 0.32],
        "alternate": [previous_angle + turn_sign * 1.08, previous_angle - turn_sign * 0.78, previous_angle + turn_sign * 0.58],
        "triangle": [previous_angle + turn_sign * 2.05, previous_angle + turn_sign * 1.02, previous_angle - turn_sign * 0.92],
        "center_recover": [center_angle, center_angle + turn_sign * 0.35, center_angle - turn_sign * 0.35],
    }

    distance_multipliers = [0.78, 0.94, 1.0, 1.14, 1.28 if event.energy >= preset.high_energy_threshold else 1.1]
    candidates: list[_Point] = []

    for mode in selected_modes:
        for angle in angle_sets[mode]:
            for distance_multiplier in distance_multipliers:
                jitter = (rng.random() - 0.5) * variation * 0.34 * profile.direction_jitter_multiplier
                distance = target_distance * distance_multiplier
                candidates.append(
                    _Point(
                        x=previous.x + math.cos(angle + jitter) * distance,
                        y=previous.y + math.sin(angle + jitter) * distance,
                    )
                )

    for index in range(8):
        spiral_angle = center_angle + (index - 3.5) * 0.44 + (rng.random() - 0.5) * variation * 0.2
        spiral_distance = target_distance * (0.74 + index * 0.05)
        candidates.append(
            _Point(
                x=previous.x + math.cos(spiral_angle) * spiral_distance,
                y=previous.y + math.sin(spiral_angle) * spiral_distance,
            )
        )

    return candidates


def _score_candidate(
    candidate: _Point,
    previous: _Point,
    points: list[_Point],
    delta_seconds: float,
    target_distance: float,
    previous_angle: float,
    center_angle: float,
    event: SelectedEvent,
    preset: DifficultyPreset,
    profile: PositionVariation,
) -> float | None:
    candidate = _clamp_point(candidate, preset)

    if not _inside_safe_area(candidate, preset):
        return None

    distance = _distance(previous, candidate)
    speed = distance / delta_seconds

    if speed > preset.max_cursor_speed + 1e-6:
        return None

    score = 100.0
    score -= abs(distance - target_distance) / max(target_distance, 1.0) * 26

    if distance < max(16.0, preset.min_jump_distance * 0.45):
        score -= 26

    if distance > preset.max_jump_distance:
        return None

    if len(points) >= 2:
        previous_previous = points[-2]
        new_angle = math.atan2(candidate.y - previous.y, candidate.x - previous.x)
        angle_delta = shortest_angle_delta(previous_angle, new_angle)

        if abs(abs(angle_delta) - math.pi) < 0.2:
            score -= 20 * profile.repetition_penalty_multiplier

        if abs(angle_delta) < 0.14:
            score -= 9 * profile.repetition_penalty_multiplier

        if _distance(candidate, previous_previous) < preset.min_jump_distance * 0.72:
            score -= 16 * profile.repetition_penalty_multiplier

        if event.energy < preset.high_energy_threshold:
            score -= abs(angle_delta) * 5
        else:
            score += min(abs(angle_delta), 1.25) * 3

    recent_points = points[-4:]
    for recent in recent_points:
        recent_distance = _distance(candidate, recent)
        if recent_distance < preset.min_jump_distance * 0.65:
            score -= (
                (preset.min_jump_distance * 0.65 - recent_distance)
                * 0.42
                * profile.recent_position_penalty_multiplier
            )

    if _is_near_edge(candidate, preset) and _is_near_edge(previous, preset):
        score -= 8 * profile.edge_penalty_multiplier

    if _quadrant(candidate) == _quadrant(previous) and sum(
        1 for recent in recent_points if _quadrant(recent) == _quadrant(candidate)
    ) >= 3:
        score -= 8 * profile.repetition_penalty_multiplier

    center_distance = _distance(candidate, _Point(*PLAYFIELD_CENTER))
    previous_center_distance = _distance(previous, _Point(*PLAYFIELD_CENTER))
    if _needs_center_recovery(previous, preset) and center_distance < previous_center_distance:
        score += 8 * profile.center_recovery_multiplier

    if event.energy < preset.high_energy_threshold and center_distance > previous_center_distance + 12:
        score -= 5 * profile.center_recovery_multiplier

    if event.energy >= preset.high_energy_threshold and distance >= preset.preferred_jump_distance:
        score += 6

    center_direction_delta = abs(shortest_angle_delta(center_angle, math.atan2(candidate.y - previous.y, candidate.x - previous.x)))
    if _needs_center_recovery(previous, preset) and center_direction_delta < 0.45:
        score += 5 * profile.center_recovery_multiplier

    return score


def _fallback_point(
    previous: _Point,
    center_angle: float,
    target_distance: float,
    preset: DifficultyPreset,
) -> _Point:
    fallback = _Point(
        x=previous.x + math.cos(center_angle) * target_distance * 0.82,
        y=previous.y + math.sin(center_angle) * target_distance * 0.82,
    )
    return _clamp_point(fallback, preset)


def _base_angle(points: list[_Point], rng: random.Random) -> float:
    if len(points) < 2:
        return rng.uniform(0.0, math.tau)

    previous = points[-1]
    previous_previous = points[-2]
    return math.atan2(previous.y - previous_previous.y, previous.x - previous_previous.x)


def _inside_safe_area(point: _Point, preset: DifficultyPreset) -> bool:
    padding = preset.circle_radius + preset.safe_margin
    return padding <= point.x <= PLAYFIELD_WIDTH - padding and padding <= point.y <= PLAYFIELD_HEIGHT - padding


def _clamp_point(point: _Point, preset: DifficultyPreset) -> _Point:
    padding = preset.circle_radius + preset.safe_margin
    return _Point(
        x=clamp(point.x, padding, PLAYFIELD_WIDTH - padding),
        y=clamp(point.y, padding, PLAYFIELD_HEIGHT - padding),
    )


def _distance(left: _Point, right: _Point) -> float:
    return math.hypot(right.x - left.x, right.y - left.y)


def _needs_center_recovery(point: _Point, preset: DifficultyPreset) -> bool:
    padding = preset.circle_radius + preset.safe_margin + 16
    return (
        point.x < padding
        or point.x > PLAYFIELD_WIDTH - padding
        or point.y < padding
        or point.y > PLAYFIELD_HEIGHT - padding
    )


def _is_near_edge(point: _Point, preset: DifficultyPreset) -> bool:
    padding = preset.circle_radius + preset.safe_margin + 8
    return (
        point.x < padding
        or point.x > PLAYFIELD_WIDTH - padding
        or point.y < padding
        or point.y > PLAYFIELD_HEIGHT - padding
    )


def _quadrant(point: _Point) -> tuple[int, int]:
    return (0 if point.x < PLAYFIELD_CENTER[0] else 1, 0 if point.y < PLAYFIELD_CENTER[1] else 1)
