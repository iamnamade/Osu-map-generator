from __future__ import annotations

from dataclasses import dataclass, field

from ..difficulty.common import clamp
from .models import EvolutionDimensionScores


@dataclass(frozen=True)
class EvolutionScoreWeights:
    quality: float = 0.16
    difficulty: float = 0.08
    playability: float = 0.10
    consistency: float = 0.07
    confidence: float = 0.05
    reading: float = 0.07
    rhythm: float = 0.08
    flow: float = 0.07
    movement: float = 0.07
    pattern: float = 0.05
    slider: float = 0.05
    spinner: float = 0.05
    replay: float = 0.10

    def to_dict(self) -> dict[str, float]:
        return {
            "quality": self.quality,
            "difficulty": self.difficulty,
            "playability": self.playability,
            "consistency": self.consistency,
            "confidence": self.confidence,
            "reading": self.reading,
            "rhythm": self.rhythm,
            "flow": self.flow,
            "movement": self.movement,
            "pattern": self.pattern,
            "slider": self.slider,
            "spinner": self.spinner,
            "replay": self.replay,
        }

    @property
    def total(self) -> float:
        return sum(
            (
                self.quality,
                self.difficulty,
                self.playability,
                self.consistency,
                self.confidence,
                self.reading,
                self.rhythm,
                self.flow,
                self.movement,
                self.pattern,
                self.slider,
                self.spinner,
                self.replay,
            )
        )


def score_candidate(
    *,
    improved_report,
    difficulty_report,
    replay_report=None,
    weights: EvolutionScoreWeights = EvolutionScoreWeights(),
) -> EvolutionDimensionScores:
    """Deterministic composite scoring for one evolution candidate.

    Combines validator quality, difficulty target match, difficulty-engine
    dimensions (reading/rhythm/flow), playability from the simulated player,
    the Phase 15 replay simulation score, and consistency/confidence from the
    difficulty report into a weighted 0..100 overall score.

    ``replay_report`` is optional: when absent (e.g. standalone scoring) the
    replay dimension is neutral so scoring remains backward compatible.
    """
    quality = _clamped(improved_report.scores.overall)
    movement = _clamped(improved_report.scores.movement)
    validator_rhythm = _clamped(improved_report.scores.rhythm)

    difficulty_score = _difficulty_match(difficulty_report)
    reading = _clamped(difficulty_report.reading.score * 100.0)
    rhythm = _clamped((difficulty_report.rhythm.score * 100.0 + validator_rhythm) / 2.0)
    flow = _clamped(difficulty_report.aim.flow_quality * 100.0)
    consistency = _clamped(difficulty_report.consistency_score * 100.0)
    confidence = _clamped(difficulty_report.confidence_score * 100.0)
    pattern = _pattern_score(difficulty_report)
    slider = _slider_score(difficulty_report)
    spinner = _spinner_score(difficulty_report)
    playability = _playability_score(difficulty_report)
    replay = _replay_score(replay_report)

    overall = clamp(
        quality * weights.quality
        + difficulty_score * weights.difficulty
        + playability * weights.playability
        + consistency * weights.consistency
        + confidence * weights.confidence
        + reading * weights.reading
        + rhythm * weights.rhythm
        + flow * weights.flow
        + movement * weights.movement
        + pattern * weights.pattern
        + slider * weights.slider
        + spinner * weights.spinner
        + replay * weights.replay,
        0.0,
        100.0,
    )

    return EvolutionDimensionScores(
        overall=round(overall, 3),
        quality=round(quality, 3),
        difficulty=round(difficulty_score, 3),
        flow=round(flow, 3),
        rhythm=round(rhythm, 3),
        movement=round(movement, 3),
        pattern=round(pattern, 3),
        slider=round(slider, 3),
        spinner=round(spinner, 3),
        reading=round(reading, 3),
        playability=round(playability, 3),
        consistency=round(consistency, 3),
        confidence=round(confidence, 3),
        replay=round(replay, 3),
    )


def _clamped(value: float) -> float:
    return clamp(float(value), 0.0, 100.0)


def _difficulty_match(difficulty_report) -> float:
    stars = float(difficulty_report.star_rating.overall)
    target = difficulty_report.target
    low, high = float(target.star_range[0]), float(target.star_range[1])
    center = (low + high) / 2.0
    half_span = max(0.5, (high - low) / 2.0)
    deviation = abs(stars - center) / half_span
    # Full marks inside the band; falls to 0 at ~4 band widths away.
    return clamp(100.0 - deviation * 25.0, 0.0, 100.0)


def _pattern_score(difficulty_report) -> float:
    metrics = difficulty_report.metrics
    variation = _clamped(metrics.pattern_variation * 100.0)
    stream_penalty = clamp((metrics.longest_stream_length - 18) * 3.0, 0.0, 30.0)
    burst_penalty = clamp((metrics.longest_burst_length - 10) * 2.5, 0.0, 20.0)
    return clamp(variation * 0.7 + 30.0 - stream_penalty - burst_penalty, 0.0, 100.0)


def _slider_score(difficulty_report) -> float:
    metrics = difficulty_report.metrics
    slider_count = metrics.slider_count
    if slider_count <= 0:
        return 100.0
    complexity = _clamped(metrics.slider_complexity * 100.0)
    repeat_penalty = clamp((metrics.average_slider_repeats - 1.5) * 12.0, 0.0, 25.0)
    return clamp(100.0 - complexity * 0.55 - repeat_penalty, 0.0, 100.0)


def _spinner_score(difficulty_report) -> float:
    metrics = difficulty_report.metrics
    frequency = float(metrics.spinner_frequency_per_minute)
    if frequency <= 0.0:
        return 100.0
    return clamp(100.0 - frequency * 22.0, 0.0, 100.0)


def _playability_score(difficulty_report) -> float:
    gameplay = difficulty_report.gameplay
    miss = _clamped(gameplay.estimated_miss_probability * 100.0)
    combo = _clamped(gameplay.estimated_combo_stability * 100.0)
    stress = _clamped(gameplay.estimated_player_stress * 100.0)
    return clamp(
        (100.0 - miss) * 0.5 + combo * 0.3 + (100.0 - stress) * 0.2,
        0.0,
        100.0,
    )


def _replay_score(replay_report) -> float:
    """Replay dimension from the Phase 15 replay report (neutral when absent)."""
    if replay_report is None:
        return 50.0
    breakdown = getattr(replay_report, "score_breakdown", None)
    if breakdown is None:
        return 50.0
    overall = getattr(breakdown, "overall", None)
    if overall is None:
        return 50.0
    return _clamped(float(overall))
