from __future__ import annotations

import math
from typing import Any

from ..config import DifficultyPreset
from ..models import SelectedEvent
from .slider_models import ControlPoint, SliderCandidate, SliderPathType, SliderShape, SustainedAnalysis
from .sustained_analysis import get_sustained_score_at

# Phase 21: phrase strategy multipliers for slider shaping. Intense phrases get
# shorter, snappier, more curved sliders; recovery phrases get longer, gentler,
# flowing ones. Neutral/unknown strategies are identity so phrase-less maps
# keep legacy behavior.
SLIDER_STRATEGY_MULTIPLIERS: dict[str, dict[str, float]] = {
    "establish": {"length": 1.05, "repeats": 1.0, "curvature": 0.9, "probability": 1.0},
    "intensify": {"length": 0.8, "repeats": 1.3, "curvature": 1.25, "probability": 1.05},
    "release": {"length": 1.2, "repeats": 0.9, "curvature": 0.8, "probability": 0.95},
    "contrast": {"length": 0.9, "repeats": 1.15, "curvature": 1.15, "probability": 1.0},
    "recover": {"length": 1.3, "repeats": 0.8, "curvature": 0.7, "probability": 0.9},
    "transition": {"length": 1.1, "repeats": 0.95, "curvature": 0.85, "probability": 0.95},
    "neutral": {"length": 1.0, "repeats": 1.0, "curvature": 1.0, "probability": 1.0},
}

# Shape pools per difficulty, (shape, base weight). Weights are shifted toward
# expressive shapes by musical intensity (sustained content + energy).
_SHAPE_POOLS: dict[str, list[tuple[SliderShape, float]]] = {
    "easy": [("linear", 70.0), ("hook", 20.0), ("arc", 10.0)],
    "normal": [("linear", 35.0), ("hook", 30.0), ("arc", 25.0), ("wave", 10.0)],
    "hard": [
        ("linear", 15.0),
        ("hook", 25.0),
        ("arc", 15.0),
        ("wave", 20.0),
        ("zigzag", 15.0),
        ("loop", 10.0),
    ],
}

_EXPRESSIVE_SHAPES = {"wave", "zigzag", "loop"}
_GENTLE_SHAPES = {"linear", "arc"}


def decide_slider(
    event: SelectedEvent,
    event_index: int,
    sustained: SustainedAnalysis,
    preset: DifficultyPreset,
    *,
    previous_event: SelectedEvent | None = None,
    next_event: SelectedEvent | None = None,
    previous_gap_ms: int | None = None,
    next_gap_ms: int | None = None,
    energy_threshold: float = 0.2,
    min_slider_length_ms: int = 100,
    max_slider_length_ms: int = 600,
    phrase_strategy: str | None = None,
    rng: Any = None,
) -> SliderCandidate | None:
    """Decide whether a timing event should become a slider.

    Returns a SliderCandidate if a slider is warranted, None otherwise.

    Decision factors:
    1. Sustained audio content at this timing
    2. Time gap to next event (longer = better slider opportunity)
    3. Energy level (moderate-high = better)
    4. Emphasis (emphasis events can be sliders too)
    5. Difficulty-specific slider preferences
    6. Phrase strategy (Phase 21): intense phrases favor shorter/curvier
       sliders, recovery phrases favor longer/gentler flowing ones
    """
    sustained_score = get_sustained_score_at(sustained, event.time_ms)
    multipliers = SLIDER_STRATEGY_MULTIPLIERS.get(
        phrase_strategy or "neutral", SLIDER_STRATEGY_MULTIPLIERS["neutral"]
    )

    probability = _compute_slider_probability(
        sustained_score=sustained_score,
        energy=event.energy,
        is_emphasis=event.is_emphasis,
        next_gap_ms=next_gap_ms,
        previous_gap_ms=previous_gap_ms,
        preset=preset,
    )
    probability *= multipliers["probability"]

    # Lower threshold so sliders appear more often across all difficulties.
    prob_threshold = 0.15 if preset.name == "easy" else 0.18
    if probability < prob_threshold:
        return None

    length_ms = _compute_slider_length_ms(
        sustained_score, next_gap_ms, preset
    )
    length_ms = max(
        min_slider_length_ms,
        min(max_slider_length_ms, int(round(length_ms * multipliers["length"]))),
    )
    end_time_ms = event.time_ms + length_ms

    shape = _choose_shape(
        sustained_score=sustained_score,
        energy=event.energy,
        preset=preset,
        phrase_strategy=phrase_strategy,
        rng=rng,
    )
    path_type = _path_type_for_shape(shape)
    repeats = _choose_repeats(
        length_ms, event.energy, sustained_score, preset
    )
    repeats = max(1, int(round(repeats * multipliers["repeats"])))
    pixel_length = _estimate_pixel_length(
        length_ms, preset, path_type
    )
    curvature = _choose_curvature(
        sustained_score=sustained_score,
        energy=event.energy,
        preset=preset,
        phrase_strategy=phrase_strategy,
        rng=rng,
    )

    return SliderCandidate(
        event_index=event_index,
        time_ms=event.time_ms,
        length_ms=length_ms,
        end_time_ms=end_time_ms,
        energy=event.energy,
        sustained_score=sustained_score,
        slider_probability=probability,
        preferred_path_type=path_type,
        preferred_repeats=repeats,
        preferred_pixel_length=pixel_length,
        preferred_shape=shape,
        preferred_curvature=curvature,
        phrase_strategy=phrase_strategy,
    )


