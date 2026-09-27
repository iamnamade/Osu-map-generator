from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .models import (
    EvolutionChampion,
    EvolutionComparisonEntry,
    EvolutionConfiguration,
    EvolutionDiagnostics,
    EvolutionDimensionScores,
    EvolutionFinalBreakdown,
    EvolutionHeatmap,
    EvolutionQualityGate,
    EvolutionRankingEntry,
    EvolutionRebalanceSummary,
    EvolutionReproductionInfo,
    EvolutionReplaySummary,
    EvolutionReport,
    EvolutionSongInfo,
    EvolutionSummary,
    ImprovementPassEntry,
    RejectedEvolutionCandidate,
)


def write_evolution_report(path: Path, report: EvolutionReport) -> None:
    write_json(path, report.to_dict())


def load_evolution_report(path: Path) -> EvolutionReport:
    raw_data = _load_json(path, "Evolution report JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Evolution report JSON must be an object: {path}")

    song = _record(raw_data.get("song"), "song")
    configuration = _record(raw_data.get("configuration"), "configuration")
    summary = _record(raw_data.get("summary"), "summary")
    champion = _record(raw_data.get("champion"), "champion")
    replay = _record(raw_data.get("replay"), "replay")
    diagnostics = _record(raw_data.get("diagnostics"), "diagnostics")
    ranking = raw_data.get("ranking")
    rejected = raw_data.get("rejectedCandidates")
    comparison = raw_data.get("comparison")
    heatmaps = raw_data.get("heatmaps")
    improvement_history = raw_data.get("improvementHistory")

    return EvolutionReport(
        version=_int(raw_data.get("version"), "version"),
        song=EvolutionSongInfo(
            title=_string(song.get("title"), "song.title"),
            artist=_string(song.get("artist"), "song.artist"),
            difficulty=_string(song.get("difficulty"), "song.difficulty"),
            audio=_string(song.get("audio"), "song.audio"),
        ),
        configuration=EvolutionConfiguration(
            root_seed=_int(configuration.get("rootSeed"), "configuration.rootSeed"),
            candidate_count=_int(
                configuration.get("candidateCount"),
                "configuration.candidateCount",
            ),
            max_passes=_int(configuration.get("maxPasses"), "configuration.maxPasses"),
            archive_policy=_string(
                configuration.get("archivePolicy"),
                "configuration.archivePolicy",
            ),
            timing_variation=_bool(
                configuration.get("timingVariation"),
                "configuration.timingVariation",
            ),
        ),
        summary=EvolutionSummary(
            generated=_int(summary.get("generated"), "summary.generated"),
            eligible=_int(summary.get("eligible"), "summary.eligible"),
            rejected=_int(summary.get("rejected"), "summary.rejected"),
            passes_used=_int(summary.get("passesUsed"), "summary.passesUsed"),
            early_stopped=_bool(
                summary.get("earlyStopped"),
                "summary.earlyStopped",
            ),
        ),
        champion=EvolutionChampion(
            candidate_index=_int(champion.get("candidateIndex"), "champion.candidateIndex"),
            candidate_seed=_int(champion.get("candidateSeed"), "champion.candidateSeed"),
            overall_score=_number(champion.get("overallScore"), "champion.overallScore"),
            quality_score=_number(champion.get("qualityScore"), "champion.qualityScore"),
            stars=_number(champion.get("stars"), "champion.stars"),
            map_path=_string(champion.get("mapPath"), "champion.mapPath"),
            report_path=_string(champion.get("reportPath"), "champion.reportPath"),
            source_map_path=_string(champion.get("sourceMapPath"), "champion.sourceMapPath"),
            source_report_path=_string(
                champion.get("sourceReportPath"),
                "champion.sourceReportPath",
            ),
            summary_path=_string(champion.get("summaryPath"), "champion.summaryPath"),
            promotion_reason=_string(
                champion.get("promotionReason"),
                "champion.promotionReason",
            ),
            final_breakdown=_final(champion.get("final")),
            weakest_sections=_string_array_or_empty(
                champion.get("weakestSections"),
                "champion.weakestSections",
            ),
            strongest_sections=_string_array_or_empty(
                champion.get("strongestSections"),
                "champion.strongestSections",
            ),
            biggest_improvements=_string_array_or_empty(
                champion.get("biggestImprovements"),
                "champion.biggestImprovements",
            ),
            lost_reasons=_string_array_or_empty(
                champion.get("lostReasons"),
                "champion.lostReasons",
            ),
        ),
        ranking=[
            EvolutionRankingEntry(
                rank=_int(item.get("rank"), f"ranking[{index}].rank"),
                candidate_index=_int(
                    item.get("candidateIndex"),
                    f"ranking[{index}].candidateIndex",
                ),
                candidate_seed=_int(
                    item.get("candidateSeed"),
                    f"ranking[{index}].candidateSeed",
                ),
                stars=_number(item.get("stars"), f"ranking[{index}].stars"),
                scores=_scores(item.get("scores"), f"ranking[{index}].scores"),
                map_path=_string(item.get("mapPath"), f"ranking[{index}].mapPath"),
                report_path=_string(item.get("reportPath"), f"ranking[{index}].reportPath"),
                summary_path=_string(
                    item.get("summaryPath"),
                    f"ranking[{index}].summaryPath",
                ),
                eligible=_bool(item.get("eligible", True), f"ranking[{index}].eligible"),
                rejection_reasons=_string_array_or_empty(
                    item.get("rejectionReasons"),
                    f"ranking[{index}].rejectionReasons",
                ),
                final=_final(item.get("final")),
                quality_gates=_gates(item.get("qualityGates")),
                validation_status=_string_or_empty(
                    item.get("validationStatus"),
                    f"ranking[{index}].validationStatus",
                )
                or "passed",
                improvements_made=_string_array_or_empty(
                    item.get("improvementsMade"),
                    f"ranking[{index}].improvementsMade",
                ),
                target_deviation=_number(
                    item.get("targetDeviation", 0.0),
                    f"ranking[{index}].targetDeviation",
                ),
                diversity_penalty=_number(
                    item.get("diversityPenalty", 0.0),
                    f"ranking[{index}].diversityPenalty",
                ),
            )
            for index, item in enumerate(_record_array(ranking, "ranking"))
        ],
        rejected_candidates=[
            RejectedEvolutionCandidate(
                candidate_index=_int(
                    item.get("candidateIndex"),
                    f"rejectedCandidates[{index}].candidateIndex",
                ),
                candidate_seed=_int(
                    item.get("candidateSeed"),
                    f"rejectedCandidates[{index}].candidateSeed",
                ),
                overall_score=_number(
                    item.get("overallScore"),
                    f"rejectedCandidates[{index}].overallScore",
                ),
                rejection_reasons=_string_array(
                    item.get("rejectionReasons"),
                    f"rejectedCandidates[{index}].rejectionReasons",
                ),
                summary_path=_string(
                    item.get("summaryPath"),
                    f"rejectedCandidates[{index}].summaryPath",
                ),
            )
            for index, item in enumerate(_record_array(rejected, "rejectedCandidates"))
        ],
        comparison=[
            EvolutionComparisonEntry(
                dimension=_string(
                    item.get("dimension"),
                    f"comparison[{index}].dimension",
                ),
                champion_value=_number(
                    item.get("championValue"),
                    f"comparison[{index}].championValue",
                ),
                runner_value=_number(
                    item.get("runnerValue"),
                    f"comparison[{index}].runnerValue",
                ),
                delta=_number(item.get("delta"), f"comparison[{index}].delta"),
                note=_string(item.get("note"), f"comparison[{index}].note"),
            )
            for index, item in enumerate(_record_array(comparison, "comparison"))
        ],
        comparison_reasons=_string_array(
            raw_data.get("comparisonReasons"),
            "comparisonReasons",
        ),
        heatmaps=[
            EvolutionHeatmap(
                dimension=_string(
                    item.get("dimension"),
                    f"heatmaps[{index}].dimension",
                ),
                label=_string(item.get("label"), f"heatmaps[{index}].label"),
                values=_number_array(item.get("values"), f"heatmaps[{index}].values"),
            )
            for index, item in enumerate(_record_array(heatmaps, "heatmaps"))
        ],
        replay=EvolutionReplaySummary(
            full_combo_chance=_number(
                replay.get("fullComboChance"),
                "replay.fullComboChance",
            ),
            expected_accuracy=_number(
                replay.get("expectedAccuracy"),
                "replay.expectedAccuracy",
            ),
            expected_misses=_number(
                replay.get("expectedMisses"),
                "replay.expectedMisses",
            ),
            highest_stress_section_ms=_int(
                replay.get("highestStressSectionMs"),
                "replay.highestStressSectionMs",
            ),
            hardest_pattern=_string(
                replay.get("hardestPattern"),
                "replay.hardestPattern",
            ),
            most_difficult_transition_ms=_int(
                replay.get("mostDifficultTransitionMs"),
                "replay.mostDifficultTransitionMs",
            ),
            replay_score=_number(
                replay.get("replayScore", 0.0),
                "replay.replayScore",
            ),
            player_profile=_string_or_empty(
                replay.get("playerProfile"),
                "replay.playerProfile",
            ),
            expected_combo_pct=_number(
                replay.get("expectedComboPct", 0.0),
                "replay.expectedComboPct",
            ),
            cursor_efficiency=_number(
                replay.get("cursorEfficiency", 0.0),
                "replay.cursorEfficiency",
            ),
            reading_score=_number(
                replay.get("readingScore", 0.0),
                "replay.readingScore",
            ),
            fatigue_average=_number(
                replay.get("fatigueAverage", 0.0),
                "replay.fatigueAverage",
            ),
            fatigue_peak=_number(
                replay.get("fatiguePeak", 0.0),
                "replay.fatiguePeak",
            ),
            combo_breaks=_int(
                replay.get("comboBreaks", 0),
                "replay.comboBreaks",
            ),
            miss_clusters=_int(
                replay.get("missClusters", 0),
                "replay.missClusters",
            ),
            weakest_section=_string_or_empty(
                replay.get("weakestSection"),
                "replay.weakestSection",
            ),
            strongest_section=_string_or_empty(
                replay.get("strongestSection"),
                "replay.strongestSection",
            ),
        ),
        improvement_history=[
            ImprovementPassEntry(
                pass_number=_int(
                    item.get("passNumber"),
                    f"improvementHistory[{index}].passNumber",
                ),
                candidate_index=_int(
                    item.get("candidateIndex"),
                    f"improvementHistory[{index}].candidateIndex",
                ),
                overall_before=_number(
                    item.get("overallBefore"),
                    f"improvementHistory[{index}].overallBefore",
                ),
                overall_after=_number(
                    item.get("overallAfter"),
                    f"improvementHistory[{index}].overallAfter",
                ),
                accepted=_bool(
                    item.get("accepted"),
                    f"improvementHistory[{index}].accepted",
                ),
            )
            for index, item in enumerate(
                _record_array(improvement_history, "improvementHistory")
            )
        ],
        diagnostics=EvolutionDiagnostics(
            score_distribution=_number_record(
                diagnostics.get("scoreDistribution"),
                "diagnostics.scoreDistribution",
            ),
            average_improvement=_number(
                diagnostics.get("averageImprovement"),
                "diagnostics.averageImprovement",
            ),
            promotion_reason=_string(
                diagnostics.get("promotionReason"),
                "diagnostics.promotionReason",
            ),
            confidence=_number(
                diagnostics.get("confidence"),
                "diagnostics.confidence",
            ),
        ),
        score_weights=_number_record(raw_data.get("scoreWeights"), "scoreWeights"),
        replay_report_path=_string_or_empty(
            raw_data.get("replayReportPath"),
            "replayReportPath",
        ),
        rebalance=_rebalance(raw_data.get("rebalance")),
        rebalance_report_path=_string_or_empty(
            raw_data.get("rebalanceReportPath"),
            "rebalanceReportPath",
        ),
        reproduction=_reproduction(raw_data.get("reproduction")),
        final_weights=_number_record_or_empty(raw_data.get("finalWeights")),
    )


