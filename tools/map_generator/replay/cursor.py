from __future__ import annotations

import math

from ..difficulty.common import clamp
from ..difficulty.loader import LoadedDifficultyMap
from .models import CursorSegment, CursorSimulation, ReplayPlayerProfile

_COMFORT_JUMP_PX = 200.0
_SHARP_TURN_DEG = 110.0


def simulate_cursor(
    beatmap: LoadedDifficultyMap,
    player: ReplayPlayerProfile,
) -> CursorSimulation:
    """Simulate the cursor path between consecutive hit objects.

    Travel distance, velocity, acceleration, and turning angles are computed
    deterministically from object geometry. Large inefficient jumps, velocity
    near/over the player's cursor speed cap, and sharp turns raise a per-segment
    penalty which lowers the overall cursor efficiency.
    """
    positioned = [item for item in beatmap.objects if item.is_positioned]
    segments: list[CursorSegment] = []
    if len(positioned) < 2:
        return CursorSimulation(
            total_travel_px=0.0,
            average_velocity_pps=0.0,
            peak_velocity_pps=0.0,
            average_acceleration_pps2=0.0,
            sharp_turn_count=0,
            efficiency=1.0,
            segments=segments,
        )

    previous_angle_deg: float | None = None
    previous_velocity = 0.0
    sharp_turns = 0
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        dx = float(right.x) - float(left.x)
        dy = float(right.y) - float(left.y)
        distance = math.hypot(dx, dy)
        gap_ms = max(1, right.time - left.time)
        velocity = distance / (gap_ms / 1000.0)
        acceleration = (velocity - previous_velocity) / (gap_ms / 1000.0)
        angle = (
            _segment_turn_angle(previous_angle_deg, dx, dy)
            if previous_angle_deg is not None
            else 0.0
        )

        velocity_penalty = clamp(
            (velocity / max(1.0, player.cursor_speed_pps)) - 0.85,
            0.0,
            1.0,
        )
        jump_penalty = clamp((distance - _COMFORT_JUMP_PX) / 400.0, 0.0, 1.0)
        turn_penalty = clamp((angle - _SHARP_TURN_DEG) / 70.0, 0.0, 1.0) * 0.6
        penalty = clamp(
            velocity_penalty * 0.5 + jump_penalty * 0.3 + turn_penalty,
            0.0,
            1.0,
        )
        if angle >= _SHARP_TURN_DEG and distance > 40.0:
            sharp_turns += 1

        segments.append(
            CursorSegment(
                from_object_id=left.id,
                to_object_id=right.id,
                start_ms=left.time,
                end_ms=right.time,
                distance_px=round(distance, 2),
                velocity_pps=round(velocity, 2),
                acceleration_pps2=round(acceleration, 2),
                angle_deg=round(angle, 2),
                required_velocity_pps=round(velocity, 2),
                penalty=round(penalty, 4),
            )
        )
        previous_angle_deg = math.degrees(math.atan2(dy, dx))
        previous_velocity = velocity

    total_travel = sum(segment.distance_px for segment in segments)
    average_velocity = sum(segment.velocity_pps for segment in segments) / len(segments)
    peak_velocity = max(segment.velocity_pps for segment in segments)
    average_acceleration = (
        sum(abs(segment.acceleration_pps2) for segment in segments) / len(segments)
    )
    efficiency = clamp(
        1.0 - (sum(segment.penalty for segment in segments) / len(segments)),
        0.0,
        1.0,
    )
    return CursorSimulation(
        total_travel_px=round(total_travel, 2),
        average_velocity_pps=round(average_velocity, 2),
        peak_velocity_pps=round(peak_velocity, 2),
        average_acceleration_pps2=round(average_acceleration, 2),
        sharp_turn_count=sharp_turns,
        efficiency=round(efficiency, 4),
        segments=segments,
    )


def _segment_turn_angle(previous_angle_deg: float, dx: float, dy: float) -> float:
    current = math.degrees(math.atan2(dy, dx))
    delta = abs((current - previous_angle_deg + 180.0) % 360.0 - 180.0)
    return delta
