from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from librosa import onset as librosa_onset
from librosa import frames_to_time as librosa_frames_to_time

from .rhythm_models import (
    BpmRegion,
    EnhancedAudioFeatures,
    SubdivisionInfo,
    SubdivisionLevel,
)
from ..models import AudioAnalysis, TimedStrength
from ..utils import clamp, round_ms


@dataclass(frozen=True)
class MultiLayerConfig:
    """Tunable parameters for multi-layer rhythm analysis."""

    flux_sample_rate: int = 22050
    flux_hop_length: int = 512
    bpm_window_ms: int = 8000
    bpm_window_step_ms: int = 2000
    bpm_search_start: tuple[float, ...] = (60.0, 90.0, 120.0, 140.0, 170.0)
    subdivision_window_ms: int = 4000
    subdivision_step_ms: int = 2000
    min_subdivision_confidence: float = 0.45
    eighth_note_threshold: float = 0.50
    sixteenth_note_threshold: float = 0.72
    max_bpm_regions: int = 20


DEFAULT_MULTI_LAYER_CONFIG = MultiLayerConfig()


def extract_enhanced_features(
    samples: np.ndarray,
    sample_rate: int,
    duration_ms: int,
    beats: list[TimedStrength],
    onsets: list[TimedStrength],
    config: MultiLayerConfig = DEFAULT_MULTI_LAYER_CONFIG,
) -> EnhancedAudioFeatures:
    """Extract multi-layer features from raw audio samples.

    All computations are deterministic (no unseeded randomness).
    """
    # 1. Spectral flux (onset strength envelope) at higher resolution
    spectral_flux = librosa_onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=config.flux_hop_length,
        aggregate=np.mean,
    )
    flux_frame_count = len(spectral_flux)
    flux_times_ms = [
        round_ms(
            librosa_frames_to_time(i, sr=sample_rate, hop_length=config.flux_hop_length)
        )
        for i in range(flux_frame_count)
    ]

    # Normalize spectral flux
    flux_max = float(np.max(spectral_flux)) if spectral_flux.size > 0 else 1.0
    if flux_max > 1e-8:
        spectral_flux = np.clip(spectral_flux / flux_max, 0.0, 1.0)

    # 2. Multi-band onset strength (simulated via different onset parameters)
    # Use different aggregate functions to get different "views" of onset energy
    flux_median = librosa_onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=config.flux_hop_length,
        aggregate=np.median,
    )
    if flux_max > 1e-8:
        flux_median = np.clip(flux_median / flux_max, 0.0, 1.0)

    flux_max_agg = librosa_onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=config.flux_hop_length,
        aggregate=np.max,
    )
    if flux_max > 1e-8:
        flux_max_agg = np.clip(flux_max_agg / flux_max, 0.0, 1.0)

    multi_band_onsets = {
        "mean_aggregate": spectral_flux.tolist(),
        "median_aggregate": flux_median.tolist(),
        "max_aggregate": flux_max_agg.tolist(),
    }

    # 3. Local BPM estimation in sliding windows
    local_bpm_estimates: list[tuple[int, float, float]] = []
    window_frames = int(config.bpm_window_ms * sample_rate / 1000)
    step_frames = int(config.bpm_window_step_ms * sample_rate / 1000)

    # Use the onset strength envelope for local BPM estimation
    onset_envelope = librosa_onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=1024,
        aggregate=np.median,
    )
    onset_envelope_max = float(np.max(onset_envelope)) if onset_envelope.size > 0 else 1.0
    if onset_envelope_max > 1e-8:
        onset_envelope = np.clip(onset_envelope / onset_envelope_max, 0.0, 1.0)

    for window_start in range(0, duration_ms, config.bpm_window_step_ms):
        window_end = min(window_start + config.bpm_window_ms, duration_ms)
        if window_end - window_start < 3000:
            break

        # Find local beats within this window
        window_beats = [
            beat for beat in beats
            if window_start <= beat.time_ms < window_end
        ]
        window_onsets = [
            onset for onset in onsets
            if window_start <= onset.time_ms < window_end
        ]

        if len(window_beats) < 4:
            continue

        # Compute local BPM from inter-beat intervals
        intervals = [
            window_beats[i + 1].time_ms - window_beats[i].time_ms
            for i in range(len(window_beats) - 1)
            if window_beats[i + 1].time_ms > window_beats[i].time_ms
        ]

        if not intervals:
            continue

        # Median interval, convert to BPM
        median_interval = float(np.median(intervals))
        if median_interval <= 0:
            continue

        local_bpm = 60000.0 / median_interval

        # Compute confidence: consistency of intervals
        if len(intervals) >= 3:
            interval_std = float(np.std(intervals))
            interval_mean = float(np.mean(intervals))
            cv = interval_std / max(interval_mean, 1.0)  # coefficient of variation
            confidence = clamp(1.0 - cv * 0.5, 0.0, 1.0)
        else:
            confidence = 0.3

        # Also check onset density for cross-validation
        onset_density = len(window_onsets) / max(1, (window_end - window_start) / 1000)
        onset_density_score = clamp(onset_density / 8.0, 0.0, 1.0)

        combined_confidence = confidence * 0.6 + onset_density_score * 0.4

        window_mid = (window_start + window_end) // 2
        local_bpm_estimates.append(
            (window_mid, round(local_bpm, 1), round(combined_confidence, 4))
        )

    # 4. Tempo stability
    if len(local_bpm_estimates) >= 3:
        bpms = [item[1] for item in local_bpm_estimates]
        bpm_mean = float(np.mean(bpms))
        bpm_std = float(np.std(bpms))
        if bpm_mean > 0:
            tempo_stability = clamp(1.0 - (bpm_std / bpm_mean) * 1.5, 0.0, 1.0)
        else:
            tempo_stability = 0.0
    else:
        tempo_stability = 1.0  # not enough data to judge instability

    return EnhancedAudioFeatures(
        spectral_flux=spectral_flux.tolist(),
        spectral_flux_times_ms=flux_times_ms,
        multi_band_onset_strengths=multi_band_onsets,
        local_bpm_estimates=local_bpm_estimates,
        tempo_stability=round(tempo_stability, 4),
    )


