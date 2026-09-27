from __future__ import annotations

import copy
import math
from typing import Any

from ..difficulty.common import clamp
from ..geometry.collision import (
    PERFECT_STACK_PX,
    STACK_TIME_WINDOW_MS,
    clamp_to_playfield,
    discs_clearance,
)
from .flow import pair_distance
from .models import ObjectAdjustment, SectionQuality

# Fallback threshold when circle radius is unavailable (legacy maps).
_LEGACY_STACK_DISTANCE_PX = 34.0
# Margin added on top of the geometric radii before a pair is an overlap.
_STACK_MARGIN_PX = 4.0
# Final separation distance between overlapping centers after unstacking.
_UNSTACK_CLEARANCE_PX = 6.0

# Minimum playfield inset for nudged objects (keeps the disc on-screen).
_PLAYFIELD_INSET_PX = 24.0

_READABILITY: dict[str, float] = {
    "stream": 0.7,
    "burst": 0.7,
    "jump": 0.75,
    "cross-screen jump": 0.5,
    "stack": 0.45,
    "linear": 0.9,
    "zigzag": 0.6,
    "symmetrical": 0.85,
}


def stack_overlap_distance(circle_radius: float | None) -> float:
    """Radius-aware stack overlap threshold.

    Two discs overlap when their centers are closer than the sum of their
    radii (plus a margin). Falls back to the legacy fixed 34px threshold for
    maps without a usable circle radius so old workspaces keep working.
    """
    if circle_radius is None or circle_radius <= 0:
        return _LEGACY_STACK_DISTANCE_PX
    return round(circle_radius * 2.0 + _STACK_MARGIN_PX, 2)


