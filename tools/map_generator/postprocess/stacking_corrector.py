from __future__ import annotations

import math
import random
from typing import Any

from ..position_generator import PLAYFIELD_CENTER
from ..utils import clamp
from .models import ExpectedCategory, PostprocessContext
from .movement_corrector import build_manual_move_action


def build_stacking_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    issue_object_ids: list[int],
    confidence: float,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) < 2:
        return None

    target_index = _resolve_target_index(objects, issue_code, issue_object_ids)
    if target_index is None:
        return None

    # Spinners have no position and cannot be de-stacked.
    target_object = objects[target_index]
    if target_object.get("x") is None or target_object.get("y") is None:
        return None

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
    candidate_positions = _generate_stacking_positions(
        target_object=target_object,
        previous_object=previous_object,
        next_object=next_object,
        circle_radius=float(map_data.get("circleRadius", context.preset.circle_radius)),
        context=context,
        issue_code=issue_code,
    )
    if not candidate_positions:
        return None

    return build_manual_move_action(
        map_data=map_data,
        current_report=current_report,
        context=context,
        object_id=int(target_object["id"]),
        issue_code=issue_code,
        candidate_positions=candidate_positions,
        confidence=min(0.99, confidence + 0.06),
        stage="stacking_corrections",
        expected_categories=_expected_categories_for_issue(issue_code),
    )


def _resolve_target_index(
    objects: list[dict[str, Any]],
    issue_code: str,
    issue_object_ids: list[int],
) -> int | None:
    if issue_object_ids:
        target_id = issue_object_ids[-1]
        for index, hit_object in enumerate(objects):
            if int(hit_object["id"]) == target_id:
                return index

    if issue_code == "READABILITY_TOO_CLOSE_TO_EDGE" and objects:
        return 0

    return None


def _generate_stacking_positions(
    *,
    target_object: dict[str, Any],
    previous_object: dict[str, Any] | None,
    next_object: dict[str, Any] | None,
    circle_radius: float,
    context: PostprocessContext,
    issue_code: str,
) -> list[tuple[float, float]]:
    padding = circle_radius + context.preset.safe_margin
    rng = random.Random(context.seed * 29 + int(target_object["id"]) * 17)
    base_positions: list[tuple[float, float]] = []
    current_x = float(target_object["x"])
    current_y = float(target_object["y"])

    if previous_object is not None and next_object is not None:
        span_x = float(next_object["x"]) - float(previous_object["x"])
        span_y = float(next_object["y"]) - float(previous_object["y"])
        span_length = math.hypot(span_x, span_y)
        if span_length > 1e-6:
            normal_x = -span_y / span_length
            normal_y = span_x / span_length
            offset = max(circle_radius * 1.35, context.preset.min_jump_distance * 0.55)
            for sign in (-1.0, 1.0):
                base_positions.append(
                    (
                        current_x + normal_x * offset * sign,
                        current_y + normal_y * offset * sign,
                    )
                )
                base_positions.append(
                    (
                        current_x + normal_x * offset * sign * 0.72 + span_x * 0.08,
                        current_y + normal_y * offset * sign * 0.72 + span_y * 0.08,
                    )
                )

    if previous_object is not None:
        angle = math.atan2(current_y - float(previous_object["y"]), current_x - float(previous_object["x"]))
    elif next_object is not None:
        angle = math.atan2(float(next_object["y"]) - current_y, float(next_object["x"]) - current_x)
    else:
        angle = math.atan2(PLAYFIELD_CENTER[1] - current_y, PLAYFIELD_CENTER[0] - current_x)

    base_distance = max(circle_radius * 1.25, context.preset.min_jump_distance * 0.45)
    for angle_offset in (-0.85, -0.45, 0.45, 0.85):
        jitter = (rng.random() - 0.5) * 0.18
        local_angle = angle + angle_offset + jitter
        base_positions.append(
            (
                current_x + math.cos(local_angle) * base_distance,
                current_y + math.sin(local_angle) * base_distance,
            )
        )

    inward_x = current_x + (PLAYFIELD_CENTER[0] - current_x) * (0.42 if issue_code == "READABILITY_TOO_CLOSE_TO_EDGE" else 0.26)
    inward_y = current_y + (PLAYFIELD_CENTER[1] - current_y) * (0.42 if issue_code == "READABILITY_TOO_CLOSE_TO_EDGE" else 0.26)
    base_positions.append((inward_x, inward_y))

    deduped: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()
    for x_value, y_value in base_positions:
        key = (int(round(x_value)), int(round(y_value)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            (
                clamp(x_value, padding, 512 - padding),
                clamp(y_value, padding, 384 - padding),
            )
        )

    return deduped


def _expected_categories_for_issue(issue_code: str) -> list[ExpectedCategory]:
    if issue_code == "READABILITY_TOO_CLOSE_TO_EDGE":
        return ["readability", "spatialBalance", "movement"]
    return ["readability", "movement", "spatialBalance"]
