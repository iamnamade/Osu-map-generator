from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .candidate_models import (
    CandidateDiversity,
    CandidateFiles,
    CandidateIdentity,
    CandidateMetrics,
    CandidateScores,
    CandidateStatus,
    CandidateSummary,
    DiversitySummary,
    RejectedCandidateEntry,
    StabilitySummary,
    TournamentChampion,
    TournamentConfiguration,
    TournamentRankingEntry,
    TournamentReport,
    TournamentScoreBreakdown,
    TournamentSongInfo,
    TournamentSummary,
)


def write_candidate_summary(path: Path, summary: CandidateSummary) -> None:
    write_json(path, summary.to_dict())


def write_tournament_report(path: Path, report: TournamentReport) -> None:
    write_json(path, report.to_dict())


def load_candidate_summary(path: Path) -> CandidateSummary:
    raw_data = _load_json(path, "Candidate summary JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Candidate summary JSON must be an object: {path}")

    candidate = _expect_record(raw_data.get("candidate"), "candidate")
    files = _expect_record(raw_data.get("files"), "files")
    scores = _expect_record(raw_data.get("scores"), "scores")
    status = _expect_record(raw_data.get("status"), "status")
    metrics = _expect_record(raw_data.get("metrics"), "metrics")
    diversity = _expect_record(raw_data.get("diversity"), "diversity")
    stability = _expect_record(raw_data.get("stability"), "stability")
    score_breakdown = _expect_record(raw_data.get("scoreBreakdown"), "scoreBreakdown")

    return CandidateSummary(
        version=_expect_int(raw_data.get("version"), "version"),
        candidate=CandidateIdentity(
            index=_expect_int(candidate.get("index"), "candidate.index"),
            difficulty=_expect_string(candidate.get("difficulty"), "candidate.difficulty"),
            root_seed=_expect_int(candidate.get("rootSeed"), "candidate.rootSeed"),
            candidate_seed=_expect_int(candidate.get("candidateSeed"), "candidate.candidateSeed"),
            timing_variation_enabled=_expect_bool(
                candidate.get("timingVariationEnabled"),
                "candidate.timingVariationEnabled",
            ),
            variation_signature=_expect_string(
                candidate.get("variationSignature"),
                "candidate.variationSignature",
            ),
            variation_profile=_expect_record(
                candidate.get("variationProfile"),
                "candidate.variationProfile",
            ),
        ),
        files=CandidateFiles(
            original_map=_expect_string(files.get("originalMap"), "files.originalMap"),
            original_report=_expect_string(files.get("originalReport"), "files.originalReport"),
            improved_map=_expect_string(files.get("improvedMap"), "files.improvedMap"),
            improved_report=_expect_string(files.get("improvedReport"), "files.improvedReport"),
            corrections=_expect_string(files.get("corrections"), "files.corrections"),
            summary=_expect_string(files.get("summary"), "files.summary"),
        ),
        scores=CandidateScores(
            original_overall=_expect_number(scores.get("originalOverall"), "scores.originalOverall"),
            improved_overall=_expect_number(scores.get("improvedOverall"), "scores.improvedOverall"),
            improvement=_expect_number(scores.get("improvement"), "scores.improvement"),
            tournament_score=_expect_number(scores.get("tournamentScore"), "scores.tournamentScore"),
            quality_score=_expect_number(scores.get("qualityScore"), "scores.qualityScore"),
            stability_score=_expect_number(scores.get("stabilityScore"), "scores.stabilityScore"),
        ),
        status=CandidateStatus(
            valid=_expect_bool(status.get("valid"), "status.valid"),
            playable=_expect_bool(status.get("playable"), "status.playable"),
            eligible=_expect_bool(status.get("eligible"), "status.eligible"),
            rejection_reasons=_expect_string_array(
                status.get("rejectionReasons"),
                "status.rejectionReasons",
            ),
        ),
        metrics=CandidateMetrics(
            accepted_corrections=_expect_int(metrics.get("acceptedCorrections"), "metrics.acceptedCorrections"),
            reverted_corrections=_expect_int(metrics.get("revertedCorrections"), "metrics.revertedCorrections"),
            destructive_corrections=_expect_int(metrics.get("destructiveCorrections"), "metrics.destructiveCorrections"),
            critical_issues=_expect_int(metrics.get("criticalIssues"), "metrics.criticalIssues"),
            errors=_expect_int(metrics.get("errors"), "metrics.errors"),
            warnings=_expect_int(metrics.get("warnings"), "metrics.warnings"),
            max_cursor_speed=_expect_number(metrics.get("maxCursorSpeed"), "metrics.maxCursorSpeed"),
            object_count=_expect_int(metrics.get("objectCount"), "metrics.objectCount"),
            max_timing_adjustment_ms=_expect_number(metrics.get("maxTimingAdjustmentMs"), "metrics.maxTimingAdjustmentMs"),
            max_coordinate_shift_px=_expect_number(metrics.get("maxCoordinateShiftPx"), "metrics.maxCoordinateShiftPx"),
            timing_signature=_expect_string(metrics.get("timingSignature"), "metrics.timingSignature"),
        ),
        diversity=CandidateDiversity(
            average_pairwise_diversity=_expect_number(
                diversity.get("averagePairwiseDiversity"),
                "diversity.averagePairwiseDiversity",
            ),
            nearest_neighbor_diversity=_expect_number(
                diversity.get("nearestNeighborDiversity"),
                "diversity.nearestNeighborDiversity",
            ),
            similarity_penalty=_expect_number(
                diversity.get("similarityPenalty"),
                "diversity.similarityPenalty",
            ),
            near_duplicate_count=_expect_int(
                diversity.get("nearDuplicateCount"),
                "diversity.nearDuplicateCount",
            ),
        ),
        stability=StabilitySummary(
            score=_expect_number(stability.get("score"), "stability.score"),
            label=_expect_string(stability.get("label"), "stability.label"),
            speed_margin_ratio=_expect_number(stability.get("speedMarginRatio"), "stability.speedMarginRatio"),
            gap_margin_ratio=_expect_number(stability.get("gapMarginRatio"), "stability.gapMarginRatio"),
            near_threshold_warnings=_expect_int(
                stability.get("nearThresholdWarnings"),
                "stability.nearThresholdWarnings",
            ),
            reverted_corrections=_expect_int(
                stability.get("revertedCorrections"),
                "stability.revertedCorrections",
            ),
            accepted_correction_magnitude=_expect_number(
                stability.get("acceptedCorrectionMagnitude"),
                "stability.acceptedCorrectionMagnitude",
            ),
            quality_swing=_expect_number(stability.get("qualitySwing"), "stability.qualitySwing"),
            severe_section_count=_expect_int(
                stability.get("severeSectionCount"),
                "stability.severeSectionCount",
            ),
        ),
        score_breakdown=TournamentScoreBreakdown(
            improved_overall_component=_expect_number(
                score_breakdown.get("improvedOverallComponent"),
                "scoreBreakdown.improvedOverallComponent",
            ),
            safety_component=_expect_number(
                score_breakdown.get("safetyComponent"),
                "scoreBreakdown.safetyComponent",
            ),
            stability_component=_expect_number(
                score_breakdown.get("stabilityComponent"),
                "scoreBreakdown.stabilityComponent",
            ),
            difficulty_component=_expect_number(
                score_breakdown.get("difficultyComponent"),
                "scoreBreakdown.difficultyComponent",
            ),
            efficiency_component=_expect_number(
                score_breakdown.get("efficiencyComponent"),
                "scoreBreakdown.efficiencyComponent",
            ),
            diversity_component=_expect_number(
                score_breakdown.get("diversityComponent"),
                "scoreBreakdown.diversityComponent",
            ),
            penalties=_expect_number_record(score_breakdown.get("penalties"), "scoreBreakdown.penalties"),
        ),
    )


