from __future__ import annotations

import math

from ..config import DifficultyPreset
from .spinner_analysis import classify_region, classify_trigger, region_musical_score
from .spinner_models import (
    FatigueProfile,
    SpinnerCandidate,
    SpinnerConfig,
    SpinnerMusicalContext,
    SpinnerRegionType,
)


def evaluate_spinner_region(
    *,
    gap_start_ms: int,
    gap_end_ms: int,
    context: SpinnerMusicalContext,
    preset: DifficultyPreset,
    min_gap_ms: int | None = None,
) -> SpinnerCandidate | None:
    """Evaluate an empty gap in the timeline for spinner suitability.

    A spinner is only proposed when the musical structure supports one.
    Returns None when the gap is too small or the music does not justify it.

    Args:
        gap_start_ms: time immediately after the previous object's end
        gap_end_ms: time immediately before the next object's start
        context: musical context
        preset: difficulty preset
        min_gap_ms: override for the minimum gap that can host a spinner

    Returns:
        SpinnerCandidate or None.
    """
    min_gap = min_gap_ms if min_gap_ms is not None else preset.spinner_min_gap_ms
    if gap_end_ms - gap_start_ms < min_gap:
        return None

    region_type = classify_region(context, gap_start_ms, gap_end_ms)
    if region_type == "dense" or region_type == "unknown":
        return None

    musical_score = region_musical_score(context, region_type, gap_start_ms, gap_end_ms)
    # Use a reduced threshold to be more permissive about spinner placement
    effective_threshold = preset.spinner_musical_threshold * 0.7
    if musical_score < effective_threshold:
        return None

    sustained_score = _average_sustained(context, gap_start_ms, gap_end_ms)
    energy = _average_energy(context, gap_start_ms, gap_end_ms)
    onset_density = _onset_density(context, gap_start_ms, gap_end_ms)

    trigger_type = classify_trigger(
        context,
        region_type,
        gap_start_ms,
        gap_end_ms,
    )
    if trigger_type == "unknown":
        # No identifiable musical trigger: a spinner here would be unmotivated.
        return None

    return SpinnerCandidate(
        region_type=region_type,
        start_ms=gap_start_ms,
        end_ms=gap_end_ms,
        duration_ms=gap_end_ms - gap_start_ms,
        musical_score=musical_score,
        sustained_score=sustained_score,
        energy=energy,
        onset_density=onset_density,
        gap_before_ms=None,
        gap_after_ms=None,
        section_label=_section_label(context, gap_start_ms, gap_end_ms),
        trigger_type=trigger_type,
        min_clearance_ms=preset.spinner_recovery_after_ms,
    )


def calculate_fatigue_profile(
    timestamps: list[float],
    distances: list[float],
    decay_lambda: float = 0.001,
) -> FatigueProfile:
    """Calculate continuous stamina strain over a list of object events.

    Implements the stamina strain model from the Phase 22 spec::

        Strain_t = Strain_{t-1} * e^(-lambda * dt) + SpacingWeight * Distance / dt

    Scores are normalized to 0.0-1.0 against the peak strain so the curve is
    comparable across maps. Fully deterministic: the output depends only on
    the timestamps, distances, and decay constant.

    Args:
        timestamps: Event times in ms (one per object).
        distances: Cursor travel in px to each object (same length).
        decay_lambda: Exponential decay per ms of the strain accumulator.

    Returns:
        A normalized FatigueProfile with the peak time recorded.
    """
    if not timestamps or len(timestamps) != len(distances):
        return FatigueProfile.empty()

    scores: list[float] = []
    current_strain = 0.0
    peak_time = timestamps[0]
    max_strain = 0.0

    for index in range(len(timestamps)):
        if index > 0:
            dt = max(timestamps[index] - timestamps[index - 1], 1.0)
            decay = math.exp(-decay_lambda * dt)
            spacing_weight = distances[index] / dt
            current_strain = current_strain * decay + spacing_weight
        else:
            current_strain = 0.0

        scores.append(current_strain)
        if current_strain > max_strain:
            max_strain = current_strain
            peak_time = timestamps[index]

    normalized = [score / max_strain if max_strain > 0 else 0.0 for score in scores]
    return FatigueProfile(
        timestamps=[int(round(time_stamp)) for time_stamp in timestamps],
        fatigue_scores=[round(value, 4) for value in normalized],
        peak_fatigue_time=int(round(peak_time)),
        peak_fatigue=round(max_strain, 4),
    )


def validate_spinner(
    candidate: SpinnerCandidate,
    next_object_time: int | None,
    config: SpinnerConfig,
) -> bool:
    """Validate a spinner against duration and post-clearance rules.

    Returns True when the spinner is playable: it lasts at least
    ``config.min_duration_ms`` and leaves at least ``min_clearance_ms`` (or
    ``config.post_clearance_ms``) before the next object.
    """
    duration = candidate.end_ms - candidate.start_ms
    if duration < config.min_duration_ms:
        return False

    if next_object_time is not None:
        clearance = next_object_time - candidate.end_ms
        required = max(candidate.min_clearance_ms, config.post_clearance_ms)
        if clearance < required:
            return False

    return True


def _average_sustained(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [frame for frame in context.sustained_frames if start_ms <= frame["timeMs"] <= end_ms]
    if not frames:
        return context.sustained_at((start_ms + end_ms) // 2)
    return sum(float(frame["sustainedScore"]) for frame in frames) / len(frames)


def _average_energy(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [frame for frame in context.energy_frames if start_ms <= frame["timeMs"] <= end_ms]
    if not frames:
        return context.energy_at((start_ms + end_ms) // 2)
    return sum(float(frame["value"]) for frame in frames) / len(frames)


def _onset_density(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    count = sum(1 for time_ms in context.onset_times if start_ms <= time_ms <= end_ms)
    seconds = max(1.0, (end_ms - start_ms) / 1000)
    return count / seconds


def _section_label(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> str | None:
    best: str | None = None
    best_overlap = 0
    for section in context.sections:
        overlap_start = max(start_ms, int(section["startMs"]))
        overlap_end = min(end_ms, int(section["endMs"]))
        overlap = max(0, overlap_end - overlap_start)
        if overlap > best_overlap:
            best = str(section["label"])
            best_overlap = overlap
    if best_overlap < max(200, int((end_ms - start_ms) * 0.2)):
        return None
    return best
