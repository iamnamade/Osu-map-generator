from __future__ import annotations

import math
import random
from typing import Any

from ..position_generator import PLAYFIELD_CENTER
from ..utils import clamp
from .local_optimizer import deadline_exceeded, evaluate_candidate_action
from .models import CorrectionAction, PostprocessContext

# Maximum candidate objects to evaluate per density issue. Candidates are
# ranked by removal priority, so the best candidates are tried first.
_MAX_CANDIDATES_PER_ISSUE = 6

REMOVE_ISSUE_CODES = {
    "DENSITY_HIGH_MAP_LOW_AUDIO",
    "DENSITY_UNEXPLAINED_SPIKE",
    "DENSITY_OBJECTS_IN_OUTRO_SILENCE",
    "TIMING_OBJECT_IN_SILENCE",
}
INSERT_ISSUE_CODES = {
    "DENSITY_LOW_MAP_HIGH_AUDIO",
    "DENSITY_EARLY_MAP_END",
    "TIMING_STRONG_EVENTS_IGNORED",
}


def build_density_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    issue_object_ids: list[int],
    confidence: float,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> Any | None:
    if issue_code in INSERT_ISSUE_CODES:
        return _build_insert_action(
            map_data=map_data,
            current_report=current_report,
            context=context,
            issue_code=issue_code,
            confidence=confidence,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )

    return _build_remove_action(
        map_data=map_data,
        current_report=current_report,
        context=context,
        issue_code=issue_code,
        issue_object_ids=issue_object_ids,
        confidence=confidence,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )


def _build_remove_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    issue_object_ids: list[int],
    confidence: float,
    start_time_ms: int | None,
    end_time_ms: int | None,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) <= 2:
        return None

    candidate_indices = [
        index
        for index, hit_object in enumerate(objects)
        if _is_in_window(int(hit_object["time"]), start_time_ms, end_time_ms)
    ]
    if issue_object_ids:
        candidate_indices = [
            index for index in candidate_indices if int(objects[index]["id"]) in set(issue_object_ids)
        ] or candidate_indices

    ranked_indices = sorted(
        candidate_indices,
        key=lambda index: (
            -_removal_priority(objects, index, context),
            int(objects[index]["time"]),
            int(objects[index]["id"]),
        ),
    )[:_MAX_CANDIDATES_PER_ISSUE]

    for index in ranked_indices:
        if deadline_exceeded():
            break
        if index == 0 or index == len(objects) - 1:
            continue
        hit_object = objects[index]
        anchor_delta_ms, anchor_strength = _nearest_anchor_profile(context, int(hit_object["time"]))
        local_energy = context.analysis.energy_at(int(hit_object["time"]))
        if anchor_strength >= max(context.preset.strong_beat_threshold, context.preset.onset_strength_threshold) and anchor_delta_ms <= 35:
            continue
        if local_energy > context.preset.high_energy_threshold * 0.95 and issue_code != "TIMING_OBJECT_IN_SILENCE":
            continue

        candidate_map = _copy_map(map_data)
        removed_object = candidate_map["objects"].pop(index)
        _reindex_objects(candidate_map["objects"])

        action = CorrectionAction(
            action_id=f"density-remove-{int(hit_object['id']):04d}",
            stage="density_corrections",
            action_type="remove_object",
            reason_code=issue_code,
            object_ids=[int(hit_object["id"])],
            before={
                "id": int(hit_object["id"]),
                "x": int(hit_object["x"]) if hit_object.get("x") is not None else None,
                "y": int(hit_object["y"]) if hit_object.get("y") is not None else None,
                "time": int(hit_object["time"]),
                "anchorDeltaMs": anchor_delta_ms,
                "anchorStrength": round(anchor_strength, 4),
                "energy": round(local_energy, 4),
            },
            after={
                "removed": True,
                "time": int(removed_object["time"]),
            },
            confidence=min(0.99, confidence + max(0.0, (0.35 - local_energy)) * 0.2),
            expected_categories=["densityConsistency", "difficultyConsistency", "rhythm"],
            expected_score_impact=0.35,
        )
        evaluation = evaluate_candidate_action(
            context=context,
            current_report=current_report,
            candidate_map=candidate_map,
            candidate_action=action,
        )
        if evaluation.accepted:
            return evaluation

    return None


