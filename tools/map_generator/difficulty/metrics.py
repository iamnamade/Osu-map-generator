from __future__ import annotations

import math

from .common import (
    bucket_count,
    clamp,
    coefficient_of_variation,
    longest_run,
    mean,
    normalize,
    standard_deviation,
)
from .loader import DifficultyObject, LoadedDifficultyMap
from .models import RawMetrics


def compute_raw_metrics(
    beatmap: LoadedDifficultyMap,
    *,
    stream_gap_ms: float = 190.0,
    burst_gap_ms: float = 300.0,
    recovery_gap_ms: float = 1200.0,
    high_density_gap_ms: float = 320.0,
    sharp_turn_deg: float = 110.0,
) -> RawMetrics:
    objects = beatmap.objects
    if not objects:
        return _empty_raw_metrics()

    active_duration_ms = max(1, objects[-1].time - objects[0].time)
    active_seconds = active_duration_ms / 1000.0
    object_count = len(objects)
    circle_count = sum(1 for item in objects if item.object_type == "circle")
    slider_count = sum(1 for item in objects if item.object_type == "slider")
    spinner_count = sum(1 for item in objects if item.object_type == "spinner")

    # Time gaps between consecutive objects (start-to-start).
    gaps_ms = [
        right.time - left.time
        for left, right in zip(objects, objects[1:], strict=False)
        if right.time > left.time
    ]

    # Jump distances / cursor velocity / acceleration across positioned objects.
    positioned = [item for item in objects if item.is_positioned]
    jump_distances: list[float] = []
    cursor_velocities: list[float] = []
    cursor_accelerations: list[float] = []
    for left, right in zip(positioned, positioned[1:], strict=False):
        distance = math.hypot(right.x - left.x, right.y - left.y)  # type: ignore[operator]
        jump_distances.append(distance)
        delta_ms = right.time - left.time
        if delta_ms > 0:
            cursor_velocities.append(distance / (delta_ms / 1000.0))

    for left_velocity, right_velocity in zip(
        cursor_velocities,
        cursor_velocities[1:],
        strict=False,
    ):
        cursor_accelerations.append(right_velocity - left_velocity)

    # Turn angles between three consecutive positioned objects.
    turn_angles: list[float] = []
    direction_change_count = 0
    for left, middle, right in zip(positioned, positioned[1:], positioned[2:], strict=False):
        angle = _turn_angle_deg(left, middle, right)
        if angle is not None:
            turn_angles.append(angle)
            if angle >= sharp_turn_deg:
                direction_change_count += 1

    # Streams and bursts are runs of objects with small gaps.
    stream_flags = [gap <= stream_gap_ms for gap in gaps_ms]
    burst_flags = [gap <= burst_gap_ms for gap in gaps_ms]
    longest_stream_length = longest_run(stream_flags) + 1
    longest_burst_length = longest_run(burst_flags) + 1

    # Slider complexity.
    slider_durations: list[float] = []
    slider_velocities: list[float] = []
    slider_repeats: list[float] = []
    for item in objects:
        if item.object_type != "slider" or item.pixel_length is None:
            continue
        duration_ms = item.duration_ms
        slider_durations.append(float(duration_ms))
        slider_repeats.append(float(item.repeats or 1))
        if duration_ms > 0:
            slider_velocities.append(item.pixel_length / (duration_ms / 1000.0))

    # Reaction time: time from an object to the next object start.
    reaction_times = gaps_ms

    # Recovery windows: gaps long enough to recover.
    recovery_window_count = sum(1 for gap in gaps_ms if gap >= recovery_gap_ms)

    # Pattern variation: distinct (distance bucket, velocity bucket) transitions.
    pattern_variation = _pattern_variation(positioned)

    # Stamina demand proxy: fraction of active time spent in high-density runs.
    stamina_demand = _stamina_demand_proxy(objects, high_density_gap_ms)

    # Rhythm complexity proxy: gap diversity + switch frequency.
    rhythm_complexity = _rhythm_complexity_proxy(gaps_ms)

    return RawMetrics(
        object_count=object_count,
        circle_count=circle_count,
        slider_count=slider_count,
        spinner_count=spinner_count,
        active_duration_ms=active_duration_ms,
        objects_per_second=object_count / active_seconds if active_seconds > 0 else 0.0,
        circle_density=circle_count / active_seconds if active_seconds > 0 else 0.0,
        slider_density=slider_count / active_seconds if active_seconds > 0 else 0.0,
        spinner_frequency_per_minute=spinner_count / max(1e-6, active_duration_ms / 60000.0),
        average_gap_ms=mean(gaps_ms) if gaps_ms else 0.0,
        minimum_gap_ms=min(gaps_ms) if gaps_ms else 0,
        maximum_gap_ms=max(gaps_ms) if gaps_ms else 0,
        gap_standard_deviation_ms=standard_deviation(gaps_ms) if gaps_ms else 0.0,
        average_jump_distance=mean(jump_distances) if jump_distances else 0.0,
        maximum_jump_distance=max(jump_distances) if jump_distances else 0.0,
        jump_distance_standard_deviation=standard_deviation(jump_distances) if jump_distances else 0.0,
        average_cursor_velocity_pps=mean(cursor_velocities) if cursor_velocities else 0.0,
        maximum_cursor_velocity_pps=max(cursor_velocities) if cursor_velocities else 0.0,
        average_cursor_acceleration_pps2=mean(cursor_accelerations) if cursor_accelerations else 0.0,
        angle_complexity=mean(turn_angles) if turn_angles else 0.0,
        direction_change_count=direction_change_count,
        longest_stream_length=longest_stream_length,
        longest_burst_length=longest_burst_length,
        average_slider_length_ms=mean(slider_durations) if slider_durations else 0.0,
        average_slider_velocity_pps=mean(slider_velocities) if slider_velocities else 0.0,
        average_slider_repeats=mean(slider_repeats) if slider_repeats else 0.0,
        slider_complexity=_slider_complexity(
            slider_velocities,
            slider_repeats,
            slider_count,
        ),
        average_reaction_time_ms=mean(reaction_times) if reaction_times else 0.0,
        minimum_reaction_time_ms=min(reaction_times) if reaction_times else 0,
        recovery_window_count=recovery_window_count,
        pattern_variation=pattern_variation,
        stamina_demand=stamina_demand,
        rhythm_complexity=rhythm_complexity,
    )


