from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from tools.map_generator.difficulty.common import clamp
from tools.map_generator.evolution.archive import (
    apply_archive_policy,
    retained_candidate_count,
    validate_archive_policy,
)
from tools.map_generator.evolution.comparison import build_comparison
from tools.map_generator.evolution.heatmaps import HEATMAP_DIMENSIONS, build_heatmaps
from tools.map_generator.evolution.improvement import (
    ImprovementResult,
    run_improvement_passes,
)
from tools.map_generator.evolution.models import (
    EvolutionChampion,
    EvolutionComparisonEntry,
    EvolutionConfiguration,
    EvolutionDiagnostics,
    EvolutionDimensionScores,
    EvolutionHeatmap,
    EvolutionRankingEntry,
    EvolutionReplaySummary,
    EvolutionReport,
    EvolutionSongInfo,
    EvolutionSummary,
    ImprovementPassEntry,
    RejectedEvolutionCandidate,
)
from tools.map_generator.evolution.report_writer import (
    load_evolution_report,
    write_evolution_report,
)
from tools.map_generator.evolution.scoring import (
    EvolutionScoreWeights,
    score_candidate,
)
from tools.map_generator.utils import MapGeneratorError


def make_validation_report(*, overall: float = 88.0, movement: float = 85.0, rhythm: float = 82.0):
    return types.SimpleNamespace(
        scores=types.SimpleNamespace(
            overall=overall,
            movement=movement,
            rhythm=rhythm,
        )
    )


def make_difficulty_report(
    *,
    stars: float = 3.1,
    reading: float = 0.45,
    rhythm: float = 0.5,
    flow: float = 0.62,
    consistency: float = 0.8,
    confidence: float = 0.75,
    pattern_variation: float = 0.55,
    longest_stream: int = 8,
    longest_burst: int = 4,
    slider_count: int = 3,
    slider_complexity: float = 0.3,
    average_slider_repeats: float = 1.2,
    spinner_frequency: float = 0.4,
    miss: float = 0.12,
    combo: float = 0.3,
    stress: float = 0.4,
    target_range: tuple[float, float] = (2.2, 3.9),
):
    return types.SimpleNamespace(
        star_rating=types.SimpleNamespace(overall=stars),
        target=types.SimpleNamespace(
            star_range=list(target_range),
        ),
        reading=types.SimpleNamespace(score=reading),
        rhythm=types.SimpleNamespace(score=rhythm),
        aim=types.SimpleNamespace(flow_quality=flow),
        consistency_score=consistency,
        confidence_score=confidence,
        metrics=types.SimpleNamespace(
            pattern_variation=pattern_variation,
            longest_stream_length=longest_stream,
            longest_burst_length=longest_burst,
            slider_count=slider_count,
            slider_complexity=slider_complexity,
            average_slider_repeats=average_slider_repeats,
            spinner_frequency_per_minute=spinner_frequency,
            objects_per_second=2.0,
            average_jump_distance=140.0,
            average_cursor_velocity_pps=520.0,
        ),
        sections=[],
        gameplay=types.SimpleNamespace(
            estimated_miss_probability=miss,
            estimated_combo_stability=combo,
            estimated_player_stress=stress,
        ),
    )


def make_difficulty_result(
    *,
    stars: float = 3.1,
    with_plan: bool = True,
) -> types.SimpleNamespace:
    """Wrap a difficulty report in the shape the improvement loop expects."""
    return types.SimpleNamespace(
        report=make_difficulty_report(stars=stars),
        rebalance_plan=(
            types.SimpleNamespace(
                actions=[
                    types.SimpleNamespace(
                        action="reduce_jump",
                        object_id=1,
                        after={"x": 100.0, "y": 100.0},
                    )
                ],
                deviation=types.SimpleNamespace(is_within_target=False),
            )
            if with_plan
            else types.SimpleNamespace(actions=[], deviation=types.SimpleNamespace(is_within_target=True))
        ),
    )


def make_scores(overall: float, quality: float | None = None) -> EvolutionDimensionScores:
    resolved_quality = 80.0 if quality is None else quality
    return EvolutionDimensionScores(
        overall=overall,
        quality=resolved_quality,
        difficulty=90.0,
        flow=75.0,
        rhythm=70.0,
        movement=85.0,
        pattern=78.0,
        slider=82.0,
        spinner=95.0,
        reading=72.0,
        playability=76.0,
        consistency=88.0,
        confidence=84.0,
    )


