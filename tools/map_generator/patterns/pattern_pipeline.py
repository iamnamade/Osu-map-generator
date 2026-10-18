from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..config import DifficultyPreset
from ..models import GeneratedCircleHitObject, SelectedEvent
from ..position_generator import (
    PLAYFIELD_CENTER,
    PLAYFIELD_HEIGHT,
    PLAYFIELD_WIDTH,
    PositionGenerationResult,
    _Point,
    _base_angle,
    _clamp_point,
    _distance,
    _first_point,
    _needs_center_recovery,
)
from ..utils import clamp
from ..variation import PositionVariation
from .flow_engine import build_flow_diagnostic, plan_direction
from ..placement.flow_dynamics import FlowEngine as FlowEngine
from .pattern_library import (
    generate_arc,
    generate_back_and_forth,
    generate_burst,
    generate_center_recovery,
    generate_double,
    generate_fan,
    generate_jump,
    generate_single,
    generate_spiral,
    generate_staircase,
    generate_stream,
    generate_triangle,
    generate_wave,
    generate_zigzag,
)
from .pattern_models import (
    CursorFlowDiagnostic,
    DirectionPlan,
    PatternDiagnostics,
    PatternPlacement,
    PatternType,
    PlayfieldHeatmap,
)
from .pattern_scorer import score_pattern_placement
from .spacing_model import (
    SpacingConfig,
    compute_difficulty_spacing,
    compute_spatial_balance,
)


@dataclass(frozen=True)
class PatternPipelineConfig:
    """Configuration for the pattern intelligence pipeline."""

    pattern_intelligence_enabled: bool = True
    spacing_config: SpacingConfig = field(default_factory=SpacingConfig)
    pattern_switch_interval: int = 4  # minimum objects before switching pattern
    max_pattern_repetition: int = 3  # max times same pattern can repeat consecutively
    min_transition_score: float = 30.0
    enable_flow_optimization: bool = True
    enable_heatmap_balancing: bool = True
    enable_velocity_modeling: bool = True


DEFAULT_PATTERN_CONFIG = PatternPipelineConfig()