def _build_insert_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    confidence: float,
    start_time_ms: int | None,
    end_time_ms: int | None,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or len(objects) < 2:
        return None

    anchors = _collect_insert_anchors(context=context, start_time_ms=start_time_ms, end_time_ms=end_time_ms)
    if not anchors:
        return None

    for anchor_time_ms, anchor_strength in anchors:
        if deadline_exceeded():
            break
        insert_index = _find_insert_index(objects, anchor_time_ms)
        previous_object = objects[insert_index - 1] if insert_index > 0 else None
        next_object = objects[insert_index] if insert_index < len(objects) else None

        if previous_object is None or next_object is None:
            continue

        gap_before = anchor_time_ms - int(previous_object["time"])
        gap_after = int(next_object["time"]) - anchor_time_ms
        if gap_before < context.preset.min_gap_ms or gap_after < context.preset.min_gap_ms:
            continue

        gap_span = int(next_object["time"]) - int(previous_object["time"])
        if gap_span < int(context.preset.target_gap_ms * 1.35):
            continue

        candidate_x, candidate_y = _safe_insert_position(
            previous_object=previous_object,
            next_object=next_object,
            anchor_time_ms=anchor_time_ms,
            circle_radius=float(map_data.get("circleRadius", context.preset.circle_radius)),
            context=context,
        )
        candidate_map = _copy_map(map_data)
        candidate_map["objects"].insert(
            insert_index,
            {
                "id": 0,
                "type": "circle",
                "x": int(round(candidate_x)),
                "y": int(round(candidate_y)),
                "time": int(anchor_time_ms),
            },
        )
        _reindex_objects(candidate_map["objects"])
        inserted_object = candidate_map["objects"][insert_index]

        action = CorrectionAction(
            action_id=f"density-insert-{anchor_time_ms}",
            stage="density_corrections",
            action_type="insert_object",
            reason_code=issue_code,
            object_ids=[int(previous_object["id"]), int(next_object["id"])],
            before={
                "gapStartId": int(previous_object["id"]),
                "gapEndId": int(next_object["id"]),
                "gapMs": gap_span,
                "anchorStrength": round(anchor_strength, 4),
            },
            after={
                "id": int(inserted_object["id"]),
                "x": int(inserted_object["x"]),
                "y": int(inserted_object["y"]),
                "time": int(inserted_object["time"]),
                "anchorStrength": round(anchor_strength, 4),
            },
            confidence=min(0.99, confidence + anchor_strength * 0.08),
            expected_categories=["densityConsistency", "difficultyConsistency", "rhythm", "movement"],
            expected_score_impact=0.4,
        )
        evaluation = evaluate_candidate_action(
            context=context,
            current_report=current_report,
            candidate_map=candidate_map,
            candidate_action=action,
        )
        if evaluation.accepted:
            return evaluation

    return None


def _collect_insert_anchors(
    *,
    context: PostprocessContext,
    start_time_ms: int | None,
    end_time_ms: int | None,
) -> list[tuple[int, float]]:
    anchors: list[tuple[float, int, float]] = []
    existing_times = {item.time_ms for item in context.analysis.beats[:0]}
    del existing_times

    for event in context.analysis.beats:
        if event.strength < context.preset.strong_beat_threshold:
            continue
        if not _is_in_window(event.time_ms, start_time_ms, end_time_ms):
            continue
        anchors.append((-event.strength * 1.1, event.time_ms, event.strength))
    for event in context.analysis.onsets:
        if event.strength < context.preset.onset_strength_threshold + 0.08:
            continue
        if not _is_in_window(event.time_ms, start_time_ms, end_time_ms):
            continue
        anchors.append((-event.strength, event.time_ms, event.strength))

    ordered = sorted(anchors, key=lambda item: (item[0], item[1]))
    deduped: list[tuple[int, float]] = []
    seen_times: set[int] = set()
    for _priority, time_ms, strength in ordered:
        if time_ms in seen_times:
            continue
        deduped.append((time_ms, strength))
        seen_times.add(time_ms)
    return deduped[:_MAX_CANDIDATES_PER_ISSUE]


def _safe_insert_position(
    *,
    previous_object: dict[str, Any],
    next_object: dict[str, Any],
    anchor_time_ms: int,
    circle_radius: float,
    context: PostprocessContext,
) -> tuple[float, float]:
    padding = circle_radius + context.preset.safe_margin
    midpoint_x = (float(previous_object["x"]) + float(next_object["x"])) / 2
    midpoint_y = (float(previous_object["y"]) + float(next_object["y"])) / 2
    span_x = float(next_object["x"]) - float(previous_object["x"])
    span_y = float(next_object["y"]) - float(previous_object["y"])
    span_length = math.hypot(span_x, span_y)
    rng = random.Random(context.seed * 43 + anchor_time_ms)

    if span_length > 1e-6:
        normal_x = -span_y / span_length
        normal_y = span_x / span_length
    else:
        angle = rng.uniform(0.0, math.tau)
        normal_x = math.cos(angle)
        normal_y = math.sin(angle)

    offset = min(
        max(circle_radius * 1.15, context.preset.min_jump_distance * 0.42),
        context.preset.preferred_jump_distance * 0.4,
    )
    sign = 1.0 if rng.random() >= 0.5 else -1.0
    candidate_x = midpoint_x + normal_x * offset * sign
    candidate_y = midpoint_y + normal_y * offset * sign

    # Phase 23: radius-aware clearance. Never leave the inserted disc inside
    # either neighbor's disc (sum of radii + margin). When the preferred
    # offset is too small to clear, push further along the same deterministic
    # normal — never diagonally across the gap.
    clearance = circle_radius * 2.0 + context.preset.safe_margin
    required_offset = _offset_for_clearance(
        previous_object=previous_object,
        next_object=next_object,
        midpoint_x=midpoint_x,
        midpoint_y=midpoint_y,
        normal_x=normal_x,
        normal_y=normal_y,
        sign=sign,
        clearance=clearance,
    )
    if required_offset is not None and required_offset > offset:
        offset = required_offset
        candidate_x = midpoint_x + normal_x * offset * sign
        candidate_y = midpoint_y + normal_y * offset * sign

    if context.analysis.energy_at(anchor_time_ms) < context.preset.high_energy_threshold * 0.8:
        candidate_x = midpoint_x + (PLAYFIELD_CENTER[0] - midpoint_x) * 0.2
        candidate_y = midpoint_y + (PLAYFIELD_CENTER[1] - midpoint_y) * 0.2

    return (
        clamp(candidate_x, padding, 512 - padding),
        clamp(candidate_y, padding, 384 - padding),
    )