def load_tournament_report(path: Path) -> TournamentReport:
    raw_data = _load_json(path, "Tournament report JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Tournament report JSON must be an object: {path}")

    song = _expect_record(raw_data.get("song"), "song")
    configuration = _expect_record(raw_data.get("configuration"), "configuration")
    summary = _expect_record(raw_data.get("summary"), "summary")
    champion = _expect_record(raw_data.get("champion"), "champion")
    diversity = _expect_record(raw_data.get("diversity"), "diversity")
    ranking = raw_data.get("ranking")
    rejected_candidates = raw_data.get("rejectedCandidates")

    return TournamentReport(
        version=_expect_int(raw_data.get("version"), "version"),
        song=TournamentSongInfo(
            title=_expect_string(song.get("title"), "song.title"),
            artist=_expect_string(song.get("artist"), "song.artist"),
            difficulty=_expect_string(song.get("difficulty"), "song.difficulty"),
            audio=_expect_string(song.get("audio"), "song.audio"),
        ),
        configuration=TournamentConfiguration(
            root_seed=_expect_int(configuration.get("rootSeed"), "configuration.rootSeed"),
            candidate_count=_expect_int(
                configuration.get("candidateCount"),
                "configuration.candidateCount",
            ),
            timing_variation=_expect_bool(
                configuration.get("timingVariation"),
                "configuration.timingVariation",
            ),
        ),
        summary=TournamentSummary(
            generated=_expect_int(summary.get("generated"), "summary.generated"),
            eligible=_expect_int(summary.get("eligible"), "summary.eligible"),
            rejected=_expect_int(summary.get("rejected"), "summary.rejected"),
            unique=_expect_int(summary.get("unique"), "summary.unique"),
            near_duplicate_groups=_expect_int(
                summary.get("nearDuplicateGroups"),
                "summary.nearDuplicateGroups",
            ),
        ),
        champion=TournamentChampion(
            candidate_index=_expect_int(champion.get("candidateIndex"), "champion.candidateIndex"),
            candidate_seed=_expect_int(champion.get("candidateSeed"), "champion.candidateSeed"),
            tournament_score=_expect_number(champion.get("tournamentScore"), "champion.tournamentScore"),
            quality_score=_expect_number(champion.get("qualityScore"), "champion.qualityScore"),
            stability_score=_expect_number(champion.get("stabilityScore"), "champion.stabilityScore"),
            map_path=_expect_string(champion.get("mapPath"), "champion.mapPath"),
            report_path=_expect_string(champion.get("reportPath"), "champion.reportPath"),
            source_map_path=_expect_string(champion.get("sourceMapPath"), "champion.sourceMapPath"),
            source_report_path=_expect_string(champion.get("sourceReportPath"), "champion.sourceReportPath"),
            summary_path=_expect_string(champion.get("summaryPath"), "champion.summaryPath"),
        ),
        ranking=[
            TournamentRankingEntry(
                rank=_expect_int(item.get("rank"), f"ranking[{index}].rank"),
                candidate_index=_expect_int(
                    item.get("candidateIndex"),
                    f"ranking[{index}].candidateIndex",
                ),
                candidate_seed=_expect_int(
                    item.get("candidateSeed"),
                    f"ranking[{index}].candidateSeed",
                ),
                tournament_score=_expect_number(
                    item.get("tournamentScore"),
                    f"ranking[{index}].tournamentScore",
                ),
                quality_score=_expect_number(
                    item.get("qualityScore"),
                    f"ranking[{index}].qualityScore",
                ),
                stability_score=_expect_number(
                    item.get("stabilityScore"),
                    f"ranking[{index}].stabilityScore",
                ),
                errors=_expect_int(item.get("errors"), f"ranking[{index}].errors"),
                warnings=_expect_int(item.get("warnings"), f"ranking[{index}].warnings"),
                destructive_corrections=_expect_int(
                    item.get("destructiveCorrections"),
                    f"ranking[{index}].destructiveCorrections",
                ),
                difficulty_consistency_score=_expect_number(
                    item.get("difficultyConsistencyScore"),
                    f"ranking[{index}].difficultyConsistencyScore",
                ),
                summary_path=_expect_string(
                    item.get("summaryPath"),
                    f"ranking[{index}].summaryPath",
                ),
                map_path=_expect_string(item.get("mapPath"), f"ranking[{index}].mapPath"),
                report_path=_expect_string(
                    item.get("reportPath"),
                    f"ranking[{index}].reportPath",
                ),
            )
            for index, item in enumerate(_expect_record_array(ranking, "ranking"))
        ],
        rejected_candidates=[
            RejectedCandidateEntry(
                candidate_index=_expect_int(
                    item.get("candidateIndex"),
                    f"rejectedCandidates[{index}].candidateIndex",
                ),
                candidate_seed=_expect_int(
                    item.get("candidateSeed"),
                    f"rejectedCandidates[{index}].candidateSeed",
                ),
                quality_score=_expect_number(
                    item.get("qualityScore"),
                    f"rejectedCandidates[{index}].qualityScore",
                ),
                stability_score=_expect_number(
                    item.get("stabilityScore"),
                    f"rejectedCandidates[{index}].stabilityScore",
                ),
                rejection_reasons=_expect_string_array(
                    item.get("rejectionReasons"),
                    f"rejectedCandidates[{index}].rejectionReasons",
                ),
                summary_path=_expect_string(
                    item.get("summaryPath"),
                    f"rejectedCandidates[{index}].summaryPath",
                ),
            )
            for index, item in enumerate(_expect_record_array(rejected_candidates, "rejectedCandidates"))
        ],
        diversity=DiversitySummary(
            candidate_count=_expect_int(diversity.get("candidateCount"), "diversity.candidateCount"),
            eligible_count=_expect_int(diversity.get("eligibleCount"), "diversity.eligibleCount"),
            unique_candidate_count=_expect_int(
                diversity.get("uniqueCandidateCount"),
                "diversity.uniqueCandidateCount",
            ),
            near_duplicate_groups=_expect_int_matrix(
                diversity.get("nearDuplicateGroups"),
                "diversity.nearDuplicateGroups",
            ),
            average_pairwise_diversity=_expect_number(
                diversity.get("averagePairwiseDiversity"),
                "diversity.averagePairwiseDiversity",
            ),
            minimum_pairwise_diversity=_expect_number(
                diversity.get("minimumPairwiseDiversity"),
                "diversity.minimumPairwiseDiversity",
            ),
            maximum_pairwise_diversity=_expect_number(
                diversity.get("maximumPairwiseDiversity"),
                "diversity.maximumPairwiseDiversity",
            ),
            most_unique_candidate=_expect_optional_int(
                diversity.get("mostUniqueCandidate"),
                "diversity.mostUniqueCandidate",
            ),
            most_duplicated_candidate=_expect_optional_int(
                diversity.get("mostDuplicatedCandidate"),
                "diversity.mostDuplicatedCandidate",
            ),
            pair_count=_expect_int(diversity.get("pairCount"), "diversity.pairCount"),
        ),
        score_weights=_expect_number_record(raw_data.get("scoreWeights"), "scoreWeights"),
    )