class ScoringTests(unittest.TestCase):
    def test_score_within_target_is_deterministic(self) -> None:
        validation = make_validation_report()
        difficulty = make_difficulty_report(stars=3.0)
        first = score_candidate(
            improved_report=validation,
            difficulty_report=difficulty,
        )
        second = score_candidate(
            improved_report=validation,
            difficulty_report=difficulty,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertGreater(first.overall, 0)
        self.assertLessEqual(first.overall, 100)

    def test_score_outside_target_reduces_difficulty_component(self) -> None:
        validation = make_validation_report()
        within = score_candidate(
            improved_report=validation,
            difficulty_report=make_difficulty_report(stars=3.0),
        )
        far = score_candidate(
            improved_report=validation,
            difficulty_report=make_difficulty_report(stars=8.5),
        )
        self.assertGreater(within.difficulty, far.difficulty)

    def test_playability_penalizes_misses(self) -> None:
        clean = make_difficulty_report(miss=0.02, combo=0.9)
        sloppy = make_difficulty_report(miss=0.55, combo=0.05)
        clean_score = score_candidate(
            improved_report=make_validation_report(),
            difficulty_report=clean,
        )
        sloppy_score = score_candidate(
            improved_report=make_validation_report(),
            difficulty_report=sloppy,
        )
        self.assertGreater(clean_score.playability, sloppy_score.playability)

    def test_weights_total_one(self) -> None:
        weights = EvolutionScoreWeights()
        self.assertAlmostEqual(weights.total, 1.0, places=4)


class ComparisonTests(unittest.TestCase):
    def test_comparison_reports_delta_and_reasons(self) -> None:
        champion = make_scores(92.0, quality=88.0)
        runner = make_scores(84.0, quality=80.0)
        entries, reasons = build_comparison(
            champion=champion,
            runner=runner,
            improvement_gain=1.2,
        )
        self.assertTrue(entries)
        self.assertTrue(reasons)
        by_dimension = {entry.dimension: entry for entry in entries}
        self.assertIn("quality", by_dimension)
        self.assertGreater(by_dimension["quality"].delta, 0)

    def test_comparison_deterministic(self) -> None:
        champion = make_scores(92.0, quality=88.0)
        runner = make_scores(84.0, quality=80.0)
        first_entries, first_reasons = build_comparison(
            champion=champion,
            runner=runner,
            improvement_gain=0.0,
        )
        second_entries, second_reasons = build_comparison(
            champion=champion,
            runner=runner,
            improvement_gain=0.0,
        )
        self.assertEqual(
            [entry.to_dict() for entry in first_entries],
            [entry.to_dict() for entry in second_entries],
        )
        self.assertEqual(first_reasons, second_reasons)


class HeatmapTests(unittest.TestCase):
    def test_heatmaps_cover_all_dimensions(self) -> None:
        reports = [make_difficulty_report(stars=2.6), make_difficulty_report(stars=3.4)]
        heatmaps = build_heatmaps(
            difficulty_reports=reports,
            ranking_indices=[1, 2],
        )
        self.assertEqual(
            [heatmap.dimension for heatmap in heatmaps],
            list(HEATMAP_DIMENSIONS),
        )
        for heatmap in heatmaps:
            self.assertEqual(len(heatmap.values), 2)
            for value in heatmap.values:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_heatmaps_deterministic(self) -> None:
        reports = [make_difficulty_report(stars=2.6), make_difficulty_report(stars=3.4)]
        first = build_heatmaps(
            difficulty_reports=reports,
            ranking_indices=[1, 2],
        )
        second = build_heatmaps(
            difficulty_reports=reports,
            ranking_indices=[1, 2],
        )
        self.assertEqual(
            [heatmap.to_dict() for heatmap in first],
            [heatmap.to_dict() for heatmap in second],
        )


class ArchiveTests(unittest.TestCase):
    def test_validate_policy_rejects_unknown(self) -> None:
        with self.assertRaises(MapGeneratorError):
            validate_archive_policy("everything")

    def test_retained_count_by_policy(self) -> None:
        self.assertEqual(retained_candidate_count("champion", 8), 1)
        self.assertEqual(retained_candidate_count("top3", 8), 3)
        self.assertEqual(retained_candidate_count("top5", 8), 5)
        self.assertEqual(retained_candidate_count("all", 8), 8)

    def test_apply_archive_policy_dry_run_keeps_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in (1, 2, 3):
                (root / f"candidate-{index:03d}").mkdir()
            retained = apply_archive_policy(
                candidates_root=root,
                ranked_candidate_indices=[2, 1, 3],
                policy="champion",
                dry_run=True,
            )
            self.assertEqual(retained, [2])
            self.assertTrue((root / "candidate-003").exists())


class ImprovementTests(unittest.TestCase):
    def _plan(self, *, actions: int = 3, within_target: bool = False):
        return types.SimpleNamespace(
            actions=[types.SimpleNamespace(action="reduce_jump", object_id=i, after={"x": 100.0, "y": 100.0}) for i in range(actions)],
            deviation=types.SimpleNamespace(is_within_target=within_target),
        )

    def test_stops_early_when_no_gain(self) -> None:
        current_scores = score_candidate(
            improved_report=make_validation_report(overall=90.0),
            difficulty_report=make_difficulty_report(stars=3.0),
        )
        baseline_overall = current_scores.overall
        improvement = run_improvement_passes(
            current_map={"title": "T", "artist": "A", "audio": "", "approachTime": 950, "circleRadius": 40, "objects": []},
            current_plan=self._plan(),
            current_scores=current_scores,
            pass_processor=lambda adjusted: (make_validation_report(overall=85.0), make_difficulty_result(stars=3.0)),
            seed=42,
            max_passes=2,
        )
        self.assertTrue(improvement.early_stopped)
        self.assertEqual(improvement.passes_used, 1)
        self.assertEqual(improvement.final_scores.overall, baseline_overall)

    def test_accepts_gain_and_stops_on_reversal(self) -> None:
        current_scores = score_candidate(
            improved_report=make_validation_report(overall=80.0),
            difficulty_report=make_difficulty_report(stars=3.0),
        )
        calls = []

        def processor(adjusted):
            calls.append(1)
            if len(calls) == 1:
                return (make_validation_report(overall=98.0), make_difficulty_result(stars=3.0))
            return (make_validation_report(overall=55.0), make_difficulty_result(stars=3.0))

        improvement = run_improvement_passes(
            current_map={"title": "T", "artist": "A", "audio": "", "approachTime": 950, "circleRadius": 40, "objects": []},
            current_plan=self._plan(),
            current_scores=current_scores,
            pass_processor=processor,
            seed=42,
            max_passes=2,
        )
        self.assertEqual(improvement.passes_used, 2)
        self.assertGreater(improvement.improvement_gain, 0)
        self.assertTrue(improvement.history[0].accepted)
        self.assertFalse(improvement.history[1].accepted)

    def test_within_target_plan_stops_immediately(self) -> None:
        improvement = run_improvement_passes(
            current_map={"title": "T", "artist": "A", "audio": "", "approachTime": 950, "circleRadius": 40, "objects": []},
            current_plan=self._plan(within_target=True),
            current_scores=make_scores(88.0),
            pass_processor=lambda adjusted: (make_validation_report(), make_difficulty_result()),
            seed=42,
            max_passes=2,
        )
        self.assertEqual(improvement.passes_used, 0)
        self.assertTrue(improvement.early_stopped)

    def test_zero_passes_returns_immediately(self) -> None:
        improvement = run_improvement_passes(
            current_map={"title": "T", "artist": "A", "audio": "", "approachTime": 950, "circleRadius": 40, "objects": []},
            current_plan=self._plan(),
            current_scores=make_scores(88.0),
            pass_processor=lambda adjusted: (make_validation_report(), make_difficulty_result()),
            seed=42,
            max_passes=0,
        )
        self.assertEqual(improvement.passes_used, 0)
        self.assertEqual(improvement.improvement_gain, 0.0)


class ReportRoundTripTests(unittest.TestCase):
    def _report(self) -> EvolutionReport:
        return EvolutionReport(
            version=1,
            song=EvolutionSongInfo(title="Test Song", artist="Unknown Artist", difficulty="normal", audio="/audio/test-song.mp3"),
            configuration=EvolutionConfiguration(root_seed=42, candidate_count=3, max_passes=2, archive_policy="all", timing_variation=False),
            summary=EvolutionSummary(generated=3, eligible=3, rejected=0, passes_used=1, early_stopped=False),
            champion=EvolutionChampion(
                candidate_index=2,
                candidate_seed=99,
                overall_score=91.2,
                quality_score=88.0,
                stars=3.2,
                map_path="/maps/champions/test-song-normal.json",
                report_path="/reports/champions/test-song-normal-report.json",
                source_map_path="public/candidates/test-song/normal/candidate-002/improved-map.json",
                source_report_path="public/candidates/test-song/normal/candidate-002/improved-report.json",
                summary_path="public/candidates/test-song/normal/candidate-002/candidate-summary.json",
                promotion_reason="Candidate 002 won by 4.1 points overall.",
            ),
            ranking=[
                EvolutionRankingEntry(
                    rank=1,
                    candidate_index=2,
                    candidate_seed=99,
                    stars=3.2,
                    scores=make_scores(91.2),
                    map_path="public/candidates/test-song/normal/candidate-002/improved-map.json",
                    report_path="public/candidates/test-song/normal/candidate-002/improved-report.json",
                    summary_path="public/candidates/test-song/normal/candidate-002/candidate-summary.json",
                ),
                EvolutionRankingEntry(
                    rank=2,
                    candidate_index=1,
                    candidate_seed=98,
                    stars=2.9,
                    scores=make_scores(87.1),
                    map_path="public/candidates/test-song/normal/candidate-001/improved-map.json",
                    report_path="public/candidates/test-song/normal/candidate-001/improved-report.json",
                    summary_path="public/candidates/test-song/normal/candidate-001/candidate-summary.json",
                ),
            ],
            rejected_candidates=[
                RejectedEvolutionCandidate(
                    candidate_index=3,
                    candidate_seed=97,
                    overall_score=40.0,
                    rejection_reasons=["Improved report is not structurally valid."],
                    summary_path="public/candidates/test-song/normal/candidate-003/candidate-summary.json",
                )
            ],
            comparison=[
                EvolutionComparisonEntry(
                    dimension="quality",
                    champion_value=88.0,
                    runner_value=80.0,
                    delta=8.0,
                    note="Champion leads by 8.0 points on Quality.",
                )
            ],
            comparison_reasons=["Champion gained 8.0 points on Quality."],
            heatmaps=[
                EvolutionHeatmap(dimension="movement", label="Movement", values=[0.5, 0.6])
            ],
            replay=EvolutionReplaySummary(
                full_combo_chance=0.3,
                expected_accuracy=0.91,
                expected_misses=0.4,
                highest_stress_section_ms=4500,
                hardest_pattern="stream",
                most_difficult_transition_ms=6200,
            ),
            improvement_history=[
                ImprovementPassEntry(pass_number=1, candidate_index=2, overall_before=88.0, overall_after=91.2, accepted=True)
            ],
            diagnostics=EvolutionDiagnostics(
                score_distribution={"60-69": 0, "70-79": 0, "80-89": 1, "90-100": 1},
                average_improvement=3.2,
                promotion_reason="Candidate 002 won by 4.1 points overall.",
                confidence=82.8,
            ),
            score_weights=EvolutionScoreWeights().to_dict(),
        )

    def test_write_and_load_round_trip(self) -> None:
        report = self._report()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evolution.json"
            write_evolution_report(path, report)
            loaded = load_evolution_report(path)
        self.assertEqual(loaded.to_dict(), report.to_dict())

    def test_loaded_report_shape(self) -> None:
        loaded = self._load_roundtrip()
        self.assertEqual(loaded.champion.candidate_index, 2)
        self.assertEqual(loaded.champion.overall_score, 91.2)
        self.assertEqual(len(loaded.ranking), 2)
        self.assertEqual(len(loaded.heatmaps), 1)
        self.assertEqual(loaded.replay.hardest_pattern, "stream")

    def _load_roundtrip(self) -> EvolutionReport:
        report = self._report()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evolution.json"
            write_evolution_report(path, report)
            return load_evolution_report(path)


if __name__ == "__main__":
    unittest.main()
