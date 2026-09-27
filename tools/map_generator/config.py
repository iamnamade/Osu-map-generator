from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DifficultyName = Literal["easy", "normal", "hard"]


@dataclass(frozen=True)
class DifficultyPreset:
    """Tunable rules for selecting events and placing circles."""

    name: DifficultyName
    min_gap_ms: int
    target_gap_ms: int
    include_offbeat_onsets: bool
    onset_strength_threshold: float
    beat_strength_threshold: float
    strong_beat_threshold: float
    merge_tolerance_ms: int
    circle_radius: int
    approach_time_ms: int
    min_jump_distance: float
    preferred_jump_distance: float
    max_jump_distance: float
    max_cursor_speed: float
    pattern_variation: float
    start_padding_ms: int
    end_padding_ms: int
    safe_margin: int
    quiet_energy_threshold: float
    high_energy_threshold: float
    # Rhythm intelligence parameters (Phase 9)
    rhythm_intelligence_enabled: bool = True
    subdivision_enabled: bool = True
    subdivision_fill_gaps: bool = True
    max_empty_gap_ms: int = 3000
    min_timing_confidence: float = 0.35
    phrase_density_weight: float = 0.4
    # Pattern intelligence parameters (Phase 10)
    pattern_intelligence_enabled: bool = True
    pattern_switch_interval: int = 4
    max_pattern_repetition: int = 3
    min_transition_score: float = 30.0
    enable_flow_optimization: bool = True
    enable_heatmap_balancing: bool = True
    enable_velocity_modeling: bool = True
    # Slider intelligence parameters (Phase 11)
    slider_enabled: bool = False
    slider_max_ratio: float = 0.25
    slider_min_ratio: float = 0.0
    slider_quality_threshold: float = 40.0
    slider_min_length_ms: int = 80
    slider_max_length_ms: int = 600
    # Spinner intelligence parameters (Phase 12)
    spinner_enabled: bool = False
    spinner_min_gap_ms: int = 1600
    spinner_min_duration_ms: int = 800
    spinner_max_duration_ms: int = 3000
    spinner_musical_threshold: float = 45.0
    spinner_quality_threshold: float = 45.0
    spinner_recovery_after_ms: int = 350
    spinner_entry_buffer_ms: int = 150
    spinner_easy_target_ms: int = 1400
    spinner_normal_target_ms: int = 1800
    spinner_hard_target_ms: int = 2400
    # Aggressive density enforcement (Phase 24)
    min_density_target: float = 0.0  # minimum objects/sec (0 = disabled)
    target_density: float = 0.0  # target objects/sec (0 = disabled)
    min_spinner_count: int = 0  # minimum spinners to place (0 = disabled)


