from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import AudioAnalysis, EnergyFrame, EnergyRegion, TimedStrength
from tools.map_generator.validation.beatmap_validator import validate_beatmap
from tools.map_generator.validation.density_validator import validate_density
from tools.map_generator.validation.models import (
    DensityMetrics,
    DifficultyMetrics,
    MovementMetrics,
    ParsedBeatmap,
    ParsedBeatmapObject,
    RepetitionMetrics,
    RhythmMetrics,
    SpatialMetrics,
    StructuralMetrics,
    TimingMetrics,
    ValidationIssue,
    ValidationMetrics,
)
from tools.map_generator.validation.movement_validator import validate_movement
from tools.map_generator.validation.quality_scorer import calculate_quality_scores
from tools.map_generator.validation.repetition_validator import validate_repetition
from tools.map_generator.validation.rhythm_validator import validate_rhythm
from tools.map_generator.validation.structural_validator import validate_structural
from tools.map_generator.validation.timing_validator import validate_timing


def make_analysis(
    *,
    duration_ms: int = 5_000,
    beats: list[int] | None = None,
    onsets: list[int] | None = None,
    high_energy_regions: list[tuple[int, int]] | None = None,
    quiet_regions: list[tuple[int, int]] | None = None,
    default_energy: float = 0.35,
) -> AudioAnalysis:
    beats = beats or [1_000, 2_000, 3_000, 4_000]
    onsets = onsets or beats
    high_energy_regions = high_energy_regions or []
    quiet_regions = quiet_regions or []
    frames: list[EnergyFrame] = []

    for time_ms in range(0, duration_ms + 1, 250):
        energy_value = default_energy
        if any(start <= time_ms <= end for start, end in high_energy_regions):
            energy_value = 1.0
        if any(start <= time_ms <= end for start, end in quiet_regions):
            energy_value = 0.05
        frames.append(EnergyFrame(time_ms=time_ms, value=energy_value))

    return AudioAnalysis(
        audio_filename="test-song.mp3",
        duration_ms=duration_ms,
        sample_rate=22_050,
        bpm=120.0,
        offset_ms=beats[0] if beats else 0,
        beats=[TimedStrength(time_ms=time_ms, strength=1.0) for time_ms in beats],
        onsets=[TimedStrength(time_ms=time_ms, strength=1.0) for time_ms in onsets],
        energy_frames=frames,
        quiet_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=0.05)
            for start, end in quiet_regions
        ],
        high_energy_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=1.0)
            for start, end in high_energy_regions
        ],
    )


def make_object(object_id: int, x: int, y: int, time_ms: int) -> ParsedBeatmapObject:
    return ParsedBeatmapObject(id=object_id, type="circle", x=x, y=y, time=time_ms)


def make_beatmap(
    objects: list[ParsedBeatmapObject],
    *,
    difficulty: str = "normal",
) -> ParsedBeatmap:
    preset = DIFFICULTY_PRESETS[difficulty]
    return ParsedBeatmap(
        path="public/maps/generated/test-map.json",
        title="Test Song",
        artist="Unknown Artist",
        audio="/audio/test-song.mp3",
        approach_time=float(preset.approach_time_ms),
        circle_radius=float(preset.circle_radius),
        objects=objects,
        generator={"difficulty": difficulty},
    )


def make_metrics() -> ValidationMetrics:
    return ValidationMetrics(
        structural=StructuralMetrics(
            object_count=4,
            valid_object_count=4,
            duplicate_id_count=0,
            duplicate_timestamp_count=0,
            non_finite_value_count=0,
        ),
        timing=TimingMetrics(
            average_anchor_delta_ms=0.0,
            average_beat_delta_ms=0.0,
            average_onset_delta_ms=0.0,
            excellent_alignment_count=4,
            good_alignment_count=0,
            acceptable_alignment_count=0,
            weak_alignment_count=0,
            mistimed_count=0,
            early_bias_count=0,
            late_bias_count=0,
            anchor_usage={"beat": 2, "onset": 2, "none": 0},
        ),
        rhythm=RhythmMetrics(
            min_gap_ms=500,
            max_gap_ms=800,
            average_gap_ms=650.0,
            median_gap_ms=650.0,
            gap_standard_deviation_ms=120.0,
            gap_percentiles_ms={"p10": 500.0, "p25": 560.0, "p75": 740.0, "p90": 800.0},
            rapid_sequence_count=0,
            long_empty_space_count=0,
            repeated_equal_gap_runs=0,
            common_rhythm_intervals_ms=[500, 750],
        ),
        movement=MovementMetrics(
            min_jump_distance=48.0,
            max_jump_distance=120.0,
            average_jump_distance=82.0,
            highest_cursor_speed=250.0,
            average_cursor_speed=170.0,
            speed_violation_count=0,
            near_limit_run_count=0,
            exact_stacking_count=0,
            near_stacking_count=0,
            overlap_count=0,
            large_isolated_jump_count=0,
        ),
        spatial=SpatialMetrics(
            grid_columns=4,
            grid_rows=3,
            region_counts={f"r{row + 1}c{column + 1}": 1 for row in range(3) for column in range(4)},
            playfield_coverage_percent=66.0,
            center_usage_percent=42.0,
            edge_usage_percent=22.0,
            corner_usage_percent=8.0,
            left_right_balance=8.0,
            top_bottom_balance=8.0,
            most_used_region="r1c1",
            least_used_region="r3c4",
        ),
        density=DensityMetrics(
            windows=[],
            high_density_low_energy_windows=0,
            low_density_high_energy_windows=0,
            abrupt_density_spikes=0,
            flat_density_despite_energy_change=0,
            ending_gap_ms=500,
        ),
        repetition=RepetitionMetrics(
            repeated_coordinate_pairs=0,
            repeated_two_point_loops=0,
            repeated_three_object_shapes=0,
            repeated_distance_patterns=0,
            repeated_angle_patterns=0,
            repeated_gap_sequences=0,
            longest_repetition_run=1,
        ),
        difficulty=DifficultyMetrics(
            estimated_behavior="within-target",
            density_ratio=1.0,
            jump_ratio=1.0,
            speed_ratio=1.0,
            timing_complexity_ratio=1.0,
            spatial_variation_ratio=1.0,
        ),
    )


class StructuralValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis()
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_duplicate_ids_detected(self) -> None:
        result = validate_structural(
            {
                "title": "Test Song",
                "artist": "Unknown Artist",
                "audio": "/audio/test-song.mp3",
                "approachTime": 950,
                "circleRadius": 40,
                "objects": [
                    {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                    {"id": 1, "type": "circle", "x": 180, "y": 130, "time": 1600},
                ],
            },
            map_path=Path("public/maps/generated/test-map.json"),
            analysis=self.analysis,
            preset=self.preset,
        )
        self.assertIn("DUPLICATE_OBJECT_ID", [issue.code for issue in result.issues])

    def test_non_sequential_ids_detected(self) -> None:
        result = validate_structural(
            {
                "title": "Test Song",
                "artist": "Unknown Artist",
                "audio": "/audio/test-song.mp3",
                "approachTime": 950,
                "circleRadius": 40,
                "objects": [
                    {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                    {"id": 3, "type": "circle", "x": 180, "y": 130, "time": 1600},
                ],
            },
            map_path=Path("public/maps/generated/test-map.json"),
            analysis=self.analysis,
            preset=self.preset,
        )
        self.assertIn("NON_SEQUENTIAL_OBJECT_IDS", [issue.code for issue in result.issues])

    def test_duplicate_timestamps_detected(self) -> None:
        result = validate_structural(
            {
                "title": "Test Song",
                "artist": "Unknown Artist",
                "audio": "/audio/test-song.mp3",
                "approachTime": 950,
                "circleRadius": 40,
                "objects": [
                    {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                    {"id": 2, "type": "circle", "x": 180, "y": 130, "time": 1000},
                ],
            },
            map_path=Path("public/maps/generated/test-map.json"),
            analysis=self.analysis,
            preset=self.preset,
        )
        self.assertIn("DUPLICATE_TIMESTAMP", [issue.code for issue in result.issues])

    def test_out_of_bounds_coordinates_detected(self) -> None:
        result = validate_structural(
            {
                "title": "Test Song",
                "artist": "Unknown Artist",
                "audio": "/audio/test-song.mp3",
                "approachTime": 950,
                "circleRadius": 40,
                "objects": [
                    {"id": 1, "type": "circle", "x": 700, "y": 100, "time": 1000},
                ],
            },
            map_path=Path("public/maps/generated/test-map.json"),
            analysis=self.analysis,
            preset=self.preset,
        )
        self.assertIn("OBJECT_OUT_OF_BOUNDS", [issue.code for issue in result.issues])

    def test_object_after_audio_duration_detected(self) -> None:
        result = validate_structural(
            {
                "title": "Test Song",
                "artist": "Unknown Artist",
                "audio": "/audio/test-song.mp3",
                "approachTime": 950,
                "circleRadius": 40,
                "objects": [
                    {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 5100},
                ],
            },
            map_path=Path("public/maps/generated/test-map.json"),
            analysis=self.analysis,
            preset=self.preset,
        )
        self.assertIn("OBJECT_AFTER_AUDIO_DURATION", [issue.code for issue in result.issues])


class ValidatorLogicTests(unittest.TestCase):
    def test_movement_speed_violation_detected(self) -> None:
        beatmap = make_beatmap(
            [
                make_object(1, 64, 64, 1000),
                make_object(2, 448, 320, 1100),
            ],
            difficulty="hard",
        )
        analysis = make_analysis(duration_ms=4000, beats=[1000, 1100, 2000, 3000])
        result = validate_movement(beatmap, analysis, DIFFICULTY_PRESETS["hard"])
        self.assertIn("MOVEMENT_SPEED_EXCEEDED", [issue.code for issue in result.issues])

    def test_exact_stacking_detected(self) -> None:
        beatmap = make_beatmap(
            [
                make_object(1, 200, 180, 1000),
                make_object(2, 200, 180, 1300),
            ]
        )
        analysis = make_analysis()
        result = validate_movement(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        self.assertIn("READABILITY_EXACT_STACKING", [issue.code for issue in result.issues])

    def test_two_point_repetition_detected(self) -> None:
        analysis = make_analysis()
        beatmap = make_beatmap(
            [
                make_object(1, 120, 120, 1000),
                make_object(2, 360, 120, 1400),
                make_object(3, 120, 120, 1800),
                make_object(4, 360, 120, 2200),
                make_object(5, 120, 120, 2600),
                make_object(6, 360, 120, 3000),
            ]
        )
        movement = validate_movement(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        rhythm = validate_rhythm(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        result = validate_repetition(beatmap, movement.pair_diagnostics, rhythm.gaps_ms)
        self.assertIn("REPETITION_TWO_POINT_LOOP", [issue.code for issue in result.issues])

    def test_low_density_high_energy_window_detected(self) -> None:
        analysis = make_analysis(
            duration_ms=6000,
            beats=[500, 2500, 4500],
            onsets=[500, 2500, 4500],
            high_energy_regions=[(0, 4000)],
            default_energy=0.4,
        )
        beatmap = make_beatmap(
            [
                make_object(1, 100, 100, 500),
                make_object(2, 300, 200, 2500),
                make_object(3, 180, 240, 4500),
            ]
        )
        timing = validate_timing(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        movement = validate_movement(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        density = validate_density(
            beatmap,
            analysis,
            DIFFICULTY_PRESETS["normal"],
            timing.diagnostics,
            movement.pair_diagnostics,
        )
        self.assertIn("DENSITY_LOW_MAP_HIGH_AUDIO", [issue.code for issue in density.issues])

    def test_timing_misalignment_detected(self) -> None:
        analysis = make_analysis(
            duration_ms=4000,
            beats=[1000, 2000, 3000],
            onsets=[1000, 2000, 3000],
        )
        beatmap = make_beatmap([make_object(1, 200, 200, 780)])
        result = validate_timing(beatmap, analysis, DIFFICULTY_PRESETS["normal"])
        self.assertIn("TIMING_MISTIMED_OBJECT", [issue.code for issue in result.issues])

    def test_score_clamping_stays_between_zero_and_hundred(self) -> None:
        result = calculate_quality_scores(
            metrics=make_metrics(),
            issues=[
                ValidationIssue(
                    code=f"ISSUE_{index}",
                    severity="critical",
                    message="Synthetic critical issue",
                    category="movement",
                )
                for index in range(8)
            ],
            preset=DIFFICULTY_PRESETS["normal"],
        )
        for score in result.scores.to_dict().values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_structural_critical_issue_caps_overall_score(self) -> None:
        result = calculate_quality_scores(
            metrics=make_metrics(),
            issues=[
                ValidationIssue(
                    code="ROOT_NOT_OBJECT",
                    severity="critical",
                    message="Root is invalid.",
                    category="structural",
                )
            ],
            preset=DIFFICULTY_PRESETS["normal"],
        )
        self.assertLessEqual(result.scores.overall, 20.0)

    def test_validation_report_is_deterministic_for_same_input(self) -> None:
        analysis = make_analysis(duration_ms=6000, beats=[1000, 2000, 3000, 4000, 5000])
        beatmap_json = {
            "title": "Test Song",
            "artist": "Unknown Artist",
            "audio": "/audio/test-song.mp3",
            "approachTime": 950,
            "circleRadius": 40,
            "objects": [
                {"id": 1, "type": "circle", "x": 120, "y": 120, "time": 1000},
                {"id": 2, "type": "circle", "x": 300, "y": 140, "time": 2000},
                {"id": 3, "type": "circle", "x": 220, "y": 280, "time": 3000},
                {"id": 4, "type": "circle", "x": 380, "y": 220, "time": 4000},
            ],
            "generator": {"difficulty": "normal", "seed": 42},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = temp_path / "map.json"
            analysis_path = temp_path / "analysis.json"
            map_path.write_text(json.dumps(beatmap_json), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis.to_dict()), encoding="utf-8")

            first = validate_beatmap(
                map_path=map_path,
                analysis_path=analysis_path,
                difficulty="normal",
                map_label="public/maps/generated/test-map.json",
            ).report.to_dict()
            second = validate_beatmap(
                map_path=map_path,
                analysis_path=analysis_path,
                difficulty="normal",
                map_label="public/maps/generated/test-map.json",
            ).report.to_dict()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
