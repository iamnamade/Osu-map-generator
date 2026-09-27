from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import AudioAnalysis, EnergyFrame, EnergyRegion, TimedStrength
from tools.map_generator.postprocess.density_corrector import build_density_action
from tools.map_generator.postprocess.difficulty_corrector import build_difficulty_action
from tools.map_generator.postprocess.models import PostprocessContext, PostprocessLimits
from tools.map_generator.postprocess.movement_corrector import build_movement_action
from tools.map_generator.postprocess.postprocessor import improve_beatmap
from tools.map_generator.postprocess.stacking_corrector import build_stacking_action
from tools.map_generator.postprocess.timing_corrector import build_timing_action
from tools.map_generator.utils import MapGeneratorError, write_json
from tools.map_generator.validation.beatmap_validator import validate_beatmap


def make_analysis(
    *,
    duration_ms: int = 6_000,
    beats: list[tuple[int, float]] | None = None,
    onsets: list[tuple[int, float]] | None = None,
    high_energy_regions: list[tuple[int, int]] | None = None,
    quiet_regions: list[tuple[int, int]] | None = None,
    default_energy: float = 0.35,
) -> AudioAnalysis:
    beats = beats or [(1_000, 1.0), (2_000, 1.0), (3_000, 1.0), (4_000, 1.0), (5_000, 1.0)]
    onsets = onsets or beats
    high_energy_regions = high_energy_regions or []
    quiet_regions = quiet_regions or []
    frames: list[EnergyFrame] = []

    for time_ms in range(0, duration_ms + 1, 250):
        energy_value = default_energy
        if any(start <= time_ms <= end for start, end in high_energy_regions):
            energy_value = 0.95
        if any(start <= time_ms <= end for start, end in quiet_regions):
            energy_value = 0.05
        frames.append(EnergyFrame(time_ms=time_ms, value=energy_value))

    return AudioAnalysis(
        audio_filename="test-song.mp3",
        duration_ms=duration_ms,
        sample_rate=22_050,
        bpm=120.0,
        offset_ms=beats[0][0] if beats else 0,
        beats=[TimedStrength(time_ms=time_ms, strength=strength) for time_ms, strength in beats],
        onsets=[TimedStrength(time_ms=time_ms, strength=strength) for time_ms, strength in onsets],
        energy_frames=frames,
        quiet_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=0.05)
            for start, end in quiet_regions
        ],
        high_energy_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=0.95)
            for start, end in high_energy_regions
        ],
    )


def make_map_json(
    objects: list[dict[str, int | str]],
    *,
    difficulty: str = "normal",
) -> dict[str, object]:
    preset = DIFFICULTY_PRESETS[difficulty]
    return {
        "title": "Test Song",
        "artist": "Unknown Artist",
        "audio": "/audio/test-song.mp3",
        "approachTime": preset.approach_time_ms,
        "circleRadius": preset.circle_radius,
        "objects": objects,
        "generator": {
            "name": "pulse-practice-generator",
            "version": 1,
            "difficulty": difficulty,
            "seed": 42,
        },
    }


def clone_map(map_json: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(map_json))


def make_aligned_analysis(
    object_times: list[int],
    *,
    quiet_regions: list[tuple[int, int]] | None = None,
    high_energy_regions: list[tuple[int, int]] | None = None,
    default_energy: float = 0.35,
) -> AudioAnalysis:
    beats = [(time_ms, 1.0) for time_ms in object_times]
    return make_analysis(
        duration_ms=max(object_times) + 1_800,
        beats=beats,
        onsets=beats,
        quiet_regions=quiet_regions,
        high_energy_regions=high_energy_regions,
        default_energy=default_energy,
    )


class PostprocessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_source_map_is_never_modified_and_actions_are_logged(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_800, 2_600, 3_400, 4_200],
            quiet_regions=[(2_300, 4_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 220, "y": 180, "time": 1_800},
                {"id": 3, "type": "circle", "x": 452, "y": 72, "time": 2_600},
                {"id": 4, "type": "circle", "x": 280, "y": 214, "time": 3_400},
                {"id": 5, "type": "circle", "x": 184, "y": 270, "time": 4_200},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )
        original_text = map_path.read_text(encoding="utf-8")

        result = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "improved.json",
            report_output_path=self.temp_path / "improved-report.json",
            changes_output_path=self.temp_path / "corrections.json",
        )

        self.assertEqual(original_text, map_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(result.correction_report.actions), 1)
        self.assertTrue(result.changes_output_path.exists())

    def test_same_seed_produces_identical_output_and_report(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_800, 2_600, 3_400, 4_200],
            quiet_regions=[(2_300, 4_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 220, "y": 180, "time": 1_800},
                {"id": 3, "type": "circle", "x": 452, "y": 72, "time": 2_600},
                {"id": 4, "type": "circle", "x": 280, "y": 214, "time": 3_400},
                {"id": 5, "type": "circle", "x": 184, "y": 270, "time": 4_200},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        first = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "improved-a.json",
            report_output_path=self.temp_path / "improved-a-report.json",
            changes_output_path=self.temp_path / "corrections-a.json",
        )
        second = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "improved-b.json",
            report_output_path=self.temp_path / "improved-b-report.json",
            changes_output_path=self.temp_path / "corrections-b.json",
        )

        self.assertEqual(
            json.loads(first.output_map_path.read_text(encoding="utf-8")),
            json.loads(second.output_map_path.read_text(encoding="utf-8")),
        )
        self.assertEqual(
            first.correction_report.actions,
            second.correction_report.actions,
        )
        self.assertEqual(first.correction_report.summary, second.correction_report.summary)
        self.assertEqual(first.correction_report.score_changes, second.correction_report.score_changes)

    def test_different_seed_keeps_timing_when_no_timing_correction_is_needed(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_800, 2_600, 3_400, 4_200],
            quiet_regions=[(2_300, 4_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 220, "y": 180, "time": 1_800},
                {"id": 3, "type": "circle", "x": 452, "y": 72, "time": 2_600},
                {"id": 4, "type": "circle", "x": 280, "y": 214, "time": 3_400},
                {"id": 5, "type": "circle", "x": 184, "y": 270, "time": 4_200},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        first = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=7,
            output_path=self.temp_path / "improved-seed-7.json",
            report_output_path=self.temp_path / "improved-seed-7-report.json",
            changes_output_path=self.temp_path / "corrections-seed-7.json",
        )
        second = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=91,
            output_path=self.temp_path / "improved-seed-91.json",
            report_output_path=self.temp_path / "improved-seed-91-report.json",
            changes_output_path=self.temp_path / "corrections-seed-91.json",
        )

        original_times = [int(item["time"]) for item in source_map["objects"]]  # type: ignore[index]
        first_times = [item["time"] for item in json.loads(first.output_map_path.read_text(encoding="utf-8"))["objects"]]
        second_times = [item["time"] for item in json.loads(second.output_map_path.read_text(encoding="utf-8"))["objects"]]

        self.assertEqual(original_times, first_times)
        self.assertEqual(original_times, second_times)

    def test_movement_correction_lowers_speed_pressure(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_800, 2_600, 3_400, 4_200],
            quiet_regions=[(2_300, 4_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 220, "y": 180, "time": 1_800},
                {"id": 3, "type": "circle", "x": 452, "y": 72, "time": 2_600},
                {"id": 4, "type": "circle", "x": 280, "y": 214, "time": 3_400},
                {"id": 5, "type": "circle", "x": 184, "y": 270, "time": 4_200},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        result = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "movement-improved.json",
            report_output_path=self.temp_path / "movement-improved-report.json",
            changes_output_path=self.temp_path / "movement-corrections.json",
        )

        self.assertGreaterEqual(
            result.final_report.scores.movement,
            result.original_report.scores.movement,
        )
        self.assertLessEqual(
            result.final_report.metrics.movement.highest_cursor_speed,
            result.original_report.metrics.movement.highest_cursor_speed,
        )

    def test_movement_action_considers_previous_and_next_objects(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_800, 2_600, 3_400, 4_200],
            quiet_regions=[(2_300, 4_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 220, "y": 180, "time": 1_800},
                {"id": 3, "type": "circle", "x": 452, "y": 72, "time": 2_600},
                {"id": 4, "type": "circle", "x": 280, "y": 214, "time": 3_400},
                {"id": 5, "type": "circle", "x": 184, "y": 270, "time": 4_200},
            ]
        )
        context, current_report = self._build_context_and_report(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        evaluation = build_movement_action(
            map_data=clone_map(source_map),
            current_report=current_report,
            context=context,
            issue_code="MOVEMENT_LARGE_JUMP_LOW_ENERGY",
            issue_object_ids=[2, 3],
            confidence=0.82,
        )

        self.assertIsNotNone(evaluation)
        assert evaluation is not None
        self.assertTrue(evaluation.accepted)

        original_objects = source_map["objects"]  # type: ignore[index]
        updated_objects = evaluation.candidate_map["objects"]
        original_max_speed = self._window_max_speed(original_objects, 1, 2, 3)
        updated_max_speed = self._window_max_speed(updated_objects, 1, 2, 3)
        self.assertLessEqual(updated_max_speed, original_max_speed)

    def test_stacking_correction_separates_overlapping_objects(self) -> None:
        analysis = make_aligned_analysis([1_000, 1_320, 2_060])
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 200, "y": 200, "time": 1_000},
                {"id": 2, "type": "circle", "x": 200, "y": 200, "time": 1_320},
                {"id": 3, "type": "circle", "x": 320, "y": 216, "time": 2_060},
            ]
        )
        context, current_report = self._build_context_and_report(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        evaluation = build_stacking_action(
            map_data=clone_map(source_map),
            current_report=current_report,
            context=context,
            issue_code="READABILITY_EXACT_STACKING",
            issue_object_ids=[1, 2],
            confidence=0.88,
        )

        self.assertIsNotNone(evaluation)
        assert evaluation is not None
        self.assertTrue(evaluation.accepted)
        updated_objects = evaluation.candidate_map["objects"]
        self.assertNotEqual(
            (updated_objects[0]["x"], updated_objects[0]["y"]),
            (updated_objects[1]["x"], updated_objects[1]["y"]),
        )

    def test_timing_correction_respects_limit_and_does_not_duplicate_timestamps(self) -> None:
        analysis = make_analysis(
            beats=[(1_000, 1.0), (2_000, 1.0), (3_000, 1.0)],
            onsets=[(1_000, 1.0), (2_045, 0.2), (3_000, 1.0)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 264, "y": 208, "time": 2_045},
                {"id": 3, "type": "circle", "x": 328, "y": 244, "time": 3_000},
            ]
        )
        context, current_report = self._build_context_and_report(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        evaluation = build_timing_action(
            map_data=clone_map(source_map),
            current_report=current_report,
            context=context,
            issue_code="TIMING_WEAK_ONSET_REFERENCE",
            issue_object_ids=[2],
            confidence=0.7,
        )

        self.assertIsNotNone(evaluation)
        assert evaluation is not None
        self.assertTrue(evaluation.accepted)
        action = evaluation.action
        delta_ms = abs(int(action.after["time"]) - int(action.before["time"]))
        self.assertLessEqual(delta_ms, context.limits.max_timing_adjustment_ms_by_difficulty["normal"])
        times = [item["time"] for item in evaluation.candidate_map["objects"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_density_insertion_uses_a_strong_unused_event(self) -> None:
        analysis = make_analysis(
            duration_ms=6_000,
            beats=[(1_000, 0.8), (2_000, 1.0), (3_000, 0.9), (4_000, 1.0), (5_000, 0.8)],
            onsets=[(1_000, 0.8), (2_000, 1.0), (3_000, 0.9), (4_000, 1.0), (5_000, 0.8)],
            high_energy_regions=[(1_500, 4_500)],
            default_energy=0.28,
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 120, "y": 180, "time": 1_000},
                {"id": 2, "type": "circle", "x": 240, "y": 200, "time": 3_000},
                {"id": 3, "type": "circle", "x": 352, "y": 220, "time": 5_000},
            ]
        )
        context, current_report = self._build_context_and_report(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        evaluation = build_density_action(
            map_data=clone_map(source_map),
            current_report=current_report,
            context=context,
            issue_code="DENSITY_LOW_MAP_HIGH_AUDIO",
            issue_object_ids=[],
            confidence=0.82,
            start_time_ms=1_000,
            end_time_ms=4_500,
        )

        self.assertIsNotNone(evaluation)
        assert evaluation is not None
        self.assertTrue(evaluation.accepted)
        updated_times = [item["time"] for item in evaluation.candidate_map["objects"]]
        self.assertEqual(len(updated_times), 4)
        inserted_time = next(time for time in updated_times if time not in {1_000, 3_000, 5_000})
        self.assertIn(inserted_time, {2_000, 4_000})

    def test_clean_map_keeps_the_original_copy(self) -> None:
        analysis = make_aligned_analysis([1_000, 2_000, 3_000, 4_000])
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 150, "y": 120, "time": 1_000},
                {"id": 2, "type": "circle", "x": 286, "y": 138, "time": 2_000},
                {"id": 3, "type": "circle", "x": 220, "y": 250, "time": 3_000},
                {"id": 4, "type": "circle", "x": 360, "y": 220, "time": 4_000},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        result = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "clean-improved.json",
            report_output_path=self.temp_path / "clean-improved-report.json",
            changes_output_path=self.temp_path / "clean-corrections.json",
            limits=PostprocessLimits(max_correction_passes=0),
        )

        self.assertFalse(result.correction_report.accepted)
        self.assertEqual(
            json.loads(map_path.read_text(encoding="utf-8")),
            json.loads(result.output_map_path.read_text(encoding="utf-8")),
        )

    def test_critical_issues_continue_with_degraded_output(self) -> None:
        # After relaxing strict evolution gates, critical structural issues
        # no longer abort the pipeline. Instead, post-processing continues
        # with degraded output — the original map is kept when the improved
        # version still has critical issues.
        analysis = make_analysis()
        invalid_map = {
            "artist": "Unknown Artist",
            "audio": "/audio/test-song.mp3",
            "approachTime": 950,
            "circleRadius": 40,
            "objects": [
                {"id": 1, "type": "circle", "x": 120, "y": 120, "time": 1_000},
            ],
        }
        map_path = self.temp_path / "invalid-map.json"
        analysis_path = self.temp_path / "analysis.json"
        report_path = self.temp_path / "placeholder-report.json"
        write_json(map_path, invalid_map)
        write_json(analysis_path, analysis.to_dict())
        write_json(
            report_path,
            {
                "map": {"path": "invalid-map.json"},
                "scores": {"overall": 0},
                "summary": {"critical": 1, "errors": 0, "warnings": 0, "info": 0},
                "issues": [],
            },
        )

        result = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "invalid-improved.json",
            report_output_path=self.temp_path / "invalid-improved-report.json",
            changes_output_path=self.temp_path / "invalid-corrections.json",
        )
        # The output map should exist and be valid JSON
        self.assertTrue(result.output_map_path.exists())
        output_data = json.loads(result.output_map_path.read_text(encoding="utf-8"))
        self.assertIsInstance(output_data, dict)

    def test_limits_and_bounds_are_respected(self) -> None:
        analysis = make_aligned_analysis(
            [1_000, 1_700, 2_400, 3_100, 3_800, 4_500, 5_200, 5_900],
            quiet_regions=[(2_200, 5_000)],
        )
        source_map = make_map_json(
            [
                {"id": 1, "type": "circle", "x": 90, "y": 90, "time": 1_000},
                {"id": 2, "type": "circle", "x": 210, "y": 110, "time": 1_700},
                {"id": 3, "type": "circle", "x": 460, "y": 74, "time": 2_400},
                {"id": 4, "type": "circle", "x": 256, "y": 188, "time": 3_100},
                {"id": 5, "type": "circle", "x": 84, "y": 284, "time": 3_800},
                {"id": 6, "type": "circle", "x": 430, "y": 292, "time": 4_500},
                {"id": 7, "type": "circle", "x": 196, "y": 152, "time": 5_200},
                {"id": 8, "type": "circle", "x": 310, "y": 252, "time": 5_900},
            ]
        )
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty="normal",
        )

        result = improve_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            report_path=report_path,
            difficulty="normal",
            seed=42,
            output_path=self.temp_path / "limited-improved.json",
            report_output_path=self.temp_path / "limited-improved-report.json",
            changes_output_path=self.temp_path / "limited-corrections.json",
            limits=PostprocessLimits(max_total_corrected_objects_ratio=0.1),
        )

        self.assertLessEqual(result.correction_report.summary.accepted_actions, 1)
        output_objects = json.loads(result.output_map_path.read_text(encoding="utf-8"))["objects"]
        self.assertEqual([item["id"] for item in output_objects], list(range(1, len(output_objects) + 1)))
        for item in output_objects:
            self.assertGreaterEqual(item["x"], 0)
            self.assertLessEqual(item["x"], 512)
            self.assertGreaterEqual(item["y"], 0)
            self.assertLessEqual(item["y"], 384)

    def _write_source_files(
        self,
        *,
        source_map: dict[str, object],
        analysis: AudioAnalysis,
        difficulty: str,
    ) -> tuple[Path, Path, Path]:
        map_path = self.temp_path / "source-map.json"
        analysis_path = self.temp_path / "analysis.json"
        report_path = self.temp_path / "source-report.json"
        write_json(map_path, source_map)
        write_json(analysis_path, analysis.to_dict())
        validate_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=report_path,
            map_label="public/maps/generated/source-map.json",
        )
        return map_path, analysis_path, report_path

    def _build_context_and_report(
        self,
        *,
        source_map: dict[str, object],
        analysis: AudioAnalysis,
        difficulty: str,
    ) -> tuple[PostprocessContext, object]:
        map_path, analysis_path, report_path = self._write_source_files(
            source_map=source_map,
            analysis=analysis,
            difficulty=difficulty,
        )
        output_map_path = self.temp_path / "candidate-improved.json"
        output_report_path = self.temp_path / "candidate-improved-report.json"
        changes_output_path = self.temp_path / "candidate-corrections.json"
        context = PostprocessContext(
            source_map_path=map_path,
            analysis_path=analysis_path,
            original_report_path=report_path,
            output_map_path=output_map_path,
            output_report_path=output_report_path,
            changes_output_path=changes_output_path,
            difficulty=difficulty,
            preset=DIFFICULTY_PRESETS[difficulty],
            seed=42,
            source_map_label="public/maps/generated/source-map.json",
            output_map_label="public/maps/improved/source-map-improved.json",
            analysis=analysis,
            limits=PostprocessLimits(),
        )
        current_report = validate_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            difficulty=difficulty,
            map_label=context.output_map_label,
        ).report
        return context, current_report

    def _window_max_speed(
        self,
        objects: list[dict[str, int | str]],
        left_index: int,
        middle_index: int,
        right_index: int,
    ) -> float:
        pair_speeds = []
        for start, end in ((left_index, middle_index), (middle_index, right_index)):
            left = objects[start]
            right = objects[end]
            distance = math.hypot(
                float(right["x"]) - float(left["x"]),
                float(right["y"]) - float(left["y"]),
            )
            gap_ms = max(1, int(right["time"]) - int(left["time"]))
            pair_speeds.append(distance / (gap_ms / 1000))
        return max(pair_speeds)


if __name__ == "__main__":
    unittest.main()