def _compute_slider_probability(
    sustained_score: float,
    energy: float,
    is_emphasis: bool,
    next_gap_ms: int | None,
    previous_gap_ms: int | None,
    preset: DifficultyPreset,
) -> float:
    """Compute a 0-1 slider probability score."""
    prob = 0.0

    if sustained_score > 0.5:
        prob += 0.4
    elif sustained_score > 0.3:
        prob += 0.25
    elif sustained_score > 0.15:
        prob += 0.1
    elif sustained_score > 0.08:
        prob += 0.05  # even mild sustained content helps slider candidacy

    if 0.25 <= energy <= 0.75:
        prob += 0.18  # moderate energy is ideal for sliders
    elif energy > 0.75:
        prob += 0.12
    elif energy < 0.1:
        prob -= 0.1

    if next_gap_ms is not None:
        if next_gap_ms >= preset.target_gap_ms * 1.5:
            prob += 0.22
        elif next_gap_ms >= preset.target_gap_ms:
            prob += 0.12

    if is_emphasis:
        prob += 0.12

    # Boost slider probability for all difficulties to improve object diversity
    if preset.name == "easy":
        prob *= 1.15
    elif preset.name == "hard":
        prob *= 1.5
    else:
        prob *= 1.35  # normal gets a significant boost

    cap = 0.80 if preset.name == "hard" else 0.65
    return max(0.0, min(cap, prob))


def _compute_slider_length_ms(
    sustained_score: float,
    next_gap_ms: int | None,
    preset: DifficultyPreset,
) -> int:
    """Compute appropriate slider duration in milliseconds."""
    # Base length scales with sustained content and difficulty.
    # Easy: shorter sliders for readability; Hard: longer for expression.
    base_ms = 100 + int(sustained_score * 350)

    if next_gap_ms is not None:
        max_ms = max(100, next_gap_ms - 30)
    else:
        max_ms = 500

    if preset.name == "easy":
        max_ms = min(max_ms, 300)
    elif preset.name == "normal":
        max_ms = min(max_ms, 500)
    else:
        max_ms = min(max_ms, 650)

    return max(80, min(max_ms, base_ms))