def compute_bpm_regions(
    beats: list[TimedStrength],
    onsets: list[TimedStrength],
    duration_ms: int,
    config: MultiLayerConfig = DEFAULT_MULTI_LAYER_CONFIG,
) -> list[BpmRegion]:
    """Divide the song into regions with consistent local BPM."""
    if not beats:
        return []

    regions: list[BpmRegion] = []
    window_size = config.bpm_window_ms
    step_size = config.bpm_window_step_ms

    for window_start in range(0, duration_ms, step_size):
        window_end = min(window_start + window_size, duration_ms)
        if window_end - window_start < 3000:
            continue

        window_beats = [
            beat for beat in beats
            if window_start <= beat.time_ms < window_end
        ]

        if len(window_beats) < 4:
            continue

        intervals = [
            window_beats[i + 1].time_ms - window_beats[i].time_ms
            for i in range(len(window_beats) - 1)
            if window_beats[i + 1].time_ms > window_beats[i].time_ms
        ]

        if not intervals:
            continue

        median_interval = float(np.median(intervals))
        if median_interval <= 0:
            continue

        local_bpm = 60000.0 / median_interval

        # Confidence based on interval consistency
        if len(intervals) >= 3:
            interval_std = float(np.std(intervals))
            interval_mean = float(np.mean(intervals))
            cv = interval_std / max(interval_mean, 1.0)
            confidence = clamp(1.0 - cv * 0.5, 0.0, 1.0)
        else:
            confidence = 0.3

        regions.append(
            BpmRegion(
                start_ms=window_start,
                end_ms=window_end,
                bpm=round(local_bpm, 1),
                confidence=round(confidence, 4),
                beat_count=len(window_beats),
            )
        )

    # Merge adjacent similar BPM regions
    if len(regions) >= 2:
        merged: list[BpmRegion] = [regions[0]]
        for region in regions[1:]:
            last = merged[-1]
            bpm_diff = abs(region.bpm - last.bpm)
            if bpm_diff < 5.0 and region.confidence > 0.4 and last.confidence > 0.4:
                # Merge by extending the last region
                new_confidence = (last.confidence + region.confidence) / 2
                merged[-1] = BpmRegion(
                    start_ms=last.start_ms,
                    end_ms=region.end_ms,
                    bpm=(last.bpm + region.bpm) / 2,
                    confidence=round(new_confidence, 4),
                    beat_count=last.beat_count + region.beat_count,
                )
            else:
                merged.append(region)
        regions = merged

    # Limit regions
    if len(regions) > config.max_bpm_regions:
        stride = len(regions) // config.max_bpm_regions
        regions = regions[::stride][: config.max_bpm_regions]

    return regions


def _beat_length_to_subdivision(beat_length_ms: float) -> int:
    """Estimate the subdivision count per beat from typical BPM beat lengths."""
    if beat_length_ms <= 0:
        return 4
    # For common bpms: 60bpm=1000ms, 120bpm=500ms, 180bpm=333ms
    if beat_length_ms >= 800:
        return 2  # half notes for very slow
    if beat_length_ms >= 400:
        return 4  # quarter notes
    if beat_length_ms >= 250:
        return 8  # eighth notes
    return 16  # sixteenth notes for fast


