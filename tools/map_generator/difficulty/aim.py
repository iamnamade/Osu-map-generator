from __future__ import annotations

import math

from .common import clamp, mean, normalize
from .loader import LoadedDifficultyMap
from .metrics import compute_pair_diagnostics
from .models import AimMetrics


def analyze_aim(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    max_cursor_speed: float = 860.0,
) -> AimMetrics:
    """Estimate aim/cursor-control demand: distance, speed, precision, angle,
    sharp turns, flow, micro-adjustments, large jumps."""
    positioned = [item for item in beatmap.objects if item.is_positioned]
    pairs = compute_pair_diagnostics(beatmap)
    if not pairs:
        return AimMetrics(
            distance_demand=0.0,
            speed_demand=0.0,
            precision_demand=0.0,
            angle_demand=0.0,
            sharp_turn_count=0,
            flow_quality=0.0,
            micro_adjustment_count=0,
            large_jump_count=0,
            score=0.0,
        )

    distances = [float(pair["distancePx"]) for pair in pairs]
    velocities = [float(pair["velocityPps"]) for pair in pairs]
    time_gaps = [float(pair["timeGapMs"]) for pair in pairs]
    average_distance = mean(distances)
    average_velocity = mean(velocities)

    # Distance demand relative to playfield diagonal.
    playfield_diagonal = math.hypot(512.0, 384.0)
    distance_demand = normalize(average_distance, playfield_diagonal * 0.45)

    # Speed demand relative to the hardest preset's max cursor speed.
    speed_demand = normalize(average_velocity, max_cursor_speed)

    # Precision demand: short gaps that still require small accurate movement.
    micro_adjustment_count = sum(
        1
        for pair in pairs
        if float(pair["distancePx"]) <= 42.0 and float(pair["timeGapMs"]) <= 320.0
    )
    precision_demand = normalize(
        micro_adjustment_count / max(1, len(pairs)),
        0.22,
    )

    # Angle demand: sharp turns over 110 degrees.
    turn_angles = _turn_angles(positioned)
    sharp_turn_count = sum(1 for angle in turn_angles if angle >= 110.0)
    average_turn = mean(turn_angles) if turn_angles else 0.0
    angle_demand = normalize(average_turn, 90.0)

    # Flow quality: fraction of turns that are smooth (under 30 degrees).
    smooth_turns = sum(1 for angle in turn_angles if angle <= 30.0) if turn_angles else 0
    flow_quality = smooth_turns / max(1, len(turn_angles)) if turn_angles else 0.0

    # Large jumps over 55% of the diagonal.
    large_jump_count = sum(1 for distance in distances if distance >= playfield_diagonal * 0.55)

    aim_score = (
        distance_demand * 0.35
        + speed_demand * 0.3
        + precision_demand * 0.1
        + angle_demand * 0.15
        + normalize(large_jump_count / max(1, len(pairs)), 0.12) * 0.1
    )
    aim_score = clamp(aim_score, 0.0, 1.0)

    return AimMetrics(
        distance_demand=round(distance_demand, 4),
        speed_demand=round(speed_demand, 4),
        precision_demand=round(precision_demand, 4),
        angle_demand=round(angle_demand, 4),
        sharp_turn_count=sharp_turn_count,
        flow_quality=round(flow_quality, 4),
        micro_adjustment_count=micro_adjustment_count,
        large_jump_count=large_jump_count,
        score=aim_score,
    )


def _turn_angles(positioned) -> list[float]:
    angles: list[float] = []
    for left, middle, right in zip(positioned, positioned[1:], positioned[2:], strict=False):
        if (
            left.x is None
            or left.y is None
            or middle.x is None
            or middle.y is None
            or right.x is None
            or right.y is None
        ):
            continue
        vector_a = (middle.x - left.x, middle.y - left.y)
        vector_b = (right.x - middle.x, right.y - middle.y)
        magnitude_a = math.hypot(*vector_a)
        magnitude_b = math.hypot(*vector_b)
        if magnitude_a <= 0 or magnitude_b <= 0:
            continue
        dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
        cosine = clamp(dot / (magnitude_a * magnitude_b), -1.0, 1.0)
        angles.append(math.degrees(math.acos(cosine)))
    return angles
