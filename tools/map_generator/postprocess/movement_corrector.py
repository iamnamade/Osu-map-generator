from __future__ import annotations

import math
import random
from typing import Any

from ..position_generator import PLAYFIELD_CENTER, PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from ..utils import clamp, shortest_angle_delta
from .local_optimizer import deadline_exceeded, evaluate_candidate_action
from .models import CorrectionAction, ExpectedCategory, PostprocessContext


def build_movement_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    issue_object_ids: list[int],
    confidence: float,
    stage: str = "movement_corrections",
    expected_categories: list[ExpectedCategory] | None = None,
    target_object_id: int | None = None,
    compact: bool = False,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) < 2:
        return None

    resolved_target_id = target_object_id or _resolve_target_object_id(issue_code, issue_object_ids, objects)
    if resolved_target_id is None:
        return None

    target_index = _find_object_index(objects, resolved_target_id)
    if target_index is None:
        return None

    # Spinners have no position and cannot be moved.
    target_object = objects[target_index]
    if target_object.get("x") is None or target_object.get("y") is None:
        return None

    candidate_positions = _generate_position_candidates(
        map_data=map_data,
        context=context,
        target_index=target_index,
        compact=compact,
    )
    if not candidate_positions:
        return None

    object_before = dict(objects[target_index])
    current_position = (float(object_before["x"]), float(object_before["y"]))
    best_evaluation: Any | None = None

    for position_score, candidate_x, candidate_y in candidate_positions[: context.limits.max_candidates_per_object]:
        if deadline_exceeded():
            break

        if abs(candidate_x - current_position[0]) < 0.5 and abs(candidate_y - current_position[1]) < 0.5:
            continue

        candidate_map = _deep_copy_map(map_data)
        candidate_object = candidate_map["objects"][target_index]
        candidate_object["x"] = int(round(candidate_x))
        candidate_object["y"] = int(round(candidate_y))

        candidate_action = CorrectionAction(
            action_id=f"movement-{resolved_target_id:04d}-{len(issue_object_ids):02d}",
            stage=stage,  # type: ignore[arg-type]
            action_type="move_object",
            reason_code=issue_code,
            object_ids=[resolved_target_id],
            before={
                "id": object_before["id"],
                "x": object_before["x"],
                "y": object_before["y"],
                "time": object_before["time"],
            },
            after={
                "id": candidate_object["id"],
                "x": candidate_object["x"],
                "y": candidate_object["y"],
                "time": candidate_object["time"],
            },
            confidence=min(0.99, confidence + min(0.14, max(0.0, position_score) / 180)),
            expected_categories=expected_categories or ["movement", "readability", "difficultyConsistency"],
            expected_score_impact=max(0.1, position_score / 120),
        )
        evaluation = evaluate_candidate_action(
            context=context,
            current_report=current_report,
            candidate_map=candidate_map,
            candidate_action=candidate_action,
        )
        if evaluation.accepted and (
            best_evaluation is None
            or evaluation.overall_delta > best_evaluation.overall_delta + 1e-6
            or (
                abs(evaluation.overall_delta - best_evaluation.overall_delta) <= 1e-6
                and evaluation.target_category_delta > best_evaluation.target_category_delta
            )
        ):
            best_evaluation = evaluation

    return best_evaluation


def build_manual_move_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    object_id: int,
    issue_code: str,
    candidate_positions: list[tuple[float, float]],
    confidence: float,
    stage: str,
    expected_categories: list[ExpectedCategory],
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list):
        return None

    target_index = _find_object_index(objects, object_id)
    if target_index is None:
        return None

    # Spinners have no position and cannot be moved.
    target_object = objects[target_index]
    if target_object.get("x") is None or target_object.get("y") is None:
        return None

    object_before = dict(objects[target_index])
    best_evaluation: Any | None = None
    for candidate_x, candidate_y in candidate_positions:
        if deadline_exceeded():
            break

        candidate_map = _deep_copy_map(map_data)
        candidate_object = candidate_map["objects"][target_index]
        candidate_object["x"] = int(round(candidate_x))
        candidate_object["y"] = int(round(candidate_y))
        action = CorrectionAction(
            action_id=f"{stage}-{object_id:04d}",
            stage=stage,  # type: ignore[arg-type]
            action_type="move_object",
            reason_code=issue_code,
            object_ids=[object_id],
            before={
                "id": object_before["id"],
                "x": object_before["x"],
                "y": object_before["y"],
                "time": object_before["time"],
            },
            after={
                "id": candidate_object["id"],
                "x": candidate_object["x"],
                "y": candidate_object["y"],
                "time": candidate_object["time"],
            },
            confidence=confidence,
            expected_categories=expected_categories,
            expected_score_impact=0.3,
        )
        evaluation = evaluate_candidate_action(
            context=context,
            current_report=current_report,
            candidate_map=candidate_map,
            candidate_action=action,
        )
        if evaluation.accepted and (
            best_evaluation is None or evaluation.overall_delta > best_evaluation.overall_delta
        ):
            best_evaluation = evaluation
    return best_evaluation


