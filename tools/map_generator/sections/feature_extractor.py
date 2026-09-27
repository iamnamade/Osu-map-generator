from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..models import AudioAnalysis, EnergyFrame, TimedStrength


@dataclass(frozen=True)
class BoundaryFeatureSnapshot:
    average_energy: float
    energy_slope: float
    beat_density: float
    onset_density: float
    average_onset_strength: float
    emphasis_ratio: float
    quiet_ratio: float
    high_energy_ratio: float


def extract_boundary_snapshot(
    analysis: AudioAnalysis,
    *,
    start_ms: int,
    end_ms: int,
) -> BoundaryFeatureSnapshot:
    duration_ms = max(1, end_ms - start_ms)
    energy_frames = _frames_in_window(analysis.energy_frames, start_ms, end_ms)
    beats = _markers_in_window(analysis.beats, start_ms, end_ms)
    onsets = _markers_in_window(analysis.onsets, start_ms, end_ms)
    average_energy = (
        sum(frame.value for frame in energy_frames) / len(energy_frames)
        if energy_frames
        else 0.0
    )
    energy_slope = _energy_slope(energy_frames)
    beat_density = len(beats) * 1000 / duration_ms
    onset_density = len(onsets) * 1000 / duration_ms
    average_onset_strength = (
        sum(marker.strength for marker in onsets) / len(onsets) if onsets else 0.0
    )
    emphasis_ratio = _emphasis_ratio(beats, onsets)
    quiet_ratio = _region_ratio(
        start_ms=start_ms,
        end_ms=end_ms,
        regions=[(region.start_ms, region.end_ms) for region in analysis.quiet_regions],
    )
    high_energy_ratio = _region_ratio(
        start_ms=start_ms,
        end_ms=end_ms,
        regions=[
            (region.start_ms, region.end_ms) for region in analysis.high_energy_regions
        ],
    )
    return BoundaryFeatureSnapshot(
        average_energy=average_energy,
        energy_slope=energy_slope,
        beat_density=beat_density,
        onset_density=onset_density,
        average_onset_strength=average_onset_strength,
        emphasis_ratio=emphasis_ratio,
        quiet_ratio=quiet_ratio,
        high_energy_ratio=high_energy_ratio,
    )


def extract_section_statistics(
    analysis: AudioAnalysis,
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, float | str]:
    snapshot = extract_boundary_snapshot(analysis, start_ms=start_ms, end_ms=end_ms)
    first_half = extract_boundary_snapshot(
        analysis,
        start_ms=start_ms,
        end_ms=start_ms + max(1, (end_ms - start_ms) // 2),
    )
    second_half = extract_boundary_snapshot(
        analysis,
        start_ms=start_ms + max(1, (end_ms - start_ms) // 2),
        end_ms=end_ms,
    )
    trend_delta = second_half.average_energy - first_half.average_energy
    if trend_delta > 0.06:
        energy_trend = "rising"
    elif trend_delta < -0.06:
        energy_trend = "falling"
    else:
        energy_trend = "steady"

    rhythm_complexity = min(
        1.0,
        (
            abs(snapshot.onset_density - snapshot.beat_density) * 0.18
            + snapshot.average_onset_strength * 0.4
            + abs(snapshot.energy_slope) * 6.0
        ),
    )

    return {
        "averageEnergy": round(snapshot.average_energy, 4),
        "energyTrend": energy_trend,
        "beatDensity": round(snapshot.beat_density, 4),
        "onsetDensity": round(snapshot.onset_density, 4),
        "rhythmComplexity": round(rhythm_complexity, 4),
        "quietRatio": round(snapshot.quiet_ratio, 4),
        "highEnergyRatio": round(snapshot.high_energy_ratio, 4),
        "emphasisRatio": round(snapshot.emphasis_ratio, 4),
    }


def nearest_anchor_time(
    analysis: AudioAnalysis,
    *,
    time_ms: int,
    max_distance_ms: int,
) -> tuple[int, str, int] | None:
    candidates: list[tuple[int, str, int, float]] = []
    for marker in analysis.beats:
        distance_ms = abs(marker.time_ms - time_ms)
        if distance_ms <= max_distance_ms:
            candidates.append((marker.time_ms, "beat", distance_ms, marker.strength))
    for marker in analysis.onsets:
        distance_ms = abs(marker.time_ms - time_ms)
        if distance_ms <= max_distance_ms:
            candidates.append((marker.time_ms, "onset", distance_ms, marker.strength))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[2], -item[3], item[0], item[1]))
    best_time, best_type, best_distance, _ = candidates[0]
    return best_time, best_type, best_distance


def _frames_in_window(
    frames: Iterable[EnergyFrame],
    start_ms: int,
    end_ms: int,
) -> list[EnergyFrame]:
    return [frame for frame in frames if start_ms <= frame.time_ms < end_ms]


def _markers_in_window(
    markers: Iterable[TimedStrength],
    start_ms: int,
    end_ms: int,
) -> list[TimedStrength]:
    return [marker for marker in markers if start_ms <= marker.time_ms < end_ms]


def _energy_slope(frames: list[EnergyFrame]) -> float:
    if len(frames) < 2:
        return 0.0
    return (frames[-1].value - frames[0].value) / max(1, frames[-1].time_ms - frames[0].time_ms)


def _emphasis_ratio(beats: list[TimedStrength], onsets: list[TimedStrength]) -> float:
    strong_events = [item for item in beats + onsets if item.strength >= 0.7]
    all_events = len(beats) + len(onsets)
    return len(strong_events) / all_events if all_events else 0.0


def _region_ratio(
    *,
    start_ms: int,
    end_ms: int,
    regions: list[tuple[int, int]],
) -> float:
    duration_ms = max(1, end_ms - start_ms)
    covered_ms = 0
    for region_start, region_end in regions:
        overlap_start = max(start_ms, region_start)
        overlap_end = min(end_ms, region_end)
        if overlap_end > overlap_start:
            covered_ms += overlap_end - overlap_start
    return covered_ms / duration_ms
