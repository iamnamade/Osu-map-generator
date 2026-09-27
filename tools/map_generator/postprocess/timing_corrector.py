from __future__ import annotations

from typing import Any

from .local_optimizer import deadline_exceeded, evaluate_candidate_action
from .models import CorrectionAction, PostprocessContext


def build_timing_action(
    *,
    map_data: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
    issue_code: str,
    issue_object_ids: list[int],
    confidence: float,
) -> Any | None:
    objects = map_data.get("objects")
    if not isinstance(objects, list) or not objects:
        return None

    target_index = _resolve_target_index(objects, issue_object_ids)
    if target_index is None:
        return None

    target_object = objects[target_index]
    previous_object = objects[target_index - 1] if target_index > 0 else None
    next_object = objects[target_index + 1] if target_index + 1 < len(objects) else None
    max_adjustment = context.limits.max_timing_adjustment_ms_by_difficulty[context.difficulty]
    anchors = _candidate_anchors(context=context, current_time=int(target_object["time"]))
    best_evaluation: Any | None = None

    for anchor_time_ms, anchor_strength in anchors:
        if deadline_exceeded():
            break
        if abs(anchor_time_ms - int(target_object["time"])) > max_adjustment:
            continue

        adjusted_time_ms = anchor_time_ms
        if previous_object is not None:
            adjusted_time_ms = max(adjusted_time_ms, int(previous_object["time"]) + context.preset.min_gap_ms)
        if next_object is not None:
            adjusted_time_ms = min(adjusted_time_ms, int(next_object["time"]) - context.preset.min_gap_ms)

        if adjusted_time_ms == int(target_object["time"]):
            continue
        if previous_object is not None and adjusted_time_ms <= int(previous_object["time"]):
            continue
        if next_object is not None and adjusted_time_ms >= int(next_object["time"]):
            continue

        candidate_map = {
            key: value if key != "objects" else [dict(item) for item in value]
            for key, value in map_data.items()
        }
        candidate_map["objects"][target_index]["time"] = int(adjusted_time_ms)

        candidate_action = CorrectionAction(
            action_id=f"timing-{int(target_object['id']):04d}",
            stage="timing_corrections",
            action_type="adjust_time",
            reason_code=issue_code,
            object_ids=[int(target_object["id"])],
            before={
                "id": int(target_object["id"]),
                "x": int(target_object["x"]) if target_object.get("x") is not None else None,
                "y": int(target_object["y"]) if target_object.get("y") is not None else None,
                "time": int(target_object["time"]),
            },
            after={
                "id": int(target_object["id"]),
                "x": int(target_object["x"]) if target_object.get("x") is not None else None,
                "y": int(target_object["y"]) if target_object.get("y") is not None else None,
                "time": int(adjusted_time_ms),
            },
            confidence=min(0.99, confidence + anchor_strength * 0.08),
            expected_categories=["timing", "rhythm", "difficultyConsistency"],
            expected_score_impact=max(0.12, abs(adjusted_time_ms - int(target_object["time"])) / max_adjustment),
        )
        evaluation = evaluate_candidate_action(
            context=context,
            current_report=current_report,
            candidate_map=candidate_map,
            candidate_action=candidate_action,
        )
        if evaluation.accepted and (
            best_evaluation is None
            or evaluation.overall_delta > best_evaluation.overall_delta
            or (
                abs(evaluation.overall_delta - best_evaluation.overall_delta) <= 1e-6
                and evaluation.target_category_delta > best_evaluation.target_category_delta
            )
        ):
            best_evaluation = evaluation

    return best_evaluation


def _resolve_target_index(objects: list[dict[str, Any]], issue_object_ids: list[int]) -> int | None:
    if issue_object_ids:
        target_id = issue_object_ids[0]
        for index, hit_object in enumerate(objects):
            if int(hit_object["id"]) == target_id:
                return index
    return 0 if objects else None


def _candidate_anchors(
    *,
    context: PostprocessContext,
    current_time: int,
) -> list[tuple[int, float]]:
    candidates: list[tuple[int, float, float]] = []
    for beat in context.analysis.beats:
        score = abs(beat.time_ms - current_time) - beat.strength * 28
        if beat.strength >= context.preset.beat_strength_threshold:
            candidates.append((score, beat.time_ms, beat.strength))
    for onset in context.analysis.onsets:
        score = abs(onset.time_ms - current_time) - onset.strength * 32
        if onset.strength >= context.preset.onset_strength_threshold * 0.85:
            candidates.append((score, onset.time_ms, onset.strength))

    ordered = sorted(candidates, key=lambda item: (item[0], item[1]))
    deduped: list[tuple[int, float]] = []
    seen_times: set[int] = set()
    for _score, anchor_time_ms, strength in ordered:
        if anchor_time_ms in seen_times:
            continue
        deduped.append((anchor_time_ms, strength))
        seen_times.add(anchor_time_ms)
    return deduped[:4]