def _resolve_target_object_id(issue_code: str, issue_object_ids: list[int], objects: list[dict[str, Any]]) -> int | None:
    if issue_object_ids:
        if issue_code.startswith("READABILITY_") and len(issue_object_ids) >= 2:
            return issue_object_ids[-1]
        if len(issue_object_ids) >= 2:
            return issue_object_ids[-1]
        return issue_object_ids[0]

    if len(objects) >= 2:
        return int(objects[1]["id"])
    return None


def _generate_position_candidates(
    *,
    map_data: dict[str, Any],
    context: PostprocessContext,
    target_index: int,
    compact: bool,
) -> list[tuple[float, float, float]]:
    objects = map_data["objects"]
    target = objects[target_index]
    previous_object = objects[target_index - 1] if target_index > 0 else None
    next_object = objects[target_index + 1] if target_index + 1 < len(objects) else None

    # Skip neighbors without coordinates (spinners) since position math
    # requires both endpoints to be positioned.
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

    padding = map_data["circleRadius"] + context.preset.safe_margin
    rng = random.Random(context.seed * 17 + int(target["id"]) * 131 + (7 if compact else 0))

    candidates: list[tuple[float, float, float]] = []
    base_angle = rng.uniform(0.0, math.tau)
    distances = [
        context.preset.min_jump_distance * (0.75 if compact else 1.0),
        context.preset.preferred_jump_distance * (0.68 if compact else 0.88),
        context.preset.preferred_jump_distance * (0.82 if compact else 1.0),
    ]

    if previous_object and next_object:
        midpoint_x = (float(previous_object["x"]) + float(next_object["x"])) / 2
        midpoint_y = (float(previous_object["y"]) + float(next_object["y"])) / 2
        candidates.append(
            (
                _local_position_score(
                    previous_object=previous_object,
                    current_object=target,
                    next_object=next_object,
                    candidate_x=midpoint_x,
                    candidate_y=midpoint_y,
                    context=context,
                ),
                clamp(midpoint_x, padding, PLAYFIELD_WIDTH - padding),
                clamp(midpoint_y, padding, PLAYFIELD_HEIGHT - padding),
            )
        )

    anchors = [item for item in (previous_object, next_object) if item is not None]
    for anchor in anchors:
        anchor_x = float(anchor["x"])
        anchor_y = float(anchor["y"])
        if previous_object and next_object:
            base_angle = math.atan2(
                float(next_object["y"]) - float(previous_object["y"]),
                float(next_object["x"]) - float(previous_object["x"]),
            )
        elif previous_object:
            base_angle = math.atan2(float(target["y"]) - float(previous_object["y"]), float(target["x"]) - float(previous_object["x"]))
        elif next_object:
            base_angle = math.atan2(float(next_object["y"]) - float(target["y"]), float(next_object["x"]) - float(target["x"]))

        for distance in distances:
            for angle_offset in (-1.2, -0.6, -0.25, 0.0, 0.25, 0.6, 1.2):
                jitter = (rng.random() - 0.5) * (0.18 if compact else 0.3)
                angle = base_angle + angle_offset + jitter
                candidate_x = clamp(
                    anchor_x + math.cos(angle) * distance,
                    padding,
                    PLAYFIELD_WIDTH - padding,
                )
                candidate_y = clamp(
                    anchor_y + math.sin(angle) * distance,
                    padding,
                    PLAYFIELD_HEIGHT - padding,
                )
                candidates.append(
                    (
                        _local_position_score(
                            previous_object=previous_object,
                            current_object=target,
                            next_object=next_object,
                            candidate_x=candidate_x,
                            candidate_y=candidate_y,
                            context=context,
                        ),
                        candidate_x,
                        candidate_y,
                    )
                )

    inward_x = float(target["x"]) + (PLAYFIELD_CENTER[0] - float(target["x"])) * 0.35
    inward_y = float(target["y"]) + (PLAYFIELD_CENTER[1] - float(target["y"])) * 0.35
    candidates.append(
        (
            _local_position_score(
                previous_object=previous_object,
                current_object=target,
                next_object=next_object,
                candidate_x=inward_x,
                candidate_y=inward_y,
                context=context,
            ),
            clamp(inward_x, padding, PLAYFIELD_WIDTH - padding),
            clamp(inward_y, padding, PLAYFIELD_HEIGHT - padding),
        )
    )

    deduped: dict[tuple[int, int], tuple[float, float, float]] = {}
    for score, x_value, y_value in candidates:
        key = (int(round(x_value)), int(round(y_value)))
        existing = deduped.get(key)
        candidate = (score, x_value, y_value)
        if existing is None or score > existing[0]:
            deduped[key] = candidate

    return sorted(deduped.values(), key=lambda item: (-item[0], item[1], item[2]))


