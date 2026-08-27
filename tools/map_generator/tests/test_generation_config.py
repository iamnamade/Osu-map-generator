from __future__ import annotations

import unittest
from dataclasses import asdict

from tools.map_generator.config import get_difficulty_preset
from tools.map_generator.difficulty.targets import build_custom_target
from tools.map_generator.event_selector import select_events
from tools.map_generator.generation_config import (
    MAPPING_PRESETS,
    MappingControls,
    apply_custom_star_adjustment,
    apply_mapping_controls,
    build_position_variation_biases,
    build_section_config,
    custom_star_adjustment,
    get_mapping_preset,
    resolve_difficulty_target,
    resolve_effective_preset,
    resolve_mapping_controls,
    validate_mapping_controls,
)
from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    EnergyRegion,
    TimedStrength,
)

TIERS = ("easy", "normal", "hard")


def make_analysis(
    *,
    duration_ms: int = 6_000,
    beats: list[int] | None = None,
    onsets: list[tuple[int, float]] | None = None,
    default_energy: float = 0.45,
) -> AudioAnalysis:
    """Synthetic analysis with strong beats and medium-strength off-beat onsets.

    Medium-strength onsets let the density control's threshold changes decide
    whether extra musical events survive selection.
    """
    beats = beats or [1_000, 2_000, 3_000, 4_000, 5_000]
    onsets = onsets or [
        (1_500, 0.5),
        (2_500, 0.5),
        (3_500, 0.5),
        (4_500, 0.5),
    ]
    frames = [
        EnergyFrame(time_ms=time_ms, value=default_energy)
        for time_ms in range(0, duration_ms + 1, 250)
    ]
    return AudioAnalysis(
        audio_filename="test-song.mp3",
        duration_ms=duration_ms,
        sample_rate=22_050,
        bpm=120.0,
        offset_ms=1_000,
        beats=[TimedStrength(time_ms=time_ms, strength=1.0) for time_ms in beats],
        onsets=[TimedStrength(time_ms=time_ms, strength=strength) for time_ms, strength in onsets],
        energy_frames=frames,
        quiet_regions=[EnergyRegion(start_ms=5_500, end_ms=6_000, average_value=0.05)],
        high_energy_regions=[EnergyRegion(start_ms=2_000, end_ms=3_000, average_value=1.0)],
    )


class IdentityMappingTests(unittest.TestCase):
    def test_default_controls_preserve_base_presets(self) -> None:
        for difficulty in TIERS:
            base = get_difficulty_preset(difficulty)
            effective = apply_mapping_controls(base, MappingControls())
            # Compare as dicts with float tolerance — round(x, 1) returns float
            # but the base preset may store ints, so exact equality can drift.
            base_d = asdict(base)
            eff_d = asdict(effective)
            for key in base_d:
                bv, ev = base_d[key], eff_d[key]
                if isinstance(bv, (int, float)) and isinstance(ev, (int, float)):
                    self.assertAlmostEqual(bv, ev, places=3, msg=f"{difficulty}.{key} drifted")
                else:
                    self.assertEqual(bv, ev, msg=f"{difficulty}.{key} drifted")

    def test_default_resolution_equals_base_preset(self) -> None:
        for difficulty in TIERS:
            resolved = resolve_effective_preset(difficulty)
            base_d = asdict(get_difficulty_preset(difficulty))
            res_d = asdict(resolved)
            for key in base_d:
                bv, ev = base_d[key], res_d[key]
                if isinstance(bv, (int, float)) and isinstance(ev, (int, float)):
                    self.assertAlmostEqual(bv, ev, places=3, msg=f"{difficulty}.{key} drifted")
                else:
                    self.assertEqual(bv, ev, msg=f"{difficulty}.{key} drifted")

    def test_mapping_is_deterministic(self) -> None:
        controls = MappingControls(
            circle_density=0.7,
            slider_density=0.3,
            jump_intensity=0.8,
            rhythm_complexity=0.6,
            pattern_variety=0.75,
            aggression=0.65,
        )
        base = get_difficulty_preset("hard")
        first = asdict(apply_mapping_controls(base, controls))
        second = asdict(apply_mapping_controls(base, controls))
        self.assertEqual(first, second)