def generate_pattern_positions(
    events: list[SelectedEvent],
    preset: DifficultyPreset,
    seed: int,
    *,
    variation: PositionVariation | None = None,
    pattern_config: PatternPipelineConfig | None = None,
    analysis: Any | None = None,
) -> PositionGenerationResult:
    """Generate positions using the Pattern Intelligence Engine.

    This is the main entry point for Phase 10 pattern-aware placement.
    Falls back gracefully when disabled.
    """
    effective_config = pattern_config or DEFAULT_PATTERN_CONFIG
    if not effective_config.pattern_intelligence_enabled:
        # Fall back to classic position generator
        from ..position_generator import generate_positions as fallback
        return fallback(events, preset, seed, variation=variation)

    rng = random.Random(seed)
    profile = variation or PositionVariation()
    playfield_heatmap = PlayfieldHeatmap()
    diagnostics = PatternDiagnostics()

    objects: list[GeneratedCircleHitObject] = []
    points: list[_Point] = []
    recent_angles: list[float] = []
    recent_speeds: list[float] = []
    recent_patterns: list[PatternType] = []
    flow_diagnostics: list[CursorFlowDiagnostic] = []
    accepted_placements: list[PatternPlacement] = []
    rejected_count = 0
    pattern_run_length = 0
    current_pattern: PatternType | None = None
    direction_plan: DirectionPlan | None = None
    skip_until = 0

    # Kiai section awareness: extract kiai data from analysis if available
    kiai_sections = getattr(analysis, 'kiai_sections', []) if analysis else []
    def _kiai_at(time_ms: int) -> float:
        for k in kiai_sections:
            if k.start_ms <= time_ms <= k.end_ms:
                return k.confidence
        return 0.0
    def _in_kiai(time_ms: int) -> bool:
        return any(k.start_ms <= time_ms <= k.end_ms for k in kiai_sections)

    # Flow dynamics: every cursor step is generated through the steering-aware
    # engine instead of raw coordinate arithmetic, so acute snap-backs and
    # border crossings are resolved by construction.
    flow = FlowEngine(width=float(preset.playfield_width), height=float(preset.playfield_height),
                      margin=float(preset.safe_margin))

    # Stack offset tracking for overlapping 1/2 and 1/4 beats
    beat_interval_ms = int(round(60000.0 / max(1.0, preset.target_gap_ms * 2.5)))
    recent_object_times: list[int] = []

    for index, event in enumerate(events):
        if index < skip_until:
            # This event was already consumed by a multi-point pattern.
            continue
        if index == 0:
            point, pattern = _place_first_pattern(
                event=event,
                preset=preset,
                rng=rng,
            )
            clamped = _clamp_point(point, preset)
            points.append(clamped)
            obj = _build_object(clamped, len(objects) + 1, event)
            objects.append(obj)
            playfield_heatmap.record(clamped.x, clamped.y)
            if pattern and current_pattern is None:
                current_pattern = pattern
                recent_patterns.append(pattern)
                pattern_run_length = 1
            continue

        previous = points[-1]
        previous_time = objects[-1].time
        delta_ms = max(1, event.time_ms - previous_time)
        delta_seconds = delta_ms / 1000

        # Compute base parameters
        previous_angle = _base_angle(points, rng)
        center_angle = math.atan2(
            PLAYFIELD_CENTER[1] - previous.y,
            PLAYFIELD_CENTER[0] - previous.x,
        )
        max_distance_by_speed = preset.max_cursor_speed * delta_seconds

        distance_scale = clamp(delta_ms / preset.target_gap_ms, 0.65, 1.85)
        energy_scale = 0.85 + event.energy * 0.38 * profile.energy_influence_multiplier
        strength_scale = 0.92 + event.strength * 0.24 * profile.strength_influence_multiplier
        base_jump_distance = preset.preferred_jump_distance * profile.preferred_jump_distance_multiplier

        # Determine kiai status for this event
        event_in_kiai = _in_kiai(event.time_ms)
        event_kiai_conf = _kiai_at(event.time_ms)

        target_distance = clamp(
            compute_difficulty_spacing(
                base_jump_distance * distance_scale * energy_scale * strength_scale,
                event.energy,
                event.is_emphasis,
                preset,
                kiai_confidence=event_kiai_conf,
                in_kiai=event_in_kiai,
            ),
            preset.min_jump_distance,
            min(preset.max_jump_distance, max_distance_by_speed),
        )
        target_distance = min(target_distance, max_distance_by_speed)

        # Boost spacing during kiai sections for more dramatic jumps
        if event_in_kiai and event_kiai_conf > 0.3:
            target_distance *= 1.0 + event_kiai_conf * 0.12

        # Direction planning
        place_direction = direction_plan.angle_radians if direction_plan else previous_angle

        # Decide which pattern to use
        needs_recovery = _needs_center_recovery(previous, preset)
        if needs_recovery:
            chosen_pattern: PatternType = "center_recovery"
        else:
            chosen_pattern = _select_pattern(
                index=index,
                event=event,
                preset=preset,
                rng=rng,
                profile=profile,
                current_pattern=current_pattern,
                pattern_run_length=pattern_run_length,
                recent_patterns=recent_patterns,
                needs_recovery=needs_recovery,
            )

        # Generate pattern points
        pattern_points: list[_Point] = []

        # Flow steering hook: every new point is produced by
        # FlowEngine.compute_next_position, which enforces bounded angular
        # deltas and centripetal border deflection before the point is used
        # by any pattern.
        engine = flow
        if chosen_pattern == "single":
            p = generate_single(
                _Point(x=previous.x, y=previous.y),
                event, preset, place_direction, target_distance, rng,
            )
            pattern_points = [p]
        elif chosen_pattern == "jump":
            p = generate_jump(
                _Point(x=previous.x, y=previous.y),
                event, preset, place_direction, target_distance * 1.3, rng,
            )
            pattern_points = [p]
        elif chosen_pattern == "double" and index + 1 < len(events):
            gap = events[index + 1].time_ms - event.time_ms
            if gap < preset.target_gap_ms * 0.6:
                p1, p2 = generate_double(
                    _Point(x=previous.x, y=previous.y),
                    events, index, preset, place_direction, target_distance, rng,
                )
                pattern_points = [p1, p2]
            else:
                p = generate_single(
                    _Point(x=previous.x, y=previous.y),
                    event, preset, place_direction, target_distance, rng,
                )
                pattern_points = [p]
        elif chosen_pattern == "burst" and index + 2 < len(events):
            burst_count = min(4, len(events) - index)
            pts = generate_burst(
                _Point(x=previous.x, y=previous.y),
                events, index, burst_count, preset,
                place_direction, target_distance * 0.5, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "stream" and index + 3 < len(events):
            stream_count = min(6, len(events) - index)
            pts = generate_stream(
                _Point(x=previous.x, y=previous.y),
                events, index, stream_count, preset,
                place_direction, target_distance * 0.6, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "triangle" and index + 2 < len(events):
            p1, p2, p3 = generate_triangle(
                _Point(x=previous.x, y=previous.y),
                events, index, preset, place_direction, target_distance, rng,
            )
            pattern_points = [p1, p2, p3]
        elif chosen_pattern == "arc" and index + 2 < len(events):
            arc_count = min(4, len(events) - index)
            pts = generate_arc(
                _Point(x=previous.x, y=previous.y),
                events, index, arc_count, preset,
                place_direction, target_distance * 0.8, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "zigzag" and index + 2 < len(events):
            zig_count = min(5, len(events) - index)
            pts = generate_zigzag(
                _Point(x=previous.x, y=previous.y),
                events, index, zig_count, preset,
                place_direction, target_distance * 0.75, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "wave" and index + 2 < len(events):
            wave_count = min(4, len(events) - index)
            pts = generate_wave(
                _Point(x=previous.x, y=previous.y),
                events, index, wave_count, preset,
                place_direction, target_distance * 0.7, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "staircase" and index + 2 < len(events):
            stair_count = min(4, len(events) - index)
            pts = generate_staircase(
                _Point(x=previous.x, y=previous.y),
                events, index, stair_count, preset,
                place_direction, target_distance * 0.7, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "back_and_forth" and index + 2 < len(events):
            bf_count = min(4, len(events) - index)
            pts = generate_back_and_forth(
                _Point(x=previous.x, y=previous.y),
                events, index, bf_count, preset,
                place_direction, target_distance * 0.6, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "fan" and index + 2 < len(events):
            fan_count = min(4, len(events) - index)
            pts = generate_fan(
                _Point(x=previous.x, y=previous.y),
                events, index, fan_count, preset,
                place_direction, target_distance, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "spiral" and index + 2 < len(events):
            spiral_count = min(4, len(events) - index)
            pts = generate_spiral(
                _Point(x=previous.x, y=previous.y),
                events, index, spiral_count, preset,
                place_direction, target_distance * 0.5, rng,
            )
            pattern_points = pts
        elif chosen_pattern == "center_recovery":
            p = generate_center_recovery(
                _Point(x=previous.x, y=previous.y),
                event, preset,
                PLAYFIELD_CENTER[0], PLAYFIELD_CENTER[1],
                target_distance, rng,
            )
            pattern_points = [p]
        else:
            p = generate_single(
                _Point(x=previous.x, y=previous.y),
                event, preset, place_direction, target_distance, rng,
            )
            pattern_points = [p]

        # Process pattern points. Each point of a multi-point pattern maps to a
        # distinct upcoming event (index + pi) so timestamps stay unique.
        for pi, pp in enumerate(pattern_points):
            # pp is a plain _Point (the pattern library returns positions only).
            # The flow engine rebuilds the coordinate from prev1 with the
            # requested Euclidean distance, applying angular flow + steering.
            px, py = flow.compute_next_position(
                prev2=points[-1] if pi > 0 else None,
                prev1=points[-1],
                distance=float(_distance(previous, pp)),
                dt_ms=delta_ms,
                seed=int(hash((index, pi, seed)) & 0xFFFFFFFF),
            )

            clamped = _Point(x=clamp(px, 0, PLAYFIELD_WIDTH), y=clamp(py, 0, PLAYFIELD_HEIGHT))
            clamped = _clamp_point(clamped, preset)

            # Score the placement
            prev_point = points[-1] if points else None
            last_angle = recent_angles[-1] if recent_angles else None
            last_speed = recent_speeds[-1] if recent_speeds else None
            prev_type = recent_patterns[-1] if recent_patterns else None

            # Determine the event this pattern point maps to
            point_event = event if pi == 0 else events[min(index + pi, len(events) - 1)]

            # Compute actual time gap for multipoint patterns
            actual_gap = delta_ms
            if pi > 0:
                next_idx = min(index + pi, len(events) - 1)
                prev_idx = min(index + pi - 1, len(events) - 1)
                actual_gap = events[next_idx].time_ms - events[prev_idx].time_ms
                actual_gap = max(1, actual_gap)

            score = score_pattern_placement(
                x=clamped.x, y=clamped.y,
                previous_x=prev_point.x if prev_point else PLAYFIELD_CENTER[0],
                previous_y=prev_point.y if prev_point else PLAYFIELD_CENTER[1],
                time_gap_ms=actual_gap,
                previous_angle=last_angle,
                previous_speed=last_speed,
                event_energy=event.energy,
                is_emphasis=event.is_emphasis,
                pattern_type=chosen_pattern,
                previous_pattern_type=prev_type,
                heatmap=playfield_heatmap,
                recent_types=recent_patterns,
                preset=preset,
                kiai_confidence=_kiai_at(point_event.time_ms),
                object_index=len(objects),
                total_objects=len(events),
            )

            if score.overall < 20 and len(objects) > 0:
                rejected_count += 1
                _increment_pattern_count(diagnostics.patterns_rejected, chosen_pattern)
                continue

            # Apply stack offset for overlapping 1/2 and 1/4 beats
            from ..patterns.spacing_model import compute_stack_offset
            stack_dx, stack_dy = compute_stack_offset(
                object_index=len(objects),
                time_ms=point_event.time_ms,
                previous_times=recent_object_times,
                beat_interval_ms=beat_interval_ms,
            )
            final_x = clamp(clamped.x + stack_dx, 0, PLAYFIELD_WIDTH)
            final_y = clamp(clamped.y + stack_dy, 0, PLAYFIELD_HEIGHT)

            # Record in heatmap
            playfield_heatmap.record(final_x, final_y, recent=True)
            recent_object_times.append(point_event.time_ms)
            if len(recent_object_times) > 12:
                recent_object_times = recent_object_times[-12:]

            # Build the object with stack-adjusted coordinates
            obj = GeneratedCircleHitObject(
                id=len(objects) + 1,
                type="circle",
                x=int(round(final_x)),
                y=int(round(final_y)),
                time=point_event.time_ms,
            )
            objects.append(obj)
            points.append(_Point(x=final_x, y=final_y))

            placement = PatternPlacement(
                x=int(round(clamped.x)),
                y=int(round(clamped.y)),
                time_ms=obj.time,
                angle_deg=math.degrees(math.atan2(
                    clamped.y - (prev_point.y if prev_point else PLAYFIELD_CENTER[1]),
                    clamped.x - (prev_point.x if prev_point else PLAYFIELD_CENTER[0]),
                )),
                distance_from_previous=_distance(prev_point or _Point(PLAYFIELD_CENTER[0], PLAYFIELD_CENTER[1]), clamped),
                cursor_speed_pps=(
                    _distance(prev_point or _Point(PLAYFIELD_CENTER[0], PLAYFIELD_CENTER[1]), clamped)
                    / max(0.001, delta_seconds)
                ),
                pattern_type=chosen_pattern,
                flow_score=score.flow,
            )
            accepted_placements.append(placement)

            # Update recent state
            new_angle = math.atan2(
                clamped.y - (prev_point.y if prev_point else PLAYFIELD_CENTER[1]),
                clamped.x - (prev_point.x if prev_point else PLAYFIELD_CENTER[0]),
            )
            recent_angles.append(new_angle)
            speed = _distance(prev_point or _Point(PLAYFIELD_CENTER[0], PLAYFIELD_CENTER[1]), clamped) / max(0.001, actual_gap / 1000)
            recent_speeds.append(speed)

            # Flow diagnostics
            if prev_point:
                fd = build_flow_diagnostic(
                    from_x=prev_point.x, from_y=prev_point.y,
                    to_x=clamped.x, to_y=clamped.y,
                    from_id=objects[-2].id if len(objects) >= 2 else 0,
                    to_id=obj.id,
                    time_gap_ms=actual_gap,
                    previous_angle=last_angle,
                    previous_speed=last_speed,
                    preset=preset,
                )
                flow_diagnostics.append(fd)

        # Mark all events covered by this pattern as consumed so the outer
        # loop does not re-place objects at the same timestamps.
        skip_until = max(skip_until, index + max(1, len(pattern_points)))

        # Update pattern tracking
        if chosen_pattern != current_pattern:
            pattern_run_length = 1
        else:
            pattern_run_length += 1
        current_pattern = chosen_pattern
        recent_patterns.append(chosen_pattern)
        _increment_pattern_count(diagnostics.patterns_used, chosen_pattern)

        # Update direction plan periodically
        if index % 8 == 0 and len(recent_angles) >= 3:
            direction_plan = plan_direction(
                recent_angles[-6:] if len(recent_angles) >= 6 else recent_angles,
                index,
                preset,
                rng,
            )

        # Clear recent heatmap entries after a while
        if index % 12 == 0:
            playfield_heatmap.clear_recent()

    # Build diagnostics summary
    diagnostics.accepted_placements = len(accepted_placements)
    diagnostics.rejected_placements = rejected_count
    diagnostics.cursor_flow_diagnostics = flow_diagnostics
    diagnostics.average_flow_score = (
        sum(p.flow_score for p in accepted_placements) / max(1, len(accepted_placements))
    )
    diagnostics.heatmap = playfield_heatmap
    diagnostics.spatial_balance_score = compute_spatial_balance(
        [p.x for p in points], [p.y for p in points]
    )

    return PositionGenerationResult(objects=objects, rejected_candidates=rejected_count)


def _place_first_pattern(
    event: SelectedEvent,
    preset: DifficultyPreset,
    rng: random.Random,
) -> tuple[_Point, PatternType]:
    """Place the first object in the map."""
    return _first_point(event, preset, rng), "single"


def _select_pattern(
    index: int,
    event: SelectedEvent,
    preset: DifficultyPreset,
    rng: random.Random,
    profile: PositionVariation,
    current_pattern: PatternType | None,
    pattern_run_length: int,
    recent_patterns: list[PatternType],
    needs_recovery: bool,
) -> PatternType:
    """Select the best pattern for the current placement."""
    if needs_recovery:
        return "center_recovery"

    # Weight available patterns. Phase 19 mapping controls adjust the base
    # weights through deterministic biases carried on the profile (stream and
    # burst intensity, pattern variety), so the controls genuinely change
    # which pattern families are produced.
    pattern_weights: dict[PatternType, float] = {
        "single": 1.0,
        "jump": 0.6 + profile.alternation_bias,
        "double": 0.4 + profile.arc_bias,
        "burst": 0.3 + profile.burst_bias + (0.2 if event.is_emphasis else 0.0),
        "stream": 0.2 + profile.continuation_bias + profile.stream_bias,
        "triangle": 0.25 + profile.triangle_bias,
        "arc": 0.35 + profile.arc_bias,
        "zigzag": 0.2 + profile.zigzag_bias,
        "wave": 0.2 + profile.wave_bias,
        "staircase": 0.15,
        "back_and_forth": 0.15,
        "fan": 0.15 + profile.fan_bias,
        "spiral": 0.1 + profile.spiral_bias,
    }

    # Adjust for difficulty
    if preset.name == "easy":
        pattern_weights["burst"] *= 0.3
        pattern_weights["stream"] *= 0.2
        pattern_weights["zigzag"] *= 0.5
        pattern_weights["triangle"] *= 0.5
    elif preset.name == "hard":
        pattern_weights["burst"] *= 1.5
        pattern_weights["stream"] *= 1.5
        pattern_weights["zigzag"] *= 1.3
        pattern_weights["jump"] *= 1.3
        pattern_weights["back_and_forth"] *= 1.5

    # Penalize recently used patterns
    for recent in recent_patterns[-4:]:
        if recent in pattern_weights:
            pattern_weights[recent] *= 0.5

    # Penalize the current pattern if it's been running too long
    if current_pattern and pattern_run_length >= 3:
        if current_pattern in pattern_weights:
            pattern_weights[current_pattern] *= 0.3

    # Select weighted random
    candidates_list = [(pt, w) for pt, w in pattern_weights.items() if w > 0.05]
    if not candidates_list:
        return "single"

    total_weight = sum(w for _, w in candidates_list)
    roll = rng.random() * total_weight
    cumulative = 0.0
    for pt, w in candidates_list:
        cumulative += w
        if roll <= cumulative:
            return pt

    return "single"


def _apply_safety(
    x: float, y: float,
    from_point: _Point,
    preset: DifficultyPreset,
) -> tuple[float, float]:
    """Apply basic safety checks to a candidate position."""
    padding = preset.circle_radius + preset.safe_margin
    cx = clamp(x, padding, PLAYFIELD_WIDTH - padding)
    cy = clamp(y, padding, PLAYFIELD_HEIGHT - padding)
    return cx, cy


def _build_object(
    point: _Point,
    obj_id: int,
    event: SelectedEvent,
) -> GeneratedCircleHitObject:
    return GeneratedCircleHitObject(
        id=obj_id,
        type="circle",
        x=int(round(point.x)),
        y=int(round(point.y)),
        time=event.time_ms,
    )


def _increment_pattern_count(
    counter: dict[str, int],
    pattern: PatternType,
) -> None:
    key = str(pattern)
    counter[key] = counter.get(key, 0) + 1
