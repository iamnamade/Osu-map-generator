"""Regression tests for the Phase 2 density / gap / spinner fixes (F1-F7, F10).

Covers:
  * Hard density reaches the 2.5-3.8 obj/s band via multi-pass gap fill.
  * ``min_density_target`` acts as an independent floor and is never collapsed
    by a smaller ``target_density``.
  * ``compute_max_allowed_gap`` tightens on isolated loud bursts.
  * Spinner clearance rejects a window that a spanning slider overlaps.
  * Injected fill respects ``min_gap_ms`` and never enters a spinner window.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

# Stub heavy audio dependencies before importing the generator package.
for _mod in ("librosa", "soundfile"):
    sys.modules.setdefault(_mod, MagicMock())

from tools.map_generator.beatmap_generator import (
    _enforce_density_minimum,
    _snap_fill_time,
)
from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    GeneratedCircleHitObject,
    GeneratedSliderHitObject,
    GeneratedSpinnerHitObject,
    HitObjectPoint,
    TimedStrength,
)
from tools.map_generator.position_generator import PositionGenerationResult
from tools.map_generator.rhythm.rhythm_density import (
    DensityConfig,
    compute_max_allowed_gap,
)
from tools.map_generator.spinners.spinner_pipeline import _check_spinner_clearance

DURATION_MS = 16_431


def _analysis(energy: float = 0.5) -> AudioAnalysis:
    return AudioAnalysis(
        audio_filename="test.mp3",
        duration_ms=DURATION_MS,
        sample_rate=22_050,
        bpm=76.0,
        offset_ms=0,
        beats=[TimedStrength(t, 1.0) for t in range(0, DURATION_MS, 789)],
        onsets=[],
        energy_frames=[EnergyFrame(t, energy) for t in range(0, DURATION_MS, 100)],
        quiet_regions=[],
        high_energy_regions=[],
    )


def _slider(obj_id: int, time: int, end_time: int) -> GeneratedSliderHitObject:
    return GeneratedSliderHitObject(
        obj_id, "slider", 256, 192, time, end_time, "linear",
        [HitObjectPoint(256, 192)], 1, 80,
    )


class DensityFillTests(unittest.TestCase):
    def _run(self, objects, preset):
        return _enforce_density_minimum(
            positioned=PositionGenerationResult(objects=list(objects), rejected_candidates=0),
            selected_events=[],
            analysis=_analysis(),
            preset=preset,
            seed=42,
        ).objects

    def test_hard_reaches_density_band(self) -> None:
        """The Phase 1 failure case (27 objects -> 1.64 obj/s) must reach 2.5+."""
        preset = DIFFICULTY_PRESETS["hard"]
        objects = [
            _slider(i + 1, 1500 + i * 575, 1500 + i * 575 + 215)
            for i in range(27)
        ]
        result = self._run(objects, preset)
        density = len(result) / (DURATION_MS / 1000.0)
        self.assertGreaterEqual(density, 2.5)
        self.assertLessEqual(density, 3.8)

    def test_min_density_floor_is_independent(self) -> None:
        """target_density below min_density_target must not collapse the floor."""
        preset = replace(
            DIFFICULTY_PRESETS["normal"],
            min_density_target=3.0,
            target_density=1.0,
        )
        objects = [
            GeneratedCircleHitObject(i + 1, "circle", 256, 192, 1500 + i * 575)
            for i in range(27)
        ]
        result = self._run(objects, preset)
        density = len(result) / (DURATION_MS / 1000.0)
        self.assertGreaterEqual(density, 2.9)

    def test_fill_respects_min_gap_and_spinner(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        spinner = GeneratedSpinnerHitObject(3, "spinner", 8000, 8500)
        objects = [
            GeneratedCircleHitObject(1, "circle", 100, 100, 2000),
            GeneratedCircleHitObject(2, "circle", 300, 200, 3000),
            spinner,
            GeneratedCircleHitObject(4, "circle", 400, 100, 9000),
        ]
        result = self._run(objects, preset)
        ordered = sorted(result, key=lambda o: o.time)
        for previous, current in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(current.time - previous.time, preset.min_gap_ms)
            if previous.type == "spinner":
                self.assertGreaterEqual(current.time, previous.end_time)
            if current.type == "spinner":
                self.assertLessEqual(previous.time, current.time - preset.min_gap_ms)

    def test_snap_fill_time_prefers_grid_inside_window(self) -> None:
        snapped = _snap_fill_time(
            center=1050.0, lo=1000.0, hi=1200.0, offset_ms=0, half_beat_ms=500,
        )
        self.assertIsNotNone(snapped)
        self.assertGreaterEqual(snapped, 1000)
        self.assertLessEqual(snapped, 1200)

    def test_snap_fill_time_returns_none_for_empty_window(self) -> None:
        self.assertIsNone(
            _snap_fill_time(center=100.0, lo=200.0, hi=100.0, offset_ms=0, half_beat_ms=500)
        )


class MaxGapEnergyTests(unittest.TestCase):
    def test_isolated_burst_tightens_gap(self) -> None:
        """A short loud accent in an otherwise quiet window must tighten the cap.

        Mean-only energy (~0.11) would land in the 0.7x band; the peak-aware
        blend pushes it into the 0.55x band instead.
        """
        frames = [EnergyFrame(t, 0.02) for t in range(0, 1800, 100)]
        frames += [EnergyFrame(1800, 0.9), EnergyFrame(1900, 0.9)]
        result = compute_max_allowed_gap(
            frames, 0, 2000, max_gap_ms=2500, config=DensityConfig(),
        )
        self.assertLessEqual(result, int(2500 * 0.6))

    def test_uniform_high_energy_still_tightest(self) -> None:
        frames = [EnergyFrame(t, 0.9) for t in range(0, 2000, 100)]
        result = compute_max_allowed_gap(
            frames, 0, 2000, max_gap_ms=2500, config=DensityConfig(),
        )
        self.assertLessEqual(result, int(2500 * 0.55))


class SpinnerClearanceTests(unittest.TestCase):
    def test_spanning_slider_is_detected(self) -> None:
        slider = _slider(8, 7198, 7412)
        others = [
            GeneratedCircleHitObject(7, "circle", 100, 100, 6800),
            slider,
        ]
        # A spinner starting inside the slider body must be rejected.
        self.assertFalse(_check_spinner_clearance(others, 7215, 7400, 125))

    def test_clear_window_after_slider_is_allowed(self) -> None:
        slider = _slider(8, 7198, 7412)
        others = [
            GeneratedCircleHitObject(7, "circle", 100, 100, 6800),
            slider,
            GeneratedCircleHitObject(9, "circle", 400, 300, 8500),
        ]
        self.assertTrue(_check_spinner_clearance(others, 7600, 8000, 125))


if __name__ == "__main__":
    unittest.main()