def format_evolution_console_report(report: EvolutionReport, *, verbose: bool = False) -> str:
    lines = [
        "Candidate evolution complete",
        "",
        f"Song: {report.song.title}",
        f"Difficulty: {report.song.difficulty}",
        f"Root seed: {report.configuration.root_seed}",
        f"Candidates: {report.summary.generated}",
        f"Eligible: {report.summary.eligible}",
        f"Rejected: {report.summary.rejected}",
        f"Improvement passes: {report.summary.passes_used}",
        f"Early stopped: {'yes' if report.summary.early_stopped else 'no'}",
        "",
        f"Champion: Candidate {report.champion.candidate_index:03d}",
        f"Overall score: {report.champion.overall_score:.1f}",
        f"Quality score: {report.champion.quality_score:.1f}",
        f"Stars: {report.champion.stars:.2f}",
        f"Promotion: {report.champion.promotion_reason}",
        "",
        "Leaderboard:",
    ]
    for entry in report.ranking[:5]:
        lines.append(
            f"{entry.rank}. Candidate {entry.candidate_index:03d} - "
            f"overall {entry.scores.overall:.1f} - {entry.stars:.2f} stars"
        )
    lines.extend(
        [
            "",
            "Champion map:",
            report.champion.map_path,
            "",
            "Evolution report:",
        ]
    )
    if verbose:
        lines.append(report.champion.summary_path.replace("candidate-summary.json", "").rstrip("/"))
        lines.extend(["", "Comparison reasons"])
        lines.extend(f"- {reason}" for reason in report.comparison_reasons)
        if report.improvement_history:
            lines.extend(["", "Improvement history"])
            for entry in report.improvement_history:
                marker = "accepted" if entry.accepted else "rejected"
                lines.append(
                    f"- Pass {entry.pass_number}: {entry.overall_before:.1f} -> "
                    f"{entry.overall_after:.1f} ({marker})"
                )
    return "\n".join(lines)


