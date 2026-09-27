from __future__ import annotations

import numpy as np

from .multi_layer_analysis import _median_beat_interval
from .rhythm_models import (
    RhythmModel,
    TimingCandidate,
    TimingQualityScore,
)
from ..models import AudioAnalysis
from ..utils import clamp


def score_timing_quality(
    model: RhythmModel,
    selected_times_ms: list[int],
) -> TimingQualityScore:
    """Score the overall quality of a set of selected timing points."""
    if not selected_times_ms:
        return TimingQualityScore(
            overall_quality=0.0,
            beat_alignment=0.0,
            onset_alignment=0.0,
            density_consistency=0.0,
            gap_uniformity=0.0,
            subdivision_usage=0.0,
            coverage_ratio=0.0,
            long_gap_count=0,
            rejected_timing_count=0,
            accepted_timing_count=0,
        )

    # 1. Beat alignment
    beat_alignment = _compute_ensemble_alignment(
        selected_times_ms, model.analysis.beats, tolerance_ms=30
    )

    # 2. Onset alignment
    onset_alignment = _compute_ensemble_alignment(
        selected_times_ms, model.analysis.onsets, tolerance_ms=20
    )

    # 3. Density consistency
    density_consistency = _compute_density_consistency(
        selected_times_ms, model.density_targets
    )

    # 4. Gap uniformity (penalize very uneven gaps)
    gaps = [
        selected_times_ms[i + 1] - selected_times_ms[i]
        for i in range(len(selected_times_ms) - 1)
    ]
    if gaps:
        mean_gap = float(np.mean(gaps))
        std_gap = float(np.std(gaps)) if len(gaps) > 1 else 0.0
        if mean_gap > 0:
            cv = std_gap / mean_gap
            gap_uniformity = clamp(1.0 - cv * 0.4, 0.0, 1.0) * 100.0
        else:
            gap_uniformity = 100.0
    else:
        gap_uniformity = 100.0

    # 5. Subdivision usage
    if model.subdivisions:
        subdivision_usage = _compute_subdivision_usage(
            selected_times_ms, model.subdivisions
        )
    else:
        subdivision_usage = 50.0

    # 6. Coverage ratio
    if selected_times_ms and model.analysis.duration_ms > 0:
        span = selected_times_ms[-1] - selected_times_ms[0]
        coverage_ratio = clamp(span / max(1, model.analysis.duration_ms), 0.0, 1.0)
    else:
        coverage_ratio = 0.0

    # 7. Long gap count
    if model.rhythm_config:
        target_gap_ms = getattr(model.rhythm_config, "target_gap_ms", 800)
        long_gap_threshold = max(target_gap_ms * 2.5, 2000)
    else:
        long_gap_threshold = 2000

    long_gap_count = sum(1 for gap in gaps if gap >= long_gap_threshold)

    # Weighted overall
    overall = (
        beat_alignment * 0.25
        + onset_alignment * 0.15
        + density_consistency * 0.20
        + gap_uniformity * 0.10
        + subdivision_usage * 0.15
        + (coverage_ratio * 100.0) * 0.15
    )

    # Penalty for long gaps
    overall -= long_gap_count * 2.0

    return TimingQualityScore(
        overall_quality=round(clamp(overall, 0.0, 100.0), 3),
        beat_alignment=round(beat_alignment, 3),
        onset_alignment=round(onset_alignment, 3),
        density_consistency=round(density_consistency, 3),
        gap_uniformity=round(gap_uniformity, 3),
        subdivision_usage=round(subdivision_usage, 3),
        coverage_ratio=round(coverage_ratio, 4),
        long_gap_count=long_gap_count,
        rejected_timing_count=0,
        accepted_timing_count=len(selected_times_ms),
    )


