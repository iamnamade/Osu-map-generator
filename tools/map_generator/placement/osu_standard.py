from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import DifficultyPreset
from ..models import GeneratedCircleHitObject, SelectedEvent
from ..utils import clamp, shortest_angle_delta
from ..variation import PositionVariation
from .base import PlacementContext, PlacementStrategy, PositionGenerationResult
from .flow_dynamics import FlowEngine

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from ..ml.markov_persona import MapperPersonaModel

PLAYFIELD_WIDTH = 512
PLAYFIELD_HEIGHT = 384
PLAYFIELD_CENTER = (PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2)

#: Slider velocity assumed when converting learned spacing into pixels. The
#: placement context carries audio analysis but no timing sections, so a
#: persona map is generated at the corpus' normalised 1.0x reference speed.
PERSONA_SLIDER_VELOCITY = 1.0


@dataclass(frozen=True)
class _Point:
    x: float
    y: float


class OsuStandardPlacementStrategy(PlacementStrategy):
    """Default osu!standard placement (512x384 playfield).

    Preserves the historical placement behaviour byte-for-byte: the pattern
    intelligence engine when enabled, and the classic jump-curve algorithm as
    the fallback. Subclasses can override ``transform_position`` to add a mode
    that only differs by coordinate mapping.
    """

    name = "standard"
    mode = "osu"

    def __init__(self, persona_model: "MapperPersonaModel | None" = None) -> None:
        """Create the standard placement strategy.

        Args:
            persona_model: Optional trained mapper-style model.  When given,
                placement is sampled from the model instead of the built-in
                pattern/jump-curve heuristics.
        """
        self.persona_model = persona_model

    @property
    def playfield_width(self) -> float:
        return float(PLAYFIELD_WIDTH)

    @property
    def playfield_height(self) -> float:
        return float(PLAYFIELD_HEIGHT)

    def generate(self, context: PlacementContext) -> PositionGenerationResult:
        events = context.events
        preset = context.preset
        seed = context.seed
        variation = context.variation
        pattern_config = context.pattern_config
        analysis = context.analysis

        if self.persona_model is not None:
            return self._generate_persona(context)

        if pattern_config is not None:
            from ..patterns.pattern_pipeline import generate_pattern_positions

            return generate_pattern_positions(
                events=events,
                preset=preset,
                seed=seed,
                variation=variation,
                pattern_config=pattern_config,
                analysis=analysis,
            )

        if preset.pattern_intelligence_enabled:
            from ..patterns.pattern_pipeline import (
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

        return self._generate_classic(
            events=events,
            preset=preset,
            seed=seed,
            variation=variation,
        )

    def _generate_persona(self, context: PlacementContext) -> PositionGenerationResult:
        """Sample object placement from a trained mapper persona.

        Timing, spacing and turn come from the Markov chain rather than from
        the selected events: the persona decides *when* the next object lands,
        not just where.  The map therefore ends when the predicted gaps run
        past the audio, or when it reaches the event count, whichever is first.

        Border handling is unchanged from the heuristics path: the centripetal
        deflection runs first so near-edge objects are steered inward, then the
        final clamp guarantees the coordinates stay inside the playfield.
        """
        from ..ml.corpus_parser import PIXELS_PER_BEAT, angle_bin_to_degrees

        model = self.persona_model
        if model is None:  # pragma: no cover - guarded by generate()
            raise ValueError("persona model is not configured")

        preset = context.preset
        analysis = context.analysis
        events = context.events

        bpm = float(getattr(analysis, "bpm", 0.0) or 0.0)
        if bpm <= 0:
            bpm = 120.0
        beat_ms = 60_000.0 / bpm

        start_ms = int(preset.start_padding_ms)
        duration_ms = int(getattr(analysis, "duration_ms", 0) or 0)
        if duration_ms > 0:
            end_ms = duration_ms - int(preset.end_padding_ms)
        elif events:
            end_ms = int(events[-1].time_ms)
        else:
            end_ms = start_ms + 60_000

        flow = FlowEngine(
            width=float(PLAYFIELD_WIDTH),
            height=float(PLAYFIELD_HEIGHT),
            margin=float(preset.safe_margin),
        )

        target_objects = max(1, len(events))
        min_gap_ms = max(1.0, float(preset.min_gap_ms))

        objects: list[GeneratedCircleHitObject] = []
        point = _Point(x=PLAYFIELD_CENTER[0], y=PLAYFIELD_CENTER[1])
        heading = 0.0
        current_time = start_ms
        previous_state = None
        current_state = model.sample_initial_state()

        while len(objects) < target_objects:
            next_state = model.predict_next_state(current_state, previous_state)

            gap_ms = max(min_gap_ms, next_state.delta_beats * beat_ms)
            object_time = int(round(current_time + gap_ms))
            if object_time > end_ms:
                break

            # Learned spacing is in beats of travel; convert back to pixels.
            spacing_px = max(0.0, next_state.spacing) * PIXELS_PER_BEAT * PERSONA_SLIDER_VELOCITY
            max_distance = preset.max_cursor_speed * (gap_ms / 1000.0)
            distance = clamp(
                spacing_px,
                preset.min_jump_distance,
                min(preset.max_jump_distance, max_distance),
            )
            if distance <= 0:
                distance = preset.min_jump_distance

            heading += math.radians(angle_bin_to_degrees(next_state.angle_bin))
            candidate = _Point(
                x=point.x + math.cos(heading) * distance,
                y=point.y + math.sin(heading) * distance,
            )
            deflected = flow.check_border_deflection((candidate.x, candidate.y), preset)
            point = self._finalize_point(_Point(x=deflected[0], y=deflected[1]), preset)

            objects.append(
                GeneratedCircleHitObject(
                    id=len(objects) + 1,
                    type="circle",
                    x=int(round(point.x)),
                    y=int(round(point.y)),
                    time=object_time,
                )
            )

            previous_state = current_state
            current_state = next_state
            current_time = object_time

        # A persona whose every sampled gap exceeds the track length would
        # otherwise yield an empty (invalid) map.
        if not objects and end_ms > start_ms:
            point = self._finalize_point(point, preset)
            objects.append(
                GeneratedCircleHitObject(
                    id=1,
                    type="circle",
                    x=int(round(point.x)),
                    y=int(round(point.y)),
                    time=min(int(round(start_ms + min_gap_ms)), end_ms),
                )
            )

        return PositionGenerationResult(objects=objects, rejected_candidates=0)

    def _generate_classic(
        self,
        *,
        events: list[SelectedEvent],
        preset: DifficultyPreset,
        seed: int,
        variation: PositionVariation | None,
    ) -> PositionGenerationResult:
        """Classic deterministic jump-curve placement (pattern engine off)."""
        rng = random.Random(seed)
        profile = variation or PositionVariation()
        objects: list[GeneratedCircleHitObject] = []
        points: list[_Point] = []
        rejected_candidates = 0

        # Flow dynamics: route every generated point through the steering-aware
        # engine so stream steps keep bounded angular deltas and border crossings
        # are deflected before any raw coordinate clamp is applied.
        flow = FlowEngine(width=float(PLAYFIELD_WIDTH), height=float(PLAYFIELD_HEIGHT),
                          margin=float(preset.safe_margin))

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
                # Remove hard coordinate clipping from the standard path and let
                # the flow engine own boundary steering; retain the circle radius
                # + safe margin inset so objects never sit on the playfield edge.
                point = _clamp_point(point, preset)
                if flow.check_border_deflection(point, preset):
                    point = flow.compute_next_position(
                        prev2=points[-2] if len(points) >= 2 else None,
                        prev1=points[-1],
                        distance=point.distance_to(points[-1]) if hasattr(point, "distance_to") else 40.0,
                        dt_ms=event.time_ms - (objects[-1].time if objects else event.time_ms),
                        seed=index,
                    )
                rejected_candidates += local_rejections

            point = self._finalize_point(point, preset)
            points.append(point)
            objects.append(
                GeneratedCircleHitObject(
                    id=index + 1,
                    type="circle",
                    x=int(round(point.x)),
                    y=int(round(point.y)),
                    time=event.time_ms,
                )
            )

        return PositionGenerationResult(
            objects=objects,
            rejected_candidates=rejected_candidates,
        )

    def _finalize_point(self, point: _Point, preset: DifficultyPreset) -> _Point:
        """Apply the mode coordinate hook, then clamp into the playfield."""
        x, y = self.transform_position(point.x, point.y)
        return _clamp_point(_Point(x=x, y=y), preset)


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
    objects: list[GeneratedCircleHitObject],
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


# Flow dynamics no longer owns candidate scoring or the standard-path clamp;
# those responsibilities live in FlowEngine (patched into the _next_point
# loop above).  This function is the single escape hatch the engine calls
# when no candidate clears the score threshold.

def _flow_standard_fallback(previous: _Point, center_angle: float, target_distance: float, preset: DifficultyPreset) -> _Point:
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

def _clamp_point(point: _Point, preset: DifficultyPreset) -> _Point:
    padding = preset.circle_radius + preset.safe_margin
    return _Point(
        x=clamp(point.x, padding, PLAYFIELD_WIDTH - padding),
        y=clamp(point.y, padding, PLAYFIELD_HEIGHT - padding),
    )

def _distance(left: _Point, right: _Point) -> float:
    return math.hypot(right.x - left.x, right.y - left.y)

def _inside_safe_area(point: _Point, preset: DifficultyPreset) -> bool:
    padding = preset.circle_radius + preset.safe_margin
    return padding <= point.x <= PLAYFIELD_WIDTH - padding and padding <= point.y <= PLAYFIELD_HEIGHT - padding


def _quadrant(point: _Point) -> tuple[int, int]:
    return (0 if point.x < PLAYFIELD_CENTER[0] else 1, 0 if point.y < PLAYFIELD_CENTER[1] else 1)

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
