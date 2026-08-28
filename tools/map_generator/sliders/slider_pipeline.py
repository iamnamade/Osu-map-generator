from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import DifficultyPreset
from ..models import (
    GeneratedCircleHitObject,
    GeneratedHitObject,
    GeneratedSliderHitObject,
    HitObjectPoint,
    SelectedEvent,
)
from ..position_generator import PLAYFIELD_CENTER, PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH, _Point
from ..utils import clamp
from .slider_decision import decide_slider
from .slider_geometry import (
    generate_shape_path,
    compute_slider_length,
    path_end_direction,
    path_start_direction,
)
from .slider_models import (
    ControlPoint,
    SliderCandidate,
    SliderDiagnostics,
    SliderPathType,
    SliderQualityScore,
    SustainedAnalysis,
)
from ..models import GeneratedSliderHitObject as _GeneratedSliderHitObject
from .slider_scorer import score_slider_candidate
from .sustained_analysis import analyze_sustained_content


@dataclass(frozen=True)
class SliderPipelineConfig:
    """Configuration for the slider intelligence pipeline."""

    slider_enabled: bool = True
    min_confidence_threshold: float = 0.2
    max_slider_ratio: float = 0.35  # max fraction of objects that can be sliders
    min_slider_ratio: float = 0.35  # minimum fraction of objects that must be sliders
    quality_threshold: float = 20.0  # lower quality threshold to accept more sliders
    fill_confidence_threshold: float = 0.08  # lower threshold for minimum-ratio fill pass


DEFAULT_SLIDER_CONFIG = SliderPipelineConfig()


