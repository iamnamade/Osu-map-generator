from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import DifficultyPreset
from ..utils import shortest_angle_delta
from .pattern_models import (
    CursorFlowDiagnostic,
    DirectionLabel,
    DirectionPlan,
)


@dataclass(frozen=True)
class FlowConfig:
    """Tunable parameters for flow evaluation."""

    max_sharp_angle_deg: float = 140.0
    comfort_speed_ratio: float = 0.85
    direction_stickiness: float = 0.7
    flow_window: int = 5


DEFAULT_FLOW_CONFIG = FlowConfig()


def evaluate_flow(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    time_gap_ms: int,
    previous_angle: float | None,
    previous_speed: float | None,
    preset: DifficultyPreset,
    config: FlowConfig = DEFAULT_FLOW_CONFIG,
) -> tuple[float, float | None, float | None, float | None]:
    """Evaluate cursor flow for a single movement.

    Returns (flow_score, angle_degrees, direction_change, cursor_speed).
    """
    dx = to_x - from_x
    dy = to_y - from_y
    distance = math.hypot(dx, dy)
    gap_seconds = max(0.001, time_gap_ms / 1000.0)
    speed = distance / gap_seconds

    angle = math.degrees(math.atan2(dy, dx))
    angle_rad = math.atan2(dy, dx)

    direction_change: float | None = None
    if previous_angle is not None:
        direction_change = abs(math.degrees(
            shortest_angle_delta(previous_angle, angle_rad)
        ))

    # Flow scoring
    flow_score = 100.0

    # Penalize sharp reversals with graduated severity
    if direction_change is not None:
        if direction_change > 170:
            # Near-180 reversal: very unnatural, heavy penalty
            flow_score -= 35
        elif direction_change > 140:
            # Sharp reversal: awkward movement
            flow_score -= (direction_change - 140) * 1.5 + 15
        elif direction_change > 110:
            # Moderate angle change: mild penalty
            flow_score -= (direction_change - 110) * 0.8
        elif direction_change > 90:
            # Slightly sharp: small penalty for readability
            flow_score -= (direction_change - 90) * 0.3
        # Smooth flow (under 90 degrees) gets a small bonus
        if direction_change < 60:
            flow_score += 5
        if direction_change < 30:
            flow_score += 5  # extra bonus for very smooth flow

    # Speed comfort check
    speed_ratio = speed / max(1.0, preset.max_cursor_speed)
    if speed_ratio > config.comfort_speed_ratio:
        flow_score -= (speed_ratio - config.comfort_speed_ratio) * 50
    if speed_ratio < 0.15:
        flow_score -= 10  # too slow feels awkward

    # Acceleration discomfort
    acceleration: float | None = None
    if previous_speed is not None and previous_speed > 0:
        acceleration = abs(speed - previous_speed) / gap_seconds
        if acceleration > preset.max_cursor_speed * 1.5:
            flow_score -= 15  # harsh acceleration

    return max(0.0, flow_score), angle, direction_change, speed


def build_flow_diagnostic(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    from_id: int,
    to_id: int,
    time_gap_ms: int,
    previous_angle: float | None,
    previous_speed: float | None,
    preset: DifficultyPreset,
) -> CursorFlowDiagnostic:
    """Build a detailed cursor flow diagnostic."""
    flow_score, angle, direction_change, speed = evaluate_flow(
        from_x=from_x, from_y=from_y,
        to_x=to_x, to_y=to_y,
        time_gap_ms=time_gap_ms,
        previous_angle=previous_angle,
        previous_speed=previous_speed,
        preset=preset,
    )
    distance = math.hypot(to_x - from_x, to_y - from_y)
    dx = to_x - from_x
    dy = to_y - from_y
    return CursorFlowDiagnostic(
        from_id=from_id,
        to_id=to_id,
        distance_px=distance,
        angle_deg=angle or 0.0,
        direction_change_deg=direction_change,
        speed_pps=speed,
        acceleration_pps2=None,
        flow_quality=flow_score,
        comfortable=flow_score >= 60.0,
    )


def plan_direction(
    recent_angles: list[float],
    event_index: int,
    preset: DifficultyPreset,
    rng: object,
) -> DirectionPlan:
    """Plan cursor direction based on recent movement history."""
    if not recent_angles:
        # No history — pick a random starting direction
        base_angle = getattr(rng, "uniform", lambda a, b: a + (b - a) * 0.5)(0.0, math.tau)
        return DirectionPlan(
            primary_direction="neutral",
            angle_radians=base_angle,
            clockwise=base_angle > 0,
            consistency=0.5,
        )

    # Analyze recent angles for consistency
    if len(recent_angles) >= 3:
        deltas = [
            shortest_angle_delta(recent_angles[i], recent_angles[i + 1])
            for i in range(len(recent_angles) - 1)
        ]
        mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
        consistency = 1.0 - min(1.0, abs(mean_delta) / math.pi)
        clockwise = mean_delta > 0
        avg_angle = math.atan2(
            sum(math.sin(a) for a in recent_angles) / len(recent_angles),
            sum(math.cos(a) for a in recent_angles) / len(recent_angles),
        )
    else:
        avg_angle = recent_angles[-1] if recent_angles else 0.0
        consistency = 0.5
        clockwise = True

    # Determine direction label
    deg = math.degrees(avg_angle) % 360
    if 45 <= deg < 135:
        label: DirectionLabel = "vertical_emphasis"
    elif 135 <= deg < 225:
        label = "left_flow"
    elif 225 <= deg < 315:
        label = "vertical_emphasis"
    else:
        label = "right_flow"

    # Plan when to switch
    if consistency > 0.7 and len(recent_angles) > 5:
        switch_time = None
    else:
        switch_time = None  # no forced switch

    return DirectionPlan(
        primary_direction=label,
        angle_radians=avg_angle,
        clockwise=clockwise,
        consistency=consistency,
        planned_switch_time_ms=switch_time,
    )


def score_flow_quality(
    flow_diagnostics: list[CursorFlowDiagnostic],
) -> float:
    """Score overall flow quality across a set of movements."""
    if not flow_diagnostics:
        return 100.0

    avg_flow = sum(d.flow_quality for d in flow_diagnostics) / len(flow_diagnostics)
    comfortable_ratio = sum(1 for d in flow_diagnostics if d.comfortable) / len(flow_diagnostics)

    # Penalize sections with many uncomfortable movements
    comfort_penalty = max(0, (1.0 - comfortable_ratio) - 0.3) * 50

    return max(0.0, avg_flow - comfort_penalty)