def _local_position_score(
    *,
    previous_object: dict[str, Any] | None,
    current_object: dict[str, Any],
    next_object: dict[str, Any] | None,
    candidate_x: float,
    candidate_y: float,
    context: PostprocessContext,
) -> float:
    score = 120.0

    if previous_object is not None:
        incoming_distance = math.hypot(candidate_x - float(previous_object["x"]), candidate_y - float(previous_object["y"]))
        incoming_gap_ms = max(1, int(current_object["time"]) - int(previous_object["time"]))
        incoming_speed = incoming_distance / (incoming_gap_ms / 1000)
        score -= abs(incoming_distance - context.preset.preferred_jump_distance) * 0.18
        score -= max(0.0, incoming_speed - context.preset.max_cursor_speed * 0.92) * 0.25
        if incoming_distance < context.preset.min_jump_distance * 0.7:
            score -= 18

    if next_object is not None:
        outgoing_distance = math.hypot(float(next_object["x"]) - candidate_x, float(next_object["y"]) - candidate_y)
        outgoing_gap_ms = max(1, int(next_object["time"]) - int(current_object["time"]))
        outgoing_speed = outgoing_distance / (outgoing_gap_ms / 1000)
        score -= abs(outgoing_distance - context.preset.preferred_jump_distance) * 0.18
        score -= max(0.0, outgoing_speed - context.preset.max_cursor_speed * 0.92) * 0.25
        if outgoing_distance < context.preset.min_jump_distance * 0.7:
            score -= 18

        if previous_object is not None:
            incoming_angle = math.atan2(candidate_y - float(previous_object["y"]), candidate_x - float(previous_object["x"]))
            outgoing_angle = math.atan2(float(next_object["y"]) - candidate_y, float(next_object["x"]) - candidate_x)
            direction_change = abs(math.degrees(shortest_angle_delta(incoming_angle, outgoing_angle)))
            score -= max(0.0, direction_change - 140) * 0.22

    center_distance = math.hypot(candidate_x - PLAYFIELD_CENTER[0], candidate_y - PLAYFIELD_CENTER[1])
    edge_distance = min(candidate_x, PLAYFIELD_WIDTH - candidate_x, candidate_y, PLAYFIELD_HEIGHT - candidate_y)
    score -= center_distance / 18
    if edge_distance < context.preset.circle_radius + context.preset.safe_margin + 10:
        score -= (context.preset.circle_radius + context.preset.safe_margin + 10 - edge_distance) * 0.6

    local_energy = context.analysis.energy_at(int(current_object["time"]))
    if local_energy < context.preset.high_energy_threshold * 0.72:
        score += max(0.0, context.preset.preferred_jump_distance - center_distance * 0.15) * 0.04

    return score


def _find_object_index(objects: list[dict[str, Any]], object_id: int) -> int | None:
    for index, hit_object in enumerate(objects):
        if int(hit_object["id"]) == object_id:
            return index
    return None


def _deep_copy_map(map_data: dict[str, Any]) -> dict[str, Any]:
    copied = {
        key: value
        if key != "objects"
        else [dict(item) for item in value]
        for key, value in map_data.items()
    }
    return copied