def format_tournament_console_report(report: TournamentReport, *, verbose: bool = False) -> str:
    lines = [
        "Candidate tournament complete",
        "",
        f"Song: {report.song.title}",
        f"Difficulty: {report.song.difficulty}",
        f"Root seed: {report.configuration.root_seed}",
        f"Generated candidates: {report.summary.generated}",
        f"Eligible candidates: {report.summary.eligible}",
        f"Rejected candidates: {report.summary.rejected}",
        f"Unique candidates: {report.summary.unique}",
        "",
        f"Champion: Candidate {report.champion.candidate_index:03d}",
        f"Tournament score: {report.champion.tournament_score:.1f}",
        f"Quality score: {report.champion.quality_score:.1f}",
        f"Stability score: {report.champion.stability_score:.1f}",
        "",
        "Top candidates:",
    ]
    for entry in report.ranking[:3]:
        lines.append(
            f"{entry.rank}. Candidate {entry.candidate_index:03d} - {entry.tournament_score:.1f}"
        )
    lines.extend(
        [
            "",
            "Champion map:",
            report.champion.map_path,
            "",
            "Tournament report:",
            report.champion.summary_path.replace("candidate-summary.json", "").rstrip("/"),
        ]
    )

    if verbose and report.rejected_candidates:
        lines.extend(["", "Rejected candidates"])
        for candidate in report.rejected_candidates:
            lines.append(
                f"- Candidate {candidate.candidate_index:03d}: {'; '.join(candidate.rejection_reasons)}"
            )

    return "\n".join(lines)