def format_evolution_comparison(reports: list[EvolutionReport]) -> str:
    if not reports:
        raise MapGeneratorError("No evolution reports were found to compare.")
    ordered = sorted(
        reports,
        key=lambda report: (
            -report.champion.overall_score,
            -report.champion.quality_score,
            report.song.difficulty,
        ),
    )
    lines = ["Evolution comparison", ""]
    for index, report in enumerate(ordered, start=1):
        lines.append(
            f"{index}. {report.song.difficulty} - Candidate {report.champion.candidate_index:03d} "
            f"- overall {report.champion.overall_score:.1f} - {report.champion.stars:.2f} stars"
        )
    return "\n".join(lines)


def _final(raw: Any) -> EvolutionFinalBreakdown | None:
    """Parse the unified final score breakdown (absent for old reports)."""
    if raw is None:
        return None
    value = _record(raw, "final")
    return EvolutionFinalBreakdown(
        weighted_score=_number(value.get("weightedScore", 0.0), "final.weightedScore"),
        rhythm=_number(value.get("rhythm", 0.0), "final.rhythm"),
        playability=_number(value.get("playability", 0.0), "final.playability"),
        pattern=_number(value.get("pattern", 0.0), "final.pattern"),
        target=_number(value.get("target", 0.0), "final.target"),
        reading=_number(value.get("reading", 0.0), "final.reading"),
        replay=_number(value.get("replay", 0.0), "final.replay"),
        consistency=_number(value.get("consistency", 0.0), "final.consistency"),
        validity=_number(value.get("validity", 0.0), "final.validity"),
        flow=_number(value.get("flow", 0.0), "final.flow"),
        section=_number(value.get("section", 0.0), "final.section"),
        fatigue=_number(value.get("fatigue", 0.0), "final.fatigue"),
        rebalance=_number(value.get("rebalance", 0.0), "final.rebalance"),
        phrase=_number(value.get("phrase", 0.0), "final.phrase"),
    )