def _offset_for_clearance(
    *,
    previous_object: dict[str, Any],
    next_object: dict[str, Any],
    midpoint_x: float,
    midpoint_y: float,
    normal_x: float,
    normal_y: float,
    sign: float,
    clearance: float,
) -> float | None:
    """Smallest offset along the normal clearing both neighbors by ``clearance``.

    Returns None when the gap is so tight that no offset up to the hard cap
    can fit a disc between the two neighbors (the caller leaves the preferred
    offset and validation rejects the candidate).
    """
    max_offset = clearance * 1.5
    required = 0.0
    for neighbor in (previous_object, next_object):
        vec_x = midpoint_x - float(neighbor["x"])
        vec_y = midpoint_y - float(neighbor["y"])
        dot = vec_x * normal_x * sign + vec_y * normal_y * sign
        span_squared = vec_x * vec_x + vec_y * vec_y
        target_squared = clearance * clearance
        discriminant = dot * dot - span_squared + target_squared
        if discriminant <= 0.0:
            # Already clears this neighbor at offset 0 (or the gap is wider
            # than the disc diameter in this direction).
            continue
        root = -dot + math.sqrt(discriminant)
        required = max(required, root)
    if required > max_offset:
        return None
    return required


def _nearest_anchor_profile(context: PostprocessContext, time_ms: int) -> tuple[int, float]:
    best_delta_ms = 10**9
    best_strength = 0.0
    for event in (*context.analysis.beats, *context.analysis.onsets):
        delta_ms = abs(event.time_ms - time_ms)
        if delta_ms < best_delta_ms or (delta_ms == best_delta_ms and event.strength > best_strength):
            best_delta_ms = delta_ms
            best_strength = event.strength
    return best_delta_ms if best_delta_ms != 10**9 else 10**9, best_strength


def _removal_priority(
    objects: list[dict[str, Any]],
    index: int,
    context: PostprocessContext,
) -> float:
    hit_object = objects[index]
    time_ms = int(hit_object["time"])
    local_energy = context.analysis.energy_at(time_ms)
    anchor_delta_ms, anchor_strength = _nearest_anchor_profile(context, time_ms)
    previous_gap = time_ms - int(objects[index - 1]["time"]) if index > 0 else context.preset.target_gap_ms
    next_gap = int(objects[index + 1]["time"]) - time_ms if index + 1 < len(objects) else context.preset.target_gap_ms
    min_gap = min(previous_gap, next_gap)
    return (
        max(0.0, context.preset.quiet_energy_threshold * 1.6 - local_energy) * 2.4
        + max(0.0, (48 - anchor_delta_ms) / 48) * 0.15
        + max(0.0, context.preset.target_gap_ms - min_gap) / max(1.0, context.preset.target_gap_ms) * 1.2
        + max(0.0, context.preset.onset_strength_threshold - anchor_strength) * 0.9
    )


def _find_insert_index(objects: list[dict[str, Any]], time_ms: int) -> int:
    for index, hit_object in enumerate(objects):
        if time_ms < int(hit_object["time"]):
            return index
    return len(objects)


def _reindex_objects(objects: list[dict[str, Any]]) -> None:
    objects.sort(key=lambda item: (int(item["time"]), int(item["id"])))
    for index, hit_object in enumerate(objects, start=1):
        hit_object["id"] = index
        hit_object["time"] = int(hit_object["time"])
        if hit_object.get("x") is not None:
            hit_object["x"] = int(round(float(hit_object["x"])))
            hit_object["y"] = int(round(float(hit_object["y"])))


def _is_in_window(time_ms: int, start_time_ms: int | None, end_time_ms: int | None) -> bool:
    if start_time_ms is not None and time_ms < start_time_ms:
        return False
    if end_time_ms is not None and time_ms > end_time_ms:
        return False
    return True


def _copy_map(map_data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if key != "objects" else [dict(item) for item in value]
        for key, value in map_data.items()
    }
