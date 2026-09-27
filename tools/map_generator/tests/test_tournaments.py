from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.map_generator.candidates.candidate_config import (
    DiversitySettings,
    EligibilityRules,
    TournamentScoreWeights,
    validate_candidate_count,
)
from tools.map_generator.candidates.candidate_generator import build_candidate_profile
from tools.map_generator.candidates.candidate_models import (
    CandidateDiversity,
    CandidateFiles,
    CandidateIdentity,
    CandidateMetrics,
    CandidateScores,
    CandidateStatus,
    CandidateSummary,
    StabilitySummary,
    TournamentScoreBreakdown,
)
from tools.map_generator.candidates.candidate_pipeline import run_candidate_tournament
from tools.map_generator.candidates.diversity_analyzer import analyze_diversity
from tools.map_generator.candidates.selection_policy import evaluate_candidate_status
from tools.map_generator.candidates.tournament_ranker import build_ranking, score_candidates
from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.tests.test_postprocessing import make_aligned_analysis
from tools.map_generator.utils import MapGeneratorError, write_json


def make_summary(index: int, *, eligible: bool = True) -> CandidateSummary:
    return CandidateSummary(
        version=1,
        candidate=CandidateIdentity(
            index=index,
            difficulty="easy",
            root_seed=42,
            candidate_seed=1000 + index,
            timing_variation_enabled=False,
            variation_signature=f"sig-{index}",
            variation_profile={"jumpDistanceMultiplier": 1.0},
        ),
        files=CandidateFiles(
            original_map=f"public/candidates/test-song/easy/candidate-{index:03d}/original-map.json",
            original_report=f"public/candidates/test-song/easy/candidate-{index:03d}/original-report.json",
            improved_map=f"public/candidates/test-song/easy/candidate-{index:03d}/improved-map.json",
            improved_report=f"public/candidates/test-song/easy/candidate-{index:03d}/improved-report.json",
            corrections=f"public/candidates/test-song/easy/candidate-{index:03d}/corrections.json",
            summary=f"public/candidates/test-song/easy/candidate-{index:03d}/candidate-summary.json",
        ),
        scores=CandidateScores(
            original_overall=82.0,
            improved_overall=90.0,
            improvement=8.0,
        ),
        status=CandidateStatus(
            valid=True,
            playable=True,
            eligible=eligible,
            rejection_reasons=[] if eligible else ["Synthetic rejection"],
        ),
        metrics=CandidateMetrics(
            accepted_corrections=2,
            reverted_corrections=0,
            destructive_corrections=0,
            critical_issues=0,
            errors=0,
            warnings=0,
            max_cursor_speed=220.0,
            object_count=5,
            max_timing_adjustment_ms=0.0,
            max_coordinate_shift_px=0.0,
            timing_signature="shared-signature",
        ),
        diversity=CandidateDiversity(
            average_pairwise_diversity=20.0,
            nearest_neighbor_diversity=10.0,
            similarity_penalty=0.0,
            near_duplicate_count=0,
        ),
        stability=StabilitySummary(
            score=85.0,
            label="Stable",
            speed_margin_ratio=0.4,
            gap_margin_ratio=0.4,
            near_threshold_warnings=0,
            reverted_corrections=0,
            accepted_correction_magnitude=0.0,
            quality_swing=8.0,
            severe_section_count=0,
        ),
        score_breakdown=TournamentScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def make_report(*, difficulty_consistency: float = 90.0) -> SimpleNamespace:
    return SimpleNamespace(
        scores=SimpleNamespace(
            structural=92.0,
            timing=91.0,
            rhythm=89.0,
            movement=90.0,
            readability=90.0,
            repetition=89.0,
            density_consistency=90.0,
            difficulty_consistency=difficulty_consistency,
            overall=90.0,
        ),
        summary=SimpleNamespace(critical=0, errors=0, warnings=0),
        metrics=SimpleNamespace(
            movement=SimpleNamespace(speed_violation_count=0, near_limit_run_count=0),
            timing=SimpleNamespace(mistimed_count=0),
        ),
    )


class TournamentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_candidate_seed_derivation_is_stable(self) -> None:
        preset = DIFFICULTY_PRESETS["normal"]
        first = build_candidate_profile(
            preset=preset,
            root_seed=42,
            candidate_index=3,
            timing_variation=False,
        )
        second = build_candidate_profile(
            preset=preset,
            root_seed=42,
            candidate_index=3,
            timing_variation=False,
        )

        self.assertEqual(first.candidate_seed, second.candidate_seed)
        self.assertEqual(first.variation_signature, second.variation_signature)

    def test_different_root_seed_changes_candidate_seed(self) -> None:
        preset = DIFFICULTY_PRESETS["normal"]
        first = build_candidate_profile(
            preset=preset,
            root_seed=42,
            candidate_index=1,
            timing_variation=False,
        )
        second = build_candidate_profile(
            preset=preset,
            root_seed=99,
            candidate_index=1,
            timing_variation=False,
        )

        self.assertNotEqual(first.candidate_seed, second.candidate_seed)

    def test_candidate_count_validation_rejects_invalid_values(self) -> None:
        with self.assertRaises(MapGeneratorError):
            validate_candidate_count(0)
        with self.assertRaises(MapGeneratorError):
            validate_candidate_count(101)
        self.assertEqual(validate_candidate_count(5), 5)

    def test_near_duplicate_candidates_are_detected(self) -> None:
        summaries = [make_summary(1), make_summary(2), make_summary(3)]
        duplicate_map = {
            "objects": [
                {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                {"id": 2, "type": "circle", "x": 200, "y": 200, "time": 2000},
            ]
        }
        unique_map = {
            "objects": [
                {"id": 1, "type": "circle", "x": 400, "y": 80, "time": 1000},
                {"id": 2, "type": "circle", "x": 460, "y": 320, "time": 2000},
            ]
        }
        result = analyze_diversity(
            candidates=summaries,
            improved_maps_by_index={1: duplicate_map, 2: duplicate_map, 3: unique_map},
            eligible_count=3,
            timing_variation_enabled=False,
            settings=DiversitySettings(),
        )

        self.assertEqual(result.summary.near_duplicate_groups, [[1, 2]])
        self.assertGreater(result.candidate_diversity[1].near_duplicate_count, 0)

    def test_score_candidates_stay_between_zero_and_hundred(self) -> None:
        summaries = [make_summary(1), make_summary(2)]
        summaries[0].metrics.destructive_corrections = 4
        improved_reports = {1: make_report(difficulty_consistency=90.0), 2: make_report(difficulty_consistency=90.0)}
        score_candidates(
            candidates=summaries,
            improved_reports_by_index=improved_reports,
            difficulty_consistency_by_index={1: 90.0, 2: 90.0},
            weights=TournamentScoreWeights(),
        )

        for summary in summaries:
            self.assertGreaterEqual(summary.scores.tournament_score, 0.0)
            self.assertLessEqual(summary.scores.tournament_score, 100.0)
        self.assertLess(summaries[0].scores.tournament_score, summaries[1].scores.tournament_score)

    def test_deterministic_tie_breaking_prefers_lower_candidate_index(self) -> None:
        summaries = [make_summary(1), make_summary(2)]
        for summary in summaries:
            summary.scores.tournament_score = 90.0
            summary.scores.improved_overall = 92.0
            summary.stability.score = 88.0
        ranking, rejected, champion = build_ranking(
            candidates=summaries,
            improved_reports_by_index={1: make_report(), 2: make_report()},
        )

        self.assertEqual(rejected, [])
        self.assertEqual(ranking[0].candidate_index, 1)
        self.assertEqual(champion.candidate_index, 1)

    def test_unplayable_candidates_are_rejected(self) -> None:
        expected_metadata = {
            "index": 1,
            "difficulty": "easy",
            "rootSeed": 42,
            "candidateSeed": 99,
            "timingVariationEnabled": False,
            "variationSignature": "sig",
            "variationProfile": {},
        }
        map_data = {
            "generator": {
                "seed": 99,
                "candidate": expected_metadata,
            }
        }
        status = evaluate_candidate_status(
            original_map=map_data,
            improved_map=map_data,
            improved_report=SimpleNamespace(
                valid=True,
                playable=False,
                summary=SimpleNamespace(critical=0, errors=0, warnings=0),
                issues=[],
                metrics=SimpleNamespace(
                    movement=SimpleNamespace(highest_cursor_speed=0.0),
                ),
                map_info=SimpleNamespace(object_count=5),
                scores=SimpleNamespace(
                    structural=90.0,
                    timing=90.0,
                    rhythm=90.0,
                    movement=90.0,
                    readability=90.0,
                    spatial_balance=90.0,
                    repetition=90.0,
                    density_consistency=90.0,
                    difficulty_consistency=90.0,
                    overall=90.0,
                ),
            ),
            candidate_seed=99,
            expected_candidate_metadata=expected_metadata,
            files_complete=True,
            preset=DIFFICULTY_PRESETS["easy"],
            rules=EligibilityRules(),
        )

        self.assertFalse(status.eligible)
        self.assertIn("Improved report is not safely playable.", status.rejection_reasons)

    def test_resume_force_and_champion_copy_behave_deterministically(self) -> None:
        audio_path, analysis_path = self._write_project_inputs()
        report_path = self.project_root / "public/tournaments/test-song-easy-tournament.json"
        result = self._run_easy_tournament(audio_path, analysis_path, count=2)

        champion_source = self.project_root / result.tournament_report.champion.source_map_path
        champion_output = self.project_root / "public/maps/champions/test-song-easy.json"
        initial_report_bytes = report_path.read_bytes()
        self.assertEqual(champion_source.read_bytes(), champion_output.read_bytes())
        self.assertEqual(result.reused_count, 0)
        self.assertEqual(result.regenerated_count, 2)

        resumed = self._run_easy_tournament(audio_path, analysis_path, count=2)
        resumed_report_bytes = report_path.read_bytes()
        self.assertEqual(resumed.reused_count, 2)
        self.assertEqual(resumed.regenerated_count, 0)
        self.assertEqual(initial_report_bytes, resumed_report_bytes)

        forced = self._run_easy_tournament(audio_path, analysis_path, count=2, force=True)
        forced_report_bytes = report_path.read_bytes()
        self.assertEqual(forced.reused_count, 0)
        self.assertEqual(forced.regenerated_count, 2)
        self.assertEqual(initial_report_bytes, forced_report_bytes)

    def test_different_seed_changes_placement(self) -> None:
        audio_path, analysis_path = self._write_project_inputs()
        first = self._run_easy_tournament(audio_path, analysis_path, count=2, seed=42)
        second = self._run_easy_tournament(
            audio_path,
            analysis_path,
            count=2,
            seed=91,
            output_slug="test-song-seed-91",
        )

        first_map = json.loads(
            (self.project_root / first.candidate_summaries[0].files.original_map).read_text(
                encoding="utf-8",
            )
        )
        second_map = json.loads(
            (self.project_root / second.candidate_summaries[0].files.original_map).read_text(
                encoding="utf-8",
            )
        )
        self.assertNotEqual(first_map["objects"], second_map["objects"])

    def test_timing_stays_shared_when_timing_variation_is_disabled(self) -> None:
        audio_path, analysis_path = self._write_project_inputs()
        result = self._run_easy_tournament(audio_path, analysis_path, count=3)

        self.assertEqual(
            len({summary.metrics.timing_signature for summary in result.candidate_summaries}),
            1,
        )

    def test_all_rejected_tournament_returns_readable_failure(self) -> None:
        audio_path, analysis_path = self._write_project_inputs()
        with patch(
            "tools.map_generator.candidates.candidate_pipeline.evaluate_candidate_status",
            return_value=CandidateStatus(
                valid=False,
                playable=False,
                eligible=False,
                rejection_reasons=["Forced rejection"],
            ),
        ):
            with self.assertRaises(MapGeneratorError) as context:
                self._run_easy_tournament(audio_path, analysis_path, count=1, output_slug="all-rejected")

        self.assertIn("All 1 candidates were rejected for easy.", str(context.exception))

    def _write_project_inputs(self) -> tuple[Path, Path]:
        audio_path = self.project_root / "public/audio/test-song.mp3"
        analysis_path = self.project_root / "public/analysis/test-song-analysis.json"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"fake mp3 data")
        analysis = make_aligned_analysis([1000, 2000, 3000, 4000, 5000])
        write_json(analysis_path, analysis.to_dict())
        return audio_path, analysis_path

    def _run_easy_tournament(
        self,
        audio_path: Path,
        analysis_path: Path,
        *,
        count: int,
        seed: int = 42,
        force: bool = False,
        output_slug: str = "test-song",
    ):
        return run_candidate_tournament(
            audio_path=audio_path,
            analysis_path=analysis_path,
            title="Test Song",
            artist="Unknown Artist",
            difficulty="easy",
            root_seed=seed,
            output_root=self.project_root / f"public/candidates/{output_slug}/easy",
            champion_map_path=self.project_root / f"public/maps/champions/{output_slug}-easy.json",
            champion_report_path=self.project_root / f"public/reports/champions/{output_slug}-easy-report.json",
            tournament_report_path=self.project_root / f"public/tournaments/{output_slug}-easy-tournament.json",
            project_root=self.project_root,
            count=count,
            force=force,
        )


if __name__ == "__main__":
    unittest.main()
