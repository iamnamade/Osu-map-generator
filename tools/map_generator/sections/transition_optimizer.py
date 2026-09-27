from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..config import DifficultyPreset
from ..models import AudioAnalysis
from ..utils import clamp
from .feature_extractor import nearest_anchor_time
from .section_config import SectionPipelineConfig
from .section_models import CandidateSectionReport, HybridSectionSelection, MapObject, SongSection
from .transition_analyzer import analyze_transition


@dataclass(frozen=True)
class TransitionOptimizationResult:
    left_objects: list[MapObject]
    right_objects: list[MapObject]
    transition: object
    accepted_corrections: list[dict[str, Any]]
    reverted_corrections: list[dict[str, Any]]
    updated_right_selection: HybridSectionSelection | None = None


def optimize_transition(
    *,
    boundary_index: int,
    left_section: SongSection,
    right_section: SongSection,
    left_selection: HybridSectionSelection,
    right_selection: HybridSectionSelection,
    left_objects: list[MapObject],
    right_objects: list[MapObject],
    candidate_reports: list[CandidateSectionReport],
    candidate_maps: dict[int, list[MapObject]],
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    config: SectionPipelineConfig,
) -> TransitionOptimizationResult:
    current_transition = analyze_transition(
        boundary_index=boundary_index,
        left_section=left_section,
        right_section=right_section,
        from_candidate=left_selection.source_candidate,
        to_candidate=right_selection.source_candidate,
        left_objects=left_objects,
        right_objects=right_objects,
        preset=preset,
    )
    accepted_corrections: list[dict[str, Any]] = []
    reverted_corrections: list[dict[str, Any]] = []
    best_left = deepcopy(left_objects)
    best_right = deepcopy(right_objects)
    best_transition = current_transition
    updated_right_selection: HybridSectionSelection | None = None

    if current_transition.classification in {"excellent", "safe"}:
        return TransitionOptimizationResult(
            left_objects=best_left,
            right_objects=best_right,
            transition=best_transition,
            accepted_corrections=accepted_corrections,
            reverted_corrections=reverted_corrections,
        )

    for attempt in (
        _try_position_adjustment,
        _try_timing_adjustment,
        _try_alternate_source,
        _try_remove_boundary_object,
        _try_insert_transition_object,
    ):
        outcome = attempt(
            boundary_index=boundary_index,
            left_section=left_section,
            right_section=right_section,
            left_selection=left_selection,
            right_selection=right_selection,
            left_objects=best_left,
            right_objects=best_right,
            candidate_reports=candidate_reports,
            candidate_maps=candidate_maps,
            analysis=analysis,
            preset=preset,
            config=config,
        )
        if outcome is None:
            continue
        if outcome["transition"].score > best_transition.score:
            best_left = outcome["left_objects"]
            best_right = outcome["right_objects"]
            best_transition = outcome["transition"]
            accepted_corrections.append(outcome["correction"])
            if outcome.get("updated_right_selection") is not None:
                updated_right_selection = outcome["updated_right_selection"]
            if best_transition.classification in {"excellent", "safe"}:
                break
        else:
            reverted_corrections.append(
                {
                    **outcome["correction"],
                    "accepted": False,
                    "rejectionReason": "Did not improve transition score.",
                }
            )

    best_transition.corrections.extend(accepted_corrections + reverted_corrections)
    return TransitionOptimizationResult(
        left_objects=best_left,
        right_objects=best_right,
        transition=best_transition,
        accepted_corrections=accepted_corrections,
        reverted_corrections=reverted_corrections,
        updated_right_selection=updated_right_selection,
    )


