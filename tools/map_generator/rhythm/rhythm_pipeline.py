from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from . import multi_layer_analysis as mla
from . import rhythm_density as rd
from . import timing_quality as tq
from .rhythm_models import (
    BpmRegion,
    EnhancedAudioFeatures,
    PhraseInfo,
    RhythmDiagnostics,
    RhythmModel,
    SubdivisionInfo,
    TimingCandidate,
)
from ..config import DifficultyPreset
from ..models import AudioAnalysis, SelectedEvent, SelectedEventSource, TimedStrength
from ..utils import MapGeneratorError, clamp
from ..variation import EventSelectionVariation


@dataclass(frozen=True)
class RhythmPipelineConfig:
    """Configuration for the complete rhythm intelligence pipeline."""

    enhanced_analysis_enabled: bool = True
    subdivision_enabled: bool = True
    phrase_aware_enabled: bool = True
    max_allowed_empty_gap_ms: int = 3000
    min_timing_confidence: float = 0.35
    fill_subdivision_gaps: bool = True
    max_timings: int = 3000
    multi_layer: Any = field(default_factory=mla.MultiLayerConfig)
    density: Any = field(default_factory=rd.DensityConfig)


DEFAULT_RHYTHM_CONFIG = RhythmPipelineConfig()


def build_rhythm_model(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    samples: np.ndarray | None = None,
    sample_rate: int | None = None,
    rhythm_config: RhythmPipelineConfig = DEFAULT_RHYTHM_CONFIG,
    phrase_info: list[PhraseInfo] | None = None,
) -> RhythmModel:
    """Build a complete RhythmModel from audio analysis.

    This is the main entry point for rhythm intelligence.
    Uses existing AudioAnalysis and optionally raw samples.
    """
    enhanced_features: EnhancedAudioFeatures | None = None
    bpm_regions: list[BpmRegion] = []
    subdivisions: list[SubdivisionInfo] = []

    if rhythm_config.enhanced_analysis_enabled and samples is not None and sample_rate is not None:
        enhanced_features = mla.extract_enhanced_features(
            samples=samples,
            sample_rate=sample_rate,
            duration_ms=analysis.duration_ms,
            beats=analysis.beats,
            onsets=analysis.onsets,
            config=rhythm_config.multi_layer,
        )
        bpm_regions = mla.compute_bpm_regions(
            beats=analysis.beats,
            onsets=analysis.onsets,
            duration_ms=analysis.duration_ms,
            config=rhythm_config.multi_layer,
        )
        if rhythm_config.subdivision_enabled:
            subdivisions = mla.detect_subdivisions(
                analysis=analysis,
                beats=analysis.beats,
                onsets=analysis.onsets,
                duration_ms=analysis.duration_ms,
                config=rhythm_config.multi_layer,
            )

    if not bpm_regions:
        bpm_regions = [
            BpmRegion(
                start_ms=0,
                end_ms=analysis.duration_ms,
                bpm=analysis.bpm,
                confidence=0.5,
                beat_count=len(analysis.beats),
            )
        ]

    tempo_confidence = mla.compute_tempo_confidence(
        bpm_regions=bpm_regions,
        beats=analysis.beats,
        duration_ms=analysis.duration_ms,
    )

    density_targets = rd.compute_density_targets(
        energy_frames=analysis.energy_frames,
        duration_ms=analysis.duration_ms,
        bpm=analysis.bpm,
        phrase_info=phrase_info,
        config=rhythm_config.density,
    )

    silent_regions = rd.detect_silent_regions(
        energy_frames=analysis.energy_frames,
        duration_ms=analysis.duration_ms,
        config=rhythm_config.density,
    )

    resolved_phrase_info = rd.build_phrase_density_info(
        sections_info=phrase_info,
        density_targets=density_targets,
        config=rhythm_config.density,
    )

    return RhythmModel(
        analysis=analysis,
        enhanced_features=enhanced_features,
        bpm_regions=bpm_regions,
        subdivisions=subdivisions,
        silent_regions=silent_regions,
        density_targets=density_targets,
        phrase_info=resolved_phrase_info,
        tempo_confidence=tempo_confidence,
        rhythm_config=rhythm_config,
        preset=preset,
    )


