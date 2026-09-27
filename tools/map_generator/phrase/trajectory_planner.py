"""Phase 20 global trajectory & transition planner.

Pre-calculates target density and difficulty curves for each phrase to
enforce dynamic musical contrast (dense -> sparse, technical -> recovery)
and pre-plans section-to-section entry/exit vectors and density hand-offs
prior to object generation.

Everything is deterministic: identical phrases produce identical targets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..utils import clamp
from .motif_engine import (
    assign_all_strategies,
    strategy_generation_multipliers,
)
from .phrase_models import Phrase, PhraseStrategyName


@dataclass(frozen=True)
class TrajectoryConfig:
    density_floor: float = 0.6
    density_ceiling: float = 4.0
    difficulty_floor: float = 0.2
    difficulty_ceiling: float = 1.0
    direction_smoothing: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "densityFloor": self.density_floor,
            "densityCeiling": self.density_ceiling,
            "difficultyFloor": self.difficulty_floor,
            "difficultyCeiling": self.difficulty_ceiling,
            "directionSmoothing": self.direction_smoothing,
        }


DEFAULT_TRAJECTORY_CONFIG = TrajectoryConfig()


def plan_trajectory(
    phrases: list[Phrase],
    config: TrajectoryConfig = DEFAULT_TRAJECTORY_CONFIG,
) -> list[Phrase]:
    """Compute per-phrase density/difficulty targets + entry/exit vectors.

    Strategy multipliers scale the acoustic base density so repeated motifs
    stay coherent while dynamic contrast is preserved. Entry/exit direction
    vectors are derived from the local energy slope (smoothed across phrases).
    """
    if not phrases:
        return phrases
    ordered = sorted(phrases, key=lambda phrase: (phrase.start_ms, phrase.id))

    for index, phrase in enumerate(ordered):
        base_density = _base_density(phrase, config)
        multipliers = strategy_generation_multipliers(phrase.strategy)
        target_density = clamp(
            base_density * multipliers["density"],
            config.density_floor,
            config.density_ceiling,
        )
        base_difficulty = _base_difficulty(phrase, config)
        target_difficulty = clamp(
            base_difficulty * multipliers["complexity"],
            config.difficulty_floor,
            config.difficulty_ceiling,
        )
        phrase.__dict__["target_density"] = round(target_density, 4)
        phrase.__dict__["target_difficulty"] = round(target_difficulty, 4)

        entry = _entry_direction(ordered, index)
        exit_direction = _exit_direction(ordered, index)
        phrase.__dict__["entry_direction_deg"] = round(entry, 2)
        phrase.__dict__["exit_direction_deg"] = round(exit_direction, 2)

        min_gap = int(round(1000.0 / max(target_density * 0.9, 0.3)))
        target_gap = int(round(1000.0 / max(target_density, 0.3)))
        phrase.__dict__["min_gap_ms"] = max(60, min_gap)
        phrase.__dict__["target_gap_ms"] = max(90, target_gap)
    return ordered


def _base_density(phrase: Phrase, config: TrajectoryConfig) -> float:
    density = phrase.onset_density
    energy_boost = clamp(phrase.average_energy, 0.0, 1.0) * 0.6
    return clamp(density * 0.85 + energy_boost, config.density_floor, config.density_ceiling)


def _base_difficulty(phrase: Phrase, config: TrajectoryConfig) -> float:
    return clamp(
        phrase.average_energy * 0.55
        + phrase.rhythm_complexity * 0.35
        + min(1.0, phrase.onset_density / 3.0) * 0.2,
        config.difficulty_floor,
        config.difficulty_ceiling,
    )


def _entry_direction(ordered: list[Phrase], index: int) -> float:
    """Smooth entry vector (deg) derived from preceding energy slopes."""
    samples: list[float] = []
    for window in range(max(0, index - 2), index):
        slope = ordered[window].energy_slope
        if abs(slope) > 1e-6:
            samples.append(math.degrees(math.atan2(slope, 1.0)))
    if not samples:
        return 0.0
    return sum(samples) / len(samples)


def _exit_direction(ordered: list[Phrase], index: int) -> float:
    samples: list[float] = []
    for window in range(index + 1, min(len(ordered), index + 3)):
        slope = ordered[window].energy_slope
        if abs(slope) > 1e-6:
            samples.append(math.degrees(math.atan2(slope, 1.0)))
    if not samples:
        return 0.0
    return sum(samples) / len(samples)


def build_trajectory_points(
    phrases: list[Phrase],
) -> list[dict[str, float]]:
    """Serialize the trajectory as (timeMs, density, difficulty) points."""
    points: list[dict[str, float]] = []
    for phrase in sorted(phrases, key=lambda item: item.start_ms):
        points.append(
            {
                "timeMs": float(phrase.start_ms),
                "density": phrase.target_density,
                "difficulty": phrase.target_difficulty,
            }
        )
        points.append(
            {
                "timeMs": float(phrase.end_ms),
                "density": phrase.target_density,
                "difficulty": phrase.target_difficulty,
            }
        )
    return points


def density_multiplier_at(
    phrases: list[Phrase],
    time_ms: int,
    default: float = 1.0,
) -> float:
    """Strategy density multiplier active at ``time_ms`` (for generation)."""
    for phrase in phrases:
        if phrase.contains(time_ms):
            multipliers = strategy_generation_multipliers(phrase.strategy)
            return multipliers["density"]
    return default


def difficulty_multiplier_at(
    phrases: list[Phrase],
    time_ms: int,
    default: float = 1.0,
) -> float:
    for phrase in phrases:
        if phrase.contains(time_ms):
            multipliers = strategy_generation_multipliers(phrase.strategy)
            return multipliers["complexity"]
    return default


def movement_multiplier_at(
    phrases: list[Phrase],
    time_ms: int,
    default: float = 1.0,
) -> float:
    for phrase in phrases:
        if phrase.contains(time_ms):
            multipliers = strategy_generation_multipliers(phrase.strategy)
            return multipliers["movement"]
    return default


def full_trajectory_plan(
    phrases: list[Phrase],
    trajectory_config: TrajectoryConfig = DEFAULT_TRAJECTORY_CONFIG,
    motif_config: Any = None,
) -> list[Phrase]:
    """Run strategies + trajectory planning in the canonical order."""
    from .motif_engine import DEFAULT_MOTIF_CONFIG

    assigned = assign_all_strategies(phrases, motif_config or DEFAULT_MOTIF_CONFIG)
    return plan_trajectory(assigned, trajectory_config)


def build_phrase_density_resolver(
    phrases: list[Phrase],
) -> Any:
    """Build a deterministic (time_ms -> target_density) resolver.

    Returns None when no phrase carries a positive density target so callers
    can fall back to their default behavior (identity for legacy runs).
    """
    ordered = sorted(
        (phrase for phrase in phrases if phrase.target_density > 0),
        key=lambda phrase: (phrase.start_ms, phrase.id),
    )
    if not ordered:
        return None

    def resolve(time_ms: int) -> float | None:
        for phrase in ordered:
            if phrase.contains(time_ms):
                return phrase.target_density
        return None

    return resolve
