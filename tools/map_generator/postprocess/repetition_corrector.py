from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ..position_generator import PLAYFIELD_CENTER
from ..utils import clamp
from .models import PostprocessContext
from .movement_corrector import build_manual_move_action


def build_repetition_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    confidence: float,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) < 4:
        return None

    target_index = _resolve_target_index(objects, issue_code)
    if target_index is None:
        return None

    candidate_positions = _candidate_positions(
        objects=objects,
        target_index=target_index,
        context=context,
        circle_radius=float(map_data.get("circleRadius", context.preset.circle_radius)),
    )
    if not candidate_positions:
        return None

    return build_manual_move_action(
        map_data=map_data,
        current_report=current_report,
        context=context,
        object_id=int(objects[target_index]["id"]),
        issue_code=issue_code,
        candidate_positions=candidate_positions,
        confidence=min(0.99, confidence + 0.05),
        stage="repetition_corrections",
        expected_categories=["repetition", "movement", "spatialBalance"],
    )


def _positioned(objects: list[dict[str, Any]]) -> list[int]:
    """Indices of objects that carry x/y coordinates (spinners have none)."""
    return [
        index
        for index, hit_object in enumerate(objects)
        if hit_object.get("x") is not None and hit_object.get("y") is not None
    ]


def _resolve_target_index(objects: list[dict[str, Any]], issue_code: str) -> int | None:
    positioned = _positioned(objects)
    if len(positioned) < 4:
        return None

    if issue_code == "REPETITION_TWO_POINT_LOOP":
        for offset in range(len(positioned) - 3):
            i0, i1, i2, i3 = positioned[offset : offset + 4]
            if _points_close(objects[i0], objects[i2]) and _points_close(objects[i1], objects[i3]):
                return i2
        return None

    if issue_code == "REPETITION_COORDINATE_PAIR_REUSE":
        counter: Counter[tuple[int, int, int, int]] = Counter()
        pair_to_index: dict[tuple[int, int, int, int], int] = {}
        for offset in range(len(positioned) - 1):
            left_index = positioned[offset]
            right_index = positioned[offset + 1]
            key = (
                int(round(float(objects[left_index]["x"]) / 16)),
                int(round(float(objects[left_index]["y"]) / 16)),
                int(round(float(objects[right_index]["x"]) / 16)),
                int(round(float(objects[right_index]["y"]) / 16)),
            )
            counter[key] += 1
            pair_to_index[key] = right_index
        for key, count in counter.items():
            if count >= 2:
                return pair_to_index[key]
        return None

    for offset in range(1, len(positioned) - 1):
        previous_index = positioned[offset - 1]
        current_index = positioned[offset]
        next_index = positioned[offset + 1]
        if _points_close(objects[previous_index], objects[current_index]) or _points_close(
            objects[current_index], objects[next_index]
        ):
            return current_index
    return positioned[len(positioned) // 2]


def _candidate_positions(
    *,
    objects: list[dict[str, Any]],
    target_index: int,
    context: PostprocessContext,
    circle_radius: float,
) -> list[tuple[float, float]]:
    target_object = objects[target_index]
    if target_object.get("x") is None or target_object.get("y") is None:
        return []
    previous_object = objects[target_index - 1] if target_index > 0 else None
    next_object = objects[target_index + 1] if target_index + 1 < len(objects) else None
    previous_object = (
        previous_object
        if previous_object is not None and previous_object.get("x") is not None
        else None
    )
    next_object = (
        next_object
        if next_object is not None and next_object.get("x") is not None
        else None
    )
    if previous_object is None or next_object is None:
        return []

    padding = circle_radius + context.preset.safe_margin
    base_distance = max(circle_radius * 1.3, context.preset.min_jump_distance * 0.58)
    span_x = float(next_object["x"]) - float(previous_object["x"])
    span_y = float(next_object["y"]) - float(previous_object["y"])
    span_length = math.hypot(span_x, span_y)

    if span_length > 1e-6:
        normal_x = -span_y / span_length
        normal_y = span_x / span_length
    else:
        angle = math.atan2(
            PLAYFIELD_CENTER[1] - float(target_object["y"]),
            PLAYFIELD_CENTER[0] - float(target_object["x"]),
        )
        normal_x = math.cos(angle)
        normal_y = math.sin(angle)

    midpoint_x = (float(previous_object["x"]) + float(next_object["x"])) / 2
    midpoint_y = (float(previous_object["y"]) + float(next_object["y"])) / 2
    positions = [
        (
            midpoint_x + normal_x * base_distance,
            midpoint_y + normal_y * base_distance,
        ),
        (
            midpoint_x - normal_x * base_distance,
            midpoint_y - normal_y * base_distance,
        ),
        (
            float(target_object["x"]) + (PLAYFIELD_CENTER[0] - float(target_object["x"])) * 0.28,
            float(target_object["y"]) + (PLAYFIELD_CENTER[1] - float(target_object["y"])) * 0.28,
        ),
    ]

    deduped: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()
    for x_value, y_value in positions:
        clamped = (
            clamp(x_value, padding, 512 - padding),
            clamp(y_value, padding, 384 - padding),
        )
        key = (int(round(clamped[0])), int(round(clamped[1])))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(clamped)
    return deduped


def _points_close(left: dict[str, Any], right: dict[str, Any], tolerance: float = 12.0) -> bool:
    return (
        abs(float(left["x"]) - float(right["x"])) <= tolerance
        and abs(float(left["y"]) - float(right["y"])) <= tolerance
    )
