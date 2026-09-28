#!/usr/bin/env python3
"""P0.3 (Phase 6 roadmap) — density regression pin across generator fixtures.

Pins per-difficulty object density to the audit spec bands on the committed
test fixture(s), so a generator change that silently drops Hard back under
its 2.5 obj/s floor (the Phase 1 regression) fails CI instead of shipping.

Bands (Phase 1 audit §2.2 / the audit requirement):
  Easy   0.8 - 2.0 obj/s   (floor 0.8, analyzer target 1.1)
  Normal 1.3 - 2.0 obj/s   (audit band 1.3-2.0, analyzer target 1.5)
  Hard   2.5 - 3.8 obj/s   (audit band 2.5-3.8, analyzer target 2.4 → floor wins)

Density is computed the same way the pipeline reports it: total objects
(including spinners) divided by active audio span (first→last object time).

Run: py -3.10 -m pytest tools/map_generator/tests/test_density_pin.py -v
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
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.map_generator.audio_analyzer import analyze_audio
from tools.map_generator.beatmap_generator import generate_beatmap_from_analysis
from tools.map_generator.config import get_difficulty_preset
from tools.map_generator.generation_config import (
    apply_mapping_controls,
    build_position_variation_biases,
    resolve_mapping_controls,
)
from tools.map_generator.utils import write_json

# Audit-mandated spec bands (obj/s), keyed by difficulty.
DENSITY_PIN_BANDS: dict[str, tuple[float, float]] = {
    "easy": (0.8, 2.0),
    "normal": (1.3, 2.0),
    "hard": (2.5, 3.8),
}

# Hard band floor per the audit requirement (2.5-3.8); the engine target is
# 3.2 obj/s with a 2.2 floor, so hitting the target lands inside the band.
# We assert the band, not the target, to match the audit contract exactly.

FIXTURE_PATHS: list[Path] = [
    PROJECT_ROOT / "public" / "audio" / "test-song.mp3",
]


def _compute_density(objects: list[dict], duration_ms: int) -> float:
    """Objects per second of total audio duration.

    Measurement basis matches both the engine's enforcement quota
    (``target_count = target_density * duration_sec`` in
    beatmap_generator._enforce_density_minimum) and the Phase 1 audit metric
    (objects / total duration, e.g. Hard 27 objects / 16.431 s = 1.64 obj/s).
    """
    if duration_ms <= 0:
        return 0.0
    return len(objects) / (duration_ms / 1000.0)


class DensityPinTests(unittest.TestCase):
    """P0.3: Hard must stay inside 2.5-3.8 obj/s; other tiers inside theirs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures: list[dict] = []
        for fixture in FIXTURE_PATHS:
            if not fixture.exists():
                continue
            analysis = analyze_audio(fixture)
            cls.fixtures.append(
                {
                    "path": fixture,
                    "analysis": analysis,
                    "name": fixture.name,
                }
            )
        if not cls.fixtures:
            raise unittest.SkipTest(
                "No density-pin fixtures found; generate public/audio/test-song.mp3 first."
            )

    def _generate(self, analysis, audio_path: Path, difficulty: str, seed: int = 42) -> list[dict]:
        preset = get_difficulty_preset(difficulty)
        controls = resolve_mapping_controls("balanced", None)
        adjusted = apply_mapping_controls(preset, controls)
        variation = build_position_variation_biases(controls)
        with tempfile.TemporaryDirectory(prefix="density-pin-") as tmp:
            output_path = Path(tmp) / f"{difficulty}.json"
            generate_beatmap_from_analysis(
                analysis=analysis,
                audio_path=audio_path,
                title="Density Pin",
                artist="Unit Test",
                difficulty=difficulty,
                seed=seed,
                output_path=output_path,
                analysis_output_path=None,
                project_root=PROJECT_ROOT,
                preset=adjusted,
                base_variation=variation,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        return payload["objects"]

    def test_hard_density_within_spec_band(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                objects = self._generate(fixture["analysis"], fixture["path"], "hard")
                density = _compute_density(objects, fixture["analysis"].duration_ms)
                low, high = DENSITY_PIN_BANDS["hard"]
                self.assertGreaterEqual(
                    density,
                    low,
                    f"Hard density regressed below the {low} obj/s audit floor: "
                    f"{density:.3f} obj/s ({len(objects)} objects) on {fixture['name']}. "
                    "See audit_reports/phase_1_density.md §2.2.",
                )
                self.assertLessEqual(
                    density,
                    high,
                    f"Hard density exceeds the {high} obj/s audit ceiling: "
                    f"{density:.3f} obj/s ({len(objects)} objects) on {fixture['name']}.",
                )

    def test_normal_density_within_spec_band(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                objects = self._generate(fixture["analysis"], fixture["path"], "normal")
                density = _compute_density(objects, fixture["analysis"].duration_ms)
                low, high = DENSITY_PIN_BANDS["normal"]
                self.assertGreaterEqual(density, low, f"Normal density {density:.3f} obj/s below {low} on {fixture['name']}")
                self.assertLessEqual(density, high, f"Normal density {density:.3f} obj/s above {high} on {fixture['name']}")

    def test_easy_density_within_spec_band(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                objects = self._generate(fixture["analysis"], fixture["path"], "easy")
                density = _compute_density(objects, fixture["analysis"].duration_ms)
                low, high = DENSITY_PIN_BANDS["easy"]
                self.assertGreaterEqual(density, low, f"Easy density {density:.3f} obj/s below {low} on {fixture['name']}")
                self.assertLessEqual(density, high, f"Easy density {density:.3f} obj/s above {high} on {fixture['name']}")

    def test_density_is_deterministic_for_fixed_seed(self) -> None:
        """Same seed → same object count (guards flaky density assertions)."""
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                first = self._generate(fixture["analysis"], fixture["path"], "hard", seed=42)
                second = self._generate(fixture["analysis"], fixture["path"], "hard", seed=42)
                self.assertEqual(len(first), len(second))


if __name__ == "__main__":
    unittest.main()
