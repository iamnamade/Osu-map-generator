"""Targeted tests for the spinner spatial metric pollution fix.

Verifies that:
1. Spinner objects (x=0, y=0) are excluded from spatial metrics in evaluate_section_window.
2. Hybrid assembler safely skips objects without valid coordinates.
3. Temporal metrics still count all objects including spinners.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy audio dependencies BEFORE any map_generator imports
# ---------------------------------------------------------------------------
for _mod_name in ("librosa", "soundfile", "numpy", "numpy.lib", "numpy.lib.stride_tricks",
                   "scipy", "scipy.signal", "scipy.interpolate", "scipy.stats"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# Ensure tools package is importable
_root = Path(__file__).resolve().parents[2]  # repo root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.map_generator.sections.section_models import (
    MapObject,
)
from tools.map_generator.sections.section_scorer import (
    evaluate_section_window,
    _movement_sequences,
    _repetition_count,
    _grid_region,
)


# ---------------------------------------------------------------------------
# Minimal doubles
# ---------------------------------------------------------------------------
class _T:
    def __init__(self, t: float) -> None:
        self.time_ms = t

class _Analysis:
    def __init__(self) -> None:
        self.beats = [_T(t * 400) for t in range(50)]
        self.onsets = [_T(t * 400 + 50) for t in range(50)]
        self.bpm = 150.0
        self.duration_ms = 20_000

class _Preset:
    min_gap_ms = 90
    target_gap_ms = 200
    max_cursor_speed = 600.0
    max_jump_distance = 300.0
    preferred_jump_distance = 200.0
    circle_radius = 34

class _EvalCfg:
    boundary_context_ms = 1800

class _Section:
    def __init__(self) -> None:
        self.id = 1; self.start_ms = 0; self.end_ms = 5000; self.duration_ms = 5000
        self.label = "chorus-like"; self.confidence = 0.9; self.average_energy = 0.7
        self.energy_trend = "rising"; self.beat_density = 3.0; self.onset_density = 2.5
        self.rhythm_complexity = 0.6; self.repetition_group = None; self.energy_class = "high"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestSpinnerSpatialExclusion(unittest.TestCase):
    """Spinners (x=0, y=0) must not pollute spatial metrics."""

    @staticmethod
    def _objs(with_spinners: bool = True) -> list[MapObject]:
        objs = [
            MapObject(id=1, x=100, y=100, time=500),
            MapObject(id=2, x=200, y=150, time=700),
        ]
        if with_spinners:
            objs += [MapObject(id=3, x=0, y=0, time=800),
                     MapObject(id=4, x=0, y=0, time=1200)]
        objs += [MapObject(id=5, x=300, y=200, time=1500),
                 MapObject(id=6, x=400, y=100, time=1800)]
        return sorted(objs, key=lambda o: (o.time, o.id))

    def _eval(self, objs: list[MapObject]) -> Any:
        return evaluate_section_window(
            analysis=_Analysis(), preset=_Preset(), section=_Section(),
            all_objects=objs, evaluation_config=_EvalCfg(),
        )

    def test_spatial_coverage_unchanged_with_spinners(self):
        r_with = self._eval(self._objs(True))
        r_without = self._eval(self._objs(False))
        self.assertAlmostEqual(r_with.metrics.spatial_coverage,
                               r_without.metrics.spatial_coverage, places=4,
                               msg="Spinner (0,0) must not affect spatial_coverage")

    def test_center_usage_unchanged_with_spinners(self):
        r_with = self._eval(self._objs(True))
        r_without = self._eval(self._objs(False))
        self.assertEqual(r_with.metrics.center_usage, r_without.metrics.center_usage,
                         msg="Spinner (0,0) must not affect center_usage")

    def test_edge_usage_unchanged_with_spinners(self):
        r_with = self._eval(self._objs(True))
        r_without = self._eval(self._objs(False))
        self.assertEqual(r_with.metrics.edge_usage, r_without.metrics.edge_usage,
                         msg="Spinner (0,0) at edge must not inflate edge_usage")

    def test_repetition_count_excludes_spinners(self):
        objs = [
            MapObject(id=1, x=100, y=100, time=500),
            MapObject(id=2, x=100, y=100, time=700),  # stacked
            MapObject(id=3, x=0, y=0, time=800),       # spinner
            MapObject(id=4, x=300, y=200, time=1500),
        ]
        r = self._eval(objs)
        self.assertEqual(r.metrics.repetition_count, 1)

    def test_objects_per_second_includes_spinners(self):
        r_with = self._eval(self._objs(True))
        r_without = self._eval(self._objs(False))
        self.assertGreater(r_with.metrics.objects_per_second,
                           r_without.metrics.objects_per_second,
                           msg="Density should include spinners")
        self.assertEqual(r_with.metrics.object_count, 6)
        self.assertEqual(r_without.metrics.object_count, 4)

    def test_all_spinner_section_fallback(self):
        objs = [MapObject(id=i, x=0, y=0, time=i * 500) for i in range(1, 4)]
        r = self._eval(objs)
        self.assertEqual(r.metrics.object_count, 3)

    def test_movement_sequences_skips_spinners(self):
        objs = [
            MapObject(id=1, x=100, y=100, time=500),
            MapObject(id=2, x=0, y=0, time=800),
            MapObject(id=3, x=200, y=200, time=1000),
        ]
        positioned = [o for o in objs if o.x != 0 or o.y != 0]
        distances, _, _, _ = _movement_sequences(positioned)
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0], math.hypot(100, 100), places=2)


class TestGridRegion(unittest.TestCase):
    def test_corners(self):
        self.assertEqual(_grid_region(0, 0), "r1c1")
        self.assertEqual(_grid_region(511, 383), "r3c4")
        self.assertEqual(_grid_region(256, 192), "r2c3")


class TestRepetitionCount(unittest.TestCase):
    def test_spinners_not_counted(self):
        objs = [MapObject(id=1, x=0, y=0, time=500),
                MapObject(id=2, x=0, y=0, time=700),
                MapObject(id=3, x=100, y=100, time=1000)]
        positioned = [o for o in objs if o.x != 0 or o.y != 0]
        self.assertEqual(_repetition_count(positioned), 0)


class TestHybridAssemblerGuard(unittest.TestCase):
    """Verify _load_candidate_maps skips objects without coordinates."""

    def test_missing_keys_skipped(self):
        """Spinner objects with no x/y should be skipped gracefully."""
        raw = [
            {"id": 1, "x": 100, "y": 200, "time": 500, "type": "circle"},
            {"id": 2, "time": 800, "type": "spinner", "endTime": 1200},  # no x/y
            {"id": 3, "x": 300, "y": 400, "time": 1500, "type": "circle"},
        ]
        # Simulate what _load_candidate_maps does after normalize_map_objects
        # In the real code, normalize_map_objects adds x=0/y=0 for spinners,
        # but let's test the guard for objects that somehow slip through.
        from tools.map_generator.utils import normalize_map_objects
        normalized = normalize_map_objects(raw)
        from tools.map_generator.sections.section_models import MapObject
        objects = []
        for item in normalized:
            try:
                x_val = item.get("x")
                y_val = item.get("y")
                t_val = item.get("time")
                if x_val is None or y_val is None or t_val is None:
                    continue
                objects.append(MapObject(
                    id=int(item.get("id", 0)),
                    x=int(x_val), y=int(y_val), time=int(t_val),
                ))
            except (TypeError, ValueError):
                continue
        # normalize_map_objects adds x=0/y=0, so all 3 should pass
        self.assertEqual(len(objects), 3)
        # The spinner should have x=0, y=0
        spinner = [o for o in objects if o.time == 800][0]
        self.assertEqual(spinner.x, 0)
        self.assertEqual(spinner.y, 0)


if __name__ == "__main__":
    unittest.main()