def process_sliders(
    events: list[SelectedEvent],
    objects: list[GeneratedHitObject],
    points: list[_Point],
    *,
    sustained: SustainedAnalysis | None = None,
    samples: np.ndarray | None = None,
    sample_rate: int | None = None,
    preset: DifficultyPreset,
    seed: int,
    slider_config: SliderPipelineConfig | None = None,
    phrase_info: list[Any] | None = None,
) -> tuple[list[GeneratedHitObject], list[_Point], SliderDiagnostics]:
    """Process events and convert eligible circles to sliders.

    This is the main entry point for slider generation.
    It runs after initial circle placement and converts some circles
    to sliders based on sustained audio analysis, phrase strategy
    (Phase 20/21), and quality scoring.

    Args:
        events: All selected timing events
        objects: Generated hit objects (circles) from the pattern pipeline
        points: Position points corresponding to objects
        sustained: Pre-computed sustained analysis
        samples: Raw audio samples
        sample_rate: Audio sample rate
        preset: Difficulty preset
        seed: RNG seed for determinism
        slider_config: Slider pipeline configuration
        phrase_info: Phase 20 phrase list (PhraseInfo objects) used to shape
            slider length/curvature per phrase strategy

    Returns:
        (modified_objects, modified_points, diagnostics)
    """
    config = slider_config or DEFAULT_SLIDER_CONFIG
    if not config.slider_enabled:
        return objects, points, SliderDiagnostics()

    if sustained is None and samples is not None and sample_rate is not None:
        sustained = analyze_sustained_content(samples, sample_rate)
    if sustained is None:
        return objects, points, SliderDiagnostics()

    rng = random.Random(seed)
    diagnostics = SliderDiagnostics()
    max_sliders = max(1, int(len(objects) * config.max_slider_ratio))
    min_sliders = max(0, int(len(objects) * config.min_slider_ratio)) if config.min_slider_ratio > 0 else 0

    event_by_time: dict[int, SelectedEvent] = {e.time_ms: e for e in events}
    strategy_lookup = _build_strategy_lookup(phrase_info)

    new_objects: list[GeneratedHitObject] = []
    new_points: list[_Point] = []
    slider_count = 0
    quality_total = 0.0

    for i, obj in enumerate(objects):
        if slider_count >= max_sliders:
            new_objects.append(obj)
            new_points.append(points[i] if i < len(points) else _Point(0, 0))
            continue

        if obj.type != "circle":
            new_objects.append(obj)
            new_points.append(points[i] if i < len(points) else _Point(0, 0))
            continue

        event = event_by_time.get(obj.time)
        if event is None:
            new_objects.append(obj)
            new_points.append(points[i] if i < len(points) else _Point(0, 0))
            continue

        event_idx = _find_event_index(events, obj.time)
        prev_event = events[event_idx - 1] if event_idx > 0 else None
        next_event = events[event_idx + 1] if event_idx < len(events) - 1 else None
        prev_gap = obj.time - events[event_idx - 1].time_ms if event_idx > 0 else None
        next_gap = events[event_idx + 1].time_ms - obj.time if event_idx < len(events) - 1 else None

        candidate = decide_slider(
            event=event,
            event_index=event_idx,
            sustained=sustained,
            preset=preset,
            previous_event=prev_event,
            next_event=next_event,
            previous_gap_ms=prev_gap,
            next_gap_ms=next_gap,
            phrase_strategy=strategy_lookup(obj.time),
            rng=rng,
        )

        diagnostics.total_candidates += 1

        if candidate is None:
            new_objects.append(obj)
            new_points.append(points[i] if i < len(points) else _Point(0, 0))
            continue

        slider_result = _build_slider(obj, candidate, points, i, preset, rng, config)
        if slider_result is None:
            diagnostics.rejected_sliders += 1
            new_objects.append(obj)
            new_points.append(points[i] if i < len(points) else _Point(0, 0))
            continue

        slider_obj, end_point, quality = slider_result
        new_objects.append(slider_obj)
        new_points.append(_Point(x=end_point[0], y=end_point[1]))
        slider_count += 1
        diagnostics.accepted_sliders += 1
        quality_total += quality
        diagnostics.path_type_counts[slider_obj.path_type] = (
            diagnostics.path_type_counts.get(slider_obj.path_type, 0) + 1
        )
        diagnostics.shape_counts[candidate.preferred_shape] = (
            diagnostics.shape_counts.get(candidate.preferred_shape, 0) + 1
        )
        diagnostics.repeat_distribution[slider_obj.repeats] = (
            diagnostics.repeat_distribution.get(slider_obj.repeats, 0) + 1
        )

    # ---- Minimum slider ratio enforcement ----
    # If we haven't met the minimum slider ratio, do a second pass converting
    # more circles to sliders with relaxed quality thresholds.
    if min_sliders > 0 and slider_count < min_sliders:
        remaining_needed = min_sliders - slider_count
        second_pass_objects: list[GeneratedHitObject] = []
        second_pass_points: list[_Point] = []
        fill_count = 0

        for i, obj in enumerate(new_objects):
            if fill_count >= remaining_needed:
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            if obj.type != "circle":
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            # Skip first/last objects for safety
            if i == 0 or i == len(new_objects) - 1:
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            event = event_by_time.get(obj.time)
            if event is None:
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            event_idx = _find_event_index(events, obj.time)
            prev_event = events[event_idx - 1] if event_idx > 0 else None
            next_event = events[event_idx + 1] if event_idx < len(events) - 1 else None
            prev_gap = obj.time - events[event_idx - 1].time_ms if event_idx > 0 else None
            next_gap = events[event_idx + 1].time_ms - obj.time if event_idx < len(events) - 1 else None

            candidate = decide_slider(
                event=event,
                event_index=event_idx,
                sustained=sustained,
                preset=preset,
                previous_event=prev_event,
                next_event=next_event,
                previous_gap_ms=prev_gap,
                next_gap_ms=next_gap,
                phrase_strategy=strategy_lookup(obj.time),
                rng=rng,
            )

            if candidate is None:
                # Force-create a mild slider candidate for minimum ratio
                candidate = _force_slider_candidate(
                    event=event, event_index=event_idx, preset=preset,
                    next_gap_ms=next_gap, rng=rng,
                )
            if candidate is None:
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            slider_result = _build_slider(obj, candidate, new_points, i, preset, rng, config)
            if slider_result is None:
                second_pass_objects.append(obj)
                second_pass_points.append(new_points[i] if i < len(new_points) else _Point(0, 0))
                continue

            slider_obj, end_point, quality = slider_result
            second_pass_objects.append(slider_obj)
            second_pass_points.append(_Point(x=end_point[0], y=end_point[1]))
            fill_count += 1
            slider_count += 1
            diagnostics.accepted_sliders += 1
            quality_total += quality
            diagnostics.path_type_counts[slider_obj.path_type] = (
                diagnostics.path_type_counts.get(slider_obj.path_type, 0) + 1
            )

        new_objects = second_pass_objects
        new_points = second_pass_points

    if diagnostics.accepted_sliders > 0:
        total_length = sum(
            o.pixel_length
            for o in new_objects
            if isinstance(o, GeneratedSliderHitObject)
        )
        total_repeats = sum(
            o.repeats
            for o in new_objects
            if isinstance(o, GeneratedSliderHitObject)
        )
        diagnostics.average_length_px = total_length / diagnostics.accepted_sliders
        diagnostics.average_repeats = total_repeats / diagnostics.accepted_sliders
        diagnostics.average_quality_score = quality_total / diagnostics.accepted_sliders

    return new_objects, new_points, diagnostics


