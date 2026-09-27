from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..difficulty.common import clamp
from .issues import detect_issues
from .models import (
    ObjectAdjustment,
    RebalancePass,
    RebalanceReport,
    RebalanceSummary,
    SectionQuality,
    SliderAdjustment,
    SpinnerAdjustment,
)
from .collisions import resolve_collisions
from .objects import rebalance_positions
from .patterns import unstack_objects
from .sections import analyze_sections
from .sliders import optimize_sliders
from .spinners import optimize_spinners

MIN_COMPOSITE_GAIN = 0.5


@dataclass
class MapEvaluation:
    """Post-evaluation snapshot produced by the host pipeline's evaluator."""

    difficulty_report: Any | None = None
    replay_report: Any | None = None
    validation_report: Any | None = None


@dataclass
class _Snapshot:
    evaluation: MapEvaluation
    sections: list[SectionQuality]
    issues: list[Any]
    quality: float
    replay_score: float
    cursor_efficiency: float
    star_rating: float
    composite: float


@dataclass
class RebalanceOutcome:
    map_dict: dict[str, Any]
    report: RebalanceReport
    final_evaluation: MapEvaluation | None
    improved: bool


def run_rebalance(
    *,
    map_dict: dict[str, Any],
    difficulty_report: Any,
    replay_report: Any,
    validation_report: Any | None = None,
    difficulty: str = "normal",
    seed: int,
    max_passes: int = 2,
    evaluator: Callable[[dict[str, Any]], MapEvaluation | None],
    map_title: str = "",
    map_artist: str = "",
    min_composite_gain: float = MIN_COMPOSITE_GAIN,
    phrase_density_at: Any | None = None,
) -> RebalanceOutcome:
    """Run iterative adaptive rebalancing passes on ``map_dict``.

    Flow per pass: analyze -> improve -> re-evaluate -> compare. When a pass
    does not produce a meaningful composite gain the loop stops early and only
    the best version is kept. Everything is deterministic: no randomness, and
    identical inputs (map, reports, seed, difficulty, options) always produce
    the identical improved map and report.
    """
    initial_snapshot = _build_snapshot(
        map_dict=map_dict,
        evaluation=MapEvaluation(
            difficulty_report=difficulty_report,
            replay_report=replay_report,
            validation_report=validation_report,
        ),
        difficulty=difficulty,
        evaluator=evaluator,
        phrase_density_at=phrase_density_at,
    )
    if initial_snapshot is None:
        return _no_change_outcome(map_dict, initial_snapshot, difficulty, seed, map_title, map_artist)

    initial_quality = initial_snapshot.quality
    initial_replay = initial_snapshot.replay_score
    initial_cursor = initial_snapshot.cursor_efficiency
    initial_star = initial_snapshot.star_rating

    best_map = map_dict
    best_snapshot = initial_snapshot
    passes: list[RebalancePass] = []
    object_adjustments: list[ObjectAdjustment] = []
    slider_adjustments: list[SliderAdjustment] = []
    spinner_adjustments: list[SpinnerAdjustment] = []
    modified_sections: set[str] = set()
    early_stopped = False

    for pass_number in range(1, max_passes + 1):
        improvements = _collect_adjustments(
            map_dict=best_map,
            sections=best_snapshot.sections,
            issues=best_snapshot.issues,
            difficulty_report=best_snapshot.evaluation.difficulty_report,
            difficulty=difficulty,
        )
        if improvements is None:
            early_stopped = True
            break
        candidate_map, adjustments, new_object, new_slider, new_spinner = improvements

        score_before = best_snapshot.composite
        candidate_snapshot = _build_snapshot(
            map_dict=candidate_map,
            evaluation=None,
            difficulty=difficulty,
            evaluator=evaluator,
            phrase_density_at=phrase_density_at,
        )
        if candidate_snapshot is None:
            # Re-evaluation failed (invalid structure): reject the pass.
            passes.append(
                RebalancePass(
                    pass_number=pass_number,
                    score_before=round(score_before, 3),
                    score_after=round(score_before, 3),
                    issues_found=len(best_snapshot.issues),
                    sections_modified=0,
                    adjustments_count=len(adjustments),
                    accepted=False,
                )
            )
            early_stopped = True
            break

        score_after = candidate_snapshot.composite
        gain = score_after - score_before
        accepted = gain >= min_composite_gain
        modified_labels = _section_labels(adjustments)
        passes.append(
            RebalancePass(
                pass_number=pass_number,
                score_before=round(score_before, 3),
                score_after=round(score_after, 3),
                issues_found=len(best_snapshot.issues),
                sections_modified=len(modified_labels),
                adjustments_count=len(adjustments),
                accepted=accepted,
            )
        )
        if accepted:
            best_map = candidate_map
            best_snapshot = candidate_snapshot
            object_adjustments.extend(new_object)
            slider_adjustments.extend(new_slider)
            spinner_adjustments.extend(new_spinner)
            modified_sections.update(modified_labels)
        else:
            early_stopped = True
            break

    final_snapshot = best_snapshot
    summary = RebalanceSummary(
        passes_run=len(passes),
        early_stopped=early_stopped,
        sections_modified=len(modified_sections),
        objects_adjusted=len(object_adjustments),
        sliders_optimized=len(slider_adjustments),
        spinners_adjusted=len(spinner_adjustments),
        issues_found=len(initial_snapshot.issues),
        quality_before=round(initial_quality, 2),
        quality_after=round(final_snapshot.quality, 2),
        quality_gain=round(final_snapshot.quality - initial_quality, 2),
        replay_before=round(initial_replay, 2),
        replay_after=round(final_snapshot.replay_score, 2),
        replay_gain=round(final_snapshot.replay_score - initial_replay, 2),
        cursor_efficiency_before=round(initial_cursor, 4),
        cursor_efficiency_after=round(final_snapshot.cursor_efficiency, 4),
        cursor_efficiency_gain=round(
            final_snapshot.cursor_efficiency - initial_cursor,
            4,
        ),
        star_rating_before=round(initial_star, 2),
        star_rating_after=round(final_snapshot.star_rating, 2),
        weakest_section=_weakest_section(final_snapshot.sections),
        strongest_section=_strongest_section(final_snapshot.sections),
    )
    report = RebalanceReport(
        version=1,
        map_title=map_title,
        map_artist=map_artist,
        difficulty=difficulty,
        seed=seed,
        sections=initial_snapshot.sections,
        issues=initial_snapshot.issues,
        object_adjustments=object_adjustments,
        slider_adjustments=slider_adjustments,
        spinner_adjustments=spinner_adjustments,
        passes=passes,
        summary=summary,
    )
    improved = bool(object_adjustments or slider_adjustments or spinner_adjustments)
    return RebalanceOutcome(
        map_dict=best_map if improved else map_dict,
        report=report,
        final_evaluation=final_snapshot.evaluation,
        improved=improved,
    )


