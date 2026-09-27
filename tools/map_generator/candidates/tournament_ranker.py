from __future__ import annotations

from .candidate_config import TournamentScoreWeights
from .candidate_models import (
    CandidateSummary,
    RejectedCandidateEntry,
    TournamentChampion,
    TournamentRankingEntry,
    TournamentScoreBreakdown,
)


def score_candidates(
    *,
    candidates: list[CandidateSummary],
    improved_reports_by_index: dict[int, object],
    difficulty_consistency_by_index: dict[int, float],
    weights: TournamentScoreWeights,
) -> None:
    for summary in candidates:
        candidate_index = summary.candidate.index
        improved_report = improved_reports_by_index[candidate_index]
        safety_score, penalties = _safety_score(improved_report)
        efficiency_score = _postprocess_efficiency(summary)
        diversity_score = max(
            0.0,
            min(
                100.0,
                summary.diversity.average_pairwise_diversity - summary.diversity.similarity_penalty,
            ),
        )
        difficulty_score = difficulty_consistency_by_index[candidate_index]
        tournament_score = max(
            0.0,
            min(
                100.0,
                summary.scores.improved_overall * weights.improved_overall
                + safety_score * weights.safety
                + summary.stability.score * weights.stability
                + difficulty_score * weights.difficulty_consistency
                + efficiency_score * weights.postprocess_efficiency
                + diversity_score * weights.diversity,
            ),
        )
        summary.scores.quality_score = summary.scores.improved_overall
        summary.scores.stability_score = summary.stability.score
        summary.scores.tournament_score = tournament_score
        summary.score_breakdown = TournamentScoreBreakdown(
            improved_overall_component=summary.scores.improved_overall * weights.improved_overall,
            safety_component=safety_score * weights.safety,
            stability_component=summary.stability.score * weights.stability,
            difficulty_component=difficulty_score * weights.difficulty_consistency,
            efficiency_component=efficiency_score * weights.postprocess_efficiency,
            diversity_component=diversity_score * weights.diversity,
            penalties=penalties,
        )


def build_ranking(
    *,
    candidates: list[CandidateSummary],
    improved_reports_by_index: dict[int, object],
) -> tuple[list[TournamentRankingEntry], list[RejectedCandidateEntry], TournamentChampion]:
    eligible_candidates = [summary for summary in candidates if summary.status.eligible]
    rejected_candidates = [
        RejectedCandidateEntry(
            candidate_index=summary.candidate.index,
            candidate_seed=summary.candidate.candidate_seed,
            quality_score=summary.scores.improved_overall,
            stability_score=summary.stability.score,
            rejection_reasons=summary.status.rejection_reasons,
            summary_path=summary.files.summary,
        )
        for summary in candidates
        if not summary.status.eligible
    ]

    ranked = sorted(
        eligible_candidates,
        key=lambda summary: _ranking_key(summary, improved_reports_by_index[summary.candidate.index]),
    )
    ranking_entries = [
        TournamentRankingEntry(
            rank=index,
            candidate_index=summary.candidate.index,
            candidate_seed=summary.candidate.candidate_seed,
            tournament_score=summary.scores.tournament_score,
            quality_score=summary.scores.improved_overall,
            stability_score=summary.stability.score,
            errors=summary.metrics.errors,
            warnings=summary.metrics.warnings,
            destructive_corrections=summary.metrics.destructive_corrections,
            difficulty_consistency_score=improved_reports_by_index[
                summary.candidate.index
            ].scores.difficulty_consistency,
            summary_path=summary.files.summary,
            map_path=summary.files.improved_map,
            report_path=summary.files.improved_report,
        )
        for index, summary in enumerate(ranked, start=1)
    ]
    champion_source = ranked[0]
    champion = TournamentChampion(
        candidate_index=champion_source.candidate.index,
        candidate_seed=champion_source.candidate.candidate_seed,
        tournament_score=champion_source.scores.tournament_score,
        quality_score=champion_source.scores.improved_overall,
        stability_score=champion_source.stability.score,
        map_path="",
        report_path="",
        source_map_path=champion_source.files.improved_map,
        source_report_path=champion_source.files.improved_report,
        summary_path=champion_source.files.summary,
    )
    return ranking_entries, rejected_candidates, champion


def _ranking_key(summary: CandidateSummary, improved_report: object) -> tuple[float, ...]:
    return (
        -summary.scores.tournament_score,
        -summary.scores.improved_overall,
        -summary.stability.score,
        summary.metrics.errors,
        summary.metrics.warnings,
        summary.metrics.destructive_corrections,
        -improved_report.scores.difficulty_consistency,
        summary.candidate.index,
    )


def _safety_score(improved_report: object) -> tuple[float, dict[str, float]]:
    base = (
        improved_report.scores.structural * 0.24
        + improved_report.scores.timing * 0.17
        + improved_report.scores.movement * 0.24
        + improved_report.scores.readability * 0.15
        + improved_report.scores.rhythm * 0.1
        + improved_report.scores.repetition * 0.05
        + improved_report.scores.density_consistency * 0.05
    )
    penalties = {
        "criticalIssues": improved_report.summary.critical * 20.0,
        "errors": improved_report.summary.errors * 8.0,
        "warnings": improved_report.summary.warnings * 1.2,
        "speedViolations": improved_report.metrics.movement.speed_violation_count * 7.0,
        "mistimedObjects": improved_report.metrics.timing.mistimed_count * 2.2,
        "nearLimitRuns": improved_report.metrics.movement.near_limit_run_count * 1.6,
    }
    score = max(0.0, min(100.0, base - sum(penalties.values())))
    return score, penalties


def _postprocess_efficiency(summary: CandidateSummary) -> float:
    score = 100.0
    score -= summary.metrics.destructive_corrections * 8.5
    score -= summary.metrics.reverted_corrections * 3.5
    score -= summary.metrics.max_timing_adjustment_ms * 0.08
    score -= summary.metrics.max_coordinate_shift_px * 0.06
    score -= summary.metrics.accepted_corrections * 0.8
    score += min(summary.scores.improvement * 0.6, 8.0)
    return max(0.0, min(100.0, score))
