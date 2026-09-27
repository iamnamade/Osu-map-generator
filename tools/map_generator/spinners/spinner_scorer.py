from __future__ import annotations

from ..config import DifficultyPreset
from .spinner_models import SpinnerCandidate, SpinnerMusicalContext, SpinnerQualityScore


def score_spinner_candidate(
    *,
    candidate: SpinnerCandidate,
    context: SpinnerMusicalContext,
    preset: DifficultyPreset,
    previous_object_end_ms: int | None = None,
    next_object_time_ms: int | None = None,
) -> SpinnerQualityScore:
    """Score a spinner candidate across musical, timing, and gameplay axes.

    Returns a SpinnerQualityScore with a 0-100 overall. Poor candidates are
    rejected by the pipeline when overall falls below the quality threshold.
    """
    musical_match = _score_musical_match(candidate)
    timing_quality = _score_timing_quality(candidate, context)
    duration_score = _score_duration(candidate, preset)
    transition_quality = _score_transition(candidate, previous_object_end_ms, next_object_time_ms)
    difficulty_impact = _score_difficulty_impact(candidate, preset)
    flow = _score_flow(candidate, context, previous_object_end_ms, next_object_time_ms)

    overall = (
        musical_match * 0.28
        + timing_quality * 0.18
        + duration_score * 0.16
        + transition_quality * 0.18
        + difficulty_impact * 0.1
        + flow * 0.1
    )

    return SpinnerQualityScore(
        musical_match=round(musical_match, 2),
        timing_quality=round(timing_quality, 2),
        duration_score=round(duration_score, 2),
        transition_quality=round(transition_quality, 2),
        difficulty_impact=round(difficulty_impact, 2),
        flow=round(flow, 2),
        overall=round(overall, 2),
    )


def _score_musical_match(candidate: SpinnerCandidate) -> float:
    """Base score on the musical justification of the region."""
    base = candidate.musical_score
    # Sustained/ambient content is the strongest musical justification.
    base += candidate.sustained_score * 30
    return max(0.0, min(100.0, base))


def _score_timing_quality(
    candidate: SpinnerCandidate,
    context: SpinnerMusicalContext,
) -> float:
    """Reward spinners that sit on meaningful musical boundaries."""
    score = 60.0
    beat_interval_ms = 60000 / max(60.0, context.bpm) if context.bpm > 0 else 500

    # Start should be close to an onset or beat boundary.
    if context.onset_times:
        nearest_delta = min(
            abs(onset_time - candidate.start_ms) for onset_time in context.onset_times
        )
        if nearest_delta <= beat_interval_ms * 0.4:
            score += 20
        elif nearest_delta <= beat_interval_ms:
            score += 10
        else:
            score -= 12

    # End should land shortly before the next object for a natural pickup.
    if candidate.gap_after_ms is not None:
        if 150 <= candidate.gap_after_ms <= 700:
            score += 15
        elif candidate.gap_after_ms > 700:
            score += 6

    return max(0.0, min(100.0, score))


def _score_duration(candidate: SpinnerCandidate, preset: DifficultyPreset) -> float:
    """Reward durations that match the difficulty expectations."""
    duration = candidate.duration_ms
    if preset.name == "easy":
        ideal_min, ideal_max = 500, 2000
    elif preset.name == "normal":
        ideal_min, ideal_max = 700, 2600
    else:
        ideal_min, ideal_max = 900, 3200

    if duration < preset.spinner_min_duration_ms:
        return 25.0
    if duration > preset.spinner_max_duration_ms:
        return 30.0

    if ideal_min <= duration <= ideal_max:
        return 95.0
    if duration < ideal_min:
        return 70.0 + (duration - preset.spinner_min_duration_ms) / max(
            1, ideal_min - preset.spinner_min_duration_ms
        ) * 25
    return 60.0


def _score_transition(
    candidate: SpinnerCandidate,
    previous_object_end_ms: int | None,
    next_object_time_ms: int | None,
) -> float:
    """Score how naturally the spinner connects into surrounding gameplay."""
    score = 70.0

    if previous_object_end_ms is not None:
        entry_gap = candidate.start_ms - previous_object_end_ms
        if 100 <= entry_gap <= 500:
            score += 15
        elif entry_gap < 100:
            score -= 20  # too rushed into the spinner

    if next_object_time_ms is not None:
        exit_gap = next_object_time_ms - candidate.end_ms
        if exit_gap >= 200:
            score += 15  # comfortable recovery after the spinner
        elif exit_gap >= 80:
            score += 5
        else:
            score -= 25  # object immediately after spinner end is awkward

    return max(0.0, min(100.0, score))


def _score_difficulty_impact(candidate: SpinnerCandidate, preset: DifficultyPreset) -> float:
    """Ensure the spinner fits the difficulty's intensity expectations."""
    # Spinners are low-intensity moments; they fit best in low/medium energy regions.
    energy = candidate.energy
    if energy <= 0.45:
        return 90.0
    if energy <= 0.65:
        return 70.0
    return 40.0


def _score_flow(
    candidate: SpinnerCandidate,
    context: SpinnerMusicalContext,
    previous_object_end_ms: int | None,
    next_object_time_ms: int | None,
) -> float:
    """Score cursor-recovery flow into and out of the spinner."""
    score = 75.0

    # Long spinners on easy need more recovery time; short spinners on hard
    # can transition faster.
    if candidate.duration_ms > 2500:
        score -= 8
    if candidate.duration_ms < 600:
        score -= 5

    if previous_object_end_ms is not None and candidate.start_ms - previous_object_end_ms < 150:
        score -= 10
    if next_object_time_ms is not None and next_object_time_ms - candidate.end_ms < 120:
        score -= 12

    return max(0.0, min(100.0, score))