def analyze_patterns(map_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Recognize pattern families and their readability.

    Returns deterministic per-family statistics: kind, count, recognizability.
    """
    positioned = _positioned_objects(map_dict)
    circle_radius = _circle_radius(map_dict)
    stack_distance = stack_overlap_distance(circle_radius)
    counts: dict[str, int] = {}
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        distance = pair_distance(left, right)
        gap = int(right["time"]) - int(left["time"])
        if distance <= stack_distance and gap <= 4000:
            counts["stack"] = counts.get("stack", 0) + 1
        if distance >= 220.0 and gap <= 600:
            counts["jump"] = counts.get("jump", 0) + 1
        if distance >= 340.0 and gap <= 900:
            counts["cross-screen jump"] = counts.get("cross-screen jump", 0) + 1

    run: list[dict[str, Any]] = []
    for item in positioned:
        if run and int(item["time"]) - int(run[-1]["time"]) <= 190:
            run.append(item)
        else:
            _classify_run(run, counts)
            run = [item]
    _classify_run(run, counts)

    _classify_linear_runs(positioned, counts)
    _classify_zigzags(positioned, counts)

    return [
        {
            "kind": kind,
            "count": counts.get(kind, 0),
            "recognizability": _READABILITY.get(kind, 0.7),
        }
        for kind in sorted(_READABILITY, key=lambda kind: (-counts.get(kind, 0), kind))
        if counts.get(kind, 0) > 0
    ]


def pattern_variety(map_dict: dict[str, Any]) -> float:
    families = analyze_patterns(map_dict)
    return clamp(len(families) / 6.0, 0.0, 1.0)


def unstack_objects(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    max_adjustments: int = 6,
) -> tuple[dict[str, Any], list[ObjectAdjustment]]:
    """Nudge stacked objects apart for readability.

    Phase 23: the overlap threshold is radius-aware — two discs overlap when
    their centers come closer than the sum of their radii (plus margin), so
    Easy's large circles and Hard's small circles get correct treatment.
    Deterministic: the nudge direction follows the incoming movement vector's
    perpendicular (flow-aligned) and falls back to a fixed axis for perfect
    stacks, never randomness.

    Intentional time-separated stacks (> STACK_TIME_WINDOW_MS apart) are
    legal osu! notation and are left untouched.
    """
    positioned = _positioned_objects(map_dict)
    circle_radius = _circle_radius(map_dict)
    overlap_distance = stack_overlap_distance(circle_radius)
    adjustments: list[ObjectAdjustment] = []
    if len(positioned) < 2:
        return map_dict, []

    for index in range(1, len(positioned)):
        if len(adjustments) >= max_adjustments:
            break
        previous = positioned[index - 1]
        item = positioned[index]
        distance = pair_distance(previous, item)
        gap = int(item["time"]) - int(previous["time"])
        if distance > overlap_distance or gap > 4000:
            continue
        # Time-separated stacks are intentional; only flag near-in-time pairs.
        if gap > STACK_TIME_WINDOW_MS and distance <= PERFECT_STACK_PX:
            continue

        dx = float(item["x"]) - float(previous["x"])
        dy = float(item["y"]) - float(previous["y"])
        magnitude = math.hypot(dx, dy)
        if magnitude <= 1.0:
            # Perfectly stacked: nudge along a deterministic fixed axis.
            angle = math.radians(45.0 if int(item["id"]) % 2 == 0 else -45.0)
            dx, dy = math.cos(angle), math.sin(angle)
            magnitude = 1.0
        # Move perpendicular to the incoming flow so cursor motion stays
        # readable instead of fighting the previous movement direction.
        perpendicular = (-dy / magnitude, dx / magnitude)
        sign = 1.0 if int(item["id"]) % 2 == 0 else -1.0
        nudge = _unstack_distance(circle_radius)
        new_x = float(item["x"]) + perpendicular[0] * sign * nudge
        new_y = float(item["y"]) + perpendicular[1] * sign * nudge
        if circle_radius is not None and circle_radius > 0:
            new_x, new_y = clamp_to_playfield(new_x, new_y, circle_radius)
        else:
            new_x = clamp(new_x, 30.0, 482.0)
            new_y = clamp(new_y, 30.0, 354.0)
        new_x, new_y = round(new_x), round(new_y)
        if abs(int(item["x"]) - new_x) <= 1 and abs(int(item["y"]) - new_y) <= 1:
            continue
        section = _section_for_time(sections, int(item["time"]))
        adjustments.append(
            ObjectAdjustment(
                object_id=int(item["id"]),
                object_type=str(item.get("type", "circle")),
                action="unstack",
                reason=f"Object overlaps the previous object ({distance:.0f}px apart, clearance {discs_clearance(float(previous['x']), float(previous['y']), circle_radius or 1.0, float(item['x']), float(item['y']), circle_radius or 1.0):.1f}px).",
                before={"x": int(item["x"]), "y": int(item["y"])},
                after={"x": new_x, "y": new_y},
                section_label=section.label if section else "",
            )
        )
        item["x"], item["y"] = new_x, new_y

    if not adjustments:
        return map_dict, []

    adjusted = copy.deepcopy(map_dict)
    by_id = {
        int(obj["id"]): obj
        for obj in adjusted.get("objects", [])
        if isinstance(obj, dict) and isinstance(obj.get("id"), (int, float))
    }
    for adjustment in adjustments:
        target = by_id.get(adjustment.object_id)
        if target is None:
            continue
        target["x"] = adjustment.after["x"]
        target["y"] = adjustment.after["y"]
    return adjusted, adjustments


def _circle_radius(map_dict: dict[str, Any]) -> float | None:
    radius = map_dict.get("circleRadius")
    if isinstance(radius, (int, float)) and float(radius) > 0:
        return float(radius)
    # Fall back to the preset radius when the map root omits it.
    objects = map_dict.get("objects")
    if isinstance(objects, list):
        for item in objects:
            if isinstance(item, dict) and item.get("circleRadius") is not None:
                value = item.get("circleRadius")
                if isinstance(value, (int, float)) and float(value) > 0:
                    return float(value)
    return None


def _unstack_distance(circle_radius: float | None) -> float:
    """How far to push the overlapping disc so it clears its neighbor.

    Larger circles need a bigger nudge; the legacy fixed 48px is kept for
    maps without a radius.
    """
    if circle_radius is None or circle_radius <= 0:
        return 48.0
    return round(circle_radius * 2.0 + _UNSTACK_CLEARANCE_PX, 2)


def _classify_run(run: list[dict[str, Any]], counts: dict[str, int]) -> None:
    if len(run) >= 5:
        counts["stream"] = counts.get("stream", 0) + 1
    elif len(run) in (3, 4):
        counts["burst"] = counts.get("burst", 0) + 1


def _classify_linear_runs(positioned: list[dict[str, Any]], counts: dict[str, int]) -> None:
    if len(positioned) < 4:
        return
    run_length = 1
    for index in range(2, len(positioned)):
        previous_previous = positioned[index - 2]
        previous = positioned[index - 1]
        current = positioned[index]
        angle = _angle(previous_previous, previous, current)
        if angle is not None and angle >= 155.0:
            run_length += 1
        else:
            if run_length >= 4:
                counts["linear"] = counts.get("linear", 0) + 1
            run_length = 1
    if run_length >= 4:
        counts["linear"] = counts.get("linear", 0) + 1


def _classify_zigzags(positioned: list[dict[str, Any]], counts: dict[str, int]) -> None:
    if len(positioned) < 4:
        return
    zigzag = 1
    previous_sign: int | None = None
    for index in range(2, len(positioned)):
        sign = _turn_sign(positioned[index - 2], positioned[index - 1], positioned[index])
        if sign is None:
            zigzag = 1
            previous_sign = None
            continue
        if previous_sign is not None and sign != previous_sign:
            zigzag += 1
        else:
            zigzag = 1
        previous_sign = sign
        if zigzag >= 3:
            counts["zigzag"] = counts.get("zigzag", 0) + 1
            zigzag = 1


def _angle(
    left: dict[str, Any],
    middle: dict[str, Any],
    right: dict[str, Any],
) -> float | None:
    vector_a = (float(middle["x"]) - float(left["x"]), float(middle["y"]) - float(left["y"]))
    vector_b = (float(right["x"]) - float(middle["x"]), float(right["y"]) - float(middle["y"]))
    magnitude_a = math.hypot(*vector_a)
    magnitude_b = math.hypot(*vector_b)
    if magnitude_a <= 0 or magnitude_b <= 0:
        return None
    dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
    cosine = clamp(dot / (magnitude_a * magnitude_b), -1.0, 1.0)
    return math.degrees(math.acos(cosine))


def _turn_sign(
    left: dict[str, Any],
    middle: dict[str, Any],
    right: dict[str, Any],
) -> int | None:
    vector_a = (float(middle["x"]) - float(left["x"]), float(middle["y"]) - float(left["y"]))
    vector_b = (float(right["x"]) - float(middle["x"]), float(right["y"]) - float(middle["y"]))
    cross = vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0]
    if abs(cross) < 1.0:
        return None
    return 1 if cross > 0 else -1


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


def _section_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> SectionQuality | None:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section
    return None