def _gates(raw: Any) -> list[EvolutionQualityGate]:
    if not isinstance(raw, list):
        return []
    output: list[EvolutionQualityGate] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        output.append(
            EvolutionQualityGate(
                code=_string(item.get("code", ""), f"qualityGates[{index}].code")
                if isinstance(item.get("code"), str)
                else f"GATE{index}",
                name=_string_or_empty(item.get("name"), f"qualityGates[{index}].name"),
                mandatory=_bool(
                    item.get("mandatory", False),
                    f"qualityGates[{index}].mandatory",
                ),
                passed=_bool(item.get("passed", False), f"qualityGates[{index}].passed"),
                detail=_string_or_empty(item.get("detail"), f"qualityGates[{index}].detail"),
                penalty=_number(
                    item.get("penalty", 0.0),
                    f"qualityGates[{index}].penalty",
                ),
            )
        )
    return output


def _reproduction(raw: Any) -> EvolutionReproductionInfo | None:
    """Parse the Phase 17 reproduction config (absent for old reports)."""
    if raw is None:
        return None
    value = _record(raw, "reproduction")
    return EvolutionReproductionInfo(
        generator_version=_string_or_empty(
            value.get("generatorVersion"),
            "reproduction.generatorVersion",
        ),
        evolution_version=_string_or_empty(
            value.get("evolutionVersion"),
            "reproduction.evolutionVersion",
        ),
        seed=_int(value.get("seed", 0), "reproduction.seed"),
        candidate_count=_int(
            value.get("candidateCount", 0),
            "reproduction.candidateCount",
        ),
        final_weights=_number_record_or_empty(value.get("finalWeights")),
        replay_profile=_string_or_empty(
            value.get("replayProfile"),
            "reproduction.replayProfile",
        ),
        rebalance_passes=_int(
            value.get("rebalancePasses", 0),
            "reproduction.rebalancePasses",
        ),
        target_difficulty=_string_or_empty(
            value.get("targetDifficulty"),
            "reproduction.targetDifficulty",
        ),
        generation_config=(
            value.get("generationConfig")
            if isinstance(value.get("generationConfig"), dict)
            else None
        ),
        phrase_report_path=(
            value.get("phraseReportPath")
            if isinstance(value.get("phraseReportPath"), str)
            else None
        ),
    )


