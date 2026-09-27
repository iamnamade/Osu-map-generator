from __future__ import annotations

import math
import random

from ..difficulty.common import clamp, mean, standard_deviation
from ..difficulty.loader import LoadedDifficultyMap
from .fatigue import fatigue_at
from .models import (
    FatigueCurve,
    HitEvent,
    HitSimulationResult,
    ReplayPlayerProfile,
)

_HIT_VALUES: dict[str, float] = {
    "perfect": 1.0,
    "great": 0.95,
    "good": 0.8,
    "meh": 0.5,
    "miss": 0.0,
}
_RHYTHM_WINDOW = 6


def simulate_hits(
    beatmap: LoadedDifficultyMap,
    player: ReplayPlayerProfile,
    rng: random.Random,
    fatigue: FatigueCurve,
    *,
    bpm: float,
) -> HitSimulationResult:
    """Simulate per-object hit windows for one deterministic playthrough.

    Every object receives an expected timing offset drawn from a normal
    distribution whose width depends on the player's reaction time and rhythm
    precision, plus the local demand (density, cursor velocity, aim distance,
    rhythm complexity, and accumulated fatigue). The distribution widens with
    BPM-scaled strain. The sampled run produces the detailed hit events; the
    expected accuracy/misses/full-combo statistics are computed analytically
    from the same per-object distributions, keeping the report stable.
    """
    positioned = [item for item in beatmap.objects if item.is_positioned]
    total = max(1, len(positioned))
    window_unit = 16.0 * (1.3 - player.rhythm_precision * 0.6)
    sigma_base = (player.reaction_time_ms / 4.0) * (1.15 - player.rhythm_precision * 0.3)
    bpm_factor = clamp(bpm / 120.0, 0.6, 2.0) if bpm and bpm > 0 else 1.0
    approach = max(1, beatmap.approach_time_ms)

    events: list[HitEvent] = []
    result_counts: dict[str, int] = {"perfect": 0, "great": 0, "good": 0, "meh": 0, "miss": 0}
    expected_value_sum = 0.0
    expected_miss_sum = 0.0
    log_survival = 0.0
    successful_offsets: list[float] = []
    peak_stress_ms = 0
    peak_demand = -1.0

    for index, item in enumerate(positioned):
        previous = positioned[index - 1] if index else None
        gap = item.time - previous.time if previous is not None else approach

        density_demand = clamp(1.0 - (min(gap, approach) / approach) * 1.05, 0.0, 1.0)
        velocity_demand = 0.0
        aim_demand = 0.0
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
            aim_demand = clamp(distance / 350.0, 0.0, 1.0)
        rhythm_demand = _rhythm_complexity(positioned, index, _RHYTHM_WINDOW)
        fatigue_value = fatigue_at(fatigue.samples, item.time)

        demand = clamp(
            density_demand * 0.30
            + velocity_demand * 0.25
            + aim_demand * 0.20
            + rhythm_demand * 0.15
            + fatigue_value * 0.10,
            0.0,
            1.0,
        )
        if demand > peak_demand:
            peak_demand = demand
            peak_stress_ms = item.time

        sigma = sigma_base * (0.5 + demand) * bpm_factor
        offset = rng.gauss(0.0, sigma)
        physical_late = max(0.0, velocity_demand - 1.0)
        if physical_late > 0.0:
            offset += physical_late * 90.0

        result = _result_from_offset(abs(offset), window_unit)
        # Analytic probabilities from the offset distribution (deterministic).
        w1, w4 = window_unit, 4.0 * window_unit
        timing_miss_p = 2.0 * _tail_probability(w4, sigma)
        aim_miss_p = clamp(demand * (1.0 - player.aim_precision) * 0.55, 0.0, 0.8)
        total_miss_p = clamp(
            1.0 - (1.0 - timing_miss_p) * (1.0 - aim_miss_p),
            0.0,
            0.95,
        )
        # Sample one concrete result for the detailed replay run.
        if result != "miss" and rng.random() < aim_miss_p * 0.85:
            result = "miss" if rng.random() < 0.4 else "meh"

        result_counts[result] += 1
        if result != "miss":
            successful_offsets.append(offset)
        expected_value_sum += (1.0 - total_miss_p) * _timing_expected_value(
            window_unit,
            sigma,
        )
        expected_miss_sum += total_miss_p
        log_survival += math.log(max(1e-9, 1.0 - total_miss_p))

        events.append(
            HitEvent(
                object_id=item.id,
                object_type=item.object_type,
                time_ms=item.time,
                offset_ms=round(offset, 2),
                result=result,
                demand=round(demand, 4),
                fatigue=round(fatigue_value, 4),
            )
        )

    expected_accuracy = clamp(expected_value_sum / total, 0.0, 1.0)
    expected_misses = clamp(expected_miss_sum, 0.0, float(total))
    full_combo_chance = clamp(math.exp(log_survival), 0.0, 1.0)
    timing_consistency = _timing_consistency(successful_offsets, window_unit, player)

    return HitSimulationResult(
        events=events,
        expected_accuracy=round(expected_accuracy, 4),
        expected_misses=round(expected_misses, 2),
        full_combo_chance=round(full_combo_chance, 4),
        result_counts=result_counts,
        timing_consistency=round(timing_consistency, 4),
        peak_stress_ms=peak_stress_ms,
    )


