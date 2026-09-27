from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _rounded(value: float, digits: int = 3) -> float:
    return round(value, digits)


@dataclass
class EvolutionSongInfo:
    title: str
    artist: str
    difficulty: str
    audio: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "difficulty": self.difficulty,
            "audio": self.audio,
        }


@dataclass
class EvolutionConfiguration:
    root_seed: int
    candidate_count: int
    max_passes: int
    archive_policy: str
    timing_variation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rootSeed": self.root_seed,
            "candidateCount": self.candidate_count,
            "maxPasses": self.max_passes,
            "archivePolicy": self.archive_policy,
            "timingVariation": self.timing_variation,
        }


@dataclass
class EvolutionSummary:
    generated: int
    eligible: int
    rejected: int
    passes_used: int
    early_stopped: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "eligible": self.eligible,
            "rejected": self.rejected,
            "passesUsed": self.passes_used,
            "earlyStopped": self.early_stopped,
        }


@dataclass
class EvolutionDimensionScores:
    overall: float
    quality: float
    difficulty: float
    flow: float
    rhythm: float
    movement: float
    pattern: float
    slider: float
    spinner: float
    reading: float
    playability: float
    consistency: float
    confidence: float
    replay: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": _rounded(self.overall),
            "quality": _rounded(self.quality),
            "difficulty": _rounded(self.difficulty),
            "flow": _rounded(self.flow),
            "rhythm": _rounded(self.rhythm),
            "movement": _rounded(self.movement),
            "pattern": _rounded(self.pattern),
            "slider": _rounded(self.slider),
            "spinner": _rounded(self.spinner),
            "reading": _rounded(self.reading),
            "playability": _rounded(self.playability),
            "consistency": _rounded(self.consistency),
            "confidence": _rounded(self.confidence),
            "replay": _rounded(self.replay),
        }

    def as_ordered_values(self) -> list[tuple[str, float]]:
        return [
            ("quality", self.quality),
            ("difficulty", self.difficulty),
            ("flow", self.flow),
            ("rhythm", self.rhythm),
            ("movement", self.movement),
            ("pattern", self.pattern),
            ("slider", self.slider),
            ("spinner", self.spinner),
            ("reading", self.reading),
            ("playability", self.playability),
            ("consistency", self.consistency),
            ("confidence", self.confidence),
            ("replay", self.replay),
        ]


@dataclass
class EvolutionRankingEntry:
    rank: int
    candidate_index: int
    candidate_seed: int
    stars: float
    scores: EvolutionDimensionScores
    map_path: str
    report_path: str
    summary_path: str
    eligible: bool = True
    rejection_reasons: list[str] = field(default_factory=list)
    final: EvolutionFinalBreakdown | None = None
    quality_gates: list[EvolutionQualityGate] = field(default_factory=list)
    validation_status: str = "passed"
    improvements_made: list[str] = field(default_factory=list)
    target_deviation: float = 0.0
    diversity_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "stars": _rounded(self.stars, 2),
            "scores": self.scores.to_dict(),
            "mapPath": self.map_path,
            "reportPath": self.report_path,
            "summaryPath": self.summary_path,
            "eligible": self.eligible,
            "rejectionReasons": self.rejection_reasons,
            "final": self.final.to_dict() if self.final is not None else None,
            "qualityGates": [gate.to_dict() for gate in self.quality_gates],
            "validationStatus": self.validation_status,
            "improvementsMade": self.improvements_made,
            "targetDeviation": _rounded(self.target_deviation, 2),
            "diversityPenalty": _rounded(self.diversity_penalty, 3),
        }


@dataclass
class RejectedEvolutionCandidate:
    candidate_index: int
    candidate_seed: int
    overall_score: float
    rejection_reasons: list[str]
    summary_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "overallScore": _rounded(self.overall_score),
            "rejectionReasons": self.rejection_reasons,
            "summaryPath": self.summary_path,
        }


@dataclass
class EvolutionChampion:
    candidate_index: int
    candidate_seed: int
    overall_score: float
    quality_score: float
    stars: float
    map_path: str
    report_path: str
    source_map_path: str
    source_report_path: str
    summary_path: str
    promotion_reason: str
    final_breakdown: EvolutionFinalBreakdown | None = None
    weakest_sections: list[str] = field(default_factory=list)
    strongest_sections: list[str] = field(default_factory=list)
    biggest_improvements: list[str] = field(default_factory=list)
    lost_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "overallScore": _rounded(self.overall_score),
            "qualityScore": _rounded(self.quality_score),
            "stars": _rounded(self.stars, 2),
            "mapPath": self.map_path,
            "reportPath": self.report_path,
            "sourceMapPath": self.source_map_path,
            "sourceReportPath": self.source_report_path,
            "summaryPath": self.summary_path,
            "promotionReason": self.promotion_reason,
            "final": self.final_breakdown.to_dict() if self.final_breakdown is not None else None,
            "weakestSections": self.weakest_sections,
            "strongestSections": self.strongest_sections,
            "biggestImprovements": self.biggest_improvements,
            "lostReasons": self.lost_reasons,
        }