def select_rhythmic_timings(
    model: RhythmModel,
    preset: DifficultyPreset,
    variation: EventSelectionVariation | None = None,
) -> tuple[list[SelectedEvent], list[int]]:
    """Select high-quality timing points using the rhythm model.

    Returns (selected_events, selected_times_ms).
    """
    effective_variation = variation or EventSelectionVariation()
    config = model.rhythm_config

    raw_candidates: list[TimingCandidate] = []
    seen_times: set[int] = set()

    # Beats as primary candidates
    for beat in model.analysis.beats:
        if beat.time_ms in seen_times:
            continue
        seen_times.add(beat.time_ms)
        confidence = tq.compute_timing_confidence(
            beat.time_ms, model.analysis,
            density_targets=model.density_targets,
        )
        raw_candidates.append(
            TimingCandidate(
                time_ms=beat.time_ms,
                source="beat",
                strength=beat.strength,
                confidence=confidence,
                alignment_score=1.0 if confidence > 0.7 else confidence,
                density_fit=_density_fit(beat.time_ms, model.density_targets),
                phase="strong" if beat.strength >= preset.strong_beat_threshold else "weak",
            )
        )

    # Onsets as secondary candidates
    include_onsets = preset.include_offbeat_onsets
    if effective_variation.allow_offbeat_onsets is not None:
        include_onsets = effective_variation.allow_offbeat_onsets

    if include_onsets:
        onset_threshold = preset.onset_strength_threshold
        if effective_variation.onset_strength_offset:
            onset_threshold = clamp(onset_threshold + effective_variation.onset_strength_offset, 0.0, 1.0)

        for onset in model.analysis.onsets:
            if onset.time_ms in seen_times:
                continue
            if onset.strength < onset_threshold:
                continue
            seen_times.add(onset.time_ms)
            confidence = tq.compute_timing_confidence(
                onset.time_ms, model.analysis,
                density_targets=model.density_targets,
            )
            raw_candidates.append(
                TimingCandidate(
                    time_ms=onset.time_ms,
                    source="onset",
                    strength=onset.strength,
                    confidence=confidence,
                    alignment_score=confidence,
                    density_fit=_density_fit(onset.time_ms, model.density_targets),
                    phase="strong" if onset.strength >= onset_threshold + 0.18 else "weak",
                )
            )

    # Add subdivision candidates
    if config.fill_subdivision_gaps and model.subdivisions:
        _add_subdivision_candidates(raw_candidates, model, seen_times)

    # Sort by time
    raw_candidates.sort(key=lambda c: c.time_ms)

    # Select by density and gap
    selected_times = _select_by_density_and_gap(raw_candidates, model, preset, config)

    if not selected_times:
        selected_times = [
            c.time_ms for c in raw_candidates
            if c.source == "beat" and c.confidence >= config.min_timing_confidence * 0.7
        ]
        if not selected_times and raw_candidates:
            selected_times = [raw_candidates[0].time_ms]

    if not selected_times:
        raise MapGeneratorError(
            "Rhythm intelligence could not select any playable timings."
        )

    # Build events
    selected_events = _build_selected_events(selected_times, raw_candidates, model)

    # Update diagnostics
    accepted_set = set(selected_times)
    model.diagnostics = RhythmDiagnostics(
        bpm_regions=model.bpm_regions,
        subdivisions=model.subdivisions,
        phrases=model.phrase_info,
        global_tempo_confidence=model.tempo_confidence,
        global_bpm=model.analysis.bpm,
        timing_candidates=raw_candidates,
        timing_quality=tq.score_timing_quality(model, selected_times),
        rejected_timings=[c for c in raw_candidates if c.time_ms not in accepted_set],
        accepted_timings=[c for c in raw_candidates if c.time_ms in accepted_set],
    )

    return selected_events, selected_times


