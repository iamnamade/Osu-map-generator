from __future__ import annotations

import math

from ..difficulty.common import clamp, mean
from ..difficulty.loader import LoadedDifficultyMap
from .models import FatigueCurve, FatigueSample, ReplayPlayerProfile, SectionReplayResult

_REST_GAP_MS = 900.0
_RECOVERY_EPISODE_HIGH = 0.5
_RECOVERY_EPISODE_LOW = 0.3


def simulate_fatigue(
    beatmap: LoadedDifficultyMap,
    player: ReplayPlayerProfile,
    *,
    bpm: float,
    sections: list[SectionReplayResult],
) -> FatigueCurve:
    """Model fatigue accumulation and recovery across the map.

    Fatigue grows from dense spacing, high cursor velocity, large jumps, and
    high BPM; it gradually recovers during rests (gaps long enough to recover).
    """
    positioned = [item for item in beatmap.objects if item.is_positioned]
    samples: list[FatigueSample] = []
    if not positioned:
        return FatigueCurve(samples=[], average=0.0, peak=0.0, recovery_episodes=0)

    bpm_factor = clamp(bpm / 120.0, 0.5, 2.2) if bpm and bpm > 0 else 1.0
    fatigue = 0.0
    peak = 0.0
    recovery_episodes = 0
    was_high = False

    for index, item in enumerate(positioned):
        previous = positioned[index - 1] if index else None
        gap = (
            item.time - previous.time
            if previous is not None
            else beatmap.approach_time_ms
        )
        if gap >= _REST_GAP_MS:
            fatigue = max(0.0, fatigue - player.recovery_speed * 0.28)
        else:
            density_demand = clamp(
                1.0 - (gap / max(1.0, beatmap.approach_time_ms)) * 1.05,
                0.0,
                1.0,
            )
            velocity_demand = 0.0
            jump_demand = 0.0
            if previous is not None:
                distance = math.hypot(
                    float(item.x) - float(previous.x),
                    float(item.y) - float(previous.y),
                )
                velocity = distance / (gap / 1000.0)
                velocity_demand = clamp(
                    velocity / max(1.0, player.cursor_speed_pps),
                    0.0,
                    1.0,
                )
                jump_demand = clamp(distance / 350.0, 0.0, 1.0)
            demand = density_demand * 0.4 + velocity_demand * 0.35 + jump_demand * 0.25
            fatigue += player.fatigue_growth * bpm_factor * demand * 0.055
        fatigue = clamp(fatigue, 0.0, 1.0)

        if fatigue >= _RECOVERY_EPISODE_HIGH and not was_high:
            was_high = True
        elif fatigue < _RECOVERY_EPISODE_LOW and was_high:
            was_high = False
            recovery_episodes += 1

        samples.append(
            FatigueSample(
                time_ms=item.time,
                fatigue=round(fatigue, 4),
                section_label=_section_label_at(sections, item.time),
            )
        )
        peak = max(peak, fatigue)

    average = mean([sample.fatigue for sample in samples])
    return FatigueCurve(
        samples=samples,
        average=round(average, 4),
        peak=round(peak, 4),
        recovery_episodes=recovery_episodes,
    )


def _section_label_at(
    sections: list[SectionReplayResult],
    time_ms: int,
) -> str:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section.label
    return ""


def fatigue_at(samples: list[FatigueSample], time_ms: int) -> float:
    """Fatigue value for a given time (clamped to the sample timeline)."""
    if not samples:
        return 0.0
    for sample in samples:
        if sample.time_ms >= time_ms:
            return sample.fatigue
    return samples[-1].fatigue