def format_tournament_comparison(reports: list[TournamentReport]) -> str:
    if not reports:
        raise MapGeneratorError("No tournament reports were found to compare.")

    ordered = sorted(
        reports,
        key=lambda report: (
            -report.champion.tournament_score,
            -report.champion.quality_score,
            report.song.difficulty,
        ),
    )
    lines = ["Tournament comparison", ""]
    for index, report in enumerate(ordered, start=1):
        lines.append(
            f"{index}. {report.song.difficulty} - Candidate {report.champion.candidate_index:03d} - {report.champion.tournament_score:.1f}"
        )
    return "\n".join(lines)


def format_candidate_inspection(summary: CandidateSummary, *, verbose: bool = False) -> str:
    lines = [
        "Candidate inspection",
        "",
        f"Candidate: {summary.candidate.index:03d}",
        f"Difficulty: {summary.candidate.difficulty}",
        f"Root seed: {summary.candidate.root_seed}",
        f"Candidate seed: {summary.candidate.candidate_seed}",
        f"Eligible: {'yes' if summary.status.eligible else 'no'}",
        f"Tournament score: {summary.scores.tournament_score:.1f}",
        f"Quality score: {summary.scores.improved_overall:.1f}",
        f"Stability score: {summary.stability.score:.1f}",
        f"Accepted corrections: {summary.metrics.accepted_corrections}",
        f"Reverted corrections: {summary.metrics.reverted_corrections}",
        f"Warnings: {summary.metrics.warnings}",
        f"Errors: {summary.metrics.errors}",
    ]
    if summary.status.rejection_reasons:
        lines.extend(["", "Rejection reasons"])
        lines.extend(f"- {reason}" for reason in summary.status.rejection_reasons)
    if verbose:
        lines.extend(["", "Variation profile", json.dumps(summary.candidate.variation_profile, indent=2)])
    return "\n".join(lines)