class PresetTests(unittest.TestCase):
    def test_all_presets_are_registered(self) -> None:
        self.assertEqual(
            set(MAPPING_PRESETS),
            {"balanced", "technical", "aim", "rhythm", "tournament"},
        )

    def test_presets_are_distinct_from_balanced(self) -> None:
        balanced = MAPPING_PRESETS["balanced"].controls
        for name in ("technical", "aim", "rhythm", "tournament"):
            preset = MAPPING_PRESETS[name]
            self.assertNotEqual(
                preset.controls.to_dict(),
                balanced.to_dict(),
                f"{name} preset should differ from balanced",
            )

    def test_named_preset_overrides_user_controls(self) -> None:
        user_controls = MappingControls(circle_density=0.9)
        effective = resolve_mapping_controls("aim", user_controls)
        self.assertEqual(effective, MAPPING_PRESETS["aim"].controls)

    def test_custom_preset_keeps_user_controls(self) -> None:
        user_controls = MappingControls(circle_density=0.9)
        effective = resolve_mapping_controls("custom", user_controls)
        self.assertEqual(effective, user_controls)

    def test_unknown_preset_falls_back_to_custom(self) -> None:
        user_controls = MappingControls(circle_density=0.9)
        effective = resolve_mapping_controls("unknown-name", user_controls)
        self.assertEqual(effective, user_controls)

    def test_get_mapping_preset_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            get_mapping_preset("does-not-exist")


class CircleDensityTests(unittest.TestCase):
    def test_density_scales_event_selection(self) -> None:
        analysis = make_analysis()
        base = get_difficulty_preset("hard")
        sparse = apply_mapping_controls(base, MappingControls(circle_density=0.1))
        dense = apply_mapping_controls(base, MappingControls(circle_density=0.9))
        self.assertLess(sparse.target_gap_ms, base.target_gap_ms * 1.6)
        self.assertGreater(dense.target_gap_ms, 100)
        self.assertLess(dense.target_gap_ms, sparse.target_gap_ms)

        sparse_events = select_events(analysis, sparse)
        dense_events = select_events(analysis, dense)
        self.assertGreaterEqual(len(dense_events), len(sparse_events))

    def test_density_raises_onset_thresholds_at_low_end(self) -> None:
        base = get_difficulty_preset("normal")
        sparse = apply_mapping_controls(base, MappingControls(circle_density=0.05))
        dense = apply_mapping_controls(base, MappingControls(circle_density=0.95))
        self.assertGreater(sparse.onset_strength_threshold, dense.onset_strength_threshold)


class SliderDensityTests(unittest.TestCase):
    def test_slider_density_scales_max_ratio(self) -> None:
        base = get_difficulty_preset("hard")
        low = apply_mapping_controls(base, MappingControls(slider_density=0.1))
        high = apply_mapping_controls(base, MappingControls(slider_density=0.9))
        self.assertGreater(high.slider_max_ratio, low.slider_max_ratio)

    def test_slider_density_zero_disables_sliders(self) -> None:
        base = get_difficulty_preset("hard")
        self.assertTrue(base.slider_enabled)
        disabled = apply_mapping_controls(base, MappingControls(slider_density=0.0))
        self.assertFalse(disabled.slider_enabled)


class SpinnerFrequencyTests(unittest.TestCase):
    def test_zero_frequency_disables_spinners(self) -> None:
        base = get_difficulty_preset("normal")
        self.assertTrue(base.spinner_enabled)
        disabled = apply_mapping_controls(base, MappingControls(spinner_frequency=0.0))
        self.assertFalse(disabled.spinner_enabled)

    def test_higher_frequency_widens_spinner_windows(self) -> None:
        base = get_difficulty_preset("normal")
        low = apply_mapping_controls(base, MappingControls(spinner_frequency=0.2))
        high = apply_mapping_controls(base, MappingControls(spinner_frequency=0.9))
        self.assertLess(high.spinner_min_gap_ms, low.spinner_min_gap_ms)


class JumpIntensityTests(unittest.TestCase):
    def test_jump_intensity_scales_movement(self) -> None:
        base = get_difficulty_preset("hard")
        calm = apply_mapping_controls(base, MappingControls(jump_intensity=0.1))
        intense = apply_mapping_controls(base, MappingControls(jump_intensity=0.9))
        self.assertGreater(intense.preferred_jump_distance, calm.preferred_jump_distance)
        self.assertGreater(intense.max_jump_distance, calm.max_jump_distance)
        self.assertGreater(intense.max_cursor_speed, calm.max_cursor_speed)


class SpacingTests(unittest.TestCase):
    def test_spacing_scales_distances(self) -> None:
        base = get_difficulty_preset("normal")
        compact = apply_mapping_controls(base, MappingControls(spacing=0.1))
        wide = apply_mapping_controls(base, MappingControls(spacing=0.9))
        self.assertGreater(wide.preferred_jump_distance, compact.preferred_jump_distance)
        self.assertGreater(wide.max_jump_distance, compact.max_jump_distance)

    def test_spacing_and_jump_combine(self) -> None:
        base = get_difficulty_preset("normal")
        both = apply_mapping_controls(
            base,
            MappingControls(jump_intensity=0.9, spacing=0.9),
        )
        jump_only = apply_mapping_controls(
            base,
            MappingControls(jump_intensity=0.9, spacing=0.5),
        )
        self.assertGreater(both.max_jump_distance, jump_only.max_jump_distance)


