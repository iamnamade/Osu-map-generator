"""Phase 19 generation configuration: a real mapping control system.

This module converts user-facing mapping controls (density, sliders, spinners,
jumps, streams, bursts, rhythm complexity, pattern variety, spacing,
aggression) into concrete values on the existing generator architecture:

* ``DifficultyPreset`` knobs (event selection, positions, sliders, spinners)
* ``PatternPipelineConfig`` knobs (pattern switching, repetition, transitions)
* ``PositionVariation`` biases (stream / burst / pattern family weights)
* a custom ``DifficultyTarget`` used by difficulty analysis and the
  Evolution Engine's ranking constraint

Every function is deterministic: identical controls and base preset always
produce identical derived configuration. The default control values (0.5)
produce the identity mapping, so existing workspaces without the new fields
keep their current behavior exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from .config import DifficultyPreset, get_difficulty_preset
from .difficulty.targets import (
    DIFFICULTY_TARGETS,
    DifficultyTarget,
    build_custom_target,
)
from .utils import clamp
from .variation import PositionVariation

ControlValue = float  # 0.0 .. 1.0

# ---------------------------------------------------------------------------
# Mapping controls
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingControls:
    """User-facing mapping controls.

    All values are 0.0..1.0. The neutral value is 0.5: it leaves the base
    difficulty preset untouched (identity mapping), which keeps backward
    compatibility for workspaces that predate Phase 19.
    """

    circle_density: float = 0.5
    slider_density: float = 0.5
    spinner_frequency: float = 0.5
    jump_intensity: float = 0.5
    stream_intensity: float = 0.5
    burst_intensity: float = 0.5
    rhythm_complexity: float = 0.5
    pattern_variety: float = 0.5
    spacing: float = 0.5
    aggression: float = 0.5

    def clamped(self) -> "MappingControls":
        return MappingControls(
            circle_density=clamp(self.circle_density, 0.0, 1.0),
            slider_density=clamp(self.slider_density, 0.0, 1.0),
            spinner_frequency=clamp(self.spinner_frequency, 0.0, 1.0),
            jump_intensity=clamp(self.jump_intensity, 0.0, 1.0),
            stream_intensity=clamp(self.stream_intensity, 0.0, 1.0),
            burst_intensity=clamp(self.burst_intensity, 0.0, 1.0),
            rhythm_complexity=clamp(self.rhythm_complexity, 0.0, 1.0),
            pattern_variety=clamp(self.pattern_variety, 0.0, 1.0),
            spacing=clamp(self.spacing, 0.0, 1.0),
            aggression=clamp(self.aggression, 0.0, 1.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "circleDensity": round(self.circle_density, 4),
            "sliderDensity": round(self.slider_density, 4),
            "spinnerFrequency": round(self.spinner_frequency, 4),
            "jumpIntensity": round(self.jump_intensity, 4),
            "streamIntensity": round(self.stream_intensity, 4),
            "burstIntensity": round(self.burst_intensity, 4),
            "rhythmComplexity": round(self.rhythm_complexity, 4),
            "patternVariety": round(self.pattern_variety, 4),
            "spacing": round(self.spacing, 4),
            "aggression": round(self.aggression, 4),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MappingControls":
        defaults = MappingControls()
        return cls(
            circle_density=float(payload.get("circleDensity", defaults.circle_density)),
            slider_density=float(payload.get("sliderDensity", defaults.slider_density)),
            spinner_frequency=float(payload.get("spinnerFrequency", defaults.spinner_frequency)),
            jump_intensity=float(payload.get("jumpIntensity", defaults.jump_intensity)),
            stream_intensity=float(payload.get("streamIntensity", defaults.stream_intensity)),
            burst_intensity=float(payload.get("burstIntensity", defaults.burst_intensity)),
            rhythm_complexity=float(payload.get("rhythmComplexity", defaults.rhythm_complexity)),
            pattern_variety=float(payload.get("patternVariety", defaults.pattern_variety)),
            spacing=float(payload.get("spacing", defaults.spacing)),
            aggression=float(payload.get("aggression", defaults.aggression)),
        ).clamped()


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingPreset:
    """A named preset that sets real mapping control values."""

    name: str
    label: str
    description: str
    controls: MappingControls


BALANCED_CONTROLS = MappingControls()
TECHNICAL_CONTROLS = MappingControls(
    circle_density=0.62,
    slider_density=0.42,
    spinner_frequency=0.38,
    jump_intensity=0.55,
    stream_intensity=0.7,
    burst_intensity=0.68,
    rhythm_complexity=0.78,
    pattern_variety=0.72,
    spacing=0.56,
    aggression=0.6,
)
AIM_CONTROLS = MappingControls(
    circle_density=0.55,
    slider_density=0.4,
    spinner_frequency=0.4,
    jump_intensity=0.8,
    stream_intensity=0.45,
    burst_intensity=0.45,
    rhythm_complexity=0.55,
    pattern_variety=0.65,
    spacing=0.72,
    aggression=0.68,
)
RHYTHM_CONTROLS = MappingControls(
    circle_density=0.62,
    slider_density=0.55,
    spinner_frequency=0.42,
    jump_intensity=0.42,
    stream_intensity=0.58,
    burst_intensity=0.6,
    rhythm_complexity=0.82,
    pattern_variety=0.6,
    spacing=0.48,
    aggression=0.55,
)
TOURNAMENT_CONTROLS = MappingControls(
    circle_density=0.55,
    slider_density=0.45,
    spinner_frequency=0.35,
    jump_intensity=0.55,
    stream_intensity=0.5,
    burst_intensity=0.5,
    rhythm_complexity=0.6,
    pattern_variety=0.55,
    spacing=0.55,
    aggression=0.5,
)

MAPPING_PRESETS: dict[str, MappingPreset] = {
    "balanced": MappingPreset(
        name="balanced",
        label="Balanced",
        description="Default general-purpose mapping.",
        controls=BALANCED_CONTROLS,
    ),
    "technical": MappingPreset(
        name="technical",
        label="Technical",
        description="Higher rhythm complexity and pattern density.",
        controls=TECHNICAL_CONTROLS,
    ),
    "aim": MappingPreset(
        name="aim",
        label="Aim",
        description="Higher movement and jump emphasis.",
        controls=AIM_CONTROLS,
    ),
    "rhythm": MappingPreset(
        name="rhythm",
        label="Rhythm",
        description="Higher rhythm complexity with controlled movement.",
        controls=RHYTHM_CONTROLS,
    ),
    "tournament": MappingPreset(
        name="tournament",
        label="Tournament",
        description="Stricter readability, consistency, and replay constraints.",
        controls=TOURNAMENT_CONTROLS,
    ),
}

MAPPING_PRESET_NAMES: tuple[str, ...] = tuple(MAPPING_PRESETS.keys())


def get_mapping_preset(name: str) -> MappingPreset:
    try:
        return MAPPING_PRESETS[name]
    except KeyError as error:
        allowed = ", ".join(MAPPING_PRESET_NAMES)
        raise ValueError(f'Unsupported mapping preset "{name}". Expected one of: {allowed}.') from error


def resolve_mapping_controls(
    preset_name: str,
    controls: MappingControls | None,
) -> MappingControls:
    """Resolve effective controls for a preset selection.

    ``custom`` keeps the user's exact controls; any other preset name takes
    the preset's stored values.
    """
    if preset_name == "custom" or preset_name not in MAPPING_PRESETS:
        return (controls or MappingControls()).clamped()
    return get_mapping_preset(preset_name).controls


# ---------------------------------------------------------------------------
# Aggression: a composite that resolves interactions in this layer.
#
# Each control is blended toward an "aggressive" target profile with its own
# influence weight. At aggression == 0.5 the blend factor is zero, so the
# control value passes through unchanged (identity). This deliberately avoids
# blindly multiplying every parameter: the blend strength differs per control
# and is capped so no single parameter can be pushed to an extreme.
# ---------------------------------------------------------------------------

_AGGRESSION_PROFILE: dict[str, float] = {
    "circle_density": 0.75,
    "slider_density": 0.55,
    "spinner_frequency": 0.4,
    "jump_intensity": 0.8,
    "stream_intensity": 0.62,
    "burst_intensity": 0.62,
    "rhythm_complexity": 0.72,
    "pattern_variety": 0.76,
    "spacing": 0.68,
}

_AGGRESSION_WEIGHTS: dict[str, float] = {
    "circle_density": 0.35,
    "slider_density": 0.2,
    "spinner_frequency": 0.12,
    "jump_intensity": 0.42,
    "stream_intensity": 0.28,
    "burst_intensity": 0.28,
    "rhythm_complexity": 0.3,
    "pattern_variety": 0.38,
    "spacing": 0.26,
}


def _apply_aggression(controls: MappingControls) -> MappingControls:
    """Blend controls toward the aggressive profile (identity at 0.5)."""
    signed = (controls.aggression - 0.5) * 2.0  # -1.0 .. 1.0
    if abs(signed) < 1e-9:
        return controls

    def blended(key: str) -> float:
        current = getattr(controls, key)
        target = _AGGRESSION_PROFILE[key]
        weight = _AGGRESSION_WEIGHTS[key]
        return clamp(current + signed * weight * (target - current), 0.0, 1.0)

    return MappingControls(
        circle_density=blended("circle_density"),
        slider_density=blended("slider_density"),
        spinner_frequency=blended("spinner_frequency"),
        jump_intensity=blended("jump_intensity"),
        stream_intensity=blended("stream_intensity"),
        burst_intensity=blended("burst_intensity"),
        rhythm_complexity=blended("rhythm_complexity"),
        pattern_variety=blended("pattern_variety"),
        spacing=blended("spacing"),
        aggression=controls.aggression,
    )


# ---------------------------------------------------------------------------
# Linear interpolation helpers (all identity at 0.5)
# ---------------------------------------------------------------------------


def _lerp_multiplier(value: float, low: float, high: float) -> float:
    """Map a 0..1 control to a multiplier that equals 1.0 at value 0.5."""
    if value <= 0.5:
        t = value / 0.5  # 0.0 .. 1.0
        return low + (1.0 - low) * t
    t = (value - 0.5) / 0.5  # 0.0 .. 1.0
    return 1.0 + (high - 1.0) * t


def _blend_gate(value: float, threshold: float = 0.5) -> bool:
    """Gate that stays off at the neutral value so identity is preserved.

    Only turns on strictly above the threshold, which keeps the base preset's
    own setting intact at the default control value (0.5).
    """
    return value > threshold


# ---------------------------------------------------------------------------
# Applying controls to a difficulty preset
# ---------------------------------------------------------------------------


def apply_mapping_controls(
    preset: DifficultyPreset,
    controls: MappingControls,
) -> DifficultyPreset:
    """Derive an effective difficulty preset from the base preset + controls.

    Deterministic and backward compatible: with default controls (all 0.5)
    the returned preset is identical to the input preset.
    """
    effective = _apply_aggression(controls.clamped())
    c = effective

    gap_multiplier = _lerp_multiplier(c.circle_density, 1.42, 0.66)
    min_gap_multiplier = _lerp_multiplier(c.circle_density, 1.3, 0.7)
    threshold_multiplier = _lerp_multiplier(c.circle_density, 1.14, 0.82)
    merge_multiplier = _lerp_multiplier(c.circle_density, 1.28, 0.72)

    # Slider density scales how many suitable musical events become sliders.
    slider_ratio_multiplier = _lerp_multiplier(c.slider_density, 0.45, 1.85)
    slider_quality_multiplier = _lerp_multiplier(c.slider_density, 1.12, 0.86)

    # Spinner frequency: 0 disables spinners entirely; otherwise it widens the
    # musical window (lower minimum gap) and lowers the musical threshold.
    if c.spinner_frequency <= 0.0:
        spinner_enabled = False
        spinner_min_gap_multiplier = 1.0
        spinner_musical_multiplier = 1.0
    else:
        spinner_enabled = True
        spinner_min_gap_multiplier = _lerp_multiplier(c.spinner_frequency, 2.0, 0.6)
        spinner_musical_multiplier = _lerp_multiplier(c.spinner_frequency, 1.12, 0.86)

    # Jump intensity scales movement strain (distance + cursor speed).
    jump_multiplier = _lerp_multiplier(c.jump_intensity, 0.74, 1.46)
    speed_multiplier = _lerp_multiplier(c.jump_intensity, 0.92, 1.16)

    # Spacing scales the general movement size; it combines with jump
    # intensity multiplicatively so both controls stay meaningful.
    spacing_multiplier = _lerp_multiplier(c.spacing, 0.8, 1.26)
    min_jump_multiplier = _lerp_multiplier(c.spacing, 0.88, 1.18)
    movement_multiplier = jump_multiplier * spacing_multiplier

    # Stream intensity demands finer timing resolution to support longer runs.
    stream_empty_gap_multiplier = _lerp_multiplier(c.stream_intensity, 1.3, 0.66)
    stream_confidence_multiplier = _lerp_multiplier(c.stream_intensity, 1.06, 0.86)

    # Burst intensity allows slightly tighter short bursts.
    burst_gap_multiplier = _lerp_multiplier(c.burst_intensity, 1.12, 0.8)

    # Rhythm complexity opens up off-beats, subdivisions, and syncopation.
    rhythm_gap_multiplier = _lerp_multiplier(c.rhythm_complexity, 1.24, 0.68)
    rhythm_confidence_multiplier = _lerp_multiplier(c.rhythm_complexity, 1.24, 0.62)
    rhythm_phrase_weight = _lerp_multiplier(c.rhythm_complexity, 0.72, 1.3)

    # Pattern variety trades repetition for switching between families.
    # Multipliers are identity at the neutral control value (0.5) so the
    # base preset's own pattern knobs are preserved by default.
    variation_multiplier = _lerp_multiplier(c.pattern_variety, 0.58, 1.5)
    switch_multiplier = _lerp_multiplier(c.pattern_variety, 1.6, 0.55)
    repetition_multiplier = _lerp_multiplier(c.pattern_variety, 1.7, 0.5)
    transition_multiplier = _lerp_multiplier(c.pattern_variety, 1.4, 0.62)

    return replace(
        preset,
        min_gap_ms=max(60, int(round(preset.min_gap_ms * min_gap_multiplier * burst_gap_multiplier))),
        target_gap_ms=max(90, int(round(preset.target_gap_ms * gap_multiplier * rhythm_gap_multiplier))),
        include_offbeat_onsets=(
            preset.include_offbeat_onsets or _blend_gate(c.rhythm_complexity, 0.5)
        ),
        onset_strength_threshold=clamp(
            preset.onset_strength_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        beat_strength_threshold=clamp(
            preset.beat_strength_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        strong_beat_threshold=clamp(
            preset.strong_beat_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        merge_tolerance_ms=max(20, int(round(preset.merge_tolerance_ms * merge_multiplier))),
        min_jump_distance=round(
            clamp(preset.min_jump_distance * min_jump_multiplier * movement_multiplier, 16.0, 120.0),
            1,
        ),
        preferred_jump_distance=round(
            clamp(preset.preferred_jump_distance * movement_multiplier, 40.0, 320.0),
            1,
        ),
        max_jump_distance=round(
            clamp(preset.max_jump_distance * movement_multiplier, 80.0, 460.0),
            1,
        ),
        max_cursor_speed=round(preset.max_cursor_speed * speed_multiplier, 1),
        pattern_variation=clamp(preset.pattern_variation * variation_multiplier, 0.05, 1.2),
        subdivision_enabled=preset.subdivision_enabled or _blend_gate(c.rhythm_complexity, 0.35),
        subdivision_fill_gaps=(
            preset.subdivision_fill_gaps
            or _blend_gate(c.rhythm_complexity, 0.5)
            or _blend_gate(c.stream_intensity, 0.5)
        ),
        max_empty_gap_ms=max(
            1200,
            int(round(preset.max_empty_gap_ms * stream_empty_gap_multiplier * rhythm_gap_multiplier)),
        ),
        min_timing_confidence=clamp(
            preset.min_timing_confidence * rhythm_confidence_multiplier * stream_confidence_multiplier,
            0.15,
            0.9,
        ),
        phrase_density_weight=clamp(preset.phrase_density_weight * rhythm_phrase_weight, 0.1, 1.4),
        pattern_switch_interval=max(
            2,
            int(round(preset.pattern_switch_interval * switch_multiplier)),
        ),
        max_pattern_repetition=max(
            1,
            int(round(preset.max_pattern_repetition * repetition_multiplier)),
        ),
        min_transition_score=clamp(
            preset.min_transition_score * transition_multiplier,
            12.0,
            80.0,
        ),
        slider_enabled=preset.slider_enabled and c.slider_density > 0.0,
        slider_max_ratio=clamp(preset.slider_max_ratio * slider_ratio_multiplier, 0.03, 0.55),
        slider_quality_threshold=clamp(
            preset.slider_quality_threshold * slider_quality_multiplier,
            20.0,
            70.0,
        ),
        spinner_enabled=spinner_enabled,
        spinner_min_gap_ms=max(
            800,
            int(round(preset.spinner_min_gap_ms * spinner_min_gap_multiplier)),
        ),
        spinner_musical_threshold=clamp(
            preset.spinner_musical_threshold * spinner_musical_multiplier,
            15.0,
            65.0,
        ),
        spinner_quality_threshold=clamp(
            preset.spinner_quality_threshold * slider_quality_multiplier,
            15.0,
            70.0,
        ),
    )


def build_position_variation_biases(controls: MappingControls) -> PositionVariation:
    """Derive base pattern biases from stream/burst/variety controls.

    All biases are signed offsets around the neutral control value (0.5), so
    the default configuration produces an all-zero bias profile (identity).
    These biases are applied to the default profile before per-candidate
    variation, so candidate diversity still layers on top deterministically.
    """
    effective = _apply_aggression(controls.clamped())
    return PositionVariation(
        stream_bias=round((effective.stream_intensity - 0.5) * 0.7, 4),
        burst_bias=round((effective.burst_intensity - 0.5) * 0.8, 4),
        pattern_switch_bias=round((effective.pattern_variety - 0.5) * 0.6, 4),
        novelty_weight=round(1.0 + (effective.pattern_variety - 0.5) * 1.0, 4),
        zigzag_bias=round((effective.pattern_variety - 0.5) * 0.44, 4),
        wave_bias=round((effective.pattern_variety - 0.5) * 0.4, 4),
        fan_bias=round((effective.pattern_variety - 0.5) * 0.36, 4),
        spiral_bias=round((effective.pattern_variety - 0.5) * 0.32, 4),
        direction_jitter_multiplier=round(
            1.0 + (effective.jump_intensity - 0.5) * 0.6, 4
        ),
    )


def build_pattern_config(preset: DifficultyPreset):
    """Build a PatternPipelineConfig from an effective preset.

    The preset already carries the pattern-intelligence knobs (Phase 10
    defaults), and ``apply_mapping_controls`` adjusts them, so this is the
    single source of truth for pattern switching behavior.
    """
    from .patterns.pattern_pipeline import PatternPipelineConfig

    return PatternPipelineConfig(
        pattern_intelligence_enabled=preset.pattern_intelligence_enabled,
        pattern_switch_interval=preset.pattern_switch_interval,
        max_pattern_repetition=preset.max_pattern_repetition,
        min_transition_score=preset.min_transition_score,
        enable_flow_optimization=preset.enable_flow_optimization,
        enable_heatmap_balancing=preset.enable_heatmap_balancing,
        enable_velocity_modeling=preset.enable_velocity_modeling,
    )


# ---------------------------------------------------------------------------
# Difficulty targets
# ---------------------------------------------------------------------------

TARGET_BY_TIER: dict[str, str] = {
    "easy": "easy",
    "normal": "normal",
    "hard": "hard",
}

CUSTOM_STAR_MIN = 0.5
CUSTOM_STAR_MAX = 12.0


def resolve_difficulty_target(
    difficulty: str,
    *,
    target_mode: str,
    custom_target_star: float | None,
    custom_min_star: float | None,
    custom_max_star: float | None,
) -> DifficultyTarget:
    """Resolve the difficulty target used by analysis and ranking.

    ``target_mode`` is ``"auto"`` (the tier's own band) or ``"custom"`` (the
    user's exact star band). Returns the tier target for unknown tiers so old
    callers keep working.
    """
    tier_name = TARGET_BY_TIER.get(difficulty, difficulty)
    tier_target = DIFFICULTY_TARGETS.get(tier_name)
    if target_mode != "custom":
        if tier_target is not None:
            return tier_target
        # Fall back to the named target (e.g. when difficulty is already a
        # target name such as "insane").
        try:
            return DIFFICULTY_TARGETS[difficulty]
        except KeyError:
            return DIFFICULTY_TARGETS["normal"]
    return build_custom_target(
        target_star=(
            custom_target_star
            if custom_target_star is not None
            else (tier_target.star_center if tier_target is not None else 3.0)
        ),
        min_star=(
            custom_min_star
            if custom_min_star is not None
            else (tier_target.star_range[0] if tier_target is not None else 1.0)
        ),
        max_star=(
            custom_max_star
            if custom_max_star is not None
            else (tier_target.star_range[1] if tier_target is not None else 6.0)
        ),
    )


def custom_star_adjustment(difficulty: str, target: DifficultyTarget) -> float:
    """Scale factor (-0.5..0.5) pulling generation toward a custom band.

    A custom target centered above the tier band makes maps denser with
    larger jumps; centered below makes them sparser and calmer. Returns 0.0
    for the tier's own target (or unknown tiers), keeping identity behavior.
    """
    tier_name = TARGET_BY_TIER.get(difficulty, difficulty)
    tier_target = DIFFICULTY_TARGETS.get(tier_name)
    if tier_target is None or target.name == tier_target.name:
        return 0.0
    tier_center = tier_target.star_center
    tier_span = max(0.5, (tier_target.star_range[1] - tier_target.star_range[0]) / 2.0)
    return clamp((target.star_center - tier_center) / tier_span, -0.5, 0.5)


def apply_custom_star_adjustment(
    preset: DifficultyPreset,
    adjustment: float,
) -> DifficultyPreset:
    """Adjust an effective preset toward a custom star band.

    The adjustment is small (capped at +/-0.5) and monotonic: higher custom
    bands produce denser, wider maps; lower bands produce sparser, calmer
    maps. Identity for adjustment == 0.
    """
    if abs(adjustment) < 1e-6:
        return preset
    gap_multiplier = 1.0 - adjustment * 0.28
    movement_multiplier = 1.0 + adjustment * 0.3
    threshold_multiplier = 1.0 - adjustment * 0.18
    return replace(
        preset,
        min_gap_ms=max(60, int(round(preset.min_gap_ms * gap_multiplier))),
        target_gap_ms=max(90, int(round(preset.target_gap_ms * gap_multiplier))),
        onset_strength_threshold=clamp(
            preset.onset_strength_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        beat_strength_threshold=clamp(
            preset.beat_strength_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        strong_beat_threshold=clamp(
            preset.strong_beat_threshold * threshold_multiplier,
            0.08,
            0.98,
        ),
        min_jump_distance=round(
            clamp(preset.min_jump_distance * movement_multiplier, 16.0, 120.0), 1
        ),
        preferred_jump_distance=round(
            clamp(preset.preferred_jump_distance * movement_multiplier, 40.0, 320.0), 1
        ),
        max_jump_distance=round(
            clamp(preset.max_jump_distance * movement_multiplier, 80.0, 460.0), 1
        ),
    )


def resolve_effective_preset(
    difficulty: str,
    *,
    preset_name: str = "balanced",
    controls: MappingControls | None = None,
    target_mode: str = "auto",
    custom_target_star: float | None = None,
    custom_min_star: float | None = None,
    custom_max_star: float | None = None,
) -> DifficultyPreset:
    """Full Phase 19 preset resolution used by the pipeline.

    Order of operations (all deterministic):

    1. Base tier preset (existing behavior).
    2. Mapping controls (identity at defaults).
    3. Custom star band adjustment (identity for auto target).
    """
    base = get_difficulty_preset(difficulty)
    effective_controls = resolve_mapping_controls(preset_name, controls)
    adjusted = apply_mapping_controls(base, effective_controls)
    if target_mode == "custom":
        target = resolve_difficulty_target(
            difficulty,
            target_mode=target_mode,
            custom_target_star=custom_target_star,
            custom_min_star=custom_min_star,
            custom_max_star=custom_max_star,
        )
        adjusted = apply_custom_star_adjustment(
            adjusted,
            custom_star_adjustment(difficulty, target),
        )
    return adjusted


# ---------------------------------------------------------------------------
# Section sensitivity
# ---------------------------------------------------------------------------


def build_section_config(section_sensitivity: float) -> Any:
    """Build a SectionPipelineConfig scaled by the section sensitivity control.

    Higher sensitivity detects more (shorter, finer) section boundaries by
    lowering the boundary detection threshold and raising the boundary cap.
    Identity at the neutral value (0.5).
    """
    from .sections.section_config import (
        SectionDetectionConfig,
        SectionPipelineConfig,
    )

    sensitivity = clamp(float(section_sensitivity), 0.0, 1.0)
    boundary_threshold = round(0.72 - (sensitivity - 0.5) * 0.5, 4)
    max_boundary_count = max(6, int(round(12 + (sensitivity - 0.5) * 8)))
    min_section_duration_ms = max(4000, int(round(6000 - (sensitivity - 0.5) * 2000)))
    return SectionPipelineConfig(
        detection=SectionDetectionConfig(
            min_section_duration_ms=min_section_duration_ms,
            boundary_threshold=boundary_threshold,
            max_boundary_count=max_boundary_count,
        )
    )


# ---------------------------------------------------------------------------
# Validation warnings
# ---------------------------------------------------------------------------


def validate_mapping_controls(
    difficulty: str,
    *,
    preset_name: str = "balanced",
    controls: MappingControls | None = None,
    target_mode: str = "auto",
    custom_target_star: float | None = None,
    custom_min_star: float | None = None,
    custom_max_star: float | None = None,
) -> list[str]:
    """Return readable warnings for conflicting or extreme combinations.

    Warnings never override user settings; they only explain the conflict and
    recommend safer values.
    """
    effective = resolve_mapping_controls(preset_name, controls).clamped()
    warnings: list[str] = []

    if effective.circle_density >= 0.75 and effective.spacing <= 0.3:
        warnings.append(
            "Very high circle density with very low spacing produces cramped, "
            "unreadable patterns. Consider raising Spacing to 45% or higher, "
            "or lowering Circle Density."
        )

    if difficulty == "easy" and effective.jump_intensity >= 0.75:
        warnings.append(
            "Excessive jump intensity for Easy. Easy maps should keep jumps "
            "moderate; 75%+ jump intensity may exceed beginner movement limits."
        )

    if (
        effective.stream_intensity >= 0.7
        and effective.rhythm_complexity <= 0.35
    ):
        warnings.append(
            "High stream intensity needs finer timing resolution. Raise Rhythm "
            "Complexity to 40%+ so streams can be subdivided musically."
        )

    if effective.spinner_frequency >= 0.8:
        warnings.append(
            "Very high spinner frequency risks spinner spam. Spinners are only "
            "inserted where the music justifies them, but values above 80% may "
            "interrupt flow."
        )

    if (
        effective.circle_density >= 0.8
        and effective.slider_density >= 0.7
    ):
        warnings.append(
            "Extremely high circle density combined with high slider density "
            "produces a very packed map. Consider lowering one of them."
        )

    if (
        effective.jump_intensity >= 0.8
        and effective.spacing >= 0.8
    ):
        warnings.append(
            "Very high jump intensity with very wide spacing creates large "
            "cross-screen movements that may exceed comfortable cursor speed."
        )

    if target_mode == "custom":
        try:
            build_custom_target(
                target_star=custom_target_star,
                min_star=custom_min_star,
                max_star=custom_max_star,
            )
        except ValueError as error:
            warnings.append(str(error))

    return warnings