def _choose_shape(
    *,
    sustained_score: float,
    energy: float,
    preset: DifficultyPreset,
    phrase_strategy: str | None,
    rng: Any = None,
) -> SliderShape:
    """Pick a slider shape family deterministically.

    Musical intensity (sustained content + energy) shifts weight toward
    expressive multi-segment shapes (wave / zigzag / loop); gentle passages
    stay with linear / arc. Recovery phrases push toward gentle shapes and
    intense phrases toward expressive ones. When ``rng`` is provided the
    choice is sampled from the weighted pool (deterministic for a fixed
    seed); otherwise the highest-weighted shape wins.
    """
    multipliers = SLIDER_STRATEGY_MULTIPLIERS.get(
        phrase_strategy or "neutral", SLIDER_STRATEGY_MULTIPLIERS["neutral"]
    )
    intensity = (sustained_score + energy) / 2.0
    strategy_curvature = multipliers["curvature"]

    pool = _SHAPE_POOLS.get(preset.name, _SHAPE_POOLS["normal"])
    weighted: list[tuple[SliderShape, float]] = []
    for shape, weight in pool:
        adjusted = weight
        if shape in _EXPRESSIVE_SHAPES:
            adjusted *= 0.6 + intensity * 0.9
        elif shape in _GENTLE_SHAPES:
            adjusted *= 1.4 - intensity * 0.7
        if strategy_curvature > 1.0 and shape in _EXPRESSIVE_SHAPES:
            adjusted *= strategy_curvature
        elif strategy_curvature < 1.0 and shape in _GENTLE_SHAPES:
            adjusted *= 2.0 - strategy_curvature
        weighted.append((shape, max(0.1, adjusted)))

    if rng is not None:
        choices = [shape for shape, _ in weighted]
        weights = [weight for _, weight in weighted]
        return rng.choices(choices, weights=weights, k=1)[0]  # type: ignore[arg-type]

    best_shape = weighted[0][0]
    best_weight = -1.0
    for shape, weight in weighted:
        if weight > best_weight:
            best_weight = weight
            best_shape = shape
    return best_shape


def _choose_curvature(
    *,
    sustained_score: float,
    energy: float,
    preset: DifficultyPreset,
    phrase_strategy: str | None,
    rng: Any = None,
) -> float:
    """Choose a curvature factor (0-1) for the slider path."""
    multipliers = SLIDER_STRATEGY_MULTIPLIERS.get(
        phrase_strategy or "neutral", SLIDER_STRATEGY_MULTIPLIERS["neutral"]
    )
    base = 0.2 + (sustained_score + energy) * 0.25
    base *= multipliers["curvature"]
    if rng is not None:
        base += (rng.random() - 0.5) * 0.15
    if preset.name == "easy":
        base = min(base, 0.35)
    return round(max(0.1, min(0.9, base)), 4)


def _path_type_for_shape(shape: SliderShape) -> SliderPathType:
    if shape == "linear":
        return "linear"
    if shape == "arc":
        return "perfect"
    return "bezier"


def _choose_repeats(
    length_ms: int,
    energy: float,
    sustained_score: float,
    preset: DifficultyPreset,
) -> int:
    """Choose number of slider repeats.

    1 = no repeat (forward only)
    2 = one repeat (forward + back)
    3+ = multiple repeats
    """
    if preset.name == "easy":
        return 1

    if length_ms < 150:
        return 1

    if length_ms >= 300 and energy > 0.6 and sustained_score > 0.4:
        return 2

    if length_ms >= 400 and energy > 0.7 and preset.name == "hard":
        return 3

    return 2 if preset.name == "hard" and length_ms >= 200 else 1


def _estimate_pixel_length(
    length_ms: int,
    preset: DifficultyPreset,
    path_type: SliderPathType,
) -> int:
    """Estimate appropriate pixel length from duration."""
    if preset.name == "easy":
        velocity_factor = 0.6
    elif preset.name == "normal":
        velocity_factor = 0.8
    else:
        velocity_factor = 1.0

    estimated = int(length_ms / 1000 * 100 * velocity_factor)

    if path_type == "perfect":
        estimated = int(estimated * 1.15)
    elif path_type == "bezier":
        estimated = int(estimated * 1.25)
    elif path_type == "catmull":
        estimated = int(estimated * 1.3)

    return max(20, min(400, estimated))
