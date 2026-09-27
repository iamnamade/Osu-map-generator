from __future__ import annotations

from dataclasses import dataclass

from .config import DifficultyPreset
from .models import AudioAnalysis, SelectedEvent, SelectedEventSource, TimedStrength
from .utils import MapGeneratorError, clamp
from .variation import EventSelectionVariation


@dataclass(frozen=True)
class _CandidateEvent:
    time_ms: int
    source: SelectedEventSource
    strength: float
    energy: float
    confidence: float
    is_emphasis: bool


def select_events(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    *,
    variation: EventSelectionVariation | None = None,
    rhythm_model=None,
) -> list[SelectedEvent]:
    """Select playable map events from beats and onsets.

    When a rhythm_model is provided (from Phase 9 rhythm intelligence),
    uses the enhanced multi-layer analysis for smarter timing selection.

    When no rhythm_model is provided, falls back to the classic algorithm
    for full backward compatibility.
    """
    if rhythm_model is not None:
        return _select_with_rhythm_model(analysis, preset, variation, rhythm_model)

    return _select_classic(analysis, preset, variation)


def _select_with_rhythm_model(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    variation: EventSelectionVariation | None,
    rhythm_model,
) -> list[SelectedEvent]:
    """Use the rhythm intelligence engine for timing selection."""
    from .rhythm.rhythm_pipeline import select_rhythmic_timings

    events, times = select_rhythmic_timings(
        model=rhythm_model,
        preset=preset,
        variation=variation,
    )

    if not events:
        raise MapGeneratorError(
            "Rhythm intelligence could not select any playable events."
        )

    return events


def _select_classic(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    variation: EventSelectionVariation | None,
) -> list[SelectedEvent]:
    """Original classic event selection algorithm (backward compatible)."""
    effective_variation = variation or EventSelectionVariation()
    effective_target_gap_ms = max(
        preset.min_gap_ms,
        int(round(preset.target_gap_ms * effective_variation.target_gap_multiplier)),
    )
    strong_beat_threshold = clamp(
        preset.strong_beat_threshold + effective_variation.strong_beat_offset,
        0.0,
        1.0,
    )
    weak_event_confidence_floor = clamp(
        0.82 + effective_variation.weak_event_confidence_bias,
        0.68,
        0.95,
    )

    candidates = _build_candidates(analysis, preset, effective_variation)
    merged = _merge_close_candidates(
        candidates,
        max(0, preset.merge_tolerance_ms + effective_variation.merge_tolerance_offset_ms),
    )

    if not merged:
        raise MapGeneratorError("Analysis returned no usable beats or onsets after filtering.")

    selected: list[_CandidateEvent] = []

    for candidate in merged:
        if candidate.time_ms < preset.start_padding_ms:
            continue

        if candidate.time_ms > analysis.duration_ms - preset.end_padding_ms:
            continue

        if analysis.in_quiet_region(candidate.time_ms) and candidate.confidence < 0.84:
            continue

        if selected:
            gap_ms = candidate.time_ms - selected[-1].time_ms

            if gap_ms <= 0:
                continue

            if gap_ms < preset.min_gap_ms:
                replacement = _pick_stronger_dense_event(selected[-1], candidate)
                if replacement is candidate:
                    selected[-1] = candidate
                continue

            if gap_ms < effective_target_gap_ms and not candidate.is_emphasis:
                if candidate.source != "beat" or candidate.strength < strong_beat_threshold + 0.08:
                    continue

            if candidate.source != "beat":
                if gap_ms < int(effective_target_gap_ms * 0.9) and candidate.confidence < weak_event_confidence_floor:
                    continue

        selected.append(candidate)

    if not selected:
        fallback = [item for item in merged if item.source == "beat"]
        selected = fallback[:1]

    if not selected:
        raise MapGeneratorError("No playable hit events remained after applying difficulty rules.")

    return [
        SelectedEvent(
            time_ms=item.time_ms,
            source=item.source,
            strength=item.strength,
            energy=item.energy,
            confidence=item.confidence,
            is_emphasis=item.is_emphasis,
        )
        for item in selected
    ]


