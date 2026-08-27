"""Tests for the rhythm density, gap enforcement, slider/spinner activation,
and dead zone prevention fixes (osu! mapping standards alignment).

Covers:
  - Difficulty presets: sliders enabled for Normal/Easy, gap/density params
  - Rhythm density config: energy thresholds, min/max density bounds
  - Max gap enforcement during active audio sections
  - Slider probability thresholds per difficulty
  - Sustained analysis thresholds
  - Gap computation for energy-based max gaps
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from tools.map_generator.config import DIFFICULTY_PRESETS, DifficultyPreset
from tools.map_generator.models import EnergyFrame, AudioAnalysis


# ---------------------------------------------------------------------------
# 1. Difficulty Preset Validation
# ---------------------------------------------------------------------------

class DifficultyPresetSliderTests(unittest.TestCase):
    """Sliders must be enabled for Normal and Hard difficulties."""

    def test_easy_slider_enabled(self) -> None:
        preset = DIFFICULTY_PRESETS["easy"]
        self.assertTrue(preset.slider_enabled, "Easy must have sliders enabled")

    def test_normal_slider_enabled(self) -> None:
        preset = DIFFICULTY_PRESETS["normal"]
        self.assertTrue(preset.slider_enabled, "Normal must have sliders enabled")

    def test_hard_slider_enabled(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        self.assertTrue(preset.slider_enabled, "Hard must have sliders enabled")

    def test_slider_max_ratio_targets_osu_standards(self) -> None:
        """Target ~25-40% slider ratio per osu! mapping standards."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreaterEqual(easy.slider_max_ratio, 0.20)
        self.assertLessEqual(easy.slider_max_ratio, 0.35)
        self.assertGreaterEqual(normal.slider_max_ratio, 0.30)
        self.assertLessEqual(normal.slider_max_ratio, 0.50)
        self.assertGreaterEqual(hard.slider_max_ratio, 0.30)
        self.assertLessEqual(hard.slider_max_ratio, 0.55)

    def test_slider_quality_thresholds_reasonable(self) -> None:
        """Quality thresholds should be low enough to allow slider placement."""
        for name in ("easy", "normal", "hard"):
            preset = DIFFICULTY_PRESETS[name]
            self.assertLessEqual(
                preset.slider_quality_threshold, 50.0,
                f"{name} slider quality threshold too high",
            )
            self.assertGreaterEqual(
                preset.slider_quality_threshold, 20.0,
                f"{name} slider quality threshold too low",
            )