DIFFICULTY_PRESETS: dict[DifficultyName, DifficultyPreset] = {
    "easy": DifficultyPreset(
        name="easy",
        min_gap_ms=420,
        target_gap_ms=880,
        include_offbeat_onsets=False,
        onset_strength_threshold=0.55,
        beat_strength_threshold=0.24,
        strong_beat_threshold=0.62,
        merge_tolerance_ms=70,
        circle_radius=46,
        approach_time_ms=1200,
        min_jump_distance=38,
        preferred_jump_distance=92,
        max_jump_distance=164,
        max_cursor_speed=470,
        pattern_variation=0.25,
        start_padding_ms=950,
        end_padding_ms=850,
        safe_margin=22,
        quiet_energy_threshold=0.14,
        high_energy_threshold=0.62,
        rhythm_intelligence_enabled=True,
        subdivision_enabled=True,
        subdivision_fill_gaps=True,
        max_empty_gap_ms=2400,
        min_timing_confidence=0.25,
        phrase_density_weight=0.5,
        pattern_intelligence_enabled=True,
        pattern_switch_interval=5,
        max_pattern_repetition=2,
        min_transition_score=35.0,
        enable_flow_optimization=True,
        enable_heatmap_balancing=True,
        enable_velocity_modeling=True,
        slider_enabled=True,
        slider_max_ratio=0.35,
        slider_min_ratio=0.15,
        slider_quality_threshold=32.0,
        slider_min_length_ms=100,
        slider_max_length_ms=350,
        spinner_enabled=True,
        spinner_min_gap_ms=1200,
        spinner_min_duration_ms=600,
        spinner_max_duration_ms=2400,
        spinner_musical_threshold=32.0,
        spinner_quality_threshold=32.0,
        spinner_recovery_after_ms=400,
        spinner_entry_buffer_ms=160,
        spinner_easy_target_ms=1200,
        spinner_normal_target_ms=1500,
        spinner_hard_target_ms=1800,
        # Moderate density enforcement
        min_density_target=0.8,
        target_density=1.2,
        min_spinner_count=1,
    ),
    "normal": DifficultyPreset(
        name="normal",
        min_gap_ms=240,
        target_gap_ms=580,
        include_offbeat_onsets=True,
        onset_strength_threshold=0.42,
        beat_strength_threshold=0.18,
        strong_beat_threshold=0.55,
        merge_tolerance_ms=44,
        circle_radius=40,
        approach_time_ms=950,
        min_jump_distance=54,
        preferred_jump_distance=132,
        max_jump_distance=224,
        max_cursor_speed=660,
        pattern_variation=0.48,
        start_padding_ms=850,
        end_padding_ms=700,
        safe_margin=20,
        quiet_energy_threshold=0.12,
        high_energy_threshold=0.58,
        rhythm_intelligence_enabled=True,
        subdivision_enabled=True,
        subdivision_fill_gaps=True,
        max_empty_gap_ms=1800,
        min_timing_confidence=0.22,
        phrase_density_weight=0.65,
        pattern_intelligence_enabled=True,
        pattern_switch_interval=4,
        max_pattern_repetition=3,
        min_transition_score=22.0,
        enable_flow_optimization=True,
        enable_heatmap_balancing=True,
        enable_velocity_modeling=True,
        slider_enabled=True,
        slider_max_ratio=0.45,
        slider_min_ratio=0.35,
        slider_quality_threshold=24.0,
        slider_min_length_ms=80,
        slider_max_length_ms=500,
        spinner_enabled=True,
        spinner_min_gap_ms=1000,
        spinner_min_duration_ms=700,
        spinner_max_duration_ms=3200,
        spinner_musical_threshold=28.0,
        spinner_quality_threshold=28.0,
        spinner_recovery_after_ms=300,
        spinner_entry_buffer_ms=120,
        spinner_easy_target_ms=1400,
        spinner_normal_target_ms=1800,
        spinner_hard_target_ms=2200,
        # Aggressive density enforcement
        min_density_target=1.3,
        target_density=1.8,
        min_spinner_count=1,
    ),
    "hard": DifficultyPreset(
        name="hard",
        min_gap_ms=140,
        target_gap_ms=340,
        include_offbeat_onsets=True,
        onset_strength_threshold=0.30,
        beat_strength_threshold=0.14,
        strong_beat_threshold=0.48,
        merge_tolerance_ms=36,
        circle_radius=34,
        approach_time_ms=720,
        min_jump_distance=72,
        preferred_jump_distance=170,
        max_jump_distance=272,
        max_cursor_speed=860,
        pattern_variation=0.74,
        start_padding_ms=700,
        end_padding_ms=600,
        safe_margin=18,
        quiet_energy_threshold=0.10,
        high_energy_threshold=0.52,
        rhythm_intelligence_enabled=True,
        subdivision_enabled=True,
        subdivision_fill_gaps=True,
        max_empty_gap_ms=1400,
        min_timing_confidence=0.18,
        phrase_density_weight=0.75,
        pattern_intelligence_enabled=True,
        pattern_switch_interval=3,
        max_pattern_repetition=4,
        min_transition_score=18.0,
        enable_flow_optimization=True,
        enable_heatmap_balancing=True,
        enable_velocity_modeling=True,
        slider_enabled=True,
        slider_max_ratio=0.50,
        slider_min_ratio=0.35,
        slider_quality_threshold=20.0,
        slider_min_length_ms=80,
        slider_max_length_ms=600,
        spinner_enabled=True,
        spinner_min_gap_ms=900,
        spinner_min_duration_ms=800,
        spinner_max_duration_ms=3500,
        spinner_musical_threshold=22.0,
        spinner_quality_threshold=22.0,
        spinner_recovery_after_ms=250,
        spinner_entry_buffer_ms=100,
        spinner_easy_target_ms=1600,
        spinner_normal_target_ms=2000,
        spinner_hard_target_ms=2800,
        # Aggressive density enforcement
        min_density_target=2.2,
        target_density=3.2,
        min_spinner_count=1,
    ),
}


def get_difficulty_preset(name: str) -> DifficultyPreset:
    try:
        return DIFFICULTY_PRESETS[name]  # type: ignore[index]
    except KeyError as error:
        allowed = ", ".join(DIFFICULTY_PRESETS)
        raise ValueError(f'Unsupported difficulty "{name}". Expected one of: {allowed}.') from error
