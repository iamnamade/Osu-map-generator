from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.map_generator.difficulty import analyze_difficulty, plan_rebalancing
from tools.map_generator.difficulty.metrics import compute_raw_metrics
from tools.map_generator.difficulty.models import DifficultyReport
from tools.map_generator.difficulty.targets import build_custom_target, get_difficulty_target
from tools.map_generator.difficulty.loader import load_difficulty_map_from_dict


def make_beatmap_dict(
    *,
    difficulty: str = "normal",
    approach_time_ms: int = 950,
    circle_radius: int = 40,
    gaps_ms: list[int] | None = None,
    spread_px: int = 120,
) -> dict:
    gaps = gaps_ms or [500, 700, 600, 800]
    objects = []
    time_ms = 1000
    x, y = 120, 120
    for index, gap in enumerate(gaps, start=1):
        objects.append(
            {
                "id": index,
                "type": "circle",
                "x": x,
                "y": y,
                "time": time_ms,
            }
        )
        time_ms += gap
        x = (x + spread_px) % 480 + 16
        y = (y + spread_px // 2) % 352 + 16
    objects.append(
        {
            "id": len(objects) + 1,
            "type": "circle",
            "x": x,
            "y": y,
            "time": time_ms,
        }
    )
    return {
        "title": "Test Song",
        "artist": "Unknown Artist",
        "audio": "/audio/test-song.mp3",
        "approachTime": approach_time_ms,
        "circleRadius": circle_radius,
        "objects": objects,
        "generator": {"difficulty": difficulty, "seed": 42},
    }


class DifficultyLoaderTests(unittest.TestCase):
    def test_load_difficulty_map_from_dict(self) -> None:
        beatmap = load_difficulty_map_from_dict(
            make_beatmap_dict(),
            map_label="public/maps/generated/test-map.json",
        )
        self.assertEqual(beatmap.object_count, 5)
        self.assertEqual(beatmap.approach_time_ms, 950)
        self.assertEqual(beatmap.circle_radius, 40)

    def test_loader_handles_sliders_and_spinners(self) -> None:
        raw = make_beatmap_dict()
        raw["objects"].append(
            {
                "id": 99,
                "type": "slider",
                "x": 100,
                "y": 100,
                "time": 9000,
                "endTime": 9500,
                "pathType": "bezier",
                "controlPoints": [{"x": 100, "y": 100}, {"x": 200, "y": 120}],
                "repeats": 2,
                "pixelLength": 90,
            }
        )
        raw["objects"].append(
            {
                "id": 100,
                "type": "spinner",
                "time": 10000,
                "endTime": 11500,
            }
        )
        beatmap = load_difficulty_map_from_dict(
            raw,
            map_label="public/maps/generated/test-map.json",
        )
        types = [item.object_type for item in beatmap.objects]
        self.assertIn("slider", types)
        self.assertIn("spinner", types)


class DifficultyMetricsTests(unittest.TestCase):
    def test_raw_metrics_compute_expected_fields(self) -> None:
        beatmap = load_difficulty_map_from_dict(
            make_beatmap_dict(),
            map_label="public/maps/generated/test-map.json",
        )
        metrics = compute_raw_metrics(beatmap)
        self.assertEqual(metrics.object_count, 5)
        self.assertGreater(metrics.objects_per_second, 0)
        self.assertGreaterEqual(metrics.average_jump_distance, 0)
        self.assertGreaterEqual(metrics.longest_stream_length, 1)
        self.assertGreaterEqual(metrics.recovery_window_count, 0)

    def test_deterministic_metrics(self) -> None:
        raw = make_beatmap_dict()
        first = compute_raw_metrics(
            load_difficulty_map_from_dict(
                raw,
                map_label="public/maps/generated/test-map.json",
            )
        )
        second = compute_raw_metrics(
            load_difficulty_map_from_dict(
                raw,
                map_label="public/maps/generated/test-map.json",
            )
        )
        self.assertEqual(first.to_dict(), second.to_dict())


class DifficultyAnalyzerTests(unittest.TestCase):
    def _run(self, raw: dict, difficulty: str = "normal") -> DifficultyReport:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = temp_path / "map.json"
            output_path = temp_path / "report.json"
            map_path.write_text(json.dumps(raw), encoding="utf-8")
            result = analyze_difficulty(
                map_path=map_path,
                analysis_path=None,
                difficulty=difficulty,
                output_path=output_path,
                map_label="public/maps/generated/test-map.json",
            )
            self.assertTrue(output_path.exists())
            return result.report

    def test_report_contains_star_rating_and_metrics(self) -> None:
        report = self._run(make_beatmap_dict())
        self.assertEqual(report.version, 1)
        self.assertGreater(report.star_rating.overall, 0)
        self.assertGreater(report.metrics.object_count, 0)
        self.assertTrue(report.curve)
        self.assertTrue(report.sections)
        self.assertIsInstance(report.diagnostics.difficulty_histogram, dict)

    def test_report_is_deterministic(self) -> None:
        raw = make_beatmap_dict()
        first = self._run(raw)
        second = self._run(raw)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_easy_and_hard_star_ordering(self) -> None:
        easy_raw = make_beatmap_dict(
            difficulty="easy",
            approach_time_ms=1200,
            circle_radius=46,
            gaps_ms=[1000, 1100, 1200, 900],
            spread_px=60,
        )
        hard_raw = make_beatmap_dict(
            difficulty="hard",
            approach_time_ms=720,
            circle_radius=34,
            gaps_ms=[180, 200, 190, 210],
            spread_px=220,
        )
        easy = self._run(easy_raw, "easy")
        hard = self._run(hard_raw, "hard")
        self.assertGreater(hard.star_rating.overall, easy.star_rating.overall)

    def test_recommended_level_present(self) -> None:
        report = self._run(make_beatmap_dict())
        self.assertIsInstance(report.recommended_player_level, str)
        self.assertTrue(report.recommended_player_level)

    def test_sections_and_heatmap_match(self) -> None:
        report = self._run(make_beatmap_dict())
        self.assertEqual(len(report.heatmap), len(report.sections))
        for heat in report.heatmap:
            self.assertIn("difficultyScore", heat)


class DifficultyTargetTests(unittest.TestCase):
    def test_target_profiles_available(self) -> None:
        for name in ("easy", "normal", "hard", "insane", "expert", "custom"):
            target = get_difficulty_target(name)
            self.assertGreater(target.star_range[1], target.star_range[0])

    def test_star_ordering_of_targets(self) -> None:
        easy = get_difficulty_target("easy")
        hard = get_difficulty_target("hard")
        self.assertLess(easy.star_center, hard.star_center)

    def test_build_custom_target_band(self) -> None:
        target = build_custom_target(5.0, 4.0, 6.0)
        self.assertEqual(target.name, "custom")
        self.assertEqual(target.star_range, (4.0, 6.0))
        self.assertAlmostEqual(target.star_center, 5.0)

    def test_build_custom_target_rejects_impossible_band(self) -> None:
        with self.assertRaises(ValueError):
            build_custom_target(8.0, 9.0, 7.0)
        with self.assertRaises(ValueError):
            build_custom_target(13.0, 12.0, 14.0)

    def test_custom_target_drives_difficulty_report(self) -> None:
        raw = make_beatmap_dict(gaps_ms=[180, 200, 190, 210], spread_px=220)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = temp_path / "map.json"
            map_path.write_text(json.dumps(raw), encoding="utf-8")
            result = analyze_difficulty(
                map_path=map_path,
                analysis_path=None,
                difficulty="hard",
                output_path=None,
                map_label="public/maps/generated/test-map.json",
                target=build_custom_target(6.0, 5.0, 7.0),
            )
        report = result.report
        self.assertEqual(report.target.name, "custom")
        self.assertEqual(report.target.star_range, (5.0, 7.0))
        # The custom target participates in the report signature.
        self.assertTrue(report.signature)
        self.assertNotEqual(
            report.target.name,
            get_difficulty_target("hard").name,
        )


class RebalancerTests(unittest.TestCase):
    def test_within_target_plan_has_no_actions(self) -> None:
        beatmap = load_difficulty_map_from_dict(
            make_beatmap_dict(),
            map_label="public/maps/generated/test-map.json",
        )
        metrics = compute_raw_metrics(beatmap)
        plan = plan_rebalancing(
            beatmap,
            star_rating=2.8,
            target=get_difficulty_target("normal"),
            metrics=metrics,
            object_scores=[],
            seed=42,
        )
        self.assertEqual(plan.deviation.direction, "within")
        self.assertEqual(plan.actions, [])

    def test_above_target_plan_proposes_actions(self) -> None:
        beatmap = load_difficulty_map_from_dict(
            make_beatmap_dict(gaps_ms=[150, 150, 150, 150], spread_px=300),
            map_label="public/maps/generated/test-map.json",
        )
        metrics = compute_raw_metrics(beatmap)
        plan = plan_rebalancing(
            beatmap,
            star_rating=8.0,
            target=get_difficulty_target("easy"),
            metrics=metrics,
            object_scores=[],
            seed=42,
        )
        self.assertEqual(plan.deviation.direction, "above")
        self.assertGreater(len(plan.actions), 0)

    def test_plan_is_deterministic(self) -> None:
        beatmap = load_difficulty_map_from_dict(
            make_beatmap_dict(gaps_ms=[150, 150, 150, 150], spread_px=300),
            map_label="public/maps/generated/test-map.json",
        )
        metrics = compute_raw_metrics(beatmap)
        first = plan_rebalancing(
            beatmap,
            star_rating=8.0,
            target=get_difficulty_target("easy"),
            metrics=metrics,
            object_scores=[],
            seed=42,
        )
        second = plan_rebalancing(
            beatmap,
            star_rating=8.0,
            target=get_difficulty_target("easy"),
            metrics=metrics,
            object_scores=[],
            seed=42,
        )
        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