class DifficultyPresetGapTests(unittest.TestCase):
    """Max empty gap must be bounded per osu! mapping standards."""

    def test_max_empty_gap_decreases_with_difficulty(self) -> None:
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreaterEqual(easy.max_empty_gap_ms, normal.max_empty_gap_ms)
        self.assertGreaterEqual(normal.max_empty_gap_ms, hard.max_empty_gap_ms)

    def test_max_empty_gap_hard_not_exceeding_2s(self) -> None:
        """Hard: max gap during active audio must NOT exceed 2.0 seconds."""
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertLessEqual(hard.max_empty_gap_ms, 2000)

    def test_max_empty_gap_normal_not_exceeding_3s(self) -> None:
        """Normal: max gap should be at most 3.0 seconds."""
        normal = DIFFICULTY_PRESETS["normal"]
        self.assertLessEqual(normal.max_empty_gap_ms, 3000)

    def test_max_empty_gap_easy_not_exceeding_4s(self) -> None:
        """Easy: max gap should be at most 4.0 seconds."""
        easy = DIFFICULTY_PRESETS["easy"]
        self.assertLessEqual(easy.max_empty_gap_ms, 4000)

    def test_phrase_density_weight_increases_with_difficulty(self) -> None:
        """Hard should weight phrase density more aggressively."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreaterEqual(normal.phrase_density_weight, easy.phrase_density_weight)
        self.assertGreaterEqual(hard.phrase_density_weight, normal.phrase_density_weight)


class DifficultyPresetSpinnerTests(unittest.TestCase):
    """Spinners must be enabled at all difficulties with reasonable thresholds."""

    def test_spinners_enabled_all_difficulties(self) -> None:
        for name in ("easy", "normal", "hard"):
            self.assertTrue(
                DIFFICULTY_PRESETS[name].spinner_enabled,
                f"Spinners must be enabled for {name}",
            )

    def test_spinner_min_gap_reasonable(self) -> None:
        """Min spinner gap must not be so large that spinners never appear."""
        for name in ("easy", "normal", "hard"):
            preset = DIFFICULTY_PRESETS[name]
            self.assertLessEqual(
                preset.spinner_min_gap_ms, 1800,
                f"{name} spinner min gap too large for placement",
            )

    def test_spinner_musical_threshold_reasonable(self) -> None:
        """Musical threshold must not be so high that spinners are rejected."""
        for name in ("easy", "normal", "hard"):
            preset = DIFFICULTY_PRESETS[name]
            self.assertLessEqual(
                preset.spinner_musical_threshold, 50.0,
                f"{name} spinner musical threshold too restrictive",
            )


# ---------------------------------------------------------------------------
# 2. Density Config Validation
# ---------------------------------------------------------------------------

class DensityConfigTests(unittest.TestCase):
    """Density configuration bounds for active audio sections."""

    def test_min_density_raises_minimum(self) -> None:
        """Minimum density must be at least 0.4 to prevent dead zones."""
        from tools.map_generator.rhythm.rhythm_density import DensityConfig
        config = DensityConfig()
        self.assertGreaterEqual(config.min_density, 0.4)

    def test_energy_ceiling_low_enough(self) -> None:
        """Energy ceiling must be <= 0.9 so high-energy sections trigger max density."""
        from tools.map_generator.rhythm.rhythm_density import DensityConfig
        config = DensityConfig()
        self.assertLessEqual(config.energy_ceiling, 0.90)

    def test_silent_energy_threshold_not_too_low(self) -> None:
        """Silent threshold should detect true silence, not just quiet music."""
        from tools.map_generator.rhythm.rhythm_density import DensityConfig
        config = DensityConfig()
        self.assertGreaterEqual(config.silent_energy_threshold, 0.06)

    def test_silent_min_duration_reasonable(self) -> None:
        """Silent min duration should not be so large it misses real breaks."""
        from tools.map_generator.rhythm.rhythm_density import DensityConfig
        config = DensityConfig()
        self.assertLessEqual(config.silent_min_duration_ms, 3000)


# ---------------------------------------------------------------------------
# 3. Max Gap Computation
# ---------------------------------------------------------------------------

class MaxGapComputationTests(unittest.TestCase):
    """compute_max_allowed_gap returns stricter limits during active audio."""

    def _make_frames(self, energy_value: float, start_ms: int, end_ms: int, step: int = 100) -> list[EnergyFrame]:
        return [
            EnergyFrame(time_ms=t, value=energy_value)
            for t in range(start_ms, end_ms, step)
        ]

    def test_high_energy_returns_tight_max_gap(self) -> None:
        from tools.map_generator.rhythm.rhythm_density import compute_max_allowed_gap, DensityConfig
        config = DensityConfig()
        frames = self._make_frames(0.9, 0, 5000)
        result = compute_max_allowed_gap(frames, 1000, 3000, max_gap_ms=2500, config=config)
        # Energy > ceiling → max_gap * 0.5
        self.assertLessEqual(result, 2500 * 0.55)

    def test_moderate_energy_returns_moderate_max_gap(self) -> None:
        from tools.map_generator.rhythm.rhythm_density import compute_max_allowed_gap, DensityConfig
        config = DensityConfig()
        # Energy above midpoint (0.475 for default) but below ceiling
        frames = self._make_frames(0.7, 0, 5000)
        result = compute_max_allowed_gap(frames, 1000, 3000, max_gap_ms=2500, config=config)
        # Should be between 0.5x and 0.75x of max_gap
        self.assertGreaterEqual(result, 2500 * 0.45)
        self.assertLessEqual(result, 2500 * 0.80)

    def test_low_energy_returns_near_max_gap(self) -> None:
        from tools.map_generator.rhythm.rhythm_density import compute_max_allowed_gap, DensityConfig
        config = DensityConfig()
        frames = self._make_frames(0.06, 0, 5000)
        result = compute_max_allowed_gap(frames, 1000, 3000, max_gap_ms=2500, config=config)
        # Low energy → near max_gap (tightened floor from 0.75 to 0.6)
        self.assertGreaterEqual(result, 2500 * 0.6)

    def test_no_frames_returns_max_gap(self) -> None:
        from tools.map_generator.rhythm.rhythm_density import compute_max_allowed_gap
        result = compute_max_allowed_gap([], 1000, 3000, max_gap_ms=2500)
        self.assertEqual(result, 2500)


# ---------------------------------------------------------------------------
# 4. Slider Decision Probability Threshold
# ---------------------------------------------------------------------------

class SliderProbabilityTests(unittest.TestCase):
    """Slider probability must be achievable for all difficulties."""

    def _make_event(self, energy: float = 0.6, emphasis: bool = True):
        from tools.map_generator.models import SelectedEvent
        return SelectedEvent(
            time_ms=5000, source="beat", strength=0.7,
            energy=energy, confidence=0.85, is_emphasis=emphasis,
        )

    def _make_sustained(self, score: float = 0.5):
        from tools.map_generator.sliders.slider_models import SustainedAnalysis
        return SustainedAnalysis(
            sustained_regions=[{"startMs": 0, "endMs": 60000, "averageScore": score}],
            sustained_frames=[
                {"timeMs": t, "sustainedScore": score}
                for t in range(0, 60001, 500)
            ],
            average_sustained_energy=score,
            sustained_ratio=score,
        )

    def test_easy_slider_candidate_exists(self) -> None:
        """With moderate sustained content, Easy should produce a slider candidate."""
        from tools.map_generator.sliders.slider_decision import decide_slider
        preset = DIFFICULTY_PRESETS["easy"]
        sustained = self._make_sustained(0.5)
        event = self._make_event(energy=0.5, emphasis=False)
        candidate = decide_slider(
            event, 1, sustained, preset,
            next_gap_ms=1200,
        )
        # With lowered threshold and boosted probability, this should pass
        self.assertIsNotNone(
            candidate,
            "Easy difficulty must produce slider candidates with moderate sustained content",
        )

    def test_normal_slider_candidate_exists(self) -> None:
        """With moderate sustained content, Normal should produce a slider candidate."""
        from tools.map_generator.sliders.slider_decision import decide_slider
        preset = DIFFICULTY_PRESETS["normal"]
        sustained = self._make_sustained(0.5)
        event = self._make_event(energy=0.6, emphasis=True)
        candidate = decide_slider(
            event, 1, sustained, preset,
            next_gap_ms=1000,
        )
        self.assertIsNotNone(
            candidate,
            "Normal difficulty must produce slider candidates with moderate sustained content",
        )

    def test_hard_slider_candidate_exists(self) -> None:
        """With moderate sustained content, Hard should produce a slider candidate."""
        from tools.map_generator.sliders.slider_decision import decide_slider
        preset = DIFFICULTY_PRESETS["hard"]
        sustained = self._make_sustained(0.5)
        event = self._make_event(energy=0.6, emphasis=True)
        candidate = decide_slider(
            event, 2, sustained, preset,
            previous_gap_ms=430, next_gap_ms=430,
        )
        self.assertIsNotNone(
            candidate,
            "Hard difficulty must produce slider candidates with moderate sustained content",
        )

    def test_slider_length_scales_with_difficulty(self) -> None:
        """Slider length caps should increase with difficulty."""
        easy_max = DIFFICULTY_PRESETS["easy"].slider_max_length_ms
        normal_max = DIFFICULTY_PRESETS["normal"].slider_max_length_ms
        hard_max = DIFFICULTY_PRESETS["hard"].slider_max_length_ms
        self.assertGreaterEqual(normal_max, easy_max)
        self.assertGreaterEqual(hard_max, normal_max)


# ---------------------------------------------------------------------------
# 5. Sustained Analysis Thresholds
# ---------------------------------------------------------------------------

class SustainedAnalysisThresholdTests(unittest.TestCase):
    """Sustained detection thresholds should catch more audio content."""

    def test_low_energy_content_detected(self) -> None:
        """Even mild sustained content should be detected as sustained."""
        from tools.map_generator.sliders.sustained_analysis import analyze_sustained_content
        import numpy as np

        # Create a low-energy sustained signal (sine wave at moderate amplitude)
        sample_rate = 22050
        duration_s = 1.0
        t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
        # Moderate amplitude sine wave - should be detected as sustained
        signal = 0.15 * np.sin(2 * np.pi * 440 * t)
        result = analyze_sustained_content(signal, sample_rate)
        self.assertGreater(
            result.sustained_ratio, 0.0,
            "A moderate sustained signal should have non-zero sustained ratio",
        )

    def test_silent_signal_not_sustained(self) -> None:
        """Pure silence should not be detected as sustained."""
        from tools.map_generator.sliders.sustained_analysis import analyze_sustained_content
        import numpy as np

        sample_rate = 22050
        duration_s = 1.0
        signal = np.zeros(int(sample_rate * duration_s))
        result = analyze_sustained_content(signal, sample_rate)
        self.assertLessEqual(
            result.sustained_ratio, 0.05,
            "Silence should not be detected as sustained",
        )


# ---------------------------------------------------------------------------
# 6. Rhythm Pipeline Gap Selection Logic
# ---------------------------------------------------------------------------

class RhythmGapSelectionTests(unittest.TestCase):
    """Verify that the rhythm pipeline gap selection logic prevents dead zones."""

    def test_config_has_subdivision_enabled(self) -> None:
        """All difficulties should have subdivision enabled for gap filling."""
        for name in ("easy", "normal", "hard"):
            preset = DIFFICULTY_PRESETS[name]
            self.assertTrue(
                preset.subdivision_enabled,
                f"{name} must have subdivision enabled",
            )
            self.assertTrue(
                preset.subdivision_fill_gaps,
                f"{name} must have subdivision_fill_gaps enabled",
            )

    def test_timing_confidence_floor_reasonable(self) -> None:
        """min_timing_confidence should be reasonable (lowered for aggressive density)."""
        for name in ("easy", "normal", "hard"):
            preset = DIFFICULTY_PRESETS[name]
            self.assertGreaterEqual(
                preset.min_timing_confidence, 0.15,
                f"{name} min_timing_confidence too low",
            )

    def test_hard_min_gap_supports_12_snap(self) -> None:
        """Hard min_gap_ms must support 1/2 beat snap (~200ms at 150 BPM)."""
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertLessEqual(hard.min_gap_ms, 200)

    def test_normal_min_gap_supports_11_snap(self) -> None:
        """Normal min_gap_ms should allow 1/1 beat snaps."""
        normal = DIFFICULTY_PRESETS["normal"]
        self.assertLessEqual(normal.min_gap_ms, 500)

    def test_easy_min_gap_supports_21_snap(self) -> None:
        """Easy min_gap_ms should allow 2/1 beat snaps."""
        easy = DIFFICULTY_PRESETS["easy"]
        self.assertGreaterEqual(easy.min_gap_ms, 400)


# ---------------------------------------------------------------------------
# 7. End-to-End Config Coherence
# ---------------------------------------------------------------------------

class ConfigCoherenceTests(unittest.TestCase):
    """Verify cross-parameter consistency across difficulty presets."""

    def test_gap_ordering(self) -> None:
        """min_gap and target_gap should decrease with difficulty."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreater(easy.min_gap_ms, normal.min_gap_ms)
        self.assertGreater(normal.min_gap_ms, hard.min_gap_ms)
        self.assertGreater(easy.target_gap_ms, normal.target_gap_ms)
        self.assertGreater(normal.target_gap_ms, hard.target_gap_ms)

    def test_circle_size_ordering(self) -> None:
        """Circle radius should decrease with difficulty."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreater(easy.circle_radius, normal.circle_radius)
        self.assertGreater(normal.circle_radius, hard.circle_radius)

    def test_approach_time_ordering(self) -> None:
        """Approach time should decrease with difficulty."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreater(easy.approach_time_ms, normal.approach_time_ms)
        self.assertGreater(normal.approach_time_ms, hard.approach_time_ms)

    def test_pattern_variation_ordering(self) -> None:
        """Pattern variation should increase with difficulty."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertLess(easy.pattern_variation, normal.pattern_variation)
        self.assertLess(normal.pattern_variation, hard.pattern_variation)

    def test_onset_threshold_ordering(self) -> None:
        """Onset strength threshold should decrease with difficulty (easier to trigger)."""
        easy = DIFFICULTY_PRESETS["easy"]
        normal = DIFFICULTY_PRESETS["normal"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreater(easy.onset_strength_threshold, normal.onset_strength_threshold)
        self.assertGreater(normal.onset_strength_threshold, hard.onset_strength_threshold)


if __name__ == "__main__":
    unittest.main()
