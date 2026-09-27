from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _rounded(value: float, digits: int = 4) -> float:
    return round(value, digits)


@dataclass
class CandidateIdentity:
    index: int
    difficulty: str
    root_seed: int
    candidate_seed: int
    timing_variation_enabled: bool
    variation_signature: str
    variation_profile: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "difficulty": self.difficulty,
            "rootSeed": self.root_seed,
            "candidateSeed": self.candidate_seed,
            "timingVariationEnabled": self.timing_variation_enabled,
            "variationSignature": self.variation_signature,
            "variationProfile": self.variation_profile,
        }


@dataclass
class CandidateFiles:
    original_map: str
    original_report: str
    improved_map: str
    improved_report: str
    corrections: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "originalMap": self.original_map,
            "originalReport": self.original_report,
            "improvedMap": self.improved_map,
            "improvedReport": self.improved_report,
            "corrections": self.corrections,
            "summary": self.summary,
        }


@dataclass
class CandidateScores:
    original_overall: float
    improved_overall: float
    improvement: float
    tournament_score: float = 0.0
    quality_score: float = 0.0
    stability_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "originalOverall": _rounded(self.original_overall, 3),
            "improvedOverall": _rounded(self.improved_overall, 3),
            "improvement": _rounded(self.improvement, 3),
            "tournamentScore": _rounded(self.tournament_score, 3),
            "qualityScore": _rounded(self.quality_score, 3),
            "stabilityScore": _rounded(self.stability_score, 3),
        }


@dataclass
class CandidateStatus:
    valid: bool
    playable: bool
    eligible: bool
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "playable": self.playable,
            "eligible": self.eligible,
            "rejectionReasons": self.rejection_reasons,
        }


@dataclass
class CandidateMetrics:
    accepted_corrections: int
    reverted_corrections: int
    destructive_corrections: int
    critical_issues: int
    errors: int
    warnings: int
    max_cursor_speed: float
    object_count: int
    max_timing_adjustment_ms: float
    max_coordinate_shift_px: float
    timing_signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptedCorrections": self.accepted_corrections,
            "revertedCorrections": self.reverted_corrections,
            "destructiveCorrections": self.destructive_corrections,
            "criticalIssues": self.critical_issues,
            "errors": self.errors,
            "warnings": self.warnings,
            "maxCursorSpeed": _rounded(self.max_cursor_speed, 3),
            "objectCount": self.object_count,
            "maxTimingAdjustmentMs": _rounded(self.max_timing_adjustment_ms, 3),
            "maxCoordinateShiftPx": _rounded(self.max_coordinate_shift_px, 3),
            "timingSignature": self.timing_signature,
        }


@dataclass
class CandidateDiversity:
    average_pairwise_diversity: float = 0.0
    nearest_neighbor_diversity: float = 0.0
    similarity_penalty: float = 0.0
    near_duplicate_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "averagePairwiseDiversity": _rounded(self.average_pairwise_diversity, 3),
            "nearestNeighborDiversity": _rounded(self.nearest_neighbor_diversity, 3),
            "similarityPenalty": _rounded(self.similarity_penalty, 3),
            "nearDuplicateCount": self.near_duplicate_count,
        }


@dataclass
class StabilitySummary:
    score: float
    label: str
    speed_margin_ratio: float
    gap_margin_ratio: float
    near_threshold_warnings: int
    reverted_corrections: int
    accepted_correction_magnitude: float
    quality_swing: float
    severe_section_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": _rounded(self.score, 3),
            "label": self.label,
            "speedMarginRatio": _rounded(self.speed_margin_ratio, 4),
            "gapMarginRatio": _rounded(self.gap_margin_ratio, 4),
            "nearThresholdWarnings": self.near_threshold_warnings,
            "revertedCorrections": self.reverted_corrections,
            "acceptedCorrectionMagnitude": _rounded(self.accepted_correction_magnitude, 3),
            "qualitySwing": _rounded(self.quality_swing, 3),
            "severeSectionCount": self.severe_section_count,
        }


@dataclass
class TournamentScoreBreakdown:
    improved_overall_component: float
    safety_component: float
    stability_component: float
    difficulty_component: float
    efficiency_component: float
    diversity_component: float
    penalties: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "improvedOverallComponent": _rounded(self.improved_overall_component, 3),
            "safetyComponent": _rounded(self.safety_component, 3),
            "stabilityComponent": _rounded(self.stability_component, 3),
            "difficultyComponent": _rounded(self.difficulty_component, 3),
            "efficiencyComponent": _rounded(self.efficiency_component, 3),
            "diversityComponent": _rounded(self.diversity_component, 3),
            "penalties": {
                key: _rounded(value, 3)
                for key, value in sorted(self.penalties.items())
            },
        }


@dataclass
class CandidateSummary:
    version: int
    candidate: CandidateIdentity
    files: CandidateFiles
    scores: CandidateScores
    status: CandidateStatus
    metrics: CandidateMetrics
    diversity: CandidateDiversity
    stability: StabilitySummary
    score_breakdown: TournamentScoreBreakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "candidate": self.candidate.to_dict(),
            "files": self.files.to_dict(),
            "scores": self.scores.to_dict(),
            "status": self.status.to_dict(),
            "metrics": self.metrics.to_dict(),
            "diversity": self.diversity.to_dict(),
            "stability": self.stability.to_dict(),
            "scoreBreakdown": self.score_breakdown.to_dict(),
        }