def _try_position_adjustment(**kwargs: Any) -> dict[str, Any] | None:
    left_objects = deepcopy(kwargs["left_objects"])
    right_objects = deepcopy(kwargs["right_objects"])
    if not left_objects or not right_objects:
        return None
    left_last = left_objects[-1]
    right_first = right_objects[0]
    midpoint_x = round((left_last.x + right_first.x) / 2)
    midpoint_y = round((left_last.y + right_first.y) / 2)
    right_objects[0] = MapObject(
        id=right_first.id,
        x=int(clamp(midpoint_x, 0, 512)),
        y=int(clamp(midpoint_y, 0, 384)),
        time=right_first.time,
    )
    transition = analyze_transition(
        boundary_index=kwargs["boundary_index"],
        left_section=kwargs["left_section"],
        right_section=kwargs["right_section"],
        from_candidate=kwargs["left_selection"].source_candidate,
        to_candidate=kwargs["right_selection"].source_candidate,
        left_objects=left_objects,
        right_objects=right_objects,
        preset=kwargs["preset"],
    )
    return {
        "left_objects": left_objects,
        "right_objects": right_objects,
        "transition": transition,
        "correction": {
            "actionType": "move_object",
            "accepted": True,
            "objectId": right_first.id,
            "reason": "Adjusted boundary entry position toward the prior section exit.",
        },
    }


def _try_timing_adjustment(**kwargs: Any) -> dict[str, Any] | None:
    right_objects = deepcopy(kwargs["right_objects"])
    if not right_objects:
        return None
    right_first = right_objects[0]
    anchor = nearest_anchor_time(
        kwargs["analysis"],
        time_ms=right_first.time,
        max_distance_ms=kwargs["config"].optimization.max_timing_shift_ms(
            kwargs["preset"].name
        ),
    )
    if anchor is None:
        return None
    anchor_time, anchor_type, _ = anchor
    right_objects[0] = MapObject(
        id=right_first.id,
        x=right_first.x,
        y=right_first.y,
        time=anchor_time,
    )
    if len(right_objects) > 1 and right_objects[1].time <= anchor_time:
        return None
    transition = analyze_transition(
        boundary_index=kwargs["boundary_index"],
        left_section=kwargs["left_section"],
        right_section=kwargs["right_section"],
        from_candidate=kwargs["left_selection"].source_candidate,
        to_candidate=kwargs["right_selection"].source_candidate,
        left_objects=kwargs["left_objects"],
        right_objects=right_objects,
        preset=kwargs["preset"],
    )
    return {
        "left_objects": deepcopy(kwargs["left_objects"]),
        "right_objects": right_objects,
        "transition": transition,
        "correction": {
            "actionType": "adjust_time",
            "accepted": True,
            "objectId": right_first.id,
            "reason": f"Shifted the boundary entry toward a nearby {anchor_type} anchor.",
        },
    }


def _try_alternate_source(**kwargs: Any) -> dict[str, Any] | None:
    section_id = kwargs["right_section"].id
    alternatives: list[tuple[float, int]] = []
    for report in kwargs["candidate_reports"]:
        for section in report.sections:
            if section.section_id != section_id:
                continue
            if report.candidate_index == kwargs["right_selection"].source_candidate:
                continue
            alternatives.append((section.scores.overall, report.candidate_index))
    alternatives.sort(key=lambda item: (-item[0], item[1]))
    for _, candidate_index in alternatives[: kwargs["config"].optimization.alternate_source_limit]:
        candidate_objects = [
            object_
            for object_ in kwargs["candidate_maps"][candidate_index]
            if kwargs["right_section"].start_ms <= object_.time < kwargs["right_section"].end_ms
        ]
        transition = analyze_transition(
            boundary_index=kwargs["boundary_index"],
            left_section=kwargs["left_section"],
            right_section=kwargs["right_section"],
            from_candidate=kwargs["left_selection"].source_candidate,
            to_candidate=candidate_index,
            left_objects=kwargs["left_objects"],
            right_objects=candidate_objects,
            preset=kwargs["preset"],
        )
        updated_selection = HybridSectionSelection(
            section_id=kwargs["right_selection"].section_id,
            start_ms=kwargs["right_selection"].start_ms,
            end_ms=kwargs["right_selection"].end_ms,
            label=kwargs["right_selection"].label,
            source_candidate=candidate_index,
            section_score=kwargs["right_selection"].section_score,
            selection_reason=(
                kwargs["right_selection"].selection_reason
                + " Swapped to an alternate source candidate to improve the boundary."
            ),
            lock_state=kwargs["right_selection"].lock_state,
            transition_status_before=kwargs["right_selection"].transition_status_before,
            transition_status_after=kwargs["right_selection"].transition_status_after,
            issues=list(kwargs["right_selection"].issues),
        )
        return {
            "left_objects": deepcopy(kwargs["left_objects"]),
            "right_objects": candidate_objects,
            "transition": transition,
            "updated_right_selection": updated_selection,
            "correction": {
                "actionType": "choose_alternative_section_source",
                "accepted": True,
                "candidateIndex": candidate_index,
                "reason": "Switched to an alternate section source with a safer entry transition.",
            },
        }
    return None