def _add_subdivision_candidates(
    candidates: list[TimingCandidate],
    model: RhythmModel,
    seen_times: set[int],
) -> None:
    """Add subdivision grid points as low-confidence filler candidates."""
    added = 0
    config = model.rhythm_config
    for sub in model.subdivisions:
        if sub.confidence < mla.DEFAULT_MULTI_LAYER_CONFIG.min_subdivision_confidence:
            continue
        for grid_time in sub.grid_times_ms:
            if grid_time in seen_times:
                continue
            added += 1
            if added > 500:
                break
            if any(start <= grid_time < end for start, end in model.silent_regions):
                continue
            seen_times.add(grid_time)
            conf = tq.compute_timing_confidence(
                grid_time, model.analysis,
                density_targets=model.density_targets,
            )
            if conf < 0.15:
                continue
            candidates.append(
                TimingCandidate(
                    time_ms=grid_time,
                    source="subdivision",
                    strength=0.3 + model.analysis.energy_at(grid_time) * 0.4,
                    confidence=conf,
                    alignment_score=conf,
                    density_fit=_density_fit(grid_time, model.density_targets),
                    phase="filler",
                )
            )


def _density_fit(
    time_ms: int,
    density_targets: list[tuple[int, float]] | None,
) -> float:
    """Compute a density fit score (0-1) for a timing point."""
    if not density_targets:
        return 0.5
    nearest = min(density_targets, key=lambda t: abs(t[0] - time_ms))
    return clamp(nearest[1] / 4.0, 0.0, 1.0)


def _select_by_density_and_gap(
    candidates: list[TimingCandidate],
    model: RhythmModel,
    preset: DifficultyPreset,
    config: RhythmPipelineConfig,
) -> list[int]:
    """Select candidate timings respecting density, gaps, and confidence.

    When the model carries real phrase structure (Phase 20), min/target gaps
    are resolved per phrase so dense phrases get tighter spacing and recovery
    phrases get room to breathe. Falls back to the preset-wide gaps when no
    phrase info is available (identical legacy behavior).
    """
    if not candidates:
        return []

    base_min_gap = preset.min_gap_ms
    base_target_gap = preset.target_gap_ms
    phrase_lookup = _build_phrase_gap_lookup(model.phrase_info)
    cand_by_time: dict[int, TimingCandidate] = {c.time_ms: c for c in candidates}
    selected: list[int] = []
    last_time = -base_target_gap

    for candidate in candidates:
        t = candidate.time_ms

        if t < preset.start_padding_ms:
            continue
        if t > model.analysis.duration_ms - preset.end_padding_ms:
            continue

        min_gap, target_gap = phrase_lookup(t, base_min_gap, base_target_gap)
        gap = t - last_time

        # Too close: keep the musically stronger of the two near-simultaneous
        # events instead of blindly sliding the last selection forward (which
        # collapses dense uniform grids to a single event). Mirrors the classic
        # selector's _pick_stronger_dense_event semantics.
        if gap < min_gap:
            if selected:
                incumbent = cand_by_time.get(selected[-1])
                if incumbent is not None and _is_better_dense_event(candidate, incumbent):
                    selected[-1] = t
                    last_time = t
            continue

        # Skip low-confidence (but be lenient during active audio to fill gaps)
        is_low = candidate.confidence < config.min_timing_confidence
        if is_low and candidate.source != "subdivision":
            if candidate.source != "beat" or gap < target_gap * 0.35:
                continue

        # Silent region check
        in_silent = any(
            start <= t < end for start, end in model.silent_regions
        )
        if in_silent and candidate.source == "subdivision":
            continue
        if in_silent and candidate.confidence < config.min_timing_confidence + 0.15:
            continue

        # Max gap constraint: during active audio sections (high energy),
        # gaps MUST NOT exceed the computed max gap to prevent dead zones.
        max_gap = rd.compute_max_allowed_gap(
            energy_frames=model.analysis.energy_frames,
            start_ms=last_time,
            end_ms=t,
            max_gap_ms=config.max_allowed_empty_gap_ms,
        )

        is_strong = candidate.phase == "strong" or candidate.strength >= preset.strong_beat_threshold

        if gap > max_gap and not in_silent:
            # Active audio section with a gap exceeding the limit: force-select
            # this candidate to fill the dead zone rather than skipping it.
            if candidate.confidence >= config.min_timing_confidence * 0.6:
                selected.append(t)
                last_time = t
            # If confidence is too low, skip (a better candidate may follow)
            continue
        elif gap >= target_gap * 0.6 or is_strong:
            selected.append(t)
        elif candidate.confidence >= config.min_timing_confidence:
            selected.append(t)
            # The accepted event still advances the gap reference: without
            # this the next candidate is measured against a stale last_time,
            # which can admit events closer than min_gap.
            last_time = t
            if len(selected) >= config.max_timings:
                break
            continue

        last_time = t
        if len(selected) >= config.max_timings:
            break

    return selected


