from __future__ import annotations

from dataclasses import dataclass

from ..difficulty.common import clamp
from .models import ReplayScoreBreakdown


@dataclass(frozen=True)
class ReplayScoreWeights:
    accuracy: float = 0.25
    miss: float = 0.20
    combo: float = 0.15
    reading: float = 0.10
    cursor: float = 0.10
    fatigue: float = 0.10
    rhythm: float = 0.10

    @property
    def total(self) -> float:
        return (
            self.accuracy
            + self.miss
            + self.combo
            + self.reading
            + self.cursor
            + self.fatigue
            + self.rhythm
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "accuracy": self.accuracy,
            "miss": self.miss,
            "combo": self.combo,
            "reading": self.reading,
            "cursor": self.cursor,
            "fatigue": self.fatigue,
            "rhythm": self.rhythm,
        }


def compute_replay_score(
    *,
    accuracy: float,
    miss_rate: float,
    combo_pct: float,
    full_combo_chance: float,
    reading_score: float,
    cursor_efficiency: float,
    fatigue_average: float,
    rhythm_consistency: float,
    weights: ReplayScoreWeights = ReplayScoreWeights(),
) -> ReplayScoreBreakdown:
    """Combine all replay metrics into one overall replay quality score.

    Contributors are normalized 0..100: accuracy prediction, miss prediction,
    combo stability, reading, cursor efficiency, fatigue, and rhythm
    consistency. The overall score is the weighted average.
    """
    accuracy_prediction = clamp(accuracy * 100.0, 0.0, 100.0)
    miss_prediction = clamp(100.0 * (1.0 - miss_rate * 2.2), 0.0, 100.0)
    combo_stability = (
        clamp(combo_pct, 0.0, 1.0) * 0.7 + clamp(full_combo_chance, 0.0, 1.0) * 0.3
    ) * 100.0
    reading = clamp(reading_score, 0.0, 100.0)
    cursor = clamp(cursor_efficiency * 100.0, 0.0, 100.0)
    fatigue = clamp(100.0 * (1.0 - fatigue_average * 1.5), 0.0, 100.0)
    rhythm = clamp(rhythm_consistency * 100.0, 0.0, 100.0)

    total = weights.total or 1.0
    overall = (
        accuracy_prediction * weights.accuracy
        + miss_prediction * weights.miss
        + combo_stability * weights.combo
        + reading * weights.reading
        + cursor * weights.cursor
        + fatigue * weights.fatigue
        + rhythm * weights.rhythm
    ) / total

    return ReplayScoreBreakdown(
        accuracy_prediction=round(accuracy_prediction, 2),
        miss_prediction=round(miss_prediction, 2),
        combo_stability=round(combo_stability, 2),
        reading=round(reading, 2),
        cursor_efficiency=round(cursor, 2),
        fatigue=round(fatigue, 2),
        rhythm_consistency=round(rhythm, 2),
        overall=round(clamp(overall, 0.0, 100.0), 2),
    )
