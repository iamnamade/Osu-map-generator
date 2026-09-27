"""Phase 23 — Collision resolution pass for the adaptive rebalancer.

``unstack_objects`` handles near-in-time disc-disc stacks, but cannot see a
slider body passing through a circle or two slider bodies crossing. This pass
closes that gap: it runs the shared ``detect_map_overlaps`` detector and nudges
the later object of every overlapping pair clear of the collision.

Determinism guarantees:

* Detection order is fixed (time, then id) and every nudge is a pure function
  of the two objects' geometry — no randomness, no iteration-order hazards.
* Nudging a slider translates its control points by the same delta (control
  points are absolute playfield coordinates), so the whole path moves intact.
* Every nudge is clamped to the playfield so discs never leave the screen.

Intentional time-separated stacks are already excluded by the detector and are
never touched.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from ..geometry.collision import (
    clamp_to_playfield,
    detect_map_overlaps,
    nearest_pair_on_polylines,
    nearest_point_on_polyline,
    path_normal_at,
    sample_slider_path,
)
from .models import ObjectAdjustment, SectionQuality
from .patterns import _circle_radius

# Extra clearance applied beyond the exact overlap depth so nudged discs do
# not immediately re-collide after rounding.
_CLEARANCE_PADDING_PX = 3.0
# Bounded re-detection loop: nudging one object can create a new overlap with
# a third object, but the pass must terminate.
_MAX_DETECTION_ROUNDS = 3


def resolve_collisions(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    max_adjustments: int = 6,
) -> tuple[dict[str, Any], list[ObjectAdjustment]]:
    """Nudge overlapping objects apart (slider bodies included).

    Returns ``(map_dict, [])`` untouched when nothing overlaps. When overlaps
    exist, returns a deep copy with the later object of each pair nudged clear
    plus one ``ObjectAdjustment`` (action ``resolve_collision``) per change.
    """
    objects = map_dict.get("objects")
    if not isinstance(objects, list) or len(objects) < 2:
        return map_dict, []
    circle_radius = _circle_radius(map_dict)
    if circle_radius is None or circle_radius <= 0:
        # Without a radius the whole radius-aware model is undefined; fall
        # back to the legacy behavior (nothing to do) for old workspaces.
        return map_dict, []

    adjustments: list[ObjectAdjustment] = []
    current = copy.deepcopy(map_dict)
    for _round in range(_MAX_DETECTION_ROUNDS):
        if len(adjustments) >= max_adjustments:
            break
        records = detect_map_overlaps(
            current.get("objects", []),
            circle_radius,
        )
        if not records:
            break
        for record in records:
            if len(adjustments) >= max_adjustments:
                break
            _nudge_pair(
                map_dict=current,
                record=record,
                circle_radius=circle_radius,
                sections=sections,
                adjustments=adjustments,
            )

    if not adjustments:
        return map_dict, []
    return current, adjustments


# After a nudge, the pair is re-checked; keep pushing until it clears.
_MAX_PAIR_NUDGES = 4


def _nudge_pair(
    *,
    map_dict: dict[str, Any],
    record: dict[str, Any],
    circle_radius: float,
    sections: list[SectionQuality],
    adjustments: list[ObjectAdjustment],
) -> None:
    """Nudge the later object of an overlapping pair clear of the collision.

    Converges per pair: after each push the pair is re-checked with the
    canonical detector and pushed again if needed (bounded), so one
    ``ObjectAdjustment`` records the full correction.
    """
    by_id = {
        int(obj["id"]): obj
        for obj in map_dict.get("objects", [])
        if isinstance(obj, dict) and isinstance(obj.get("id"), (int, float))
    }
    left = by_id.get(int(record["left_id"]))
    right = by_id.get(int(record["right_id"]))
    if left is None or right is None:
        return
    if right.get("type") not in ("circle", "slider"):
        return

    direction = _nudge_direction(left, right, record["kind"])
    if direction is None:
        return

    old_x = float(right.get("x") or 0.0)
    old_y = float(right.get("y") or 0.0)
    clearance = float(record["clearance_px"])
    new_x, new_y = old_x, old_y
    for _ in range(_MAX_PAIR_NUDGES):
        nudge = max(4.0, abs(clearance) + _CLEARANCE_PADDING_PX)
        candidate_x = new_x + direction[0] * nudge
        candidate_y = new_y + direction[1] * nudge
        candidate_x, candidate_y = clamp_to_playfield(candidate_x, candidate_y, circle_radius)
        candidate_x, candidate_y = round(candidate_x), round(candidate_y)
        if (
            abs(round(new_x) - candidate_x) <= 1
            and abs(round(new_y) - candidate_y) <= 1
        ):
            break
        new_x, new_y = candidate_x, candidate_y
        remaining = _pair_clearance(left, right, new_x, new_y, circle_radius)
        if remaining is None or remaining >= 0.0:
            break
        clearance = remaining

    if abs(int(right.get("x", 0)) - new_x) <= 1 and abs(int(right.get("y", 0)) - new_y) <= 1:
        return

    section = _section_for_time(sections, int(right.get("time", 0)))
    adjustments.append(
        ObjectAdjustment(
            object_id=int(right["id"]),
            object_type=str(right.get("type", "circle")),
            action="resolve_collision",
            reason=(
                f"Object overlaps {left.get('type')} {left.get('id')} by "
                f"{-record['clearance_px']:.1f}px (required {circle_radius * 2.0:.0f}px gap)."
            ),
            before={"x": int(right.get("x", 0)), "y": int(right.get("y", 0))},
            after={"x": new_x, "y": new_y},
            section_label=section.label if section else "",
        )
    )
    right["x"] = new_x
    right["y"] = new_y
    if right.get("type") == "slider":
        _translate_control_points(right, new_x - old_x, new_y - old_y)


def _pair_clearance(
    left: dict[str, Any],
    right: dict[str, Any],
    new_x: float,
    new_y: float,
    circle_radius: float,
) -> float | None:
    """Signed clearance of the pair with ``right`` moved to (new_x, new_y)."""
    right_copy = copy.deepcopy(right)
    right_copy["x"] = new_x
    right_copy["y"] = new_y
    if right_copy.get("type") == "slider":
        _translate_control_points(
            right_copy,
            new_x - float(right.get("x") or 0.0),
            new_y - float(right.get("y") or 0.0),
        )
    records = detect_map_overlaps([left, right_copy], circle_radius)
    if not records:
        return None
    return float(records[0]["clearance_px"])


def _nudge_direction(
    left: dict[str, Any],
    right: dict[str, Any],
    kind: str,
) -> tuple[float, float] | None:
    """Away vector (unit) from the collision to the later object's head.

    Deterministic per kind: disc-disc pushes along the center-to-center line;
    slider-involved kinds push away from the nearest point on the other path.
    Degenerate (perfectly stacked) disc-disc pairs use a fixed axis.
    """
    if kind == "disc-disc":
        dx = float(right.get("x") or 0.0) - float(left.get("x") or 0.0)
        dy = float(right.get("y") or 0.0) - float(left.get("y") or 0.0)
        magnitude = math.hypot(dx, dy)
        if magnitude <= 1.0:
            angle = math.radians(45.0 if int(right.get("id", 0)) % 2 == 0 else -45.0)
            return math.cos(angle), math.sin(angle)
        return dx / magnitude, dy / magnitude

    if kind == "disc-slider":
        circle = left if left.get("type") == "circle" else right
        slider = right if left.get("type") == "circle" else left
        slider_path = sample_slider_path(slider)
        circle_x = float(circle.get("x") or 0.0)
        circle_y = float(circle.get("y") or 0.0)
        nearest = nearest_point_on_polyline(circle_x, circle_y, slider_path)
        return _away_from(
            circle_x,
            circle_y,
            nearest[0],
            nearest[1],
            int(circle.get("id", 0)),
            fallback=path_normal_at(slider_path, nearest, int(circle.get("id", 0))),
        )

    # slider-slider: separate the paths along the nearest-pair vector. When
    # the paths cross the pair coincides, so fall back to the earlier path's
    # normal — pushing the later slider along its own axis would never clear
    # a perpendicular crossing.
    left_path = sample_slider_path(left)
    right_path = sample_slider_path(right)
    left_point, right_point, _distance = nearest_pair_on_polylines(left_path, right_path)
    return _away_from(
        right_point[0],
        right_point[1],
        left_point[0],
        left_point[1],
        int(right.get("id", 0)),
        fallback=path_normal_at(left_path, left_point, int(right.get("id", 0))),
    )


def _away_from(
    point_x: float,
    point_y: float,
    anchor_x: float,
    anchor_y: float,
    object_id: int,
    *,
    fallback: tuple[float, float],
) -> tuple[float, float] | None:
    dx = point_x - anchor_x
    dy = point_y - anchor_y
    magnitude = math.hypot(dx, dy)
    if magnitude <= 1.0:
        return fallback
    return dx / magnitude, dy / magnitude


def _translate_control_points(slider: dict[str, Any], dx: float, dy: float) -> None:
    control_points = slider.get("controlPoints")
    if not isinstance(control_points, list):
        return
    for point in control_points:
        if not isinstance(point, dict):
            continue
        if isinstance(point.get("x"), (int, float)):
            point["x"] = round(float(point["x"]) + dx, 2)
        if isinstance(point.get("y"), (int, float)):
            point["y"] = round(float(point["y"]) + dy, 2)


def _section_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> SectionQuality | None:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section
    return None
