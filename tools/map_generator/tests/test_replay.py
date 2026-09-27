from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from tools.map_generator.evolution.models import EvolutionDimensionScores
from tools.map_generator.evolution.scoring import score_candidate
from tools.map_generator.replay import (
    PLAYER_PROFILES,
    ReplayScoreWeights,
    compute_replay_score,
    load_replay_report,
    resolve_player_profile,
    simulate_replay,
    write_replay_report,
)
from tools.map_generator.replay.models import ReplayScoreBreakdown
from tools.map_generator.replay.replay_simulator import replay_generator_metadata
from tools.map_generator.utils import write_json


def _make_map(*, approach_time: int = 700, radius: int = 40) -> dict:
    objects = [
        {"id": 1, "type": "circle", "x": 100.0, "y": 100.0, "time": 500},
        {"id": 2, "type": "circle", "x": 220.0, "y": 130.0, "time": 900},
        {"id": 3, "type": "circle", "x": 340.0, "y": 100.0, "time": 1300},
        {"id": 4, "type": "circle", "x": 360.0, "y": 220.0, "time": 1700},
        {"id": 5, "type": "circle", "x": 240.0, "y": 230.0, "time": 2100},
        {"id": 6, "type": "circle", "x": 120.0, "y": 210.0, "time": 2500},
        {"id": 7, "type": "circle", "x": 100.0, "y": 320.0, "time": 2900},
        {"id": 8, "type": "circle", "x": 260.0, "y": 340.0, "time": 3300},
        {"id": 9, "type": "circle", "x": 380.0, "y": 300.0, "time": 3700},
        {"id": 10, "type": "slider", "x": 400.0, "y": 120.0, "time": 4100, "endTime": 4400},
        {"id": 11, "type": "spinner", "time": 4600, "endTime": 5600},
        {"id": 12, "type": "circle", "x": 200.0, "y": 160.0, "time": 5800},
    ]
    return {
        "title": "Replay Test",
        "artist": "Unit Tests",
        "audio": "/audio/replay-test.mp3",
        "approachTime": approach_time,
        "circleRadius": radius,
        "objects": objects,
    }


def _write_map(temp_dir: Path) -> Path:
    path = temp_dir / "map.json"
    write_json(path, _make_map())
    return path