def _rebalance(raw: Any) -> EvolutionRebalanceSummary:
    """Parse the Phase 16 rebalance summary tolerantly (absent for old reports)."""
    if raw is None:
        return EvolutionRebalanceSummary.empty()
    value = _record(raw, "rebalance")
    return EvolutionRebalanceSummary(
        passes_run=_int(value.get("passesRun", 0), "rebalance.passesRun"),
        early_stopped=_bool(
            value.get("earlyStopped", True),
            "rebalance.earlyStopped",
        ),
        sections_modified=_int(
            value.get("sectionsModified", 0),
            "rebalance.sectionsModified",
        ),
        objects_adjusted=_int(
            value.get("objectsAdjusted", 0),
            "rebalance.objectsAdjusted",
        ),
        sliders_optimized=_int(
            value.get("slidersOptimized", 0),
            "rebalance.slidersOptimized",
        ),
        spinners_adjusted=_int(
            value.get("spinnersAdjusted", 0),
            "rebalance.spinnersAdjusted",
        ),
        issues_found=_int(value.get("issuesFound", 0), "rebalance.issuesFound"),
        quality_before=_number(
            value.get("qualityBefore", 0.0),
            "rebalance.qualityBefore",
        ),
        quality_after=_number(value.get("qualityAfter", 0.0), "rebalance.qualityAfter"),
        quality_gain=_number(value.get("qualityGain", 0.0), "rebalance.qualityGain"),
        replay_before=_number(value.get("replayBefore", 0.0), "rebalance.replayBefore"),
        replay_after=_number(value.get("replayAfter", 0.0), "rebalance.replayAfter"),
        replay_gain=_number(value.get("replayGain", 0.0), "rebalance.replayGain"),
        cursor_efficiency_before=_number(
            value.get("cursorEfficiencyBefore", 0.0),
            "rebalance.cursorEfficiencyBefore",
        ),
        cursor_efficiency_after=_number(
            value.get("cursorEfficiencyAfter", 0.0),
            "rebalance.cursorEfficiencyAfter",
        ),
        cursor_efficiency_gain=_number(
            value.get("cursorEfficiencyGain", 0.0),
            "rebalance.cursorEfficiencyGain",
        ),
        star_rating_before=_number(
            value.get("starRatingBefore", 0.0),
            "rebalance.starRatingBefore",
        ),
        star_rating_after=_number(
            value.get("starRatingAfter", 0.0),
            "rebalance.starRatingAfter",
        ),
        weakest_section=_string_or_empty(
            value.get("weakestSection"),
            "rebalance.weakestSection",
        ),
        strongest_section=_string_or_empty(
            value.get("strongestSection"),
            "rebalance.strongestSection",
        ),
    )