def _try_remove_boundary_object(**kwargs: Any) -> dict[str, Any] | None:
    left_objects = deepcopy(kwargs["left_objects"])
    right_objects = deepcopy(kwargs["right_objects"])
    if len(right_objects) >= 2:
        removed = right_objects.pop(0)
        transition = analyze_transition(
            boundary_index=kwargs["boundary_index"],
            left_section=kwargs["left_section"],
            right_section=kwargs["right_section"],
            from_candidate=kwargs["left_selection"].source_candidate,
            to_candidate=kwargs["right_selection"].source_candidate,
            left_objects=left_objects,
            right_objects=right_objects,
            preset=kwargs["preset"],
        )
        return {
            "left_objects": left_objects,
            "right_objects": right_objects,
            "transition": transition,
            "correction": {
                "actionType": "remove_object",
                "accepted": True,
                "objectId": removed.id,
                "reason": "Removed the first boundary object to clear an unsafe join.",
            },
        }
    if len(left_objects) >= 2:
        removed = left_objects.pop()
        transition = analyze_transition(
            boundary_index=kwargs["boundary_index"],
            left_section=kwargs["left_section"],
            right_section=kwargs["right_section"],
            from_candidate=kwargs["left_selection"].source_candidate,
            to_candidate=kwargs["right_selection"].source_candidate,
            left_objects=left_objects,
            right_objects=right_objects,
            preset=kwargs["preset"],
        )
        return {
            "left_objects": left_objects,
            "right_objects": right_objects,
            "transition": transition,
            "correction": {
                "actionType": "remove_object",
                "accepted": True,
                "objectId": removed.id,
                "reason": "Removed the last boundary object to clear an unsafe join.",
            },
        }
    return None


def _try_insert_transition_object(**kwargs: Any) -> dict[str, Any] | None:
    if not kwargs["config"].optimization.insertion_enabled:
        return None
    left_objects = deepcopy(kwargs["left_objects"])
    right_objects = deepcopy(kwargs["right_objects"])
    if not left_objects or not right_objects:
        return None
    left_last = left_objects[-1]
    right_first = right_objects[0]
    anchor = nearest_anchor_time(
        kwargs["analysis"],
        time_ms=(left_last.time + right_first.time) // 2,
        max_distance_ms=300,
    )
    if anchor is None:
        return None
    anchor_time, anchor_type, _ = anchor
    if anchor_time <= left_last.time or anchor_time >= right_first.time:
        return None
    new_object = MapObject(
        id=max([item.id for item in left_objects + right_objects], default=0) + 1000,
        x=round((left_last.x + right_first.x) / 2),
        y=round((left_last.y + right_first.y) / 2),
        time=anchor_time,
    )
    right_objects.insert(0, new_object)
    transition = analyze_transition(
        boundary_index=kwargs["boundary_index"],
        left_section=kwargs["left_section"],
        right_section=kwargs["right_section"],
        from_candidate=kwargs["left_selection"].source_candidate,
        to_candidate=kwargs["right_selection"].source_candidate,
        left_objects=left_objects,
        right_objects=right_objects,
        preset=kwargs["preset"],
    )
    return {
        "left_objects": left_objects,
        "right_objects": right_objects,
        "transition": transition,
        "correction": {
            "actionType": "insert_transition_object",
            "accepted": True,
            "anchorType": anchor_type,
            "reason": "Inserted one musically anchored transition circle between sections.",
        },
    }