def _force_slider_candidate(
    event: SelectedEvent,
    event_index: int,
    preset: DifficultyPreset,
    next_gap_ms: int | None = None,
    rng: Any = None,
) -> SliderCandidate | None:
    """Force-create a slider candidate for minimum-ratio enforcement.

    Used when the natural slider pipeline hasn't met the minimum ratio.
    Creates a modest-length linear slider at the event's position.
    """
    length_ms = 180
    if next_gap_ms is not None and next_gap_ms > 200:
        length_ms = min(400, int(next_gap_ms * 0.45))

    end_time_ms = event.time_ms + length_ms
    pixel_length = max(60, int(length_ms * 0.55))

    return SliderCandidate(
        event_index=event_index,
        time_ms=event.time_ms,
        length_ms=length_ms,
        end_time_ms=end_time_ms,
        energy=event.energy,
        sustained_score=0.3,
        slider_probability=0.5,
        preferred_path_type="linear",
        preferred_repeats=1,
        preferred_pixel_length=pixel_length,
        preferred_shape="linear",
        preferred_curvature=0.0,
        phrase_strategy=None,
    )


def _build_strategy_lookup(
    phrase_info: list[Any] | None,
) -> Any:
    """Return a deterministic time -> phrase strategy resolver.

    Falls back to None (no phrase context) when no phrase structure exists,
    preserving legacy slider shaping for phrase-less maps.
    """
    if not phrase_info:
        return lambda time_ms: None
    sorted_phrases = sorted(phrase_info, key=lambda phrase: phrase.start_ms)

    def resolve(time_ms: int) -> str | None:
        for phrase in sorted_phrases:
            if phrase.contains(time_ms):
                return getattr(phrase, "strategy", None) or None
        return None

    return resolve


def _build_slider(
    circle_obj: GeneratedHitObject,
    candidate: SliderCandidate,
    points: list[_Point],
    index: int,
    preset: DifficultyPreset,
    rng: random.Random,
    config: SliderPipelineConfig,
) -> tuple[GeneratedSliderHitObject, tuple[int, int], float] | None:
    """Build a slider object from a circle and slider candidate."""
    if not hasattr(circle_obj, "x") or not hasattr(circle_obj, "y"):
        return None

    start_x = int(circle_obj.x)  # type: ignore[union-attr]
    start_y = int(circle_obj.y)  # type: ignore[union-attr]

    flow_in_deg = _flow_in_angle(points, index, start_x, start_y)
    end_x, end_y = _choose_slider_endpoint(
        start_x, start_y, points, index, candidate, preset, rng, flow_in_deg
    )
    flow_out_deg = _flow_out_angle(points, index, end_x, end_y)

    # Phase 21: expressive shape geometry (multi-segment paths with red
    # anchors for wave/zigzag/loop; flow-aligned tangents for hooks).
    path_type, control_points = generate_shape_path(
        start_x,
        start_y,
        end_x,
        end_y,
        candidate.preferred_shape,
        flow_in_deg=flow_in_deg,
        flow_out_deg=flow_out_deg,
        curvature=candidate.preferred_curvature,
    )

    if not control_points:
        return None

    pixel_length = int(round(
        compute_slider_length(control_points, start_x, start_y, path_type)
    ))
    pixel_length = max(20, min(400, pixel_length))

    repeats = candidate.preferred_repeats

    entry_angle = _compute_entry_angle(points, index, start_x, start_y)
    exit_angle = _compute_exit_angle(points, index, end_x, end_y)
    prev_dist = _compute_previous_distance(points, index, start_x, start_y)

    quality = score_slider_candidate(
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        control_points=control_points,
        path_type=path_type,
        repeats=repeats,
        pixel_length=float(pixel_length),
        sustained_score=candidate.sustained_score,
        energy=candidate.energy,
        previous_distance=prev_dist,
        previous_angle=_compute_prev_angle_from_points(points, index),
        entry_angle_deg=entry_angle,
        exit_angle_deg=exit_angle,
        preset=preset,
        shape=candidate.preferred_shape,
        flow_in_deg=flow_in_deg,
        flow_out_deg=flow_out_deg,
    )

    if quality.overall < config.quality_threshold:
        return None

    return (
        GeneratedSliderHitObject(
            id=circle_obj.id,
            type="slider",
            x=start_x,
            y=start_y,
            time=circle_obj.time,
            end_time=candidate.end_time_ms,
            path_type=path_type,
            control_points=[
                HitObjectPoint(x=cp.x, y=cp.y) for cp in control_points
            ],
            repeats=repeats,
            pixel_length=pixel_length,
        ),
        (end_x, end_y),
        quality.overall,
    )


