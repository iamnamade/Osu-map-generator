#!/usr/bin/env python3
"""P0.1 (Phase 6 roadmap) — multi-BPM timing-point export tests.

Verifies that ``build_timing_points`` emits one uninherited timing point per
detected stable tempo region (from ``enhanced.bpmRegions``), and falls back
to the historical single global point for tempo-stable tracks or analyses
without enhanced region data.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = SCRIPT_DIR.parent.parent
PROJECT_ROOT = TOOLS_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.map_generator.osu_format.timing_converter import build_timing_points
from tools.map_generator.utils import write_json


def _write_analysis(directory: Path, bpm_regions: list[dict] | None) -> Path:
    """Write a minimal but structurally valid analysis JSON."""
    payload = {
        "version": 2,
        "audio": {
            "filename": "test-song.mp3",
            "durationMs": 20000,
            "sampleRate": 22050,
        },
        "rhythm": {
            "bpm": 120.0,
            "offsetMs": 100,
            "beats": [],
            "onsets": [],
        },
        "energy": {
            "frames": [],
            "quietRegions": [],
            "highEnergyRegions": [],
        },
    }
    if bpm_regions is not None:
        payload["enhanced"] = {"bpmRegions": bpm_regions}
    path = directory / "analysis.json"
    write_json(path, payload)
    return path


class MultiBpmTimingExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_two_stable_regions_emit_two_timing_points(self) -> None:
        analysis_path = _write_analysis(
            self.tmp_path,
            [
                {"startMs": 0, "endMs": 9000, "bpm": 120.0, "confidence": 0.9, "beatCount": 18},
                {"startMs": 10000, "endMs": 20000, "bpm": 160.0, "confidence": 0.85, "beatCount": 26},
            ],
        )
        points, bpm, offset_ms = build_timing_points(analysis_path)
        self.assertEqual(len(points), 2)
        self.assertTrue(all(point.uninherited == 1 for point in points))
        # First point anchors at the analysis offset with the first region BPM.
        self.assertEqual(points[0].time, 100)
        self.assertAlmostEqual(points[0].beat_length, 60000.0 / 120.0, places=2)
        # Second point sits at the second region start with its BPM.
        self.assertEqual(points[1].time, 10000)
        self.assertAlmostEqual(points[1].beat_length, 60000.0 / 160.0, places=2)
        self.assertEqual(bpm, 120.0)
        self.assertEqual(offset_ms, 100)

    def test_single_region_falls_back_to_single_point(self) -> None:
        analysis_path = _write_analysis(
            self.tmp_path,
            [
                {"startMs": 0, "endMs": 20000, "bpm": 120.0, "confidence": 0.9, "beatCount": 40},
            ],
        )
        points, bpm, _offset = build_timing_points(analysis_path)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].beat_length, 500.0, places=2)
        self.assertEqual(bpm, 120.0)

    def test_low_confidence_regions_are_skipped(self) -> None:
        analysis_path = _write_analysis(
            self.tmp_path,
            [
                {"startMs": 0, "endMs": 9000, "bpm": 120.0, "confidence": 0.9, "beatCount": 18},
                {"startMs": 10000, "endMs": 20000, "bpm": 175.0, "confidence": 0.2, "beatCount": 30},
            ],
        )
        points, _bpm, _offset = build_timing_points(analysis_path)
        self.assertEqual(len(points), 1)

    def test_close_regions_with_same_tempo_are_deduplicated(self) -> None:
        analysis_path = _write_analysis(
            self.tmp_path,
            [
                {"startMs": 0, "endMs": 9000, "bpm": 120.0, "confidence": 0.9, "beatCount": 18},
                {"startMs": 11000, "endMs": 20000, "bpm": 122.0, "confidence": 0.9, "beatCount": 18},
            ],
        )
        points, _bpm, _offset = build_timing_points(analysis_path)
        self.assertEqual(len(points), 1)

    def test_no_enhanced_data_keeps_single_point(self) -> None:
        analysis_path = _write_analysis(self.tmp_path, None)
        points, _bpm, _offset = build_timing_points(analysis_path)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].uninherited, 1)


if __name__ == "__main__":
    unittest.main()