def _build_candidates(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    variation: EventSelectionVariation,
) -> list[_CandidateEvent]:
    beat_strength_threshold = clamp(
        preset.beat_strength_threshold + variation.beat_strength_offset,
        0.0,
        1.0,
    )
    onset_strength_threshold = clamp(
        preset.onset_strength_threshold + variation.onset_strength_offset,
        0.0,
        1.0,
    )
    strong_beat_threshold = clamp(
        preset.strong_beat_threshold + variation.strong_beat_offset,
        0.0,
        1.0,
    )
    include_offbeat_onsets = (
        preset.include_offbeat_onsets
        if variation.allow_offbeat_onsets is None
        else variation.allow_offbeat_onsets
    )
    beat_candidates = [
        _candidate_from_timed_strength(
            timed_strength=beat,
            analysis=analysis,
            source="beat",
            emphasis=beat.strength >= strong_beat_threshold,
            confidence_bonus=0.11,
        )
        for beat in analysis.beats
        if beat.strength >= beat_strength_threshold
    ]

    onset_candidates: list[_CandidateEvent] = []
    if include_offbeat_onsets:
        onset_candidates = [
            _candidate_from_timed_strength(
                timed_strength=onset,
                analysis=analysis,
                source="onset",
                emphasis=onset.strength >= onset_strength_threshold + 0.18,
                confidence_bonus=0.03,
            )
            for onset in analysis.onsets
            if onset.strength >= onset_strength_threshold
        ]

    return sorted(
        beat_candidates + onset_candidates,
        key=lambda item: (item.time_ms, -item.confidence),
    )


def _candidate_from_timed_strength(
    timed_strength: TimedStrength,
    analysis: AudioAnalysis,
    source: SelectedEventSource,
    emphasis: bool,
    confidence_bonus: float,
) -> _CandidateEvent:
    energy = analysis.energy_at(timed_strength.time_ms)
    confidence = min(1.0, timed_strength.strength * 0.62 + energy * 0.38 + confidence_bonus)
    return _CandidateEvent(
        time_ms=timed_strength.time_ms,
        source=source,
        strength=timed_strength.strength,
        energy=energy,
        confidence=round(confidence, 4),
        is_emphasis=emphasis or analysis.in_high_energy_region(timed_strength.time_ms),
    )


def _merge_close_candidates(
    candidates: list[_CandidateEvent],
    tolerance_ms: int,
) -> list[_CandidateEvent]:
    if not candidates:
        return []

    merged: list[_CandidateEvent] = [candidates[0]]

    for candidate in candidates[1:]:
        previous = merged[-1]

        if candidate.time_ms - previous.time_ms > tolerance_ms:
            merged.append(candidate)
            continue

        winner = previous if previous.confidence >= candidate.confidence else candidate
        source: SelectedEventSource = winner.source
        if previous.source != candidate.source:
            source = "merged"

        merged[-1] = _CandidateEvent(
            time_ms=winner.time_ms,
            source=source,
            strength=max(previous.strength, candidate.strength),
            energy=max(previous.energy, candidate.energy),
            confidence=round(min(1.0, max(previous.confidence, candidate.confidence) + 0.06), 4),
            is_emphasis=previous.is_emphasis or candidate.is_emphasis,
        )

    return merged


def _pick_stronger_dense_event(
    current: _CandidateEvent,
    challenger: _CandidateEvent,
) -> _CandidateEvent:
    if challenger.source == "beat" and current.source != "beat" and challenger.confidence >= current.confidence - 0.04:
        return challenger

    if challenger.is_emphasis and not current.is_emphasis:
        return challenger

    if challenger.confidence > current.confidence + 0.08:
        return challenger

    return current
