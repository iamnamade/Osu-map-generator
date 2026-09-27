from __future__ import annotations

from dataclasses import dataclass

from ..utils import clamp
from .section_config import HybridSelectionConfig
from .section_models import CandidateSectionReport, HybridSectionSelection, SectionState, SongSection


@dataclass(frozen=True)
class SelectionNode:
    candidate_index: int
    section_id: int
    score: float
    previous_candidate_index: int | None


def select_section_sources(
    *,
    sections: list[SongSection],
    candidate_reports: list[CandidateSectionReport],
    config: HybridSelectionConfig,
) -> list[HybridSectionSelection]:
    evaluations_by_section: dict[int, list[tuple[int, object, dict[str, float]]]] = {}
    for report in candidate_reports:
        if not bool(report.status.get("eligible", True)):
            continue
        quality = float(report.summary.get("candidateQuality", 0.0))
        stability = float(report.summary.get("candidateStability", 0.0))
        biases = {"quality": quality, "stability": stability}
        for section in report.sections:
            evaluations_by_section.setdefault(section.section_id, []).append(
                (report.candidate_index, section, biases)
            )

    if len(evaluations_by_section) != len(sections):
        missing = [section.id for section in sections if section.id not in evaluations_by_section]
        raise ValueError(f"Missing candidate evaluations for section ids: {missing}")

    previous_scores: dict[int, tuple[float, int, int | None]] = {}
    paths: list[dict[int, int | None]] = []
    for section in sections:
        path_entries: dict[int, int | None] = {}
        next_scores: dict[int, tuple[float, int, int | None]] = {}
        options = evaluations_by_section[section.id]
        for candidate_index, evaluation, biases in options:
            node_score = _node_score(
                overall=evaluation.scores.overall,
                timing=evaluation.scores.timing,
                movement=evaluation.scores.movement,
                rhythm=evaluation.scores.rhythm,
                confidence=section.confidence,
                quality=biases["quality"],
                stability=biases["stability"],
            )
            if not previous_scores:
                next_scores[candidate_index] = (node_score, 0, None)
                path_entries[candidate_index] = None
                continue

            best_entry: tuple[float, int, int | None] | None = None
            for previous_candidate, (previous_total, previous_switches, _) in previous_scores.items():
                compatibility = _compatibility_score(
                    left_state=_lookup_exit_state(candidate_reports, previous_candidate, section.id - 1),
                    right_state=evaluation.entry_state,
                    same_candidate=previous_candidate == candidate_index,
                    config=config,
                )
                switch_penalty = config.switch_penalty if previous_candidate != candidate_index else 0.0
                total_score = previous_total + node_score + compatibility - switch_penalty
                total_switches = previous_switches + (0 if previous_candidate == candidate_index else 1)
                candidate_entry = (total_score, total_switches, previous_candidate)
                if best_entry is None or _is_better(candidate_entry, best_entry):
                    best_entry = candidate_entry
            assert best_entry is not None
            next_scores[candidate_index] = best_entry
            path_entries[candidate_index] = best_entry[2]
        previous_scores = next_scores
        paths.append(path_entries)

    if not previous_scores:
        return []

    best_candidate, best_score_entry = min(
        previous_scores.items(),
        key=lambda item: (-item[1][0], item[1][1], item[0]),
    )
    ordered_candidates: list[int] = [best_candidate]
    current_candidate = best_candidate
    for path_entries in reversed(paths[1:]):
        previous_candidate = path_entries[current_candidate]
        if previous_candidate is None:
            break
        ordered_candidates.append(previous_candidate)
        current_candidate = previous_candidate
    ordered_candidates.reverse()

    selections: list[HybridSectionSelection] = []
    for section, candidate_index in zip(sections, ordered_candidates):
        report, evaluation = _find_evaluation(candidate_reports, candidate_index, section.id)
        reason = _selection_reason(
            section=section,
            evaluation=evaluation,
            quality=float(report.summary.get("candidateQuality", 0.0)),
            stability=float(report.summary.get("candidateStability", 0.0)),
        )
        selections.append(
            HybridSectionSelection(
                section_id=section.id,
                start_ms=section.start_ms,
                end_ms=section.end_ms,
                label=section.label,
                source_candidate=candidate_index,
                section_score=evaluation.scores.overall,
                selection_reason=reason,
            )
        )
    return selections