def compute_timing_confidence(
    time_ms: int,
    analysis: AudioAnalysis,
    beats: list | None = None,
    onsets: list | None = None,
    density_targets: list[tuple[int, float]] | None = None,
) -> float:
    """Compute a confidence score (0-1) for a single timing point."""
    beats = beats or analysis.beats
    onsets = onsets or analysis.onsets

    # Find nearest beat
    beat_distances = [abs(time_ms - b.time_ms) for b in beats] if beats else [999]
    nearest_beat_dist = min(beat_distances) if beat_distances else 999

    # Find nearest onset
    onset_distances = [abs(time_ms - o.time_ms) for o in onsets] if onsets else [999]
    nearest_onset_dist = min(onset_distances) if onset_distances else 999

    # Beat alignment score (0-1)
    if nearest_beat_dist <= 15:
        beat_score = 1.0
    elif nearest_beat_dist <= 30:
        beat_score = 0.9
    elif nearest_beat_dist <= 60:
        beat_score = 0.7
    elif nearest_beat_dist <= 100:
        beat_score = 0.4
    else:
        beat_score = 0.1

    # Onset alignment score (0-1)
    if nearest_onset_dist <= 10:
        onset_score = 1.0
    elif nearest_onset_dist <= 25:
        onset_score = 0.85
    elif nearest_onset_dist <= 50:
        onset_score = 0.6
    elif nearest_onset_dist <= 90:
        onset_score = 0.3
    else:
        onset_score = 0.05

    # Energy contribution
    energy = analysis.energy_at(time_ms)
    energy_score = clamp(energy * 1.5, 0.0, 1.0)

    # Density fit
    density_score = 0.5
    if density_targets:
        target = _interpolate_density_target(density_targets, time_ms)
        if target is not None:
            # Higher confidence when energy matches density expectation
            if energy > 0.5 and target > 0.8:
                density_score = 1.0
            elif energy < 0.2 and target < 0.4:
                density_score = 0.8
            else:
                density_score = 0.6

    confidence = (
        beat_score * 0.35
        + onset_score * 0.25
        + energy_score * 0.20
        + density_score * 0.20
    )

    return round(clamp(confidence, 0.0, 1.0), 4)


def _compute_ensemble_alignment(
    times_ms: list[int],
    events: list,
    tolerance_ms: int,
) -> float:
    """Compute average alignment of times to nearest events."""
    if not times_ms or not events:
        return 50.0

    total_alignment = 0.0
    for t in times_ms:
        distances = [abs(t - e.time_ms) for e in events]
        min_dist = min(distances) if distances else tolerance_ms * 2
        if min_dist <= tolerance_ms:
            alignment = 1.0 - (min_dist / tolerance_ms)
        else:
            alignment = max(0.0, 1.0 - (min_dist - tolerance_ms) / tolerance_ms)
        total_alignment += alignment

    return clamp((total_alignment / len(times_ms)) * 100.0, 0.0, 100.0)


def _compute_density_consistency(
    times_ms: list[int],
    density_targets: list[tuple[int, float]] | None,
) -> float:
    """Score how well actual timing density matches target density."""
    if not times_ms or not density_targets or len(times_ms) < 2:
        return 60.0

    gaps = [
        times_ms[i + 1] - times_ms[i]
        for i in range(len(times_ms) - 1)
    ]
    if not gaps:
        return 60.0

    total_deviation = 0.0
    measurements = 0

    for i, gap in enumerate(gaps):
        midpoint = (times_ms[i] + times_ms[i + 1]) // 2
        target_density = _interpolate_density_target(density_targets, midpoint)
        if target_density is None or target_density <= 0:
            continue

        actual_density = 1000.0 / max(gap, 1)
        expected_density = target_density

        # Relative deviation
        if expected_density > 0:
            deviation = abs(actual_density - expected_density) / expected_density
            score = clamp(1.0 - deviation, 0.0, 1.0)
            total_deviation += score
            measurements += 1

    if measurements == 0:
        return 60.0

    return clamp((total_deviation / measurements) * 100.0, 0.0, 100.0)


def _compute_subdivision_usage(
    times_ms: list[int],
    subdivisions: list,
) -> float:
    """Score how well timings align with detected subdivisions."""
    if not times_ms or not subdivisions:
        return 50.0

    aligned_count = 0
    for t in times_ms:
        for sub in subdivisions:
            if sub.start_ms <= t < sub.end_ms:
                if any(abs(t - gt) <= 30 for gt in sub.grid_times_ms):
                    aligned_count += 1
                break

    ratio = aligned_count / len(times_ms) if times_ms else 0.0
    return clamp(ratio * 100.0, 0.0, 100.0)


def _interpolate_density_target(
    density_targets: list[tuple[int, float]], time_ms: int
) -> float | None:
    """Interpolate the density target at a given time."""
    if not density_targets:
        return None

    if len(density_targets) == 1:
        return density_targets[0][1]

    # Binary search for the surrounding targets
    lo, hi = 0, len(density_targets) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if density_targets[mid][0] <= time_ms:
            lo = mid
        else:
            hi = mid

    if lo == hi or time_ms <= density_targets[lo][0]:
        return density_targets[lo][1]
    if time_ms >= density_targets[hi][0]:
        return density_targets[hi][1]

    # Linear interpolation
    t0, d0 = density_targets[lo]
    t1, d1 = density_targets[hi]
    if t1 == t0:
        return d0

    ratio = (time_ms - t0) / (t1 - t0)
    return d0 + (d1 - d0) * ratio
