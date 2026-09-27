from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TurnStat:
    object_id: int
    time_ms: int
    turn_angle_deg: float | None
    sharp: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "timeMs": self.time_ms,
            "turnAngleDeg": (
                round(self.turn_angle_deg, 2) if self.turn_angle_deg is not None else None
            ),
            "sharp": self.sharp,
        }


@dataclass(frozen=True)
class FlowAnalysis:
    average_turn_angle_deg: float
    sharp_turn_count: int
    direction_change_count: int
    turns: list[TurnStat]

    def to_dict(self) -> dict[str, Any]:
        return {
            "averageTurnAngleDeg": round(self.average_turn_angle_deg, 2),
            "sharpTurnCount": self.sharp_turn_count,
            "directionChangeCount": self.direction_change_count,
            "turns": [turn.to_dict() for turn in self.turns],
        }


SHARP_TURN_THRESHOLD_DEG = 135.0


def analyze_flow(map_dict: dict[str, Any]) -> FlowAnalysis:
    """Compute cursor-path turn statistics for every positioned object.

    Deterministic: pure geometry over the object list. A ``turn_angle_deg`` of
    180 means the path continues straight; angles near 0 mean the path doubles
    back sharply. ``sharp`` marks turns below the sharp-turn threshold.
    """
    positioned = _positioned_objects(map_dict)
    turns: list[TurnStat] = []
    for index in range(1, len(positioned) - 1):
        left = positioned[index - 1]
        middle = positioned[index]
        right = positioned[index + 1]
        angle = _turn_angle(left, middle, right)
        turns.append(
            TurnStat(
                object_id=int(middle["id"]),
                time_ms=int(middle["time"]),
                turn_angle_deg=angle,
                sharp=angle is not None and angle < SHARP_TURN_THRESHOLD_DEG,
            )
        )
    angles = [turn.turn_angle_deg for turn in turns if turn.turn_angle_deg is not None]
    average = sum(angles) / len(angles) if angles else 180.0
    sharp_count = sum(1 for turn in turns if turn.sharp)
    direction_changes = _direction_change_count(positioned)
    return FlowAnalysis(
        average_turn_angle_deg=average,
        sharp_turn_count=sharp_count,
        direction_change_count=direction_changes,
        turns=turns,
    )


def turn_angle_at(
    map_dict: dict[str, Any],
    object_id: int,
) -> float | None:
    """Return the turn angle at ``object_id`` or None when it has no neighbors."""
    positioned = _positioned_objects(map_dict)
    for index, item in enumerate(positioned):
        if int(item["id"]) != object_id:
            continue
        if index == 0 or index == len(positioned) - 1:
            return None
        return _turn_angle(positioned[index - 1], item, positioned[index + 1])
    return None


def pair_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_x = left.get("x")
    left_y = left.get("y")
    right_x = right.get("x")
    right_y = right.get("y")
    if (
        not isinstance(left_x, (int, float))
        or not isinstance(left_y, (int, float))
        or not isinstance(right_x, (int, float))
        or not isinstance(right_y, (int, float))
    ):
        return 0.0
    return math.hypot(float(right_x) - float(left_x), float(right_y) - float(left_y))


def _positioned_objects(map_dict: dict[str, Any]) -> list[dict[str, Any]]:
    objects = map_dict.get("objects")
    if not isinstance(objects, list):
        return []
    positioned = [
        item
        for item in objects
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("x"), (int, float))
        and isinstance(item.get("y"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item.get("time", 0)), int(item.get("id", 0))))
    return positioned


def _turn_angle(
    left: dict[str, Any],
    middle: dict[str, Any],
    right: dict[str, Any],
) -> float | None:
    left_x, left_y = _coords(left)
    middle_x, middle_y = _coords(middle)
    right_x, right_y = _coords(right)
    if None in (left_x, left_y, middle_x, middle_y, right_x, right_y):
        return None
    vector_a = (middle_x - left_x, middle_y - left_y)
    vector_b = (right_x - middle_x, right_y - middle_y)
    magnitude_a = math.hypot(*vector_a)
    magnitude_b = math.hypot(*vector_b)
    if magnitude_a <= 0 or magnitude_b <= 0:
        return None
    dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
    cosine = max(-1.0, min(1.0, dot / (magnitude_a * magnitude_b)))
    return math.degrees(math.acos(cosine))


def _direction_change_count(positioned: list[dict[str, Any]]) -> int:
    """Count direction sign flips of consecutive jumps (alternating sides)."""
    changes = 0
    previous_side = None
    for index in range(1, len(positioned)):
        left_x, left_y = _coords(positioned[index - 1])
        right_x, right_y = _coords(positioned[index])
        if None in (left_x, left_y, right_x, right_y):
            continue
        dx = right_x - left_x
        dy = right_y - left_y
        if abs(dx) < 1.0 and abs(dy) < 1.0:
            continue
        side = -1 if dx < 0 else 1
        if dx == 0:
            side = -1 if dy < 0 else 1
        if previous_side is not None and side != previous_side:
            changes += 1
        previous_side = side
    return changes


def _coords(item: dict[str, Any]) -> tuple[float | None, float | None]:
    x = item.get("x")
    y = item.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None, None
    return float(x), float(y)