def _build_snapshot(
    *,
    map_dict: dict[str, Any],
    evaluation: MapEvaluation | None,
    difficulty: str,
    evaluator: Callable[[dict[str, Any]], MapEvaluation | None],
    phrase_density_at: Any | None = None,
) -> _Snapshot | None:
    if evaluation is None:
        evaluation = evaluator(map_dict)
    if evaluation is None or evaluation.difficulty_report is None:
        return None
    sections = analyze_sections(
        map_dict=map_dict,
        difficulty_report=evaluation.difficulty_report,
        replay_report=evaluation.replay_report,
        difficulty=difficulty,
        phrase_density_at=phrase_density_at,
    )
    issues = detect_issues(
        sections=sections,
        map_dict=map_dict,
        difficulty_report=evaluation.difficulty_report,
        replay_report=evaluation.replay_report,
        difficulty=difficulty,
    )
    quality = (
        sum(section.quality_score for section in sections) / len(sections)
        if sections
        else 50.0
    )
    replay_score = _replay_overall(evaluation.replay_report)
    cursor_efficiency = _cursor_efficiency(evaluation.replay_report)
    star_rating = float(
        getattr(
            getattr(evaluation.difficulty_report, "star_rating", None),
            "overall",
            0.0,
        )
        or 0.0
    )
    composite = clamp(
        quality * 0.55 + replay_score * 0.30 + cursor_efficiency * 100.0 * 0.15,
        0.0,
        100.0,
    )
    return _Snapshot(
        evaluation=evaluation,
        sections=sections,
        issues=issues,
        quality=quality,
        replay_score=replay_score,
        cursor_efficiency=cursor_efficiency,
        star_rating=star_rating,
        composite=composite,
    )


