from __future__ import annotations

import copy
import math
from typing import Any

from ..difficulty.common import clamp
from .flow import SHARP_TURN_THRESHOLD_DEG, analyze_flow, pair_distance
from .models import ObjectAdjustment, SectionQuality

_FLOW_ISSUE_CODES = {
    "DIFFICULTY_SPIKE",
    "AWKWARD_SPACING",
    "UNREADABLE_JUMP",
    "FLOW_BREAK",
}

_PLAYFIELD_X_MIN = 30.0
_PLAYFIELD_X_MAX = 482.0
_PLAYFIELD_Y_MIN = 30.0
_PLAYFIELD_Y_MAX = 354.0
_MIN_OBJECT_GAP_PX = 26.0


def rebalance_positions(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    issues: list[Any],
    difficulty_report: Any | None,
    difficulty: str = "normal",
    max_adjustments: int = 10,
) -> tuple[dict[str, Any], list[ObjectAdjustment]]:
    """Deterministically adjust object positions in weak sections.

    Improves spacing, smooths angle transitions, and reduces awkward jumps.
    Never randomizes positions: every adjustment is a pure function of the
    current geometry and the flagged issues.
    """
    flagged_section_ids = {
        issue.section_label: issue.code
        for issue in issues
        if issue.code in _FLOW_ISSUE_CODES
    }
    if not flagged_section_ids:
        return map_dict, []

    target_jump = _target_jump(difficulty_report, difficulty)
    positioned = _positioned_objects(map_dict)
    if len(positioned) < 2:
        return map_dict, []

    flow = analyze_flow(map_dict)
    turn_by_id = {turn.object_id: turn for turn in flow.turns}

    adjustments: list[ObjectAdjustment] = []
    section_by_label: dict[str, SectionQuality] = {
        section.label: section for section in sections
    }

    for index in range(1, len(positioned)):
        if len(adjustments) >= max_adjustments:
            break
        item = positioned[index]
        time = int(item["time"])
        section = _section_for_time(sections, time)
        if section is None or section.label not in flagged_section_ids:
            continue

        previous = positioned[index - 1]
        jump = pair_distance(previous, item)
        object_type = str(item.get("type", "circle"))
        object_id = int(item["id"])
        reason_parts: list[str] = []

        # --- Jump reduction -------------------------------------------------
        jump_threshold = max(target_jump * 1.5, target_jump + 70.0)
        if jump > jump_threshold:
            reduced = clamp(target_jump * 1.2, 40.0, jump * 0.85)
            new_position = _place_at_distance(previous, item, reduced)
            if new_position is not None and _moved(item, new_position):
                adjustments.append(
                    ObjectAdjustment(
                        object_id=object_id,
                        object_type=object_type,
                        action="reduce_jump",
                        reason=f"Jump of {jump:.0f}px exceeds the {jump_threshold:.0f}px threshold.",
                        before={"x": int(item["x"]), "y": int(item["y"])},
                        after={"x": int(new_position[0]), "y": int(new_position[1])},
                        section_label=section.label,
                    )
                )
                item["x"], item["y"] = new_position
                reason_parts.append("jump")
                continue

        # --- Angle smoothing ------------------------------------------------
        if index < len(positioned) - 1:
            turn = turn_by_id.get(object_id)
            if turn is not None and turn.turn_angle_deg is not None and turn.turn_angle_deg < SHARP_TURN_THRESHOLD_DEG:
                nxt = positioned[index + 1]
                distance_to_next = pair_distance(previous, nxt)
                if distance_to_next > 60.0:
                    along = min(jump, distance_to_next * 0.7)
                    projected = _place_at_distance(previous, nxt, along)
                    if projected is not None and _moved(item, projected):
                        adjustments.append(
                            ObjectAdjustment(
                                object_id=object_id,
                                object_type=object_type,
                                action="smooth_turn",
                                reason=f"Turn of {turn.turn_angle_deg:.0f} deg doubles back on the cursor path.",
                                before={"x": int(item["x"]), "y": int(item["y"])},
                                after={"x": int(projected[0]), "y": int(projected[1])},
                                section_label=section.label,
                            )
                        )
                        item["x"], item["y"] = projected
                        reason_parts.append("angle")

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


def _place_at_distance(
    anchor: dict[str, Any],
    target: dict[str, Any],
    distance: float,
) -> tuple[float, float] | None:
    """Place ``target`` at ``distance`` from ``anchor`` along the anchor->target ray."""
    dx = float(target["x"]) - float(anchor["x"])
    dy = float(target["y"]) - float(anchor["y"])
    magnitude = math.hypot(dx, dy)
    if magnitude <= 0.0:
        return None
    scale = distance / magnitude
    x = clamp(float(anchor["x"]) + dx * scale, _PLAYFIELD_X_MIN, _PLAYFIELD_X_MAX)
    y = clamp(float(anchor["y"]) + dy * scale, _PLAYFIELD_Y_MIN, _PLAYFIELD_Y_MAX)
    # Keep a minimum separation from the anchor to avoid stacking.
    separation = math.hypot(x - float(anchor["x"]), y - float(anchor["y"]))
    if separation < _MIN_OBJECT_GAP_PX:
        return None
    return (round(x), round(y))


def _target_jump(difficulty_report: Any | None, difficulty: str) -> float:
    target = getattr(difficulty_report, "target", None)
    if target is not None:
        value = getattr(target, "jump_target", None)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return {"easy": 90.0, "normal": 130.0, "hard": 180.0}.get(difficulty, 130.0)


def _moved(item: dict[str, Any], position: tuple[float, float]) -> bool:
    return abs(int(item["x"]) - int(position[0])) > 1 or abs(
        int(item["y"]) - int(position[1])
    ) > 1


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