def _is_better_dense_event(
    challenger: TimingCandidate,
    incumbent: TimingCandidate,
) -> bool:
    """Decide whether a too-close challenger should replace the last selection.

    Mirrors the classic selector's dense-event picker: a challenger wins only
    when it is the musically stronger event (strong beat over weak, beat over
    offbeat onset, or clearly higher confidence). Equal-strength events never
    replace each other, so uniform grids select at the target density instead
    of collapsing to a single sliding event.
    """
    if challenger.phase == "strong" and incumbent.phase != "strong":
        return True
    if (
        challenger.source == "beat"
        and incumbent.source != "beat"
        and challenger.confidence >= incumbent.confidence - 0.04
    ):
        return True
    if challenger.confidence > incumbent.confidence + 0.08:
        return True
    return False


def _build_phrase_gap_lookup(
    phrase_info: list[PhraseInfo],
) -> Any:
    """Return a deterministic (time_ms, min_gap, target_gap) resolver.

    Only activates phrase-aware gaps when the model carries real phrase
    structure (more than the single uniform fallback phrase).
    """
    real_phrases = [
        phrase
        for phrase in phrase_info
        if phrase.expected_density > 0.0
    ]
    if len(real_phrases) <= 1:
        return lambda time_ms, min_gap, target_gap: (min_gap, target_gap)

    mean_density = sum(phrase.expected_density for phrase in real_phrases) / len(real_phrases)
    sorted_phrases = sorted(real_phrases, key=lambda phrase: phrase.start_ms)

    def resolve(time_ms: int, min_gap: int, target_gap: int) -> tuple[int, int]:
        for phrase in sorted_phrases:
            if phrase.contains(time_ms):
                # Phrase-aware relative scale anchored on the preset gaps: a
                # phrase at the map's mean density keeps the preset gaps;
                # denser (intensify) phrases tighten, sparser (recover/
                # release) phrases open up. The band is bounded so every
                # selection stays playable for the difficulty preset.
                scale = clamp(mean_density / max(phrase.expected_density, 0.01), 0.6, 1.4)
                return (
                    max(60, int(round(min_gap * scale))),
                    max(90, int(round(target_gap * scale))),
                )
        return min_gap, target_gap

    return resolve


def _build_selected_events(
    selected_times: list[int],
    all_candidates: list[TimingCandidate],
    model: RhythmModel,
) -> list[SelectedEvent]:
    """Build SelectedEvent objects from selected timing times."""
    cand_by_time: dict[int, TimingCandidate] = {c.time_ms: c for c in all_candidates}
    events: list[SelectedEvent] = []

    for time_ms in selected_times:
        cand = cand_by_time.get(time_ms)
        if cand is not None:
            src: SelectedEventSource = cand.source  # type: ignore
            events.append(
                SelectedEvent(
                    time_ms=time_ms,
                    source=src,
                    strength=cand.strength,
                    energy=model.analysis.energy_at(time_ms),
                    confidence=cand.confidence,
                    is_emphasis=cand.phase == "strong" or cand.strength >= model.preset.strong_beat_threshold,
                )
            )
        else:
            conf = tq.compute_timing_confidence(
                time_ms, model.analysis,
                density_targets=model.density_targets,
            )
            events.append(
                SelectedEvent(
                    time_ms=time_ms,
                    source="beat",
                    strength=0.4,
                    energy=model.analysis.energy_at(time_ms),
                    confidence=conf,
                    is_emphasis=False,
                )
            )

    return events