def _load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise MapGeneratorError(
            f"{label} is malformed at {path}: {error.msg} (line {error.lineno}, column {error.colno})"
        ) from error
    except OSError as error:
        raise MapGeneratorError(f"{label} could not be read from {path}: {error}") from error


def _expect_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return value


def _expect_record_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MapGeneratorError(f"{label}[{index}] must be an object.")
        output.append(item)
    return output


def _expect_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MapGeneratorError(f"{label} must be a non-empty string.")
    return value


def _expect_string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[str] = []
    for index, item in enumerate(value):
        output.append(_expect_string(item, f"{label}[{index}]"))
    return output


def _expect_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise MapGeneratorError(f"{label} must be a finite number.")
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise MapGeneratorError(f"{label} must be a finite number.")
    return numeric


def _expect_int(value: Any, label: str) -> int:
    numeric = _expect_number(value, label)
    if int(numeric) != numeric:
        raise MapGeneratorError(f"{label} must be an integer.")
    return int(numeric)


def _expect_optional_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _expect_int(value, label)


def _expect_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MapGeneratorError(f"{label} must be a boolean.")
    return value


def _expect_number_record(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return {str(key): _expect_number(item, f"{label}.{key}") for key, item in value.items()}


def _expect_int_matrix(value: Any, label: str) -> list[list[int]]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[list[int]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            raise MapGeneratorError(f"{label}[{row_index}] must be an array.")
        output.append(
            [_expect_int(item, f"{label}[{row_index}][{column_index}]") for column_index, item in enumerate(row)]
        )
    return output