def _scores(raw: Any, label: str) -> EvolutionDimensionScores:
    value = _record(raw, label)
    return EvolutionDimensionScores(
        overall=_number(value.get("overall"), f"{label}.overall"),
        quality=_number(value.get("quality"), f"{label}.quality"),
        difficulty=_number(value.get("difficulty"), f"{label}.difficulty"),
        flow=_number(value.get("flow"), f"{label}.flow"),
        rhythm=_number(value.get("rhythm"), f"{label}.rhythm"),
        movement=_number(value.get("movement"), f"{label}.movement"),
        pattern=_number(value.get("pattern"), f"{label}.pattern"),
        slider=_number(value.get("slider"), f"{label}.slider"),
        spinner=_number(value.get("spinner"), f"{label}.spinner"),
        reading=_number(value.get("reading"), f"{label}.reading"),
        playability=_number(value.get("playability"), f"{label}.playability"),
        consistency=_number(value.get("consistency"), f"{label}.consistency"),
        confidence=_number(value.get("confidence"), f"{label}.confidence"),
        replay=_number(value.get("replay", 0.0), f"{label}.replay"),
    )


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


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return value


def _record_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MapGeneratorError(f"{label}[{index}] must be an object.")
        output.append(item)
    return output


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MapGeneratorError(f"{label} must be a non-empty string.")
    return value


def _string_or_empty(value: Any, label: str) -> str:
    """Parse a string that may be absent (defaults to empty for older reports)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MapGeneratorError(f"{label} must be a string.")
    return value


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    return [_string(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _string_array_or_empty(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise MapGeneratorError(f"{label}[{index}] must be a string.")
        output.append(item)
    return output


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise MapGeneratorError(f"{label} must be a finite number.")
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise MapGeneratorError(f"{label} must be a finite number.")
    return numeric


def _number_array(value: Any, label: str) -> list[float]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    return [_number(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _number_record(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return {str(key): _number(item, f"{label}.{key}") for key, item in value.items()}


def _number_record_or_empty(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MapGeneratorError("finalWeights must be an object when present.")
    return {str(key): _number(item, f"finalWeights.{key}") for key, item in value.items()}


def _int(value: Any, label: str) -> int:
    numeric = _number(value, label)
    if int(numeric) != numeric:
        raise MapGeneratorError(f"{label} must be an integer.")
    return int(numeric)


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MapGeneratorError(f"{label} must be a boolean.")
    return value
