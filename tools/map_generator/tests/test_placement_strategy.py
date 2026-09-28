#!/usr/bin/env python3
"""P2.1 — PlacementStrategy abstraction tests.

Pins the standard osu! placement output (the production pattern-intelligence
path) to a golden baseline so the refactor is provably regression-free, and
covers the extensibility seam (registry, custom strategy, mode hooks).
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = SCRIPT_DIR.parent.parent
PROJECT_ROOT = TOOLS_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.map_generator.config import get_difficulty_preset
from tools.map_generator.models import SelectedEvent
from tools.map_generator.placement import (
    DEFAULT_PLACEMENT_STRATEGY,
    PlacementContext,
    PlacementStrategy,
    PositionGenerationResult,
    get_placement_strategy,
    list_placement_strategies,
    register_placement_strategy,
)
from tools.map_generator.placement.osu_modes import (
    OsuCatchPlacementStrategy,
    OsuManiaPlacementStrategy,
)
from tools.map_generator.placement.osu_standard import OsuStandardPlacementStrategy
from tools.map_generator.position_generator import generate_positions
from tools.map_generator.utils import MapGeneratorError

# Golden output captured from the pre-refactor standard path for this exact
# synthetic event list and seed. Any drift means default placement changed.
_GOLDEN_POSITIONS: dict[str, list[tuple[int, int]]] = {
    "easy": [
        (276, 136), (268, 185), (264, 214), (244, 236), (256, 263), (251, 292),
        (256, 262), (251, 292), (256, 262), (251, 292), (246, 316), (249, 279),
        (250, 239), (249, 232), (249, 226), (249, 219), (251, 213), (274, 204),
        (268, 189), (251, 180), (230, 183), (207, 177), (187, 189), (164, 182),
    ],
    "normal": [
        (276, 136), (259, 246), (185, 262), (250, 299), (176, 315), (242, 324),
        (168, 324), (219, 248), (192, 287), (219, 248), (192, 287), (219, 248),
        (172, 164), (126, 86), (99, 60), (65, 60), (60, 60), (60, 60), (60, 60),
        (60, 60), (108, 92), (62, 60), (128, 105), (70, 60),
    ],
    "hard": [
        (276, 136), (242, 332), (250, 248), (400, 207), (261, 138), (411, 97),
        (272, 52), (422, 52), (327, 132), (271, 243), (327, 132), (271, 243),
        (327, 132), (405, 52), (316, 136), (401, 52), (317, 133), (251, 65),
        (174, 52), (97, 52), (52, 52), (52, 52), (52, 52), (174, 136),
    ],
}


def _events() -> list[SelectedEvent]:
    return [
        SelectedEvent(
            time_ms=1000 + index * 240,
            source="beat",
            strength=0.3 + (index % 5) * 0.14,
            energy=0.2 + (index % 4) * 0.2,
            confidence=0.8,
            is_emphasis=index % 3 == 0,
        )
        for index in range(24)
    ]


class PlacementStrategyTests(unittest.TestCase):
    def test_default_strategy_is_standard(self) -> None:
        strategy = get_placement_strategy()
        self.assertIsInstance(strategy, OsuStandardPlacementStrategy)
        self.assertEqual(strategy.name, DEFAULT_PLACEMENT_STRATEGY)
        self.assertEqual(strategy.mode, "osu")
        self.assertEqual(strategy.playfield_width, 512.0)
        self.assertEqual(strategy.playfield_height, 384.0)

    def test_registry_exposes_future_mode_hooks(self) -> None:
        names = list_placement_strategies()
        self.assertEqual(names, ("catch", "mania", "standard"))
        self.assertEqual(get_placement_strategy("catch").mode, "catch")
        self.assertEqual(get_placement_strategy("mania").mode, "mania")

    def test_unknown_strategy_raises(self) -> None:
        with self.assertRaises(MapGeneratorError):
            get_placement_strategy("does-not-exist")

    def test_standard_placement_matches_golden_baseline(self) -> None:
        events = _events()
        for difficulty, expected in _GOLDEN_POSITIONS.items():
            with self.subTest(difficulty=difficulty):
                preset = get_difficulty_preset(difficulty)
                result = generate_positions(events, preset, 42)
                coordinates = [(obj.x, obj.y) for obj in result.objects]
                self.assertEqual(
                    coordinates,
                    expected,
                    f"{difficulty} placement drifted from the pinned standard baseline",
                )

    def test_facade_delegates_to_strategy(self) -> None:
        events = _events()
        preset = get_difficulty_preset("hard")
        direct = OsuStandardPlacementStrategy().generate(
            PlacementContext(events=events, preset=preset, seed=42)
        )
        via_facade = generate_positions(events, preset, 42)
        self.assertEqual(
            [(obj.x, obj.y) for obj in direct.objects],
            [(obj.x, obj.y) for obj in via_facade.objects],
        )

    def test_custom_strategy_is_honored(self) -> None:
        class _StubStrategy(PlacementStrategy):
            name = "stub"
            mode = "stub"

            @property
            def playfield_width(self) -> float:
                return 512.0

            @property
            def playfield_height(self) -> float:
                return 384.0

            def generate(self, context: PlacementContext) -> PositionGenerationResult:
                return PositionGenerationResult(objects=[], rejected_candidates=7)

        result = generate_positions(
            _events(),
            get_difficulty_preset("hard"),
            42,
            strategy=_StubStrategy(),
        )
        self.assertEqual(result.rejected_candidates, 7)
        self.assertEqual(result.objects, [])

    def test_classic_fallback_is_deterministic_and_in_bounds(self) -> None:
        """The classic jump-curve path (pattern engine off) stays in-bounds."""
        events = _events()
        preset = replace(get_difficulty_preset("hard"), pattern_intelligence_enabled=False)

        first = generate_positions(events, preset, 42)
        second = generate_positions(events, preset, 42)

        self.assertEqual(len(first.objects), len(events))
        self.assertEqual(
            [(obj.x, obj.y) for obj in first.objects],
            [(obj.x, obj.y) for obj in second.objects],
        )
        padding = preset.circle_radius + preset.safe_margin
        for obj in first.objects:
            self.assertGreaterEqual(obj.x, padding)
            self.assertLessEqual(obj.x, 512 - padding)
            self.assertGreaterEqual(obj.y, padding)
            self.assertLessEqual(obj.y, 384 - padding)

    def test_catch_hook_pins_plate_row(self) -> None:
        catch = OsuCatchPlacementStrategy()
        self.assertEqual(catch.transform_position(123.0, 45.0), (123.0, 192.0))

    def test_mania_hook_quantizes_columns(self) -> None:
        mania = OsuManiaPlacementStrategy(columns=4)
        # x=300 falls in column 2 (128-256), centered at 320.
        self.assertEqual(mania.transform_position(300.0, 0.0)[0], 320.0)
        # x=10 clamps to column 0, centered at 64.
        self.assertEqual(mania.transform_position(10.0, 0.0)[0], 64.0)
        # x=600 clamps to the last column, centered at 448.
        self.assertEqual(mania.transform_position(600.0, 0.0)[0], 448.0)

    def test_duplicate_registration_is_rejected(self) -> None:
        with self.assertRaises(MapGeneratorError):
            register_placement_strategy(OsuStandardPlacementStrategy())


if __name__ == "__main__":
    unittest.main()