def _collect_adjustments(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    issues: list[Any],
    difficulty_report: Any | None,
    difficulty: str,
) -> tuple[dict[str, Any], list[Any], list[ObjectAdjustment], list[SliderAdjustment], list[SpinnerAdjustment]] | None:
    """Apply every improvement module in a deterministic order.

    Returns the candidate map plus the per-module adjustment records, or None
    when no module found anything to improve.
    """
    current = map_dict
    adjustments: list[Any] = []
    new_object: list[ObjectAdjustment] = []
    new_slider: list[SliderAdjustment] = []
    new_spinner: list[SpinnerAdjustment] = []

    current, records = rebalance_positions(
        map_dict=current,
        sections=sections,
        issues=issues,
        difficulty_report=difficulty_report,
        difficulty=difficulty,
    )
    adjustments.extend(records)
    new_object.extend(records)

    current, records = unstack_objects(
        map_dict=current,
        sections=sections,
    )
    adjustments.extend(records)
    new_object.extend(records)

    # Phase 23: resolve slider-body collisions (disc vs slider body, slider
    # vs slider) that unstacking cannot see. Runs after unstacking so
    # already-fixed disc pairs are not double-adjusted.
    current, records = resolve_collisions(
        map_dict=current,
        sections=sections,
    )
    adjustments.extend(records)
    new_object.extend(records)

    current, records = optimize_sliders(
        map_dict=current,
        sections=sections,
        issues=issues,
        difficulty=difficulty,
    )
    adjustments.extend(records)
    new_slider.extend(records)

    current, records = optimize_spinners(
        map_dict=current,
        sections=sections,
        issues=issues,
        difficulty=difficulty,
    )
    adjustments.extend(records)
    new_spinner.extend(records)

    if not adjustments:
        return None
    return current, adjustments, new_object, new_slider, new_spinner


def _section_labels(adjustments: list[Any]) -> set[str]:
    return {
        getattr(adjustment, "section_label", "")
        for adjustment in adjustments
        if getattr(adjustment, "section_label", "")
    }


def _replay_overall(replay_report: Any | None) -> float:
    if replay_report is None:
        return 50.0
    breakdown = getattr(replay_report, "score_breakdown", None)
    overall = getattr(breakdown, "overall", None)
    if overall is None:
        return 50.0
    return clamp(float(overall), 0.0, 100.0)


def _cursor_efficiency(replay_report: Any | None) -> float:
    if replay_report is None:
        return 0.5
    cursor = getattr(replay_report, "cursor", None)
    efficiency = getattr(cursor, "efficiency", None)
    if efficiency is None:
        return 0.5
    return clamp(float(efficiency), 0.0, 1.0)


def _weakest_section(sections: list[SectionQuality]) -> str:
    if not sections:
        return ""
    return min(sections, key=lambda section: section.quality_score).label


def _strongest_section(sections: list[SectionQuality]) -> str:
    if not sections:
        return ""
    return max(sections, key=lambda section: section.quality_score).label


def _no_change_outcome(
    map_dict: dict[str, Any],
    snapshot: _Snapshot | None,
    difficulty: str,
    seed: int,
    map_title: str,
    map_artist: str,
) -> RebalanceOutcome:
    quality = snapshot.quality if snapshot is not None else 50.0
    replay_score = snapshot.replay_score if snapshot is not None else 50.0
    cursor = snapshot.cursor_efficiency if snapshot is not None else 0.5
    star = snapshot.star_rating if snapshot is not None else 0.0
    sections = snapshot.sections if snapshot is not None else []
    issues = snapshot.issues if snapshot is not None else []
    summary = RebalanceSummary(
        passes_run=0,
        early_stopped=True,
        sections_modified=0,
        objects_adjusted=0,
        sliders_optimized=0,
        spinners_adjusted=0,
        issues_found=len(issues),
        quality_before=round(quality, 2),
        quality_after=round(quality, 2),
        quality_gain=0.0,
        replay_before=round(replay_score, 2),
        replay_after=round(replay_score, 2),
        replay_gain=0.0,
        cursor_efficiency_before=round(cursor, 4),
        cursor_efficiency_after=round(cursor, 4),
        cursor_efficiency_gain=0.0,
        star_rating_before=round(star, 2),
        star_rating_after=round(star, 2),
        weakest_section=_weakest_section(sections),
        strongest_section=_strongest_section(sections),
    )
    report = RebalanceReport(
        version=1,
        map_title=map_title,
        map_artist=map_artist,
        difficulty=difficulty,
        seed=seed,
        sections=sections,
        issues=issues,
        object_adjustments=[],
        slider_adjustments=[],
        spinner_adjustments=[],
        passes=[],
        summary=summary,
    )
    return RebalanceOutcome(
        map_dict=map_dict,
        report=report,
        final_evaluation=snapshot.evaluation if snapshot is not None else None,
        improved=False,
    )