@dataclass
class EvolutionComparisonEntry:
    dimension: str
    champion_value: float
    runner_value: float
    delta: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "championValue": _rounded(self.champion_value),
            "runnerValue": _rounded(self.runner_value),
            "delta": _rounded(self.delta),
            "note": self.note,
        }


@dataclass
class EvolutionHeatmap:
    dimension: str
    label: str
    values: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "label": self.label,
            "values": [_rounded(value, 4) for value in self.values],
        }


@dataclass
class ImprovementPassEntry:
    pass_number: int
    candidate_index: int
    overall_before: float
    overall_after: float
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "passNumber": self.pass_number,
            "candidateIndex": self.candidate_index,
            "overallBefore": _rounded(self.overall_before),
            "overallAfter": _rounded(self.overall_after),
            "accepted": self.accepted,
        }


@dataclass
class EvolutionDiagnostics:
    score_distribution: dict[str, int]
    average_improvement: float
    promotion_reason: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoreDistribution": self.score_distribution,
            "averageImprovement": _rounded(self.average_improvement),
            "promotionReason": self.promotion_reason,
            "confidence": _rounded(self.confidence),
        }


@dataclass
class EvolutionFinalBreakdown:
    """Unified Phase 17 weighted score with every component visible."""

    weighted_score: float
    rhythm: float
    playability: float
    pattern: float
    target: float
    reading: float
    replay: float
    consistency: float
    validity: float
    flow: float
    section: float
    fatigue: float
    rebalance: float
    phrase: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "weightedScore": _rounded(self.weighted_score, 3),
            "rhythm": _rounded(self.rhythm),
            "playability": _rounded(self.playability),
            "pattern": _rounded(self.pattern),
            "target": _rounded(self.target),
            "reading": _rounded(self.reading),
            "replay": _rounded(self.replay),
            "consistency": _rounded(self.consistency),
            "validity": _rounded(self.validity),
            "flow": _rounded(self.flow),
            "section": _rounded(self.section),
            "fatigue": _rounded(self.fatigue),
            "rebalance": _rounded(self.rebalance),
            "phrase": _rounded(self.phrase),
        }


@dataclass
class EvolutionQualityGate:
    code: str
    name: str
    mandatory: bool
    passed: bool
    detail: str
    penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "mandatory": self.mandatory,
            "passed": self.passed,
            "detail": self.detail,
            "penalty": _rounded(self.penalty),
        }


@dataclass
class EvolutionReproductionInfo:
    """Configuration required to reproduce the champion (Phase 17)."""

    generator_version: str
    evolution_version: str
    seed: int
    candidate_count: int
    final_weights: dict[str, float]
    replay_profile: str
    rebalance_passes: int
    target_difficulty: str
    generation_config: dict[str, Any] | None = None
    phrase_report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generatorVersion": self.generator_version,
            "evolutionVersion": self.evolution_version,
            "seed": self.seed,
            "candidateCount": self.candidate_count,
            "finalWeights": {
                key: _rounded(value, 4)
                for key, value in sorted(self.final_weights.items())
            },
            "replayProfile": self.replay_profile,
            "rebalancePasses": self.rebalance_passes,
            "targetDifficulty": self.target_difficulty,
        }
        if self.generation_config is not None:
            payload["generationConfig"] = self.generation_config
        if self.phrase_report_path is not None:
            payload["phraseReportPath"] = self.phrase_report_path
        return payload


@dataclass
class EvolutionReplaySummary:
    full_combo_chance: float
    expected_accuracy: float
    expected_misses: float
    highest_stress_section_ms: int
    hardest_pattern: str
    most_difficult_transition_ms: int
    replay_score: float = 0.0
    player_profile: str = ""
    expected_combo_pct: float = 0.0
    cursor_efficiency: float = 0.0
    reading_score: float = 0.0
    fatigue_average: float = 0.0
    fatigue_peak: float = 0.0
    combo_breaks: int = 0
    miss_clusters: int = 0
    weakest_section: str = ""
    strongest_section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fullComboChance": _rounded(self.full_combo_chance, 4),
            "expectedAccuracy": _rounded(self.expected_accuracy, 4),
            "expectedMisses": _rounded(self.expected_misses, 2),
            "highestStressSectionMs": self.highest_stress_section_ms,
            "hardestPattern": self.hardest_pattern,
            "mostDifficultTransitionMs": self.most_difficult_transition_ms,
            "replayScore": _rounded(self.replay_score, 2),
            "playerProfile": self.player_profile,
            "expectedComboPct": _rounded(self.expected_combo_pct, 4),
            "cursorEfficiency": _rounded(self.cursor_efficiency, 4),
            "readingScore": _rounded(self.reading_score, 2),
            "fatigueAverage": _rounded(self.fatigue_average, 4),
            "fatiguePeak": _rounded(self.fatigue_peak, 4),
            "comboBreaks": self.combo_breaks,
            "missClusters": self.miss_clusters,
            "weakestSection": self.weakest_section,
            "strongestSection": self.strongest_section,
        }


