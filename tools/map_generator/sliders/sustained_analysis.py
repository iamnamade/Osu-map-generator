from __future__ import annotations

import math
import numpy as np
from typing import Any

from .slider_models import SustainedAnalysis


def analyze_sustained_content(
    samples: np.ndarray,
    sample_rate: int,
    frame_ms: int = 40,
    hop_ms: int = 10,
    low_cutoff_hz: float = 80.0,
    high_cutoff_hz: float = 8000.0,
) -> SustainedAnalysis:
    """Analyze audio for sustained musical content.

    Detects regions where sound is held continuously (vocals, pads, strings,
    synth pads, guitar sustain) by examining spectral flux and energy
    stability across frames. Low spectral flux + high energy = sustained.

    Returns a SustainedAnalysis with sustained regions and frame scores.
    """
    frame_samples = int(sample_rate * frame_ms / 1000)
    hop_samples = int(sample_rate * hop_ms / 1000)
    total_frames = max(1, (len(samples) - frame_samples) // hop_samples + 1)

    if total_frames < 3 or len(samples) < frame_samples:
        return SustainedAnalysis()

    # Compute per-frame RMS energy and spectral flux
    frame_energy: list[float] = []
    frame_spectral_flux: list[float] = []
    frame_times: list[int] = []
    prev_spectrum: np.ndarray | None = None

    for i in range(total_frames):
        start = i * hop_samples
        end = start + frame_samples
        if end > len(samples):
            break

        frame = samples[start:end]
        time_ms = int(start / sample_rate * 1000)
        frame_times.append(time_ms)

        # RMS energy
        rms = float(np.sqrt(np.mean(frame ** 2)))
        frame_energy.append(rms)

        # Spectral flux (simplified: frame-to-frame energy change)
        spectrum = np.abs(np.fft.rfft(frame))
        if prev_spectrum is not None:
            flux = float(np.mean(np.abs(spectrum - prev_spectrum)))
            frame_spectral_flux.append(flux)
        else:
            frame_spectral_flux.append(0.0)
        prev_spectrum = spectrum

    if len(frame_energy) < 3:
        return SustainedAnalysis()

    # Normalize energy
    max_energy = max(frame_energy) if max(frame_energy) > 0 else 1.0
    norm_energy = [e / max_energy for e in frame_energy]

    # Normalize spectral flux
    max_flux = max(frame_spectral_flux) if max(frame_spectral_flux) > 0 else 1.0
    norm_flux = [f / max_flux for f in frame_spectral_flux]

    # Sustained score = energy above threshold AND low spectral flux.
    # Aggressively low thresholds to catch vocal holds, guitar sustain,
    # synth pads, and other sustained musical content as slider candidates.
    energy_threshold = 0.045
    flux_threshold = 0.50
    sustained_frames: list[dict[str, Any]] = []
    sustained_regions: list[dict[str, Any]] = []
    in_region = False
    region_start = 0
    region_total_score = 0.0
    region_count = 0

    for i in range(len(norm_energy)):
        energy = norm_energy[i]
        flux = norm_flux[i]
        is_sustained = energy > energy_threshold and flux < flux_threshold

        sustained_score = 0.0
        if is_sustained:
            # Higher energy + lower flux = more sustained
            sustained_score = energy * (1.0 - min(flux, 0.8) / 0.8)
            sustained_score = min(1.0, sustained_score * 1.5)

        sustained_frames.append({
            "timeMs": frame_times[i],
            "energy": round(energy, 4),
            "spectralFlux": round(flux, 4),
            "sustainedScore": round(sustained_score, 4),
        })

        if is_sustained:
            if not in_region:
                region_start = frame_times[i]
                region_total_score = 0.0
                region_count = 0
                in_region = True
            region_total_score += sustained_score
            region_count += 1
        elif in_region:
            # End region if gap > 150ms
            gap = frame_times[i] - frame_times[i - 1] if i > 0 else 0
            if gap > 150:
                in_region = False
                if region_count >= 3:
                    sustained_regions.append({
                        "startMs": region_start,
                        "endMs": frame_times[i - 1],
                        "averageScore": round(region_total_score / max(1, region_count), 4),
                    })

    if in_region and region_count >= 3:
        sustained_regions.append({
            "startMs": region_start,
            "endMs": frame_times[-1],
            "averageScore": round(region_total_score / max(1, region_count), 4),
        })

    avg_sustained = (
        sum(f["sustainedScore"] for f in sustained_frames) / max(1, len(sustained_frames))
    )
    sustained_ratio = (
        sum(f["sustainedScore"] for f in sustained_frames if f["sustainedScore"] > 0.3)
        / max(1, len(sustained_frames))
    )

    return SustainedAnalysis(
        sustained_regions=sustained_regions,
        sustained_frames=sustained_frames,
        average_sustained_energy=avg_sustained,
        sustained_ratio=sustained_ratio,
    )


def get_sustained_score_at(
    sustained: SustainedAnalysis,
    time_ms: int,
    window_ms: int = 100,
) -> float:
    """Get the sustained score at a specific time.

    Averages sustained scores within a window around the given time.
    Returns 0-1 score where >0.3 indicates likely sustained content.
    """
    if not sustained.sustained_frames:
        return 0.0

    half_window = window_ms // 2
    nearby = [
        f["sustainedScore"]
        for f in sustained.sustained_frames
        if abs(f["timeMs"] - time_ms) <= half_window
    ]
    if not nearby:
        return 0.0
    return sum(nearby) / len(nearby)