def _choose_slider_endpoint(
    start_x: int, start_y: int,
    points: list[_Point],
    index: int,
    candidate: SliderCandidate,
    preset: DifficultyPreset,
    rng: random.Random,
    flow_in_deg: float | None,
) -> tuple[int, int]:
    """Choose where the slider should end.

    Phase 21: the endpoint continues the incoming cursor flow (so the slider
    starts along the player's motion) with a mild pull toward center for
    readability, plus deterministic variation via the seeded rng.
    """
    center_x, center_y = PLAYFIELD_CENTER
    if flow_in_deg is not None:
        angle = math.radians(flow_in_deg)
        center_angle = math.atan2(center_y - start_y, center_x - start_x)
        # Blend flow with a gentle center recovery pull.
        angle = angle * 0.85 + center_angle * 0.15
    else:
        angle = math.atan2(center_y - start_y, center_x - start_x)

    angle += (rng.random() - 0.5) * 0.4

    length = candidate.preferred_pixel_length
    end_x = clamp(int(round(start_x + math.cos(angle) * length)), 20, PLAYFIELD_WIDTH - 20)
    end_y = clamp(int(round(start_y + math.sin(angle) * length)), 20, PLAYFIELD_HEIGHT - 20)

    return end_x, end_y


def _flow_in_angle(
    points: list[_Point],
    index: int,
    start_x: int,
    start_y: int,
) -> float | None:
    """Direction the cursor is moving when it arrives at this slider."""
    if index > 0 and len(points) >= 2:
        prev = points[min(index - 1, len(points) - 1)]
        if math.hypot(start_x - prev.x, start_y - prev.y) > 4:
            return math.degrees(math.atan2(start_y - prev.y, start_x - prev.x))
    return None


def _flow_out_angle(
    points: list[_Point],
    index: int,
    end_x: int,
    end_y: int,
) -> float | None:
    """Direction the cursor should leave the slider (toward the next object)."""
    if index < len(points) - 1:
        nxt = points[min(index + 1, len(points) - 1)]
        if math.hypot(nxt.x - end_x, nxt.y - end_y) > 4:
            return math.degrees(math.atan2(nxt.y - end_y, nxt.x - end_x))
    return None


def _find_event_index(events: list[SelectedEvent], time_ms: int) -> int:
    """Find the index of an event by its time."""
    for i, e in enumerate(events):
        if e.time_ms == time_ms:
            return i
    return 0


def _compute_entry_angle(
    points: list[_Point],
    index: int,
    x: int, y: int,
) -> float:
    """Compute the entry angle to this slider (degrees)."""
    if len(points) >= 2 and index > 0:
        prev_idx = min(index - 1, len(points) - 1)
        prev = points[prev_idx]
        angle = math.degrees(math.atan2(y - prev.y, x - prev.x))
        return abs(angle % 360)
    return 0.0


def _compute_exit_angle(
    points: list[_Point],
    index: int,
    end_x: int, end_y: int,
) -> float:
    """Compute the exit angle from this slider (degrees)."""
    if index > 0:
        prev_idx = min(index - 1, len(points) - 1)
        prev = points[prev_idx]
        angle = math.degrees(math.atan2(end_y - prev.y, end_x - prev.x))
        return abs(angle % 360)
    return 0.0


def _compute_previous_distance(
    points: list[_Point],
    index: int,
    x: int, y: int,
) -> float:
    """Compute distance from previous point."""
    if index > 0 and len(points) >= 2:
        prev_idx = min(index - 1, len(points) - 1)
        return math.hypot(x - points[prev_idx].x, y - points[prev_idx].y)
    return 0.0


def _compute_prev_angle_from_points(
    points: list[_Point],
    index: int,
) -> float | None:
    """Compute the angle of the previous movement."""
    if len(points) >= 2 and index >= 2:
        p1 = points[index - 2]
        p2 = points[index - 1]
        return math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))
    return None