@dataclass
class EvolutionRebalanceSummary:
    """Phase 16 adaptive rebalancing results for the champion."""

    passes_run: int = 0
    early_stopped: bool = True
    sections_modified: int = 0
    objects_adjusted: int = 0
    sliders_optimized: int = 0
    spinners_adjusted: int = 0
    issues_found: int = 0
    quality_before: float = 0.0
    quality_after: float = 0.0
    quality_gain: float = 0.0
    replay_before: float = 0.0
    replay_after: float = 0.0
    replay_gain: float = 0.0
    cursor_efficiency_before: float = 0.0
    cursor_efficiency_after: float = 0.0
    cursor_efficiency_gain: float = 0.0
    star_rating_before: float = 0.0
    star_rating_after: float = 0.0
    weakest_section: str = ""
    strongest_section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passesRun": self.passes_run,
            "earlyStopped": self.early_stopped,
            "sectionsModified": self.sections_modified,
            "objectsAdjusted": self.objects_adjusted,
            "slidersOptimized": self.sliders_optimized,
            "spinnersAdjusted": self.spinners_adjusted,
            "issuesFound": self.issues_found,
            "qualityBefore": _rounded(self.quality_before, 2),
            "qualityAfter": _rounded(self.quality_after, 2),
            "qualityGain": _rounded(self.quality_gain, 2),
            "replayBefore": _rounded(self.replay_before, 2),
            "replayAfter": _rounded(self.replay_after, 2),
            "replayGain": _rounded(self.replay_gain, 2),
            "cursorEfficiencyBefore": _rounded(self.cursor_efficiency_before, 4),
            "cursorEfficiencyAfter": _rounded(self.cursor_efficiency_after, 4),
            "cursorEfficiencyGain": _rounded(self.cursor_efficiency_gain, 4),
            "starRatingBefore": _rounded(self.star_rating_before, 2),
            "starRatingAfter": _rounded(self.star_rating_after, 2),
            "weakestSection": self.weakest_section,
            "strongestSection": self.strongest_section,
        }

    @classmethod
    def empty(cls) -> "EvolutionRebalanceSummary":
        return cls()


@dataclass
class EvolutionReport:
    version: int
    song: EvolutionSongInfo
    configuration: EvolutionConfiguration
    summary: EvolutionSummary
    champion: EvolutionChampion
    ranking: list[EvolutionRankingEntry]
    rejected_candidates: list[RejectedEvolutionCandidate]
    comparison: list[EvolutionComparisonEntry]
    comparison_reasons: list[str]
    heatmaps: list[EvolutionHeatmap]
    replay: EvolutionReplaySummary
    improvement_history: list[ImprovementPassEntry]
    diagnostics: EvolutionDiagnostics
    score_weights: dict[str, float]
    replay_report_path: str = ""
    rebalance: EvolutionRebalanceSummary = field(
        default_factory=EvolutionRebalanceSummary.empty
    )
    rebalance_report_path: str = ""
    reproduction: EvolutionReproductionInfo | None = None
    final_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "song": self.song.to_dict(),
            "configuration": self.configuration.to_dict(),
            "summary": self.summary.to_dict(),
            "champion": self.champion.to_dict(),
            "ranking": [entry.to_dict() for entry in self.ranking],
            "rejectedCandidates": [
                entry.to_dict() for entry in self.rejected_candidates
            ],
            "comparison": [entry.to_dict() for entry in self.comparison],
            "comparisonReasons": self.comparison_reasons,
            "heatmaps": [heatmap.to_dict() for heatmap in self.heatmaps],
            "replay": self.replay.to_dict(),
            "improvementHistory": [entry.to_dict() for entry in self.improvement_history],
            "diagnostics": self.diagnostics.to_dict(),
            "scoreWeights": {
                key: _rounded(value, 4)
                for key, value in sorted(self.score_weights.items())
            },
            "replayReportPath": self.replay_report_path,
            "rebalance": self.rebalance.to_dict(),
            "rebalanceReportPath": self.rebalance_report_path,
            "reproduction": (
                self.reproduction.to_dict() if self.reproduction is not None else None
            ),
            "finalWeights": {
                key: _rounded(value, 4)
                for key, value in sorted(self.final_weights.items())
            },
        }