def compute_pair_diagnostics(beatmap: LoadedDifficultyMap) -> list[dict[str, float | int]]:
    """Per-pair diagnostics used by aim/reading/stamina modules."""
    positioned = [item for item in beatmap.objects if item.is_positioned]
    diagnostics: list[dict[str, float | int]] = []
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        distance = math.hypot(right.x - left.x, right.y - left.y)  # type: ignore[operator]
        delta_ms = max(1, right.time - left.time)
        diagnostics.append(
            {
                "fromId": left.id,
                "toId": right.id,
                "fromTimeMs": left.time,
                "toTimeMs": right.time,
                "distancePx": distance,
                "timeGapMs": delta_ms,
                "velocityPps": distance / (delta_ms / 1000.0),
            }
        )
    return diagnostics


def _turn_angle_deg(
    left: DifficultyObject,
    middle: DifficultyObject,
    right: DifficultyObject,
) -> float | None:
    if (
        left.x is None
        or left.y is None
        or middle.x is None
        or middle.y is None
        or right.x is None
        or right.y is None
    ):
        return None
    vector_a = (middle.x - left.x, middle.y - left.y)
    vector_b = (right.x - middle.x, right.y - middle.y)
    magnitude_a = math.hypot(*vector_a)
    magnitude_b = math.hypot(*vector_b)
    if magnitude_a <= 0 or magnitude_b <= 0:
        return None
    dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
    cosine = clamp(dot / (magnitude_a * magnitude_b), -1.0, 1.0)
    angle_rad = math.acos(cosine)
    angle_deg = math.degrees(angle_rad)
    # Normalize to [0, 180]; sharp turns are near 180.
    return angle_deg