class StreamBurstTests(unittest.TestCase):
    def test_stream_intensity_tightens_timing_resolution(self) -> None:
        base = get_difficulty_preset("normal")
        neutral = apply_mapping_controls(base, MappingControls())
        streams = apply_mapping_controls(base, MappingControls(stream_intensity=0.9))
        self.assertTrue(streams.subdivision_fill_gaps)
        self.assertLess(streams.max_empty_gap_ms, neutral.max_empty_gap_ms)
        self.assertLessEqual(
            streams.min_timing_confidence,
            neutral.min_timing_confidence,
        )

    def test_stream_and_burst_biases_are_real(self) -> None:
        neutral = build_position_variation_biases(MappingControls())
        self.assertEqual(neutral.stream_bias, 0.0)
        self.assertEqual(neutral.burst_bias, 0.0)
        intense = build_position_variation_biases(
            MappingControls(stream_intensity=0.9, burst_intensity=0.9)
        )
        self.assertGreater(intense.stream_bias, 0.0)
        self.assertGreater(intense.burst_bias, 0.0)
        calm = build_position_variation_biases(
            MappingControls(stream_intensity=0.1, burst_intensity=0.1)
        )
        self.assertLess(calm.stream_bias, 0.0)
        self.assertLess(calm.burst_bias, 0.0)


class RhythmComplexityTests(unittest.TestCase):
    def test_high_complexity_opens_offbeats_and_subdivisions(self) -> None:
        base = get_difficulty_preset("easy")
        self.assertFalse(base.include_offbeat_onsets)
        complex_rhythm = apply_mapping_controls(
            base,
            MappingControls(rhythm_complexity=0.9),
        )
        self.assertTrue(complex_rhythm.include_offbeat_onsets)
        self.assertTrue(complex_rhythm.subdivision_enabled)
        self.assertLess(
            complex_rhythm.min_timing_confidence,
            base.min_timing_confidence,
        )
        self.assertGreater(
            complex_rhythm.phrase_density_weight,
            base.phrase_density_weight,
        )


class PatternVarietyTests(unittest.TestCase):
    def test_variety_switches_patterns_more_often(self) -> None:
        base = get_difficulty_preset("hard")
        repetitive = apply_mapping_controls(base, MappingControls(pattern_variety=0.1))
        varied = apply_mapping_controls(base, MappingControls(pattern_variety=0.9))
        self.assertLessEqual(varied.pattern_switch_interval, repetitive.pattern_switch_interval)
        self.assertLessEqual(varied.max_pattern_repetition, repetitive.max_pattern_repetition)
        self.assertGreater(varied.pattern_variation, repetitive.pattern_variation)
        self.assertLessEqual(varied.min_transition_score, repetitive.min_transition_score)


class AggressionTests(unittest.TestCase):
    def test_aggression_is_identity_at_neutral(self) -> None:
        base = get_difficulty_preset("hard")
        with_aggression = apply_mapping_controls(base, MappingControls(aggression=0.5))
        base_d = asdict(base)
        eff_d = asdict(with_aggression)
        for key in base_d:
            bv, ev = base_d[key], eff_d[key]
            if isinstance(bv, (int, float)) and isinstance(ev, (int, float)):
                self.assertAlmostEqual(bv, ev, places=3, msg=f"{key} drifted at neutral")
            else:
                self.assertEqual(bv, ev, msg=f"{key} drifted at neutral")

    def test_aggression_pulls_controls_toward_profile(self) -> None:
        base = get_difficulty_preset("normal")
        calm = apply_mapping_controls(base, MappingControls(aggression=0.0))
        aggressive = apply_mapping_controls(base, MappingControls(aggression=1.0))
        self.assertLess(calm.target_gap_ms, base.target_gap_ms * 1.5)
        self.assertGreaterEqual(aggressive.target_gap_ms, 90)
        self.assertGreater(aggressive.preferred_jump_distance, calm.preferred_jump_distance)
        self.assertGreater(aggressive.pattern_variation, calm.pattern_variation)

    def test_aggression_does_not_push_every_parameter(self) -> None:
        # Spinner frequency has a low aggression influence and should not be
        # driven to extremes by the composite alone.
        base = get_difficulty_preset("hard")
        aggressive = apply_mapping_controls(base, MappingControls(aggression=1.0))
        self.assertGreater(aggressive.spinner_min_gap_ms, 800)