@dataclass
class PairwiseSimilarity:
    left_index: int
    right_index: int
    similarity_percent: float
    diversity_percent: float
    coordinate_difference: float
    jump_distance_difference: float
    region_difference: float
    angle_difference: float
    timing_difference: float
    near_duplicate: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "leftIndex": self.left_index,
            "rightIndex": self.right_index,
            "similarityPercent": _rounded(self.similarity_percent, 3),
            "diversityPercent": _rounded(self.diversity_percent, 3),
            "coordinateDifference": _rounded(self.coordinate_difference, 4),
            "jumpDistanceDifference": _rounded(self.jump_distance_difference, 4),
            "regionDifference": _rounded(self.region_difference, 4),
            "angleDifference": _rounded(self.angle_difference, 4),
            "timingDifference": _rounded(self.timing_difference, 4),
            "nearDuplicate": self.near_duplicate,
        }


@dataclass
class DiversitySummary:
    candidate_count: int
    eligible_count: int
    unique_candidate_count: int
    near_duplicate_groups: list[list[int]]
    average_pairwise_diversity: float
    minimum_pairwise_diversity: float
    maximum_pairwise_diversity: float
    most_unique_candidate: int | None
    most_duplicated_candidate: int | None
    pair_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateCount": self.candidate_count,
            "eligibleCount": self.eligible_count,
            "uniqueCandidateCount": self.unique_candidate_count,
            "nearDuplicateGroups": self.near_duplicate_groups,
            "averagePairwiseDiversity": _rounded(self.average_pairwise_diversity, 3),
            "minimumPairwiseDiversity": _rounded(self.minimum_pairwise_diversity, 3),
            "maximumPairwiseDiversity": _rounded(self.maximum_pairwise_diversity, 3),
            "mostUniqueCandidate": self.most_unique_candidate,
            "mostDuplicatedCandidate": self.most_duplicated_candidate,
            "pairCount": self.pair_count,
        }


@dataclass
class TournamentRankingEntry:
    rank: int
    candidate_index: int
    candidate_seed: int
    tournament_score: float
    quality_score: float
    stability_score: float
    errors: int
    warnings: int
    destructive_corrections: int
    difficulty_consistency_score: float
    summary_path: str
    map_path: str
    report_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "tournamentScore": _rounded(self.tournament_score, 3),
            "qualityScore": _rounded(self.quality_score, 3),
            "stabilityScore": _rounded(self.stability_score, 3),
            "errors": self.errors,
            "warnings": self.warnings,
            "destructiveCorrections": self.destructive_corrections,
            "difficultyConsistencyScore": _rounded(self.difficulty_consistency_score, 3),
            "summaryPath": self.summary_path,
            "mapPath": self.map_path,
            "reportPath": self.report_path,
        }


@dataclass
class RejectedCandidateEntry:
    candidate_index: int
    candidate_seed: int
    quality_score: float
    stability_score: float
    rejection_reasons: list[str]
    summary_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "qualityScore": _rounded(self.quality_score, 3),
            "stabilityScore": _rounded(self.stability_score, 3),
            "rejectionReasons": self.rejection_reasons,
            "summaryPath": self.summary_path,
        }


@dataclass
class TournamentChampion:
    candidate_index: int
    candidate_seed: int
    tournament_score: float
    quality_score: float
    stability_score: float
    map_path: str
    report_path: str
    source_map_path: str
    source_report_path: str
    summary_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateIndex": self.candidate_index,
            "candidateSeed": self.candidate_seed,
            "tournamentScore": _rounded(self.tournament_score, 3),
            "qualityScore": _rounded(self.quality_score, 3),
            "stabilityScore": _rounded(self.stability_score, 3),
            "mapPath": self.map_path,
            "reportPath": self.report_path,
            "sourceMapPath": self.source_map_path,
            "sourceReportPath": self.source_report_path,
            "summaryPath": self.summary_path,
        }


@dataclass
class TournamentConfiguration:
    root_seed: int
    candidate_count: int
    timing_variation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rootSeed": self.root_seed,
            "candidateCount": self.candidate_count,
            "timingVariation": self.timing_variation,
        }


@dataclass
class TournamentSummary:
    generated: int
    eligible: int
    rejected: int
    unique: int
    near_duplicate_groups: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "eligible": self.eligible,
            "rejected": self.rejected,
            "unique": self.unique,
            "nearDuplicateGroups": self.near_duplicate_groups,
        }


@dataclass
class TournamentSongInfo:
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
class TournamentReport:
    version: int
    song: TournamentSongInfo
    configuration: TournamentConfiguration
    summary: TournamentSummary
    champion: TournamentChampion
    ranking: list[TournamentRankingEntry]
    rejected_candidates: list[RejectedCandidateEntry]
    diversity: DiversitySummary
    score_weights: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "song": self.song.to_dict(),
            "configuration": self.configuration.to_dict(),
            "summary": self.summary.to_dict(),
            "champion": self.champion.to_dict(),
            "ranking": [entry.to_dict() for entry in self.ranking],
            "rejectedCandidates": [entry.to_dict() for entry in self.rejected_candidates],
            "diversity": self.diversity.to_dict(),
            "scoreWeights": {
                key: _rounded(value, 4)
                for key, value in sorted(self.score_weights.items())
            },
        }