class ReplaySimulationTests(unittest.TestCase):
    def test_deterministic_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            first = simulate_replay(map_path=map_path, difficulty="normal", seed=7, player_profile="advanced")
            second = simulate_replay(map_path=map_path, difficulty="normal", seed=7, player_profile="advanced")
            self.assertEqual(first.to_dict(), second.to_dict())

    def test_players_ranked_by_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            beginner = simulate_replay(map_path=map_path, difficulty="normal", seed=7, player_profile="beginner")
            tournament = simulate_replay(map_path=map_path, difficulty="normal", seed=7, player_profile="tournament")
            self.assertGreater(
                beginner.expected_misses,
                tournament.expected_misses,
            )
            self.assertGreater(
                tournament.score_breakdown.overall,
                beginner.score_breakdown.overall,
            )

    def test_profiles_available(self) -> None:
        for name in ("beginner", "intermediate", "advanced", "tournament", "custom"):
            self.assertIn(name, PLAYER_PROFILES)

    def test_custom_profile_overrides(self) -> None:
        profile = resolve_player_profile(
            "advanced",
            {"reactionTimeMs": 150.0, "aimPrecision": 0.99},
        )
        self.assertEqual(profile.reaction_time_ms, 150.0)
        self.assertEqual(profile.aim_precision, 0.99)
        self.assertEqual(profile.cursor_speed_pps, PLAYER_PROFILES["advanced"].cursor_speed_pps)
        clamped = resolve_player_profile("advanced", {"aimPrecision": 5.0})
        self.assertEqual(clamped.aim_precision, 1.0)

    def test_hit_results_cover_all_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=3, player_profile="intermediate")
            positioned = sum(1 for item in report.hit_events)
            self.assertEqual(
                sum(report.result_counts.values()),
                positioned,
            )
            self.assertGreaterEqual(report.expected_accuracy, 0.0)
            self.assertLessEqual(report.expected_accuracy, 1.0)
            for result in report.result_counts:
                self.assertIn(result, ("perfect", "great", "good", "meh", "miss"))

    def test_cursor_simulation_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=3)
            self.assertGreater(report.cursor.total_travel_px, 0.0)
            self.assertGreaterEqual(report.cursor.efficiency, 0.0)
            self.assertLessEqual(report.cursor.efficiency, 1.0)
            self.assertGreater(len(report.cursor.segments), 0)

    def test_combo_stats_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=3)
            self.assertGreaterEqual(report.combo.expected_combo_pct, 0.0)
            self.assertLessEqual(report.combo.expected_combo_pct, 1.0)
            self.assertLessEqual(report.combo.max_combo, len(report.hit_events))

    def test_combo_miss_cluster_counting(self) -> None:
        from tools.map_generator.replay.combo import simulate_combo
        from tools.map_generator.replay.models import HitEvent

        def event(time_ms: int, result: str) -> HitEvent:
            return HitEvent(
                object_id=1,
                object_type="circle",
                time_ms=time_ms,
                offset_ms=0.0,
                result=result,
                demand=0.5,
                fatigue=0.1,
            )

        chain = simulate_combo(
            [
                event(1000, "perfect"),
                event(2000, "miss"),
                event(2500, "miss"),
                event(3000, "miss"),
                event(9000, "perfect"),
            ]
        )
        self.assertEqual(chain.miss_clusters, 1)
        self.assertEqual(chain.isolated_misses, 0)

        isolated = simulate_combo(
            [
                event(1000, "perfect"),
                event(2000, "miss"),
                event(9000, "perfect"),
            ]
        )
        self.assertEqual(isolated.miss_clusters, 1)
        self.assertEqual(isolated.isolated_misses, 1)

    def test_pattern_recognition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=3)
            self.assertTrue(report.patterns.patterns)
            for pattern in report.patterns.patterns:
                self.assertGreaterEqual(pattern.recognizability, 0.0)
                self.assertLessEqual(pattern.recognizability, 1.0)
            self.assertGreaterEqual(report.patterns.overall_recognizability, 0.0)
            self.assertLessEqual(report.patterns.overall_recognizability, 1.0)

    def test_reading_and_fatigue_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=3)
            self.assertGreaterEqual(report.reading.score, 0.0)
            self.assertLessEqual(report.reading.score, 100.0)
            self.assertGreaterEqual(report.fatigue.average, 0.0)
            self.assertLessEqual(report.fatigue.peak, 1.0)
            self.assertGreater(len(report.fatigue.samples), 0)

    def test_score_breakdown_and_weights(self) -> None:
        breakdown = compute_replay_score(
            accuracy=0.95,
            miss_rate=0.01,
            combo_pct=0.9,
            full_combo_chance=0.1,
            reading_score=80.0,
            cursor_efficiency=0.85,
            fatigue_average=0.1,
            rhythm_consistency=0.8,
        )
        self.assertAlmostEqual(ReplayScoreWeights().total, 1.0, places=6)
        self.assertGreaterEqual(breakdown.overall, 0.0)
        self.assertLessEqual(breakdown.overall, 100.0)
        for value in (
            breakdown.accuracy_prediction,
            breakdown.miss_prediction,
            breakdown.combo_stability,
            breakdown.reading,
            breakdown.cursor_efficiency,
            breakdown.fatigue,
            breakdown.rhythm_consistency,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)

    def test_report_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=11)
            report_path = Path(temp_dir) / "replay.json"
            write_replay_report(report_path, report)
            loaded = load_replay_report(report_path)
            self.assertEqual(loaded.to_dict(), report.to_dict())

    def test_generator_metadata_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = _write_map(Path(temp_dir))
            report = simulate_replay(map_path=map_path, difficulty="normal", seed=11)
            metadata = replay_generator_metadata(report, "public/reports/replay/x.json")
            self.assertEqual(metadata["playerProfile"], report.player.name)
            self.assertAlmostEqual(metadata["replayScore"], report.score_breakdown.overall)
            self.assertIn("weakestSection", metadata)
            self.assertIn("replayReportPath", metadata)

    def test_evolution_scoring_includes_replay(self) -> None:
        validation = types.SimpleNamespace(
            scores=types.SimpleNamespace(overall=80.0, movement=70.0, rhythm=65.0),
        )
        difficulty_report = types.SimpleNamespace(
            star_rating=types.SimpleNamespace(overall=3.0),
            target=types.SimpleNamespace(star_range=[2.2, 3.9]),
            reading=types.SimpleNamespace(score=0.5),
            rhythm=types.SimpleNamespace(score=0.5),
            aim=types.SimpleNamespace(flow_quality=0.6),
            consistency_score=0.7,
            confidence_score=0.7,
            metrics=types.SimpleNamespace(
                pattern_variation=0.5,
                longest_stream_length=8,
                longest_burst_length=4,
                slider_count=0,
                slider_complexity=0.0,
                average_slider_repeats=0.0,
                spinner_frequency_per_minute=0.0,
            ),
            sections=[],
            gameplay=types.SimpleNamespace(
                estimated_miss_probability=0.1,
                estimated_combo_stability=0.4,
                estimated_player_stress=0.5,
            ),
        )
        replay_report = types.SimpleNamespace(
            score_breakdown=ReplayScoreBreakdown(
                accuracy_prediction=90.0,
                miss_prediction=80.0,
                combo_stability=70.0,
                reading=75.0,
                cursor_efficiency=80.0,
                fatigue=60.0,
                rhythm_consistency=70.0,
                overall=78.5,
            )
        )
        with_replay = score_candidate(
            improved_report=validation,
            difficulty_report=difficulty_report,
            replay_report=replay_report,
        )
        without = score_candidate(
            improved_report=validation,
            difficulty_report=difficulty_report,
        )
        self.assertNotEqual(with_replay.replay, without.replay)
        self.assertEqual(without.replay, 50.0)
        self.assertEqual(with_replay.replay, 78.5)
        self.assertNotEqual(with_replay.overall, without.overall)

    def test_evolution_dimension_scores_include_replay(self) -> None:
        scores = EvolutionDimensionScores(
            overall=80.0,
            quality=80.0,
            difficulty=80.0,
            flow=80.0,
            rhythm=80.0,
            movement=80.0,
            pattern=80.0,
            slider=80.0,
            spinner=80.0,
            reading=80.0,
            playability=80.0,
            consistency=80.0,
            confidence=80.0,
        )
        self.assertEqual(scores.replay, 0.0)
        self.assertIn("replay", scores.to_dict())
        self.assertIn("replay", [key for key, _ in scores.as_ordered_values()])


if __name__ == "__main__":
    unittest.main()
