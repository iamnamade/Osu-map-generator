from __future__ import annotations

import math

from .common import clamp, mean, normalize
from .loader import LoadedDifficultyMap
from .models import (
    GameplayAnalytics,
    PlayerSimulation,
    ReplaySimulation,
)


def analyze_gameplay(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    aim_score: float,
    reading_score: float,
    rhythm_score: float,
    stamina_score: float,
    recovery_gap_ms: float = 1000.0,
    simulated_playcount: int = 200,
) -> GameplayAnalytics:
    """Estimate miss probability, combo stability, player stress, and
    recovery windows from a deterministic simulated play model.

    The model is purely heuristic and deterministic; it does not attempt to
    reproduce osu! gameplay. It converts per-object reaction/aim/reading
    demand into a per-object miss probability and aggregates the results.

    Extended in Phase 14 with a full deterministic player simulation
    (cursor travel, reaction difficulty, fatigue, reading stress) and a
    replay simulation (full-combo chance, expected accuracy and misses,
    hardest patterns and transitions).
    """
    objects = beatmap.objects
    if not objects:
        empty = GameplayAnalytics(
            estimated_miss_probability=0.0,
            estimated_combo_stability=1.0,
            estimated_player_stress=0.0,
            recovery_window_count=0,
            average_recovery_window_ms=0.0,
            hardest_passage_ms=0,
            simulated_playcount=simulated_playcount,
        )
        return _attach_simulations(
            empty,
            beatmap=beatmap,
            metrics=metrics,
            reading_score=reading_score,
            stamina_score=stamina_score,
            aim_score=aim_score,
        )

    positioned_times = [item.time for item in objects if item.is_positioned]
    gaps = [
        right - left
        for left, right in zip(positioned_times, positioned_times[1:], strict=False)
        if right > left
    ]
    if not gaps:
        gaps = [0]

    approach_time_ms = beatmap.approach_time_ms
    average_reaction = metrics.average_reaction_time_ms
    average_velocity = metrics.average_cursor_velocity_pps

    # Per-object miss probabilities are deterministic functions of local demand.
    per_object_miss: list[float] = []
    per_object_reaction: list[float] = []
    fatigue = 0.0
    fatigue_samples: list[float] = []
    for index in range(len(positioned_times)):
        reaction = gaps[index] if index < len(gaps) else approach_time_ms
        reaction_ratio = reaction / max(1.0, approach_time_ms)
        reaction_demand = clamp(1.0 - reaction_ratio * 1.1, 0.0, 1.0)
        per_object_reaction.append(reaction_demand)

        velocity_demand = normalize(average_velocity, 900.0)
        reading_demand = reading_score
        aim_demand = aim_score

        # Fatigue builds in rapid sequences and recovers during rests.
        is_rest = reaction >= recovery_gap_ms
        fatigue = max(0.0, fatigue - (0.25 if is_rest else 0.0))
        if not is_rest and reaction <= 260:
            fatigue += 0.04
        fatigue_component = clamp(fatigue, 0.0, 1.0)
        fatigue_samples.append(fatigue_component)

        miss = (
            reaction_demand * 0.35
            + velocity_demand * 0.2
            + reading_demand * 0.2
            + aim_demand * 0.15
            + fatigue_component * 0.1
        )
        miss = clamp(miss * 0.35, 0.02, 0.85)
        per_object_miss.append(miss)

    if not per_object_miss:
        miss_probability = 0.0
    else:
        miss_probability = mean(per_object_miss)

    # Combo stability: probability of a full-combo pass per simulated run.
    expected_clean_runs = sum(
        (1.0 - miss_probability) ** len(positioned_times) for _ in range(simulated_playcount)
    )
    combo_stability = expected_clean_runs / simulated_playcount

    # Player stress: weighted aggregate of the demand components.
    player_stress = clamp(
        (aim_score * 0.3 + reading_score * 0.2 + rhythm_score * 0.15 + stamina_score * 0.2)
        / 0.85,
        0.0,
        1.0,
    )

    # Recovery windows: rests long enough to recover.
    recovery_windows = [
        gap for gap in gaps if gap >= recovery_gap_ms
    ]
    recovery_window_count = len(recovery_windows)
    average_recovery_window_ms = (
        mean(recovery_windows) if recovery_windows else 0.0
    )

    # Hardest passage: time of the object with the tightest reaction window.
    hardest_passage_ms = 0
    best_miss = -1.0
    for index, miss in enumerate(per_object_miss):
        if miss > best_miss:
            best_miss = miss
            hardest_passage_ms = positioned_times[index] if index < len(positioned_times) else 0

    analytics = GameplayAnalytics(
        estimated_miss_probability=round(clamp(miss_probability, 0.0, 1.0), 4),
        estimated_combo_stability=round(clamp(combo_stability, 0.0, 1.0), 4),
        estimated_player_stress=round(clamp(player_stress, 0.0, 1.0), 4),
        recovery_window_count=recovery_window_count,
        average_recovery_window_ms=round(average_recovery_window_ms, 4),
        hardest_passage_ms=hardest_passage_ms,
        simulated_playcount=simulated_playcount,
    )
    return _attach_simulations(
        analytics,
        beatmap=beatmap,
        metrics=metrics,
        reading_score=reading_score,
        stamina_score=stamina_score,
        aim_score=aim_score,
        per_object_reaction=per_object_reaction,
        fatigue_samples=fatigue_samples,
        miss_probability=miss_probability,
        combo_stability=combo_stability,
    )