def _result_from_offset(abs_offset: float, window_unit: float) -> str:
    if abs_offset <= window_unit:
        return "perfect"
    if abs_offset <= 2.0 * window_unit:
        return "great"
    if abs_offset <= 3.0 * window_unit:
        return "good"
    if abs_offset <= 4.0 * window_unit:
        return "meh"
    return "miss"


def _tail_probability(threshold: float, sigma: float) -> float:
    """P(N(0, sigma) > threshold) for a positive threshold."""
    if sigma <= 1e-9:
        return 0.0 if threshold > 0 else 0.5
    return 0.5 * (1.0 - math.erf(threshold / (sigma * math.sqrt(2.0))))


def _timing_expected_value(window_unit: float, sigma: float) -> float:
    """Expected hit value from the timing distribution alone (before aim-miss)."""
    if sigma <= 1e-9:
        return 1.0
    scale = sigma * math.sqrt(2.0)
    p_perfect = math.erf(window_unit / scale)
    p_great = math.erf(2.0 * window_unit / scale) - p_perfect
    p_good = math.erf(3.0 * window_unit / scale) - math.erf(2.0 * window_unit / scale)
    p_meh = math.erf(4.0 * window_unit / scale) - math.erf(3.0 * window_unit / scale)
    survival = p_perfect + p_great + p_good + p_meh
    if survival <= 1e-9:
        return 0.0
    return (
        p_perfect * _HIT_VALUES["perfect"]
        + p_great * _HIT_VALUES["great"]
        + p_good * _HIT_VALUES["good"]
        + p_meh * _HIT_VALUES["meh"]
    ) / survival


def _timing_consistency(
    successful_offsets: list[float],
    window_unit: float,
    player: ReplayPlayerProfile,
) -> float:
    """1.0 when successful hits cluster tightly around the target time."""
    if len(successful_offsets) < 3:
        return player.consistency
    jitter = standard_deviation([abs(value) for value in successful_offsets])
    consistency = 1.0 - jitter / (3.0 * max(window_unit, 1e-6))
    return clamp(consistency * 0.7 + player.consistency * 0.3, 0.0, 1.0)


def _rhythm_complexity(positioned, index: int, window: int) -> float:
    """Local timing irregularity measured against recent average gaps."""
    start = max(0, index - window)
    neighbors = positioned[start : index + 1]
    if len(neighbors) < 3:
        return 0.0
    gaps = [
        neighbors[i + 1].time - neighbors[i].time
        for i in range(len(neighbors) - 1)
        if neighbors[i + 1].time > neighbors[i].time
    ]
    if not gaps:
        return 0.0
    average = mean([float(gap) for gap in gaps])
    if average <= 1e-6:
        return 0.0
    deviation = standard_deviation([float(gap) for gap in gaps])
    return clamp(deviation / average * 1.2, 0.0, 1.0)
