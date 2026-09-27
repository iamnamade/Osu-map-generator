from __future__ import annotations

from dataclasses import dataclass, field

from ..config import DifficultyName
from ..utils import MapGeneratorError

DEFAULT_CANDIDATE_COUNTS: dict[DifficultyName, int] = {
    "easy": 8,
    "normal": 10,
    "hard": 12,
}
MAX_CANDIDATES_PER_RUN = 100


@dataclass(frozen=True)
class TournamentScoreWeights:
    improved_overall: float = 0.60
    safety: float = 0.15
    stability: float = 0.10
    difficulty_consistency: float = 0.05
    postprocess_efficiency: float = 0.05
    diversity: float = 0.05

    def to_dict(self) -> dict[str, float]:
        return {
            "improvedOverall": self.improved_overall,
            "safety": self.safety,
            "stability": self.stability,
            "difficultyConsistency": self.difficulty_consistency,
            "postprocessEfficiency": self.postprocess_efficiency,
            "diversity": self.diversity,
        }


@dataclass(frozen=True)
class EligibilityRules:
    hard_speed_safety_multiplier: float = 1.0
    maximum_file_gap_tolerance: int = 0


@dataclass(frozen=True)
class DiversitySettings:
    near_duplicate_similarity_threshold: float = 96.0
    coordinate_weight: float = 0.45
    jump_weight: float = 0.2
    region_weight: float = 0.2
    angle_weight: float = 0.15
    timing_weight: float = 0.15


@dataclass(frozen=True)
class StabilitySettings:
    near_limit_speed_ratio: float = 0.92
    near_limit_gap_ratio: float = 1.08


@dataclass(frozen=True)
class TournamentSettings:
    candidate_count: int
    timing_variation: bool = False
    force: bool = False
    weights: TournamentScoreWeights = field(default_factory=TournamentScoreWeights)
    eligibility_rules: EligibilityRules = field(default_factory=EligibilityRules)
    diversity: DiversitySettings = field(default_factory=DiversitySettings)
    stability: StabilitySettings = field(default_factory=StabilitySettings)


def default_candidate_count(difficulty: str) -> int:
    try:
        return DEFAULT_CANDIDATE_COUNTS[difficulty]  # type: ignore[index]
    except KeyError as error:
        raise MapGeneratorError(
            f'Unsupported difficulty "{difficulty}" for candidate generation.'
        ) from error


def validate_candidate_count(count: int) -> int:
    if count <= 0:
        raise MapGeneratorError("Candidate count must be at least 1.")
    if count > MAX_CANDIDATES_PER_RUN:
        raise MapGeneratorError(
            f"Candidate count {count} exceeds the maximum supported limit of {MAX_CANDIDATES_PER_RUN}."
        )
    return count
