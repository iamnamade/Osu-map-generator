from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .multi_layer_analysis import _median_beat_interval
from .rhythm_models import PhraseInfo, PhraseLabel
from ..models import AudioAnalysis, EnergyFrame
from ..utils import clamp


@dataclass(frozen=True)
class DensityConfig:
    """Tunable parameters for rhythm density modeling."""

    density_window_ms: int = 3000
    density_step_ms: int = 500
    min_density: float = 1.0  # objects per second minimum (aggressive floor to prevent dead zones)
    max_density: float = 5.0  # objects per second maximum (raised for hard density)
    energy_floor: float = 0.03
    energy_ceiling: float = 0.72  # lowered so high-energy sections get max density sooner
    silent_energy_threshold: float = 0.06
    silent_min_duration_ms: int = 2500
    density_smoothing_passes: int = 2


DEFAULT_DENSITY_CONFIG = DensityConfig()


def compute_density_targets(
    energy_frames: list[EnergyFrame],
    duration_ms: int,
    bpm: float,
    phrase_info: list[PhraseInfo] | None = None,
    config: DensityConfig = DEFAULT_DENSITY_CONFIG,
) -> list[tuple[int, float]]:
    """Compute target density (objects per second) for each point in time.

    Returns list of (time_ms, target_density) pairs.
    """
    if not energy_frames:
        return _uniform_density(duration_ms, bpm, config)

    density_targets: list[tuple[int, float]] = []

    for time_ms in range(0, duration_ms, config.density_step_ms):
        # Average energy in the window around this time
        window_start = max(0, time_ms - config.density_window_ms // 2)
        window_end = min(duration_ms, time_ms + config.density_window_ms // 2)

        window_energy = [
            frame.value
            for frame in energy_frames
            if window_start <= frame.time_ms < window_end
        ]

        if not window_energy:
            avg_energy = 0.0
        else:
            avg_energy = float(np.mean(window_energy))

        # Map energy to density
        if avg_energy <= config.energy_floor:
            density = config.min_density
        elif avg_energy >= config.energy_ceiling:
            density = config.max_density
        else:
            # Linear interpolation
            normalized = (avg_energy - config.energy_floor) / (
                config.energy_ceiling - config.energy_floor
            )
            # Use cubic curve for more contrast
            density = config.min_density + (config.max_density - config.min_density) * (
                normalized**0.7
            )

        density_targets.append((time_ms, round(clamp(density, config.min_density, config.max_density), 4)))

    # Apply phrase-aware adjustments
    if phrase_info:
        density_targets = _apply_phrase_density_adjustments(
            density_targets, phrase_info, config
        )

    # Smooth
    for _ in range(config.density_smoothing_passes):
        density_targets = _smooth_density(density_targets)

    return density_targets


def _uniform_density(
    duration_ms: int, bpm: float, config: DensityConfig
) -> list[tuple[int, float]]:
    """Create uniform density targets based on BPM."""
    if bpm > 0:
        base_density = bpm / 60.0  # beats per second
    else:
        base_density = 2.0

    density = clamp(base_density, config.min_density, config.max_density)
    return [
        (time_ms, density)
        for time_ms in range(0, duration_ms, config.density_step_ms)
    ]


def _apply_phrase_density_adjustments(
    targets: list[tuple[int, float]],
    phrases: list[PhraseInfo],
    config: DensityConfig,
) -> list[tuple[int, float]]:
    """Adjust density targets based on phrase characteristics."""
    if not phrases:
        return targets

    adjusted: list[tuple[int, float]] = []
    for time_ms, density in targets:
        phrase = _find_phrase_at(phrases, time_ms)
        if phrase is not None:
            # Blend target density with phrase-expected density
            blend = clamp(phrase.density_flexibility, 0.0, 1.0)
            expected = phrase.expected_density
            adjusted_density = density * (1 - blend) + expected * blend
            adjusted.append((time_ms, round(clamp(adjusted_density, config.min_density, config.max_density), 4)))
        else:
            adjusted.append((time_ms, density))

    return adjusted


def _smooth_density(
    targets: list[tuple[int, float]],
) -> list[tuple[int, float]]:
    """Apply simple moving average smoothing to density targets."""
    if len(targets) < 3:
        return targets

    smoothed: list[tuple[int, float]] = []
    for i in range(len(targets)):
        indices = [max(0, i - 1), i, min(len(targets) - 1, i + 1)]
        window = [targets[j][1] for j in indices]
        avg = float(np.mean(window))
        smoothed.append((targets[i][0], round(avg, 4)))

    return smoothed


def detect_silent_regions(
    energy_frames: list[EnergyFrame],
    duration_ms: int,
    config: DensityConfig = DEFAULT_DENSITY_CONFIG,
) -> list[tuple[int, int]]:
    """Detect regions of genuine silence where no objects should be placed."""
    if not energy_frames:
        return []

    silent_regions: list[tuple[int, int]] = []
    current_silent: list[EnergyFrame] = []

    for frame in energy_frames:
        if frame.value <= config.silent_energy_threshold:
            current_silent.append(frame)
        else:
            if current_silent:
                span_ms = current_silent[-1].time_ms - current_silent[0].time_ms
                if span_ms >= config.silent_min_duration_ms:
                    silent_regions.append(
                        (current_silent[0].time_ms, current_silent[-1].time_ms)
                    )
            current_silent = []

    # Check trailing silent region
    if current_silent:
        span_ms = current_silent[-1].time_ms - current_silent[0].time_ms
        if span_ms >= config.silent_min_duration_ms:
            silent_regions.append(
                (current_silent[0].time_ms, current_silent[-1].time_ms)
            )

    return silent_regions


def estimate_target_gap_from_density(density: float) -> int:
    """Convert a density target (objects/sec) to a target gap in ms."""
    if density <= 0:
        return 1000
    return int(round(1000.0 / density))


def compute_max_allowed_gap(
    energy_frames: list[EnergyFrame],
    start_ms: int,
    end_ms: int,
    max_gap_ms: int,
    config: DensityConfig = DEFAULT_DENSITY_CONFIG,
) -> int:
    """Compute the maximum allowed gap in a region based on energy.

    High-energy regions get shorter max gaps to prevent them from feeling empty.
    """
    window_energy = [
        frame.value
        for frame in energy_frames
        if start_ms <= frame.time_ms < end_ms
    ]

    if not window_energy:
        return max_gap_ms

    avg_energy = float(np.mean(window_energy))

    # During active audio sections (above energy ceiling), gaps must be very
    # tight to prevent dead zones where the player stares at an empty screen.
    if avg_energy > config.energy_ceiling:
        return int(max_gap_ms * 0.35)
    # Above the midpoint: aggressive tightening
    if avg_energy > config.energy_floor + (config.energy_ceiling - config.energy_floor) * 0.5:
        return int(max_gap_ms * 0.55)
    # Low energy: still apply a strict cap to avoid long idle gaps
    if avg_energy > config.energy_floor:
        return int(max_gap_ms * 0.7)

    return max_gap_ms


def _find_phrase_at(phrases: list[PhraseInfo], time_ms: int) -> PhraseInfo | None:
    """Find the phrase that contains the given time."""
    for phrase in phrases:
        if phrase.contains(time_ms):
            return phrase
    return None


def build_phrase_density_info(
    sections_info: list[PhraseInfo] | None,
    density_targets: list[tuple[int, float]],
    config: DensityConfig = DEFAULT_DENSITY_CONFIG,
) -> list[PhraseInfo]:
    """Build phrase density info from existing sections or from energy analysis."""
    if sections_info:
        return sections_info

    # Without section info, create a simple uniform phrase
    if not density_targets:
        return []

    avg_density = float(np.mean([d for _, d in density_targets]))
    return [
        PhraseInfo(
            start_ms=density_targets[0][0],
            end_ms=density_targets[-1][0],
            label="unknown",
            confidence=0.5,
            expected_density=avg_density,
            density_flexibility=0.8,
            min_gap_ms=100,
            target_gap_ms=int(round(1000.0 / max(avg_density, 0.3))),
        )
    ]
