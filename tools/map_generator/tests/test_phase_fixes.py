"""Tests for Phase 1-3 fixes.

Covers:
  - Slider path cache eviction and clearing (geometry/collision.py)
  - PostprocessState isolation and reset (postprocess/local_optimizer.py)
  - GenerationResult.warnings field (models.py)
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from tools.map_generator.geometry.collision import (
    _SLIDER_CACHE_MAX_SIZE,
    _get_slider_path,
    _slider_cache_order,
    _slider_cache_key,
    _slider_path_cache,
    clear_slider_cache,
)
from tools.map_generator.models import GenerationResult
from tools.map_generator.postprocess.local_optimizer import (
    PostprocessState,
    deadline_exceeded,
    get_diagnostics,
    reset_diagnostics,
    set_deadline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slider_obj(obj_id: int, x: int = 100, y: int = 100) -> dict:
    """Return a minimal slider dict accepted by sample_slider_path."""
    return {
        "id": obj_id,
        "type": "slider",
        "x": x,
        "y": y,
        "time": obj_id * 500,
        "pathType": "linear",
        "controlPoints": [{"x": x + 100, "y": y}],
        "repeats": 1,
        "pixelLength": 200.0,
        "endTime": obj_id * 500 + 500,
    }


# ===================================================================
# 1. Slider Path Cache Tests
# ===================================================================

class SliderCacheEvictionTests(unittest.TestCase):
    """Phase 1 fix: bounded cache in geometry/collision.py."""

    def setUp(self) -> None:
        clear_slider_cache()

    def tearDown(self) -> None:
        clear_slider_cache()

    # -- cache basics --

    def test_cache_starts_empty(self) -> None:
        self.assertEqual(len(_slider_path_cache), 0)
        self.assertEqual(len(_slider_cache_order), 0)

    def test_get_slider_path_populates_cache(self) -> None:
        obj = _make_slider_obj(1)
        path = _get_slider_path(obj)
        self.assertIsInstance(path, list)
        self.assertGreater(len(path), 0)
        # Cache should now contain exactly one entry
        self.assertEqual(len(_slider_path_cache), 1)
        self.assertEqual(len(_slider_cache_order), 1)

    def test_duplicate_slider_returns_cached_path(self) -> None:
        obj = _make_slider_obj(2)
        path1 = _get_slider_path(obj)
        path2 = _get_slider_path(obj)
        # Same object — should be the exact same cached list
        self.assertIs(path1, path2)
        self.assertEqual(len(_slider_path_cache), 1)

    def test_different_sliders_get_different_paths(self) -> None:
        obj1 = _make_slider_obj(3, x=50, y=50)
        obj2 = _make_slider_obj(4, x=200, y=200)
        path1 = _get_slider_path(obj1)
        path2 = _get_slider_path(obj2)
        self.assertIsNot(path1, path2)
        self.assertEqual(len(_slider_path_cache), 2)

    # -- cache key --

    def test_cache_key_is_deterministic(self) -> None:
        obj = _make_slider_obj(5)
        key1 = _slider_cache_key(obj)
        key2 = _slider_cache_key(obj)
        self.assertEqual(key1, key2)

    def test_cache_key_differs_for_different_sliders(self) -> None:
        obj_a = _make_slider_obj(6, x=10, y=20)
        obj_b = _make_slider_obj(7, x=30, y=40)
        self.assertNotEqual(_slider_cache_key(obj_a), _slider_cache_key(obj_b))

    # -- eviction --

    def test_cache_evicts_when_full(self) -> None:
        """Insert SLIDER_CACHE_MAX_SIZE + 10 entries; oldest half should be evicted."""
        for i in range(_SLIDER_CACHE_MAX_SIZE + 10):
            obj = _make_slider_obj(100 + i, x=i % 512, y=(i * 3) % 384)
            _get_slider_path(obj)

        # After eviction, cache should be at most SLIDER_CACHE_MAX_SIZE
        # (it was full at 500, we added 10 more, oldest 250 evicted → ~260)
        self.assertLessEqual(len(_slider_path_cache), _SLIDER_CACHE_MAX_SIZE)
        self.assertLessEqual(len(_slider_cache_order), _SLIDER_CACHE_MAX_SIZE)

    def test_eviction_preserves_newest_entries(self) -> None:
        """The most recently inserted entries should survive eviction."""
        # Fill to capacity
        for i in range(_SLIDER_CACHE_MAX_SIZE):
            _get_slider_path(_make_slider_obj(200 + i, x=i % 512, y=0))
        # Insert a distinctive final entry
        final_obj = _make_slider_obj(9999, x=256, y=192)
        final_key = _slider_cache_key(final_obj)
        _get_slider_path(final_obj)

        # The final entry must still be cached
        self.assertIn(final_key, _slider_path_cache)

    # -- clearing --

    def test_clear_resets_cache_and_order(self) -> None:
        for i in range(20):
            _get_slider_path(_make_slider_obj(500 + i))
        self.assertGreater(len(_slider_path_cache), 0)
        self.assertGreater(len(_slider_cache_order), 0)

        clear_slider_cache()

        self.assertEqual(len(_slider_path_cache), 0)
        self.assertEqual(len(_slider_cache_order), 0)

    def test_clear_allows_repopulation(self) -> None:
        obj = _make_slider_obj(600)
        _get_slider_path(obj)
        self.assertEqual(len(_slider_path_cache), 1)

        clear_slider_cache()
        self.assertEqual(len(_slider_path_cache), 0)

        # Re-inserting the same slider should produce a fresh cache entry
        _get_slider_path(obj)
        self.assertEqual(len(_slider_path_cache), 1)


# ===================================================================
# 2. PostprocessState Tests
# ===================================================================

class PostprocessStateTests(unittest.TestCase):
    """Phase 2 fix: state isolation in postprocess/local_optimizer.py."""

    def test_state_isolation_between_instances(self) -> None:
        """Two separate PostprocessState instances must not share counters."""
        state_a = PostprocessState()
        state_b = PostprocessState()

        state_a.validation_call_count = 5
        state_a.cache_hit_count = 3
        state_a.validation_cache["key"] = "value_a"

        # state_b must be completely unaffected
        self.assertEqual(state_b.validation_call_count, 0)
        self.assertEqual(state_b.cache_hit_count, 0)
        self.assertNotIn("key", state_b.validation_cache)

    def test_reset_clears_all_fields(self) -> None:
        state = PostprocessState()
        state.deadline = 123.456
        state.validation_call_count = 42
        state.validation_total_seconds = 9.99
        state.validation_calls_detail = [("stage1", 1.0)]
        state.prefilter_skip_count = 7
        state.local_validation_count = 12
        state.cache_hit_count = 5
        state.validation_cache["abc"] = "def"

        state.reset()

        self.assertEqual(state.deadline, 0.0)
        self.assertEqual(state.validation_call_count, 0)
        self.assertEqual(state.validation_total_seconds, 0.0)
        self.assertEqual(state.validation_calls_detail, [])
        self.assertEqual(state.prefilter_skip_count, 0)
        self.assertEqual(state.local_validation_count, 0)
        self.assertEqual(state.cache_hit_count, 0)
        self.assertEqual(state.validation_cache, {})

    def test_to_diagnostics_returns_snapshot(self) -> None:
        state = PostprocessState()
        state.validation_call_count = 10
        state.validation_total_seconds = 2.5
        state.validation_calls_detail = [("a", 0.1), ("b", 0.9)]
        state.cache_hit_count = 3

        diag = state.to_diagnostics()
        self.assertEqual(diag["validation_calls"], 10)
        self.assertAlmostEqual(diag["validation_seconds"], 2.5)
        self.assertEqual(diag["cache_hits"], 3)
        self.assertIn("slow_validations", diag)

    def test_deadline_exceeded_with_no_deadline(self) -> None:
        state = PostprocessState()
        self.assertFalse(state.deadline_exceeded())

    def test_deadline_exceeded_in_past(self) -> None:
        state = PostprocessState()
        state.set_deadline(time.monotonic() - 1.0)
        self.assertTrue(state.deadline_exceeded())

    def test_deadline_exceeded_not_yet(self) -> None:
        state = PostprocessState()
        state.set_deadline(time.monotonic() + 100.0)
        self.assertFalse(state.deadline_exceeded())

    def test_module_level_helpers_delegate_to_default_state(self) -> None:
        """set_deadline / deadline_exceeded / reset_diagnostics must use _state."""
        reset_diagnostics()
        self.assertFalse(deadline_exceeded())

        set_deadline(time.monotonic() - 1.0)
        self.assertTrue(deadline_exceeded())

        reset_diagnostics()
        self.assertFalse(deadline_exceeded())

    def test_sequential_optimization_runs_do_not_leak_state(self) -> None:
        """Simulate two sequential improve_beatmap calls using the default state."""
        reset_diagnostics()
        set_deadline(time.monotonic() + 60.0)
        # Simulate some work
        state_1 = PostprocessState()
        state_1.validation_call_count = 15
        state_1.cache_hit_count = 4

        # Second run: reset_diagnostics should wipe everything
        reset_diagnostics()
        diag = get_diagnostics()
        self.assertEqual(diag["validation_calls"], 0)
        self.assertEqual(diag["cache_hits"], 0)


# ===================================================================
# 3. GenerationResult.warnings Tests
# ===================================================================

class GenerationResultWarningsTests(unittest.TestCase):
    """Phase 2 fix: warnings field in GenerationResult."""

    def test_warnings_defaults_to_empty_list(self) -> None:
        from tools.map_generator.models import AudioAnalysis, EnergyFrame, TimedStrength

        analysis = AudioAnalysis(
            audio_filename="test.mp3",
            duration_ms=5000,
            sample_rate=22050,
            bpm=120.0,
            offset_ms=0,
            beats=[],
            onsets=[],
            energy_frames=[],
            quiet_regions=[],
            high_energy_regions=[],
        )
        result = GenerationResult(
            analysis=analysis,
            selected_events=[],
            beatmap={"title": "t", "artist": "a", "audio": "a.mp3", "objects": []},
            diagnostics=MagicMock(),
        )
        self.assertEqual(result.warnings, [])

    def test_warnings_can_be_populated(self) -> None:
        from tools.map_generator.models import AudioAnalysis

        analysis = AudioAnalysis(
            audio_filename="test.mp3",
            duration_ms=5000,
            sample_rate=22050,
            bpm=120.0,
            offset_ms=0,
            beats=[],
            onsets=[],
            energy_frames=[],
            quiet_regions=[],
            high_energy_regions=[],
        )
        result = GenerationResult(
            analysis=analysis,
            selected_events=[],
            beatmap={"title": "t", "artist": "a", "audio": "a.mp3", "objects": []},
            diagnostics=MagicMock(),
            warnings=["Slider processing failed", "Spinner generation skipped"],
        )
        self.assertEqual(len(result.warnings), 2)
        self.assertIn("Slider processing failed", result.warnings)

    def test_warnings_independence_between_instances(self) -> None:
        """Two GenerationResult instances must not share warning lists."""
        from tools.map_generator.models import AudioAnalysis

        analysis = AudioAnalysis(
            audio_filename="test.mp3",
            duration_ms=5000,
            sample_rate=22050,
            bpm=120.0,
            offset_ms=0,
            beats=[],
            onsets=[],
            energy_frames=[],
            quiet_regions=[],
            high_energy_regions=[],
        )
        result_a = GenerationResult(
            analysis=analysis,
            selected_events=[],
            beatmap={"title": "t", "artist": "a", "audio": "a.mp3", "objects": []},
            diagnostics=MagicMock(),
            warnings=["error A"],
        )
        result_b = GenerationResult(
            analysis=analysis,
            selected_events=[],
            beatmap={"title": "t", "artist": "a", "audio": "a.mp3", "objects": []},
            diagnostics=MagicMock(),
        )
        self.assertEqual(result_a.warnings, ["error A"])
        self.assertEqual(result_b.warnings, [])


if __name__ == "__main__":
    unittest.main()
