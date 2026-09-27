from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from .models import ImprovementPassEntry

# Callback contract: given an adjusted map, run the standard validate ->
# improve -> validate post-process pipeline plus difficulty analysis, and
# return (validation_report, difficulty_result). difficulty_result must carry
# .report (DifficultyReport) and .rebalance_plan (RebalancePlan). Returning
# None signals that this pass cannot produce a valid improved map.
PassProcessor = Callable[[dict[str, Any]], tuple[Any, Any] | None]


@dataclass(frozen=True)
class ImprovementResult:
    passes_used: int
    early_stopped: bool
    history: list[ImprovementPassEntry]
    final_map: dict[str, Any] | None
    final_scores: Any | None
    improvement_gain: float
    final_replay_report: Any | None = None


def run_improvement_passes(
    *,
    current_map: dict[str, Any],
    current_plan: Any,
    current_scores: Any,
    pass_processor: PassProcessor,
    seed: int,
    candidate_index: int | None = None,
    max_passes: int = 2,
    stop_gain_threshold: float = 0.15,
) -> ImprovementResult:
    """Run up to ``max_passes`` deterministic improvement rounds.

    Each pass applies the difficulty engine's rebalancing plan to the current
    champion map, hands the adjusted map to ``pass_processor`` (validate ->
    improve -> validate -> difficulty), and re-scores the improved output.
    A pass is accepted only when the composite overall score improves by more
    than ``stop_gain_threshold``; otherwise evolution stops early.
    """
    from ..difficulty.common import clamp

    if max_passes <= 0:
        return ImprovementResult(
            passes_used=0,
            early_stopped=True,
            history=[],
            final_map=None,
            final_scores=current_scores,
            improvement_gain=0.0,
        )

    history: list[ImprovementPassEntry] = []
    early_stopped = False
    gain = 0.0
    current_replay_report = None

    for pass_number in range(1, max_passes + 1):
        if not current_plan or not current_plan.actions or getattr(
            current_plan.deviation, "is_within_target", False
        ):
            early_stopped = True
            break

        adjusted = _apply_rebalance_actions(current_map, current_plan)
        outcome = pass_processor(adjusted)
        if outcome is None:
            early_stopped = True
            break

        replay_report = None
        if len(outcome) >= 3:
            validation_report, difficulty_result, replay_report = (
                outcome[0],
                outcome[1],
                outcome[2],
            )
        else:
            validation_report, difficulty_result = outcome
        new_scores = _score_candidate(
            validation_report=validation_report,
            difficulty_report=difficulty_result.report,
            replay_report=replay_report,
        )
        delta = new_scores.overall - current_scores.overall
        accepted = delta > stop_gain_threshold
        history.append(
            ImprovementPassEntry(
                pass_number=pass_number,
                candidate_index=(
                    candidate_index if candidate_index is not None else _candidate_index_from_seed(seed)
                ),
                overall_before=round(float(current_scores.overall), 3),
                overall_after=round(float(new_scores.overall), 3),
                accepted=accepted,
            )
        )
        if not accepted:
            early_stopped = True
            break

        gain += delta
        current_map = adjusted
        current_scores = new_scores
        current_replay_report = replay_report
        current_plan = difficulty_result.rebalance_plan

    return ImprovementResult(
        passes_used=len(history),
        early_stopped=early_stopped,
        history=history,
        final_map=current_map if gain > 0 else None,
        final_scores=current_scores,
        improvement_gain=round(gain, 3),
        final_replay_report=current_replay_report if gain > 0 else None,
    )


def _apply_rebalance_actions(
    map_data: dict[str, Any],
    plan: Any,
) -> dict[str, Any]:
    """Deterministically apply positional rebalancing actions to a map dict."""
    adjusted = copy.deepcopy(map_data)
    objects = adjusted.get("objects")
    if not isinstance(objects, list):
        return adjusted
    object_lookup = {
        item.get("id"): item
        for item in objects
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    for action in plan.actions:
        if action.action not in ("reduce_jump", "increase_movement", "simplify_slider"):
            continue
        target = object_lookup.get(action.object_id)
        if target is None:
            continue
        after = action.after
        if isinstance(after, dict):
            if isinstance(after.get("x"), (int, float)) and isinstance(
                after.get("y"), (int, float)
            ):
                target["x"] = round(float(after["x"]), 2)
                target["y"] = round(float(after["y"]), 2)
            if isinstance(after.get("repeats"), int):
                target["repeats"] = after["repeats"]
    return adjusted


def _score_candidate(
    *,
    validation_report: Any,
    difficulty_report: Any,
    replay_report: Any = None,
) -> Any:
    from .scoring import score_candidate

    return score_candidate(
        improved_report=validation_report,
        difficulty_report=difficulty_report,
        replay_report=replay_report,
    )


def _candidate_index_from_seed(seed: int) -> int:
    return seed % 1000