class CustomDifficultyTests(unittest.TestCase):
    def test_build_custom_target_valid_band(self) -> None:
        target = build_custom_target(target_star=5.0, min_star=4.0, max_star=6.0)
        self.assertEqual(target.name, "custom")
        self.assertEqual(target.star_range, (4.0, 6.0))
        self.assertEqual(target.star_center, 5.0)

    def test_build_custom_target_rejects_impossible_range(self) -> None:
        with self.assertRaises(ValueError):
            build_custom_target(target_star=8.0, min_star=9.0, max_star=7.0)
        with self.assertRaises(ValueError):
            build_custom_target(target_star=0.2, min_star=0.1, max_star=0.4)

    def test_resolve_target_auto_uses_tier(self) -> None:
        target = resolve_difficulty_target(
            "hard",
            target_mode="auto",
            custom_target_star=None,
            custom_min_star=None,
            custom_max_star=None,
        )
        self.assertEqual(target.name, "hard")

    def test_resolve_target_custom_uses_band(self) -> None:
        target = resolve_difficulty_target(
            "hard",
            target_mode="custom",
            custom_target_star=6.0,
            custom_min_star=5.0,
            custom_max_star=7.0,
        )
        self.assertEqual(target.name, "custom")
        self.assertEqual(target.star_range, (5.0, 7.0))

    def test_custom_band_above_tier_densifies_map(self) -> None:
        base = get_difficulty_preset("hard")
        target = resolve_difficulty_target(
            "hard",
            target_mode="custom",
            custom_target_star=6.0,
            custom_min_star=5.0,
            custom_max_star=7.0,
        )
        adjustment = custom_star_adjustment("hard", target)
        self.assertGreater(adjustment, 0.0)
        adjusted = apply_custom_star_adjustment(base, adjustment)
        self.assertLess(adjusted.target_gap_ms, base.target_gap_ms)
        self.assertGreater(adjusted.max_jump_distance, base.max_jump_distance)

    def test_effective_preset_applies_custom_band(self) -> None:
        resolved = resolve_effective_preset(
            "hard",
            preset_name="custom",
            controls=MappingControls(),
            target_mode="custom",
            custom_target_star=6.0,
            custom_min_star=5.0,
            custom_max_star=7.0,
        )
        self.assertLess(resolved.target_gap_ms, get_difficulty_preset("hard").target_gap_ms)


class ValidationWarningTests(unittest.TestCase):
    def test_density_spacing_conflict(self) -> None:
        warnings = validate_mapping_controls(
            "hard",
            preset_name="custom",
            controls=MappingControls(circle_density=0.9, spacing=0.1),
        )
        self.assertTrue(any("cramped" in warning for warning in warnings))

    def test_easy_jump_conflict(self) -> None:
        warnings = validate_mapping_controls(
            "easy",
            preset_name="custom",
            controls=MappingControls(jump_intensity=0.9),
        )
        self.assertTrue(any("Easy" in warning for warning in warnings))

    def test_stream_without_rhythm_resolution_warning(self) -> None:
        warnings = validate_mapping_controls(
            "hard",
            preset_name="custom",
            controls=MappingControls(stream_intensity=0.9, rhythm_complexity=0.2),
        )
        self.assertTrue(any("timing resolution" in warning for warning in warnings))

    def test_spinner_spam_warning(self) -> None:
        warnings = validate_mapping_controls(
            "hard",
            preset_name="custom",
            controls=MappingControls(spinner_frequency=0.95),
        )
        self.assertTrue(any("spinner spam" in warning for warning in warnings))

    def test_impossible_custom_range_warning(self) -> None:
        warnings = validate_mapping_controls(
            "hard",
            preset_name="custom",
            controls=MappingControls(),
            target_mode="custom",
            custom_target_star=9.0,
            custom_min_star=2.0,
            custom_max_star=4.0,
        )
        self.assertTrue(any("impossible" in warning for warning in warnings))

    def test_no_warnings_for_balanced_defaults(self) -> None:
        warnings = validate_mapping_controls(
            "hard",
            preset_name="custom",
            controls=MappingControls(),
        )
        self.assertEqual(warnings, [])


class BackwardCompatibilityTests(unittest.TestCase):
    def test_from_dict_ignores_missing_keys(self) -> None:
        controls = MappingControls.from_dict({})
        self.assertEqual(controls, MappingControls())

    def test_from_dict_clamps_out_of_range(self) -> None:
        controls = MappingControls.from_dict({"circleDensity": 3.0, "spacing": -1.0})
        self.assertEqual(controls.circle_density, 1.0)
        self.assertEqual(controls.spacing, 0.0)

    def test_section_sensitivity_is_real(self) -> None:
        low = build_section_config(0.1)
        high = build_section_config(0.9)
        self.assertGreater(low.detection.boundary_threshold, high.detection.boundary_threshold)
        self.assertGreaterEqual(
            high.detection.max_boundary_count,
            low.detection.max_boundary_count,
        )


if __name__ == "__main__":
    unittest.main()
