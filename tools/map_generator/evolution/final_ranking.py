"""Final evolution ranking & champion selection (Phase 17).

Combines every available evaluation signal — difficulty, rhythm, pattern,
section quality, reading, cursor-flow, fatigue, replay simulation, miss
probability, combo stability, adaptive rebalancing gain, structural
validation, and target-difficulty accuracy — into one unified, configurable
weighted score. Each component stays separately visible in the final report.

Also implements:

* Quality gates (mandatory + quality) that run before champion selection.
  Mandatory failures disqualify a candidate from becoming champion; quality
  failures apply ranking penalties instead of being ignored.
* Diversity protection: near-identical candidates are detected from object
  timing, positions, pattern distribution, rhythm structure, and section
  difficulty, and penalized so the leaderboard keeps variety.
* Target difficulty matching: candidates are rewarded for landing naturally
  inside the requested difficulty band rather than merely maximizing stars.

Everything is deterministic: identical inputs always produce the identical
ranking and champion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..difficulty.common import clamp
from ..geometry.collision import detect_map_overlaps
from ..rebalance.patterns import analyze_patterns
from .models import EvolutionFinalBreakdown, EvolutionQualityGate

# Maximum diversity penalty points applied to a near-duplicate candidate.
DIVERSITY_PENALTY_MAX = 12.0
# Gate penalties (points) subtracted from the weighted score when a quality
# gate fails.
GATE_PENALTIES: dict[str, float] = {
    "REPLAY_SCORE": 3.0,
    "MISS_PROBABILITY": 3.0,
    "FATIGUE": 2.0,
    "DIFFICULTY_SPIKES": 3.0,
    "READABILITY": 2.0,
    "FLOW": 2.0,
    "COMBO_STABILITY": 2.0,
}


@dataclass(frozen=True)
class EvolutionFinalWeights:
    """Configurable unified-score weights (defaults sum to 1.0)."""

    rhythm: float = 0.14
    playability: float = 0.12
    pattern: float = 0.08
    target: float = 0.12
    reading: float = 0.10
    replay: float = 0.12
    consistency: float = 0.05
    validity: float = 0.05
    flow: float = 0.07
    section: float = 0.06
    fatigue: float = 0.05
    rebalance: float = 0.04
    phrase: float = 0.0

    def with_overrides(self, overrides: dict[str, float] | None) -> "EvolutionFinalWeights":
        if not overrides:
            return self
        allowed = {
            "rhythm",
            "playability",
            "pattern",
            "target",
            "reading",
            "replay",
            "consistency",
            "validity",
            "flow",
            "section",
            "fatigue",
            "rebalance",
            "phrase",
        }
        values: dict[str, float] = {}
        for key, value in self.to_dict().items():
            values[key] = value
        for key, value in (overrides or {}).items():
            if key in allowed:
                values[key] = float(value)
        return EvolutionFinalWeights(
            rhythm=values["rhythm"],
            playability=values["playability"],
            pattern=values["pattern"],
            target=values["target"],
            reading=values["reading"],
            replay=values["replay"],
            consistency=values["consistency"],
            validity=values["validity"],
            flow=values["flow"],
            section=values["section"],
            fatigue=values["fatigue"],
            rebalance=values["rebalance"],
            phrase=values["phrase"],
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "rhythm": self.rhythm,
            "playability": self.playability,
            "pattern": self.pattern,
            "target": self.target,
            "reading": self.reading,
            "replay": self.replay,
            "consistency": self.consistency,
            "validity": self.validity,
            "flow": self.flow,
            "section": self.section,
            "fatigue": self.fatigue,
            "rebalance": self.rebalance,
            "phrase": self.phrase,
        }

    @property
    def total(self) -> float:
        return sum(self.to_dict().values())


def compute_final_breakdown(
    *,
    scores: Any,
    difficulty_report: Any,
    replay_report: Any | None,
    validation_report: Any | None,
    rebalance_report: Any | None,
    weights: EvolutionFinalWeights = EvolutionFinalWeights(),
    phrase_report: Any | None = None,
    map_dict: dict[str, Any] | None = None,
) -> EvolutionFinalBreakdown:
    """Compute the unified weighted score with a fully visible breakdown.

    Phase 20: when a phrase report is supplied, a phrase-coherence component
    (structural trajectory consistency + contrast) is computed and folded
    into the weighted score.
    """
    rhythm = _clamped(scores.rhythm)
    playability = _clamped(scores.playability)
    pattern = _clamped(scores.pattern)
    target = _target_difficulty_score(difficulty_report)
    reading = _clamped(scores.reading)
    replay = _replay_overall(replay_report)
    consistency = _clamped(scores.consistency)
    validity = _validity_score(validation_report)
    flow = _clamped(scores.flow)
    section = _section_score(difficulty_report)
    fatigue = _fatigue_score(replay_report)
    rebalance = _rebalance_score(rebalance_report)
    phrase = _phrase_coherence_score(
        difficulty_report,
        phrase_report=phrase_report,
        map_dict=map_dict,
    )

    weighted = (
        rhythm * weights.rhythm
        + playability * weights.playability
        + pattern * weights.pattern
        + target * weights.target
        + reading * weights.reading
        + replay * weights.replay
        + consistency * weights.consistency
        + validity * weights.validity
        + flow * weights.flow
        + section * weights.section
        + fatigue * weights.fatigue
        + rebalance * weights.rebalance
        + phrase * weights.phrase
    )
    return EvolutionFinalBreakdown(
        weighted_score=round(clamp(weighted, 0.0, 100.0), 3),
        rhythm=round(rhythm, 3),
        playability=round(playability, 3),
        pattern=round(pattern, 3),
        target=round(target, 3),
        reading=round(reading, 3),
        replay=round(replay, 3),
        consistency=round(consistency, 3),
        validity=round(validity, 3),
        flow=round(flow, 3),
        section=round(section, 3),
        fatigue=round(fatigue, 3),
        rebalance=round(rebalance, 3),
        phrase=round(phrase, 3),
    )


def run_quality_gates(
    *,
    difficulty_report: Any,
    replay_report: Any | None,
    validation_report: Any | None,
    map_dict: dict[str, Any],
) -> list[EvolutionQualityGate]:
    """Run the final quality gates before champion selection.

    Mandatory gates disqualify a candidate from becoming champion; quality
    gates apply ranking penalties when they fail.
    """
    gates: list[EvolutionQualityGate] = []

    # --- Mandatory gates --------------------------------------------------
    validation_summary = getattr(validation_report, "summary", None) if validation_report else None
    parsed = validation_summary is not None and validation_report.scores.overall > 0.0
    # Allow a small proportion of critical issues for generated maps.
    _gate_obj_count = len(map_dict.get("objects", []) or [])
    _gate_max_critical = max(3, _gate_obj_count // 20)
    gates.append(
        EvolutionQualityGate(
            code="VALID_STRUCTURE",
            name="Valid beatmap structure",
            mandatory=True,
            passed=bool(parsed and getattr(validation_summary, "critical", 0) <= _gate_max_critical),
            detail=(
                "Structure parsed successfully."
                if parsed
                else "Validation report did not parse or is empty."
            ),
            penalty=0.0,
        )
    )

    approach_time = float(map_dict.get("approachTime") or 0.0)
    metrics = getattr(difficulty_report, "metrics", None)
    average_gap = float(getattr(metrics, "average_gap_ms", 0.0) or 0.0)
    object_count_metrics = int(getattr(metrics, "object_count", 0) or 0)
    gates.append(
        EvolutionQualityGate(
            code="VALID_TIMING",
            name="Valid timing",
            mandatory=True,
            passed=approach_time > 0.0 and average_gap > 0.0 and object_count_metrics > 0,
            detail=(
                f"approach time {approach_time:.0f}ms, average gap "
                f"{average_gap:.0f}ms, {object_count_metrics} objects."
            ),
            penalty=0.0,
        )
    )

    ordering_ok, ordering_detail = _hit_order_check(map_dict)
    gates.append(
        EvolutionQualityGate(
            code="HIT_ORDER",
            name="Valid hit-object ordering",
            mandatory=True,
            passed=ordering_ok,
            detail=ordering_detail,
            penalty=0.0,
        )
    )

    coords_ok, coords_detail = _coordinate_check(map_dict)
    gates.append(
        EvolutionQualityGate(
            code="COORDINATES",
            name="Coordinates in playfield",
            mandatory=True,
            passed=coords_ok,
            detail=coords_detail,
            penalty=0.0,
        )
    )

    states_ok, states_detail = _impossible_state_check(map_dict)
    gates.append(
        EvolutionQualityGate(
            code="NO_IMPOSSIBLE_STATE",
            name="No impossible object states",
            mandatory=True,
            passed=states_ok,
            detail=states_detail,
            penalty=0.0,
        )
    )

    # Phase 23: physical anti-overlap gate. A candidate whose discs or slider
    # bodies collide is unreadable no matter how good its scores are. Legacy
    # maps without a circle radius cannot be checked and pass through.
    collisions_ok, collisions_detail = _collision_check(map_dict)
    gates.append(
        EvolutionQualityGate(
            code="COLLISION_FREE",
            name="No overlapping hit objects",
            mandatory=True,
            passed=collisions_ok,
            detail=collisions_detail,
            penalty=0.0,
        )
    )

    target = getattr(difficulty_report, "target", None)
    gates.append(
        EvolutionQualityGate(
            code="DIFFICULTY_METADATA",
            name="Correct difficulty metadata",
            mandatory=True,
            passed=target is not None,
            detail=(
                f"Target '{target.name}' present."
                if target is not None
                else "No difficulty target metadata found."
            ),
            penalty=0.0,
        )
    )

    gates.append(
        EvolutionQualityGate(
            code="PARSER_VALIDATION",
            name="Parser validation",
            mandatory=True,
            passed=parsed,
            detail="Validation report accepted the map." if parsed else "Parser rejected the map.",
            penalty=0.0,
        )
    )

    # --- Quality gates ----------------------------------------------------
    replay_overall = _replay_overall(replay_report)
    gates.append(
        EvolutionQualityGate(
            code="REPLAY_SCORE",
            name="Acceptable replay score",
            mandatory=False,
            passed=replay_overall >= 60.0,
            detail=f"Replay score {replay_overall:.1f} (threshold 60).",
            penalty=GATE_PENALTIES["REPLAY_SCORE"] if replay_overall < 60.0 else 0.0,
        )
    )

    expected_misses = _replay_field(replay_report, "expected_misses")
    object_count = _object_count(map_dict)
    miss_rate = expected_misses / max(1, object_count)
    gates.append(
        EvolutionQualityGate(
            code="MISS_PROBABILITY",
            name="Acceptable miss probability",
            mandatory=False,
            passed=miss_rate <= 0.10,
            detail=f"Expected miss rate {miss_rate:.1%} ({expected_misses:.1f} of {object_count}).",
            penalty=GATE_PENALTIES["MISS_PROBABILITY"] if miss_rate > 0.10 else 0.0,
        )
    )

    fatigue_peak = _replay_field(replay_report, "fatigue_peak")
    gates.append(
        EvolutionQualityGate(
            code="FATIGUE",
            name="Acceptable fatigue",
            mandatory=False,
            passed=fatigue_peak <= 0.92,
            detail=f"Peak fatigue {fatigue_peak:.2f} (threshold 0.92).",
            penalty=GATE_PENALTIES["FATIGUE"] if fatigue_peak > 0.92 else 0.0,
        )
    )

    spikes_ok, spikes_detail = _spike_check(difficulty_report)
    gates.append(
        EvolutionQualityGate(
            code="DIFFICULTY_SPIKES",
            name="No severe difficulty spikes",
            mandatory=False,
            passed=spikes_ok,
            detail=spikes_detail,
            penalty=GATE_PENALTIES["DIFFICULTY_SPIKES"] if not spikes_ok else 0.0,
        )
    )

    reading = _clamped(
        getattr(getattr(difficulty_report, "reading", None), "score", 0.0) * 100.0
        if getattr(difficulty_report, "reading", None)
        else 50.0
    )
    gates.append(
        EvolutionQualityGate(
            code="READABILITY",
            name="No major readability problems",
            mandatory=False,
            passed=reading >= 40.0,
            detail=f"Reading score {reading:.1f} (threshold 40).",
            penalty=GATE_PENALTIES["READABILITY"] if reading < 40.0 else 0.0,
        )
    )

    flow = _clamped(getattr(getattr(difficulty_report, "aim", None), "flow_quality", 0.0) * 100.0)
    gates.append(
        EvolutionQualityGate(
            code="FLOW",
            name="No severe flow problems",
            mandatory=False,
            passed=flow >= 40.0,
            detail=f"Flow quality {flow:.1f} (threshold 40).",
            penalty=GATE_PENALTIES["FLOW"] if flow < 40.0 else 0.0,
        )
    )

    combo_pct = _replay_field(replay_report, "expected_combo_pct")
    gates.append(
        EvolutionQualityGate(
            code="COMBO_STABILITY",
            name="Combo stability",
            mandatory=False,
            passed=combo_pct >= 0.5,
            detail=f"Expected combo {combo_pct:.0%} (threshold 50%).",
            penalty=GATE_PENALTIES["COMBO_STABILITY"] if combo_pct < 0.5 else 0.0,
        )
    )

    return gates


def mandatory_gates_passed(gates: list[EvolutionQualityGate]) -> bool:
    return all(gate.passed for gate in gates if gate.mandatory)


def quality_gate_penalty(gates: list[EvolutionQualityGate]) -> float:
    return sum(gate.penalty for gate in gates)


def candidate_similarity(
    map_a: dict[str, Any],
    map_b: dict[str, Any],
) -> float:
    """0..1 structural similarity between two candidate maps.

    Compares object-timing histograms, jump-distance histograms, pattern
    family distributions, and rhythm subdivision ratios. Identical maps score
    1.0; unrelated maps score near 0.
    """
    features_a = _similarity_features(map_a)
    features_b = _similarity_features(map_b)
    similarities: list[float] = []
    for key in ("time_gaps", "jump_distances", "patterns", "rhythm"):
        left = features_a[key]
        right = features_b[key]
        similarities.append(1.0 - _l1_distance(left, right) / 2.0)
    return clamp(sum(similarities) / len(similarities), 0.0, 1.0)


def diversity_penalty(
    map_dict: dict[str, Any],
    higher_ranked_maps: list[dict[str, Any]],
) -> float:
    """Penalty points for duplicating a higher-ranked candidate."""
    if not higher_ranked_maps:
        return 0.0
    worst = max(
        candidate_similarity(map_dict, other) for other in higher_ranked_maps
    )
    return round(clamp(worst, 0.0, 1.0) * DIVERSITY_PENALTY_MAX, 3)


def target_deviation(difficulty_report: Any) -> float:
    """Absolute star deviation from the target band center."""
    stars = float(getattr(getattr(difficulty_report, "star_rating", None), "overall", 0.0) or 0.0)
    target = getattr(difficulty_report, "target", None)
    if target is None:
        return 0.0
    low, high = float(target.star_range[0]), float(target.star_range[1])
    center = (low + high) / 2.0
    return round(abs(stars - center), 2)


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------


def _target_difficulty_score(difficulty_report: Any) -> float:
    stars = float(getattr(getattr(difficulty_report, "star_rating", None), "overall", 0.0) or 0.0)
    target = getattr(difficulty_report, "target", None)
    if target is None:
        return 50.0
    low, high = float(target.star_range[0]), float(target.star_range[1])
    center = (low + high) / 2.0
    half_span = max(0.5, (high - low) / 2.0)
    deviation = abs(stars - center) / half_span
    return clamp(100.0 - deviation * 25.0, 0.0, 100.0)


def _validity_score(validation_report: Any | None) -> float:
    if validation_report is None:
        return 50.0
    summary = getattr(validation_report, "summary", None)
    if summary is None:
        return 50.0
    return clamp(
        100.0
        - int(summary.critical) * 15.0
        - int(summary.errors) * 6.0
        - int(summary.warnings) * 1.5,
        0.0,
        100.0,
    )


def _section_score(difficulty_report: Any) -> float:
    sections = getattr(difficulty_report, "sections", None) or []
    scores = [float(section.difficulty_score) for section in sections if section.difficulty_score > 0]
    if not scores:
        return 50.0
    mean = sum(scores) / len(scores)
    variance = sum((value - mean) ** 2 for value in scores) / len(scores)
    stdev = math.sqrt(variance)
    # Balanced sections (low variance) score high.
    return clamp(100.0 - stdev * 60.0, 0.0, 100.0)


def _phrase_coherence_score(
    difficulty_report: Any,
    *,
    phrase_report: Any | None,
    map_dict: dict[str, Any] | None,
) -> float:
    """Phase 20 phrase-coherence score (0-100).

    Rewards candidates whose per-section density follows the phrase
    trajectory (dense phrases dense, sparse phrases sparse) while keeping
    adjacent-phrase contrast musical rather than erratic. Returns a neutral
    50 when no phrase report is available.
    """
    if phrase_report is None:
        return 50.0
    phrases = getattr(phrase_report, "phrases", None) or []
    if not phrases:
        return 50.0
    sections = getattr(difficulty_report, "sections", None) or []
    if not sections:
        return 50.0

    # Map phrase targets by time; map measured section densities by time.
    phrase_targets = sorted(
        (phrase for phrase in phrases if phrase.target_density > 0),
        key=lambda phrase: phrase.start_ms,
    )
    measured = [
        (float(section.start_ms), float(section.density))
        for section in sections
        if float(getattr(section, "density", 0.0) or 0.0) > 0
    ]
    if not phrase_targets or not measured:
        return 50.0

    matches: list[float] = []
    for start_ms, density in measured:
        phrase = _phrase_at(phrase_targets, start_ms)
        if phrase is None:
            continue
        target = phrase.target_density
        ratio = density / max(target, 0.1)
        # Perfect match = 1.0; drift beyond 1.6x or 0.55x is penalized.
        if ratio >= 1.0:
            match = clamp(2.0 - ratio, 0.0, 1.0)
        else:
            match = clamp(ratio / 0.8, 0.0, 1.0)
        matches.append(match)
    if not matches:
        return 50.0
    coherence = sum(matches) / len(matches)

    # Contrast index: adjacent phrases with different targets should not
    # collapse into identical measured densities (variation without chaos).
    contrast_samples: list[float] = []
    for index in range(1, len(phrase_targets)):
        left = phrase_targets[index - 1]
        right = phrase_targets[index]
        target_delta = abs(right.target_density - left.target_density)
        if target_delta < 0.15:
            continue
        left_measured = _density_near(measured, left.start_ms)
        right_measured = _density_near(measured, right.start_ms)
        if left_measured is None or right_measured is None:
            continue
        measured_delta = abs(right_measured - left_measured)
        direction_ok = (
            (right.target_density > left.target_density)
            == (right_measured > left_measured)
        )
        contrast_samples.append(1.0 if direction_ok else 0.35)
    contrast = (
        sum(contrast_samples) / len(contrast_samples)
        if contrast_samples
        else 0.75
    )
    return clamp(coherence * 70.0 + contrast * 30.0, 0.0, 100.0)


def _phrase_at(phrases: list[Any], time_ms: float) -> Any | None:
    for phrase in phrases:
        if phrase.start_ms <= time_ms < phrase.end_ms:
            return phrase
    return None


def _density_near(measured: list[tuple[float, float]], time_ms: float) -> float | None:
    if not measured:
        return None
    nearest = min(measured, key=lambda item: abs(item[0] - time_ms))
    if abs(nearest[0] - time_ms) > 8000:
        return None
    return nearest[1]


def _fatigue_score(replay_report: Any | None) -> float:
    if replay_report is None:
        return 50.0
    fatigue = getattr(replay_report, "fatigue", None)
    if fatigue is None:
        return 50.0
    average = float(getattr(fatigue, "average", 0.0) or 0.0)
    peak = float(getattr(fatigue, "peak", 0.0) or 0.0)
    return clamp((1.0 - average) * 70.0 + (1.0 - peak) * 30.0, 0.0, 100.0)


def _rebalance_score(rebalance_report: Any | None) -> float:
    if rebalance_report is None:
        return 50.0
    summary = getattr(rebalance_report, "summary", None)
    if summary is None:
        return 50.0
    gain = float(getattr(summary, "quality_gain", 0.0) or 0.0)
    return clamp(50.0 + gain * 10.0, 0.0, 100.0)


def _replay_overall(replay_report: Any | None) -> float:
    if replay_report is None:
        return 50.0
    breakdown = getattr(replay_report, "score_breakdown", None)
    overall = getattr(breakdown, "overall", None)
    if overall is None:
        return 50.0
    return clamp(float(overall), 0.0, 100.0)


def _replay_field(replay_report: Any | None, attribute: str) -> float:
    if replay_report is None:
        return 0.0
    value = getattr(replay_report, attribute, None)
    if value is None:
        return 0.0
    return float(value)


def _clamped(value: float) -> float:
    return clamp(float(value), 0.0, 100.0)


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------


def _hit_order_check(map_dict: dict[str, Any]) -> tuple[bool, str]:
    times = [
        int(item["time"])
        for item in (map_dict.get("objects") or [])
        if isinstance(item, dict) and isinstance(item.get("time"), (int, float))
    ]
    if not times:
        return False, "No hit objects to order."
    ordered = sorted(times)
    if times != ordered:
        return False, "Hit objects are not sorted by time."
    return True, f"{len(times)} objects in ascending time order."


def _coordinate_check(map_dict: dict[str, Any]) -> tuple[bool, str]:
    out_of_bounds = 0
    total = 0
    for item in map_dict.get("objects") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in ("circle", "slider"):
            continue
        x = item.get("x")
        y = item.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        total += 1
        if x < 0 or x > 512 or y < 0 or y > 384:
            out_of_bounds += 1
    if out_of_bounds:
        return False, f"{out_of_bounds} of {total} objects outside the playfield."
    return True, f"All {total} positioned objects inside the playfield."


def _impossible_state_check(map_dict: dict[str, Any]) -> tuple[bool, str]:
    issues = 0
    for item in map_dict.get("objects") or []:
        if not isinstance(item, dict):
            continue
        time = int(item.get("time", 0))
        object_type = item.get("type")
        if object_type == "spinner":
            end = int(item.get("endTime", time))
            if end < time:
                issues += 1
        elif object_type == "slider":
            repeats = item.get("repeats")
            if repeats is not None and isinstance(repeats, (int, float)) and repeats < 1:
                issues += 1
            end = item.get("endTime")
            if isinstance(end, (int, float)) and int(end) < time:
                issues += 1
    if issues:
        return False, f"{issues} impossible object state(s) found."
    return True, "No impossible object states."


def _spike_check(difficulty_report: Any) -> tuple[bool, str]:
    sections = getattr(difficulty_report, "sections", None) or []
    scores = [float(section.difficulty_score) for section in sections]
    if not scores:
        return True, "No section data to check."
    mean = sum(scores) / len(scores)
    worst = max(scores)
    peak_section = max(sections, key=lambda section: section.difficulty_score)
    ratio = worst / mean if mean > 0.0 else 0.0
    if worst > 0.75 and ratio > 1.9:
        return False, (
            f"{peak_section.label} spikes at {worst:.2f} against a "
            f"{mean:.2f} section average (ratio {ratio:.2f})."
        )
    return True, f"No section exceeds {ratio:.2f}x the map's section average."


def _object_count(map_dict: dict[str, Any]) -> int:
    objects = map_dict.get("objects")
    return len(objects) if isinstance(objects, list) else 0


def _collision_check(map_dict: dict[str, Any]) -> tuple[bool, str]:
    radius = map_dict.get("circleRadius")
    if not isinstance(radius, (int, float)) or float(radius) <= 0:
        return True, "No circle radius available; collision check skipped."
    objects = map_dict.get("objects")
    if not isinstance(objects, list):
        return True, "No hit objects to check."
    overlaps = detect_map_overlaps(objects, float(radius))
    if not overlaps:
        return True, f"No overlaps among {len(objects)} hit objects."
    worst = max(overlaps, key=lambda record: abs(record["clearance_px"]))
    return False, (
        f"{len(overlaps)} overlap(s) found; worst is objects "
        f"{worst['left_id']} and {worst['right_id']} "
        f"({worst['kind']}, {-worst['clearance_px']:.1f}px overlap)."
    )


# ---------------------------------------------------------------------------
# Diversity features
# ---------------------------------------------------------------------------

_TIME_GAP_BINS = (125, 250, 375, 500, 750, 1000)
_JUMP_BINS = (60, 120, 200, 320)


def _similarity_features(map_dict: dict[str, Any]) -> dict[str, list[float]]:
    positioned = [
        item
        for item in (map_dict.get("objects") or [])
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("x"), (int, float))
        and isinstance(item.get("y"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item.get("time", 0)), int(item.get("id", 0))))

    time_gaps = [0.0] * (len(_TIME_GAP_BINS) + 1)
    jump_distances = [0.0] * (len(_JUMP_BINS) + 1)
    for index in range(1, len(positioned)):
        gap = int(positioned[index]["time"]) - int(positioned[index - 1]["time"])
        time_gaps[_bin_index(gap, _TIME_GAP_BINS)] += 1.0
        distance = math.hypot(
            float(positioned[index]["x"]) - float(positioned[index - 1]["x"]),
            float(positioned[index]["y"]) - float(positioned[index - 1]["y"]),
        )
        jump_distances[_bin_index(distance, _JUMP_BINS)] += 1.0

    # Rhythm subdivision ratios: 1/4, 1/3, 1/2, 3/4, 1 beat.
    subdivisions = [0.0] * 5
    for index in range(1, len(positioned)):
        gap = int(positioned[index]["time"]) - int(positioned[index - 1]["time"])
        if gap <= 0:
            continue
        if gap <= 130:
            subdivisions[0] += 1.0
        elif gap <= 190:
            subdivisions[1] += 1.0
        elif gap <= 260:
            subdivisions[2] += 1.0
        elif gap <= 390:
            subdivisions[3] += 1.0
        else:
            subdivisions[4] += 1.0

    pattern_counts = [0.0] * 6
    for family in analyze_patterns(map_dict)[:6]:
        pattern_counts[len(pattern_counts) - 1] += float(family["count"])

    return {
        "time_gaps": _normalize(time_gaps),
        "jump_distances": _normalize(jump_distances),
        "patterns": _normalize(pattern_counts),
        "rhythm": _normalize(subdivisions),
    }


def _bin_index(value: float, bins: tuple[float, ...]) -> int:
    for index, limit in enumerate(bins):
        if value <= limit:
            return index
    return len(bins)


def _normalize(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 0.0:
        return [0.0] * len(values)
    return [value / total for value in values]


def _l1_distance(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    return sum(abs(left[index] - right[index]) for index in range(size))
