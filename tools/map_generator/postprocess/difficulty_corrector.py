from __future__ import annotations

import math
from typing import Any

from .models import PostprocessContext
from .movement_corrector import build_movement_action


def build_difficulty_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    confidence: float,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) < 2:
        return None

    if issue_code in {"DIFFICULTY_BEHAVIOR_INCONSISTENT", "DIFFICULTY_BEHAVIOR_TOO_HARD"}:
        target_ids = _select_spike_pair(objects, context)
        if not target_ids:
            return None
        return build_movement_action(
            map_data=map_data,
            current_report=current_report,
            context=context,
            issue_code=issue_code,
            issue_object_ids=target_ids,
            confidence=min(0.99, confidence + 0.04),
            stage="difficulty_corrections",
            expected_categories=["difficultyConsistency", "movement", "readability"],
            target_object_id=target_ids[-1],
            compact=True,
        )

    return None


def _select_spike_pair(
    objects: list[dict[str, Any]],
    context: PostprocessContext,
) -> list[int]:
    best_score = float("-inf")
    best_pair: list[int] | None = None

    positioned = [obj for obj in objects if obj.get("x") is not None and obj.get("y") is not None]
    for left, right in zip(positioned, positioned[1:], strict=False):
        distance = math.hypot(float(right["x"]) - float(left["x"]), float(right["y"]) - float(left["y"]))
        gap_ms = max(1, int(right["time"]) - int(left["time"]))
        speed = distance / (gap_ms / 1000)
        local_energy = context.analysis.energy_at(int(right["time"]))
        score = (
            max(0.0, distance - context.preset.preferred_jump_distance) * 0.7
            + max(0.0, speed - context.preset.max_cursor_speed * 0.72) * 0.4
            + max(0.0, context.preset.high_energy_threshold * 0.9 - local_energy) * 120
        )
        if score > best_score:
            best_score = score
            best_pair = [int(left["id"]), int(right["id"])]

    return best_pair or []