def detect_subdivisions(
    analysis: AudioAnalysis,
    beats: list[TimedStrength],
    onsets: list[TimedStrength],
    duration_ms: int,
    config: MultiLayerConfig = DEFAULT_MULTI_LAYER_CONFIG,
) -> list[SubdivisionInfo]:
    """Detect the most appropriate subdivision level across the song.

    Returns per-region subdivision information.
    """
    if not beats:
        return []

    subdivisions: list[SubdivisionInfo] = []
    global_beat_interval = _median_beat_interval(beats)

    if global_beat_interval <= 0:
        return []

    window_size = config.subdivision_window_ms
    step_size = config.subdivision_step_ms

    for window_start in range(0, duration_ms, step_size):
        window_end = min(window_start + window_size, duration_ms)
        window_mid = (window_start + window_end) // 2

        window_onsets = [
            onset for onset in onsets
            if window_start <= onset.time_ms < window_end
        ]

        if not window_onsets:
            continue

        # Test each subdivision level
        levels: list[SubdivisionLevel] = ["half", "quarter", "eighth", "sixteenth"]
        best_level: SubdivisionLevel = "quarter"
        best_score = -1.0
        best_grid: list[int] = []

        for level in levels:
            grid = _build_subdivision_grid(
                window_start, window_end, global_beat_interval, level
            )
            if not grid:
                continue

            score = _score_subdivision_grid(grid, window_onsets)
            if score > best_score:
                best_score = score
                best_level = level
                best_grid = grid

        if best_score >= config.min_subdivision_confidence:
            subdivisions.append(
                SubdivisionInfo(
                    start_ms=window_start,
                    end_ms=window_end,
                    level=best_level,
                    confidence=round(best_score, 4),
                    grid_times_ms=best_grid,
                    average_alignment_score=round(
                        _compute_alignment_score(best_grid, window_onsets), 4
                    ),
                )
            )

    return subdivisions


def _median_beat_interval(beats: list[TimedStrength]) -> float:
    """Compute the median interval between consecutive beats in ms."""
    if len(beats) < 2:
        return 0.0
    intervals = [
        beats[i + 1].time_ms - beats[i].time_ms
        for i in range(len(beats) - 1)
        if beats[i + 1].time_ms > beats[i].time_ms
    ]
    if not intervals:
        return 0.0
    return float(np.median(intervals))


def _build_subdivision_grid(
    start_ms: int,
    end_ms: int,
    beat_interval_ms: float,
    level: SubdivisionLevel,
) -> list[int]:
    """Build a grid of timing points at the specified subdivision level."""
    divisions = {"half": 2, "quarter": 4, "eighth": 8, "sixteenth": 16}
    div_count = divisions.get(level, 4)
    step = beat_interval_ms / (div_count / 4)  # quarter = 1 step per beat
    if step <= 0:
        return []

    # Find first beat-aligned time
    first_time = start_ms
    offset = first_time % beat_interval_ms if beat_interval_ms > 0 else 0
    grid_start = first_time - offset

    grid: list[int] = []
    t = grid_start
    while t < end_ms:
        if t >= start_ms:
            grid.append(int(round(t)))
        t += step

    return grid


def _score_subdivision_grid(
    grid: list[int],
    onsets: list[TimedStrength],
    alignment_tolerance_ms: int = 30,
) -> float:
    """Score how well a subdivision grid aligns with detected onsets."""
    if not grid or not onsets:
        return 0.0

    # For each grid point, check if there's a nearby onset
    hit_count = 0
    for grid_time in grid:
        for onset in onsets:
            if abs(onset.time_ms - grid_time) <= alignment_tolerance_ms:
                hit_count += 1
                break

    coverage = hit_count / max(1, len(grid))
    onset_density = len(onsets) / max(1, grid[-1] - grid[0]) * 1000

    # A good subdivision level has many hits without being too dense
    score = coverage * 0.7 + min(onset_density / 15.0, 1.0) * 0.3
    return float(clamp(score, 0.0, 1.0))


def _compute_alignment_score(
    grid: list[int],
    onsets: list[TimedStrength],
    tolerance_ms: int = 50,
) -> float:
    """Compute average alignment score between grid points and nearest onsets."""
    if not grid or not onsets:
        return 0.0

    total_deviation = 0.0
    measured = 0

    for grid_time in grid:
        distances = [abs(grid_time - o.time_ms) for o in onsets]
        min_dist = min(distances) if distances else tolerance_ms
        if min_dist <= tolerance_ms:
            total_deviation += 1.0 - (min_dist / tolerance_ms)
            measured += 1

    return total_deviation / max(1, measured)


def compute_tempo_confidence(
    bpm_regions: list[BpmRegion],
    beats: list[TimedStrength],
    duration_ms: int,
) -> float:
    """Compute an overall tempo confidence score (0-1)."""
    if not beats:
        return 0.0

    # Confidence from BPM region consistency
    region_confidence = (
        float(np.mean([r.confidence for r in bpm_regions])) if bpm_regions else 0.0
    )

    # Confidence from beat coverage
    if len(beats) >= 2 and duration_ms > 0:
        beat_span = beats[-1].time_ms - beats[0].time_ms
        beat_coverage = beat_span / max(1, duration_ms)
    else:
        beat_coverage = 0.0

    # Confidence from beat regularity
    intervals = [
        beats[i + 1].time_ms - beats[i].time_ms
        for i in range(len(beats) - 1)
        if beats[i + 1].time_ms > beats[i].time_ms
    ]
    if intervals:
        cv = float(np.std(intervals)) / max(float(np.mean(intervals)), 1.0)
        regularity = clamp(1.0 - cv * 0.3, 0.0, 1.0)
    else:
        regularity = 0.0

    return clamp(
        region_confidence * 0.4 + beat_coverage * 0.3 + regularity * 0.3,
        0.0,
        1.0,
    )