def _lookup_exit_state(
    reports: list[CandidateSectionReport],
    candidate_index: int,
    section_id: int,
) -> SectionState | None:
    for report in reports:
        if report.candidate_index != candidate_index:
            continue
        for section in report.sections:
            if section.section_id == section_id:
                return section.exit_state
    return None


def _node_score(
    *,
    overall: float,
    timing: float,
    movement: float,
    rhythm: float,
    confidence: float,
    quality: float,
    stability: float,
) -> float:
    return (
        overall * (0.74 + confidence * 0.16)
        + quality * 0.08
        + stability * 0.06
        + timing * 0.05
        + movement * 0.04
        + rhythm * 0.03
    )


def _compatibility_score(
    *,
    left_state: SectionState | None,
    right_state: SectionState,
    same_candidate: bool,
    config: HybridSelectionConfig,
) -> float:
    if left_state is None or left_state.time_ms is None or right_state.time_ms is None:
        return 0.0
    time_gap_ms = right_state.time_ms - left_state.time_ms
    if time_gap_ms <= 0:
        return -55.0
    distance_px = 0.0
    if None not in (left_state.x, left_state.y, right_state.x, right_state.y):
        distance_px = ((right_state.x - left_state.x) ** 2 + (right_state.y - left_state.y) ** 2) ** 0.5
    speed_pps = distance_px * 1000 / max(1, time_gap_ms)
    direction_delta = 0.0
    if left_state.direction_deg is not None and right_state.direction_deg is not None:
        direction_delta = abs(((right_state.direction_deg - left_state.direction_deg + 180) % 360) - 180)
    base_score = 26.0
    if same_candidate:
        base_score += 8.0
    base_score -= max(0.0, speed_pps - 620.0) * 0.04
    base_score -= max(0.0, direction_delta - 140.0) * 0.03
    base_score -= max(0.0, abs((left_state.density or 0.0) - (right_state.density or 0.0)) - 0.55) * 8.0
    if left_state.region == right_state.region:
        base_score -= 1.2
    return clamp(base_score, -60.0, 32.0)


def _is_better(
    left: tuple[float, int, int | None],
    right: tuple[float, int, int | None],
) -> bool:
    if abs(left[0] - right[0]) > 1e-6:
        return left[0] > right[0]
    if left[1] != right[1]:
        return left[1] < right[1]
    return (left[2] or 0) < (right[2] or 0)


def _find_evaluation(
    reports: list[CandidateSectionReport],
    candidate_index: int,
    section_id: int,
) -> tuple[CandidateSectionReport, object]:
    for report in reports:
        if report.candidate_index != candidate_index:
            continue
        for section in report.sections:
            if section.section_id == section_id:
                return report, section
    raise ValueError(
        f"Candidate section evaluation is missing for candidate {candidate_index} section {section_id}"
    )


def _selection_reason(
    *,
    section: SongSection,
    evaluation: object,
    quality: float,
    stability: float,
) -> str:
    strengths = [
        ("timing", evaluation.scores.timing),
        ("movement", evaluation.scores.movement),
        ("rhythm", evaluation.scores.rhythm),
        ("readability", evaluation.scores.readability),
    ]
    best_metric, best_value = max(strengths, key=lambda item: item[1])
    return (
        f"Best {best_metric} for {section.label} section with "
        f"{best_value:.1f} local score, {quality:.1f} candidate quality, "
        f"and {stability:.1f} stability."
    )