def _attach_simulations(
    analytics: GameplayAnalytics,
    *,
    beatmap: LoadedDifficultyMap,
    metrics,
    reading_score: float,
    stamina_score: float,
    aim_score: float,
    per_object_reaction: list[float] | None = None,
    fatigue_samples: list[float] | None = None,
    miss_probability: float | None = None,
    combo_stability: float | None = None,
) -> GameplayAnalytics:
    positioned = [item for item in beatmap.objects if item.is_positioned]

    cursor_travel_px = 0.0
    for left, right in zip(positioned, positioned[1:], strict=False):
        if left.x is None or left.y is None or right.x is None or right.y is None:
            continue
        cursor_travel_px += math.hypot(right.x - left.x, right.y - left.y)

    if per_object_reaction is None:
        per_object_reaction = [analytics.estimated_player_stress] * max(1, len(positioned))
    reaction_difficulty = mean(per_object_reaction) if per_object_reaction else 0.0

    if fatigue_samples is None:
        fatigue_samples = []
    cursor_fatigue = mean(fatigue_samples) if fatigue_samples else 0.0

    stream_fatigue = clamp(
        normalize(metrics.longest_stream_length, 24.0) * 0.6
        + normalize(metrics.objects_per_second, 6.0) * 0.4,
        0.0,
        1.0,
    )
    reading_stress = clamp(reading_score, 0.0, 1.0)
    recovery_ability = clamp(
        0.35
        + normalize(analytics.recovery_window_count, 8.0) * 0.4
        + normalize(analytics.average_recovery_window_ms, 2200.0) * 0.25,
        0.0,
        1.0,
    )

    resolved_miss = (
        analytics.estimated_miss_probability
        if miss_probability is None
        else miss_probability
    )
    resolved_combo = (
        analytics.estimated_combo_stability
        if combo_stability is None
        else combo_stability
    )

    player = PlayerSimulation(
        cursor_travel_px=round(cursor_travel_px, 2),
        reaction_difficulty=round(clamp(reaction_difficulty, 0.0, 1.0), 4),
        miss_probability=round(clamp(resolved_miss, 0.0, 1.0), 4),
        combo_stability=round(clamp(resolved_combo, 0.0, 1.0), 4),
        recovery_ability=round(clamp(recovery_ability, 0.0, 1.0), 4),
        cursor_fatigue=round(clamp(cursor_fatigue, 0.0, 1.0), 4),
        stream_fatigue=round(clamp(stream_fatigue, 0.0, 1.0), 4),
        reading_stress=round(clamp(reading_stress, 0.0, 1.0), 4),
    )
    replay = _build_replay_simulation(
        beatmap=beatmap,
        metrics=metrics,
        aim_score=aim_score,
        stamina_score=stamina_score,
        miss_probability=resolved_miss,
        combo_stability=resolved_combo,
        simulated_playcount=analytics.simulated_playcount,
    )
    return GameplayAnalytics(
        estimated_miss_probability=analytics.estimated_miss_probability,
        estimated_combo_stability=analytics.estimated_combo_stability,
        estimated_player_stress=analytics.estimated_player_stress,
        recovery_window_count=analytics.recovery_window_count,
        average_recovery_window_ms=analytics.average_recovery_window_ms,
        hardest_passage_ms=analytics.hardest_passage_ms,
        simulated_playcount=analytics.simulated_playcount,
        player=player,
        replay=replay,
    )


def _build_replay_simulation(
    *,
    beatmap: LoadedDifficultyMap,
    metrics,
    aim_score: float,
    stamina_score: float,
    miss_probability: float,
    combo_stability: float,
    simulated_playcount: int,
) -> ReplaySimulation:
    """Deterministic replay estimate: how a typical playthrough would end."""
    object_count = max(1, beatmap.object_count)
    expected_misses = clamp(miss_probability * object_count, 0.0, float(object_count))

    # Expected accuracy decays as miss probability and fatigue rise.
    accuracy = clamp(
        1.0 - miss_probability * 0.85 - (1.0 - combo_stability) * 0.15,
        0.0,
        1.0,
    )
    full_combo_chance = combo_stability

    # Hardest pattern from the longest stream/burst length.
    if metrics.longest_stream_length >= 12:
        hardest_pattern = "stream"
    elif metrics.longest_burst_length >= 5:
        hardest_pattern = "burst"
    elif metrics.maximum_jump_distance >= 300:
        hardest_pattern = "wide-jump"
    elif metrics.direction_change_count >= 40:
        hardest_pattern = "zigzag"
    elif metrics.slider_complexity > 0.55:
        hardest_pattern = "slider-chain"
    else:
        hardest_pattern = "rhythm-complexity"

    positioned_times = [item.time for item in beatmap.objects if item.is_positioned]
    hardest_stress_ms = 0
    highest_stress = -1.0
    for index in range(len(positioned_times)):
        local = clamp(
            aim_score * 0.4
            + normalize(metrics.average_jump_distance, 320.0) * 0.3
            + stamina_score * 0.3,
            0.0,
            1.0,
        )
        if local > highest_stress:
            highest_stress = local
            hardest_stress_ms = positioned_times[index]

    # Most difficult transition: largest jump between consecutive objects.
    most_difficult_transition_ms = 0
    largest_jump = -1.0
    for left, right in zip(positioned_times, positioned_times[1:], strict=False):
        gap = right - left
        if 0 < gap <= 300 and gap > largest_jump:
            largest_jump = gap
            most_difficult_transition_ms = right

    return ReplaySimulation(
        full_combo_chance=round(clamp(full_combo_chance, 0.0, 1.0), 4),
        expected_accuracy=round(clamp(accuracy, 0.0, 1.0), 4),
        expected_misses=round(expected_misses, 2),
        highest_stress_section_ms=hardest_stress_ms,
        hardest_pattern=hardest_pattern,
        most_difficult_transition_ms=most_difficult_transition_ms,
        simulated_playcount=simulated_playcount,
    )
