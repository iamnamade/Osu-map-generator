from __future__ import annotations

from typing import Any, Literal

from ._constants import load_osu_interop_constants
from .models import OsuDifficultyValues, ProjectBeatmap

SupportedProjectDifficulty = Literal["easy", "normal", "hard"]


def project_radius_to_circle_size(radius: int) -> float:
    constants = load_osu_interop_constants()["circleSizeFormula"]
    return _round_clamp(
        (float(constants["radiusBase"]) - float(radius)) / float(constants["radiusStep"]),
        float(constants["minimum"]),
        float(constants["maximum"]),
    )


def circle_size_to_project_radius(circle_size: float) -> int:
    constants = load_osu_interop_constants()["circleSizeFormula"]
    return round(float(constants["radiusBase"]) - float(circle_size) * float(constants["radiusStep"]))


def project_approach_time_to_ar(approach_time_ms: int) -> float:
    constants = load_osu_interop_constants()["approachRateFormula"]
    slow_pivot = float(constants["slowPivotMs"])
    if float(approach_time_ms) >= slow_pivot:
        value = (float(constants["slowReferenceMs"]) - float(approach_time_ms)) / float(constants["slowStepMsPerAr"])
    else:
        value = 5 + (float(constants["fastPivotMs"]) - float(approach_time_ms)) / float(constants["fastStepMsPerAr"])
    return _round_clamp(value, float(constants["minimum"]), float(constants["maximum"]))


def ar_to_project_approach_time(approach_rate: float) -> int:
    constants = load_osu_interop_constants()["approachRateFormula"]
    clamped = _clamp(float(approach_rate), float(constants["minimum"]), float(constants["maximum"]))
    if clamped <= 5:
        return round(float(constants["slowReferenceMs"]) - clamped * float(constants["slowStepMsPerAr"]))
    return round(float(constants["fastPivotMs"]) - (clamped - 5) * float(constants["fastStepMsPerAr"]))


def infer_project_difficulty(beatmap: ProjectBeatmap) -> SupportedProjectDifficulty | None:
    explicit = _normalize_difficulty_name(
        _first_defined_string(
            _read_nested_string(beatmap.extra_fields, ["generator", "difficulty"]),
            _read_nested_string(beatmap.extra_fields, ["hybrid", "difficulty"]),
            _read_nested_string(beatmap.extra_fields, ["editor", "sourceDifficulty"]),
            _read_nested_string(beatmap.extra_fields, ["osu", "beatmapVersion"]),
        )
    )
    if explicit:
        return explicit

    candidates = [
        ("easy", 1200, 46),
        ("normal", 950, 40),
        ("hard", 720, 34),
    ]
    ranked = sorted(
        (
            (
                name,
                abs(target_approach_time - beatmap.approach_time)
                + abs(target_circle_radius - beatmap.circle_radius) * 12,
            )
            for name, target_approach_time, target_circle_radius in candidates
        ),
        key=lambda item: item[1],
    )
    return ranked[0][0] if ranked else None


def convert_project_difficulty_to_osu_values(
    beatmap: ProjectBeatmap,
    difficulty_name: SupportedProjectDifficulty | None,
) -> OsuDifficultyValues:
    constants = load_osu_interop_constants()
    preset_name: SupportedProjectDifficulty = difficulty_name if difficulty_name in constants["difficultyPresets"] else "normal"
    preset = constants["difficultyPresets"][preset_name]
    defaults = constants["difficultyDefaults"]
    return OsuDifficultyValues(
        hp_drain_rate=float(preset["hpDrainRate"]),
        circle_size=project_radius_to_circle_size(beatmap.circle_radius),
        overall_difficulty=float(preset["overallDifficulty"]),
        approach_rate=project_approach_time_to_ar(beatmap.approach_time),
        slider_multiplier=float(defaults["sliderMultiplier"]),
        slider_tick_rate=float(defaults["sliderTickRate"]),
    )


def derive_version_name(beatmap: ProjectBeatmap, difficulty_name: SupportedProjectDifficulty | None) -> str | None:
    osu_version = _read_nested_string(beatmap.extra_fields, ["osu", "beatmapVersion"])
    if osu_version:
        return osu_version
    source_type = _read_nested_string(beatmap.extra_fields, ["editor", "sourceType"])
    has_hybrid_metadata = isinstance(beatmap.extra_fields.get("hybrid"), dict)
    if (source_type == "hybrid" or has_hybrid_metadata) and difficulty_name:
        return f"Hybrid {difficulty_name.capitalize()}"
    if source_type == "imported":
        return "Imported"
    if difficulty_name:
        return difficulty_name.capitalize()
    return None


def _normalize_difficulty_name(value: str | None) -> SupportedProjectDifficulty | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if "easy" in normalized:
        return "easy"
    if "hard" in normalized:
        return "hard"
    if "normal" in normalized:
        return "normal"
    return None


def _read_nested_string(value: dict[str, Any], path: list[str]) -> str | None:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, str) and current.strip():
        return current.strip()
    return None


def _first_defined_string(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round_clamp(value: float, minimum: float, maximum: float) -> float:
    return round(_clamp(value, minimum, maximum), 2)