def _pattern_variation(positioned: list[DifficultyObject]) -> float:
    if len(positioned) < 2:
        return 0.0
    buckets: set[tuple[int, int]] = set()
    transitions = 0
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        distance = math.hypot(right.x - left.x, right.y - left.y)  # type: ignore[operator]
        delta_ms = max(1, right.time - left.time)
        velocity = distance / (delta_ms / 1000.0)
        distance_bucket = int(distance // 48.0)
        velocity_bucket = int(velocity // 120.0)
        buckets.add((distance_bucket, velocity_bucket))
        transitions += 1
    return len(buckets) / max(1, transitions)


def _stamina_demand_proxy(
    objects: list[DifficultyObject],
    high_density_gap_ms: float,
) -> float:
    if len(objects) < 2:
        return 0.0
    positioned_times = [item.time for item in objects if item.is_positioned]
    if len(positioned_times) < 2:
        return 0.0
    active_duration = max(1, positioned_times[-1] - positioned_times[0])
    run_flags: list[bool] = []
    for left, right in zip(positioned_times, positioned_times[1:], strict=False):
        run_flags.append((right - left) <= high_density_gap_ms)
    longest_run_ms = 0.0
    current_start = positioned_times[0]
    previous_active = False
    for index, is_active in enumerate(run_flags):
        if is_active and not previous_active:
            current_start = positioned_times[index]
        if not is_active and previous_active:
            longest_run_ms = max(longest_run_ms, positioned_times[index] - current_start)
        previous_active = is_active
    if previous_active:
        longest_run_ms = max(longest_run_ms, positioned_times[-1] - current_start)
    continuous_share = longest_run_ms / active_duration
    return clamp(continuous_share * 2.0, 0.0, 1.0)


def _rhythm_complexity_proxy(gaps_ms: list[int]) -> float:
    if not gaps_ms:
        return 0.0
    mean_gap = mean(gaps_ms)
    if mean_gap <= 0:
        return 0.0
    switch_count = sum(
        1
        for left, right in zip(gaps_ms, gaps_ms[1:], strict=False)
        if (right - left) / max(1.0, mean_gap) >= 0.35
    )
    switch_ratio = switch_count / max(1, len(gaps_ms) - 1)
    gap_variety = bucket_count([float(gap) for gap in gaps_ms], 100.0) / max(
        1, len(gaps_ms)
    )
    return clamp(switch_ratio * 0.7 + gap_variety * 0.3, 0.0, 1.0)


def _slider_complexity(
    slider_velocities: list[float],
    slider_repeats: list[float],
    slider_count: int,
) -> float:
    if slider_count == 0:
        return 0.0
    velocity_component = normalize(mean(slider_velocities) if slider_velocities else 0.0, 900.0)
    repeat_component = clamp((mean(slider_repeats) - 1.0) / 3.0, 0.0, 1.0) if slider_repeats else 0.0
    return clamp(velocity_component * 0.6 + repeat_component * 0.4, 0.0, 1.0)


def _empty_raw_metrics() -> RawMetrics:
    return RawMetrics(
        object_count=0,
        circle_count=0,
        slider_count=0,
        spinner_count=0,
        active_duration_ms=1,
        objects_per_second=0.0,
        circle_density=0.0,
        slider_density=0.0,
        spinner_frequency_per_minute=0.0,
        average_gap_ms=0.0,
        minimum_gap_ms=0,
        maximum_gap_ms=0,
        gap_standard_deviation_ms=0.0,
        average_jump_distance=0.0,
        maximum_jump_distance=0.0,
        jump_distance_standard_deviation=0.0,
        average_cursor_velocity_pps=0.0,
        maximum_cursor_velocity_pps=0.0,
        average_cursor_acceleration_pps2=0.0,
        angle_complexity=0.0,
        direction_change_count=0,
        longest_stream_length=0,
        longest_burst_length=0,
        average_slider_length_ms=0.0,
        average_slider_velocity_pps=0.0,
        average_slider_repeats=0.0,
        slider_complexity=0.0,
        average_reaction_time_ms=0.0,
        minimum_reaction_time_ms=0,
        recovery_window_count=0,
        pattern_variation=0.0,
        stamina_demand=0.0,
        rhythm_complexity=0.0,
    )
