"""Phase 21 advanced slider geometry engine tests.

Covers shape-family determinism, red-anchor multi-segment geometry, flow
(tangent) alignment, phrase-aware slider shaping, phrase threading through the
slider pipeline, .osu export round-tripping (including multi-segment sliders),
and backward compatibility for legacy callers.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    EnergyRegion,
    GeneratedCircleHitObject,
    SelectedEvent,
    TimedStrength,
)
from tools.map_generator.osu_format.hitobject_converter import project_objects_to_osu_hit_objects
from tools.map_generator.osu_format.export_pipeline import export_osu_file
from tools.map_generator.osu_format.models import (
    OsuSliderHitObject,
    ProjectBeatmap,
    ProjectSliderObject,
)
from tools.map_generator.osu_format.parser import parse_osu_text
from tools.map_generator.osu_format.validator import validate_parsed_osu_beatmap
from tools.map_generator.sliders.slider_decision import (
    SLIDER_STRATEGY_MULTIPLIERS,
    decide_slider,
)
from tools.map_generator.sliders.slider_geometry import (
    compute_slider_length,
    generate_hook_path,
    generate_loop_path,
    generate_shape_path,
    generate_wave_path,
    generate_zigzag_path,
    path_end_direction,
    path_start_direction,
)
from tools.map_generator.sliders.slider_models import SliderCandidate, SustainedAnalysis
from tools.map_generator.sliders.slider_pipeline import (
    DEFAULT_SLIDER_CONFIG,
    process_sliders,
)
from tools.map_generator.sliders.slider_scorer import score_slider_candidate
from tools.map_generator.utils import write_json


def make_sustained(sustained_score: float = 0.6) -> SustainedAnalysis:
    return SustainedAnalysis(
        sustained_regions=[{"startMs": 0, "endMs": 60000, "averageScore": sustained_score}],
        sustained_frames=[
            {"timeMs": time_ms, "sustainedScore": sustained_score}
            for time_ms in range(0, 60001, 500)
        ],
        average_sustained_energy=sustained_score,
        sustained_ratio=sustained_score,
    )


def make_event(time_ms: int, *, energy: float = 0.6, emphasis: bool = True) -> SelectedEvent:
    return SelectedEvent(
        time_ms=time_ms,
        source="beat",
        strength=0.8,
        energy=energy,
        confidence=0.9,
        is_emphasis=emphasis,
    )


def make_circle(object_id: int, time_ms: int, x: int = 128, y: int = 128) -> GeneratedCircleHitObject:
    return GeneratedCircleHitObject(
        id=object_id,
        type="circle",
        x=x,
        y=y,
        time=time_ms,
    )


class ShapeGeometryTests(unittest.TestCase):
    def test_all_shapes_are_deterministic(self) -> None:
        for shape in ("linear", "hook", "arc", "wave", "zigzag", "loop"):
            first_path, first_cps = generate_shape_path(
                100, 100, 300, 200, shape,
                flow_in_deg=30.0, flow_out_deg=45.0, curvature=0.4,
            )
            second_path, second_cps = generate_shape_path(
                100, 100, 300, 200, shape,
                flow_in_deg=30.0, flow_out_deg=45.0, curvature=0.4,
            )
            self.assertEqual(first_path, second_path, f"{shape} path type differs")
            self.assertEqual(first_cps, second_cps, f"{shape} control points differ")

    def test_shape_path_types(self) -> None:
        linear_path, _ = generate_shape_path(100, 100, 300, 200, "linear")
        self.assertEqual(linear_path, "linear")
        arc_path, _ = generate_shape_path(100, 100, 300, 200, "arc")
        self.assertEqual(arc_path, "perfect")
        for shape in ("hook", "wave", "zigzag", "loop"):
            path_type, _ = generate_shape_path(100, 100, 300, 200, shape)
            self.assertEqual(path_type, "bezier", f"{shape} should be a bezier")

    def test_multi_segment_shapes_emit_red_anchors(self) -> None:
        wave_cps = generate_wave_path(100, 100, 300, 200, curvature=0.4)
        # [C1, M, M, C2, E]: the midpoint is duplicated (red anchor).
        self.assertEqual(len(wave_cps), 5)
        self.assertEqual(
            (wave_cps[1].x, wave_cps[1].y),
            (wave_cps[2].x, wave_cps[2].y),
            "Wave midpoint must be a duplicated red anchor.",
        )

        zigzag_cps = generate_zigzag_path(100, 100, 300, 200, curvature=0.4)
        self.assertEqual(len(zigzag_cps), 8)
        anchors = [
            index
            for index in range(1, len(zigzag_cps))
            if (zigzag_cps[index].x, zigzag_cps[index].y)
            == (zigzag_cps[index - 1].x, zigzag_cps[index - 1].y)
        ]
        self.assertEqual(len(anchors), 2, "Zigzag should have two red anchors.")

        loop_cps = generate_loop_path(100, 100, 300, 200, flow_in_deg=30.0)
        self.assertGreater(len(loop_cps), 10, "Loop should be a multi-segment path.")
        self.assertEqual(
            (loop_cps[-1].x, loop_cps[-1].y),
            (300, 200),
            "Loop must end at the target end point.",
        )

    def test_control_points_stay_in_playfield(self) -> None:
        for shape in ("wave", "zigzag", "loop"):
            _, cps = generate_shape_path(
                50, 50, 480, 360, shape,
                flow_in_deg=30.0, flow_out_deg=45.0, curvature=0.5,
            )
            for control_point in cps:
                self.assertGreaterEqual(control_point.x, 0)
                self.assertGreaterEqual(control_point.y, 0)
                self.assertLessEqual(control_point.x, 512)
                self.assertLessEqual(control_point.y, 384)

    def test_red_anchor_length_is_computed(self) -> None:
        # The wave is curved, so its sampled length exceeds the straight-line
        # endpoint distance and the red-anchor split must not break sampling.
        cps = generate_wave_path(100, 100, 300, 200, curvature=0.5)
        length = compute_slider_length(cps, 100, 100, "bezier")
        straight = 200.0
        self.assertGreater(length, straight, "Curved wave should be longer than the chord.")
        self.assertLess(length, straight * 2.0)

    def test_loop_geometry_is_self_contained(self) -> None:
        cps = generate_loop_path(200, 200, 260, 240, flow_in_deg=0.0, curvature=0.4)
        length = compute_slider_length(cps, 200, 200, "bezier")
        # A full loop must be substantially longer than the straight chord.
        self.assertGreater(length, 200.0)
        self.assertLess(length, 600.0)


class FlowAlignmentTests(unittest.TestCase):
    def test_hook_follows_incoming_flow(self) -> None:
        flow_in = 30.0
        flow_out = 45.0
        cps = generate_hook_path(
            100, 100, 300, 200,
            flow_in_deg=flow_in, flow_out_deg=flow_out, curvature=0.4,
        )
        start_tangent = path_start_direction(100, 100, cps, "bezier")
        end_tangent = path_end_direction(100, 100, cps, "bezier")
        self.assertIsNotNone(start_tangent)
        self.assertIsNotNone(end_tangent)
        self.assertLess(abs((start_tangent or 0) - flow_in), 12.0)
        self.assertLess(abs((end_tangent or 0) - flow_out), 12.0)

    def test_tangent_helpers_handle_short_paths(self) -> None:
        cps = generate_hook_path(
            100, 100, 105, 102,
            flow_in_deg=0.0, flow_out_deg=0.0, curvature=0.3,
        )
        # Short paths may not yield a measurable tangent, but must not crash.
        start_tangent = path_start_direction(100, 100, cps, "bezier")
        end_tangent = path_end_direction(100, 100, cps, "bezier")
        self.assertIsInstance(start_tangent, (float, type(None)))
        self.assertIsInstance(end_tangent, (float, type(None)))


class PhraseAwareDecisionTests(unittest.TestCase):
    def test_intensify_vs_recover_shape_differences(self) -> None:
        sustained = make_sustained(0.7)
        preset = DIFFICULTY_PRESETS["hard"]
        event = make_event(5000, energy=0.7)
        intense = decide_slider(
            event, 2, sustained, preset,
            previous_event=make_event(3000),
            next_event=make_event(7000),
            previous_gap_ms=2000, next_gap_ms=2000,
            phrase_strategy="intensify",
        )
        recovery = decide_slider(
            event, 2, sustained, preset,
            previous_event=make_event(3000),
            next_event=make_event(7000),
            previous_gap_ms=2000, next_gap_ms=2000,
            phrase_strategy="recover",
        )
        self.assertIsNotNone(intense)
        self.assertIsNotNone(recovery)
        if intense is None or recovery is None:
            return
        self.assertLess(intense.length_ms, recovery.length_ms)
        self.assertGreaterEqual(intense.preferred_repeats, recovery.preferred_repeats)
        self.assertGreater(intense.preferred_curvature, recovery.preferred_curvature)
        self.assertEqual(intense.phrase_strategy, "intensify")
        self.assertEqual(recovery.phrase_strategy, "recover")

    def test_strategy_multiplier_table_is_bounded(self) -> None:
        for multipliers in SLIDER_STRATEGY_MULTIPLIERS.values():
            self.assertGreater(multipliers["length"], 0.0)
            self.assertGreater(multipliers["repeats"], 0.0)
            self.assertGreater(multipliers["curvature"], 0.0)

    def test_easy_never_selects_expressive_shapes(self) -> None:
        sustained = make_sustained(0.9)
        preset = DIFFICULTY_PRESETS["easy"]
        seen_shapes: set[str] = set()
        for time_ms in range(1000, 20000, 1000):
            candidate = decide_slider(
                make_event(time_ms, energy=0.8), 1, sustained, preset,
                next_gap_ms=2000,
            )
            if candidate is not None:
                seen_shapes.add(candidate.preferred_shape)
        self.assertFalse(
            seen_shapes & {"wave", "zigzag", "loop"},
            f"Easy must not produce expressive shapes, got {seen_shapes}",
        )

    def test_decision_is_deterministic_for_fixed_seed(self) -> None:
        import random

        sustained = make_sustained(0.7)
        preset = DIFFICULTY_PRESETS["hard"]
        first = decide_slider(
            make_event(5000), 2, sustained, preset,
            next_gap_ms=2000, rng=random.Random(7),
        )
        second = decide_slider(
            make_event(5000), 2, sustained, preset,
            next_gap_ms=2000, rng=random.Random(7),
        )
        self.assertEqual(first, second)


class SliderPipelineTests(unittest.TestCase):
    def _objects(self) -> list[GeneratedCircleHitObject]:
        return [
            make_circle(1, 1000, x=100, y=100),
            make_circle(2, 4000, x=300, y=100),
            make_circle(3, 7000, x=300, y=300),
            make_circle(4, 10000, x=100, y=300),
            make_circle(5, 13000, x=100, y=100),
        ]

    def _events(self) -> list[SelectedEvent]:
        return [make_event(t, energy=0.7) for t in (1000, 4000, 7000, 10000, 13000)]

    def test_pipeline_is_deterministic_with_phrase_info(self) -> None:
        from tools.map_generator.rhythm.rhythm_models import PhraseInfo

        preset = DIFFICULTY_PRESETS["hard"]
        phrase_info = [
            PhraseInfo(
                start_ms=0, end_ms=8000, label="chorus-like", confidence=0.8,
                expected_density=3.0, density_flexibility=0.6,
                min_gap_ms=100, target_gap_ms=250, strategy="intensify",
            ),
            PhraseInfo(
                start_ms=8000, end_ms=16000, label="verse-like", confidence=0.8,
                expected_density=1.5, density_flexibility=0.6,
                min_gap_ms=250, target_gap_ms=500, strategy="recover",
            ),
        ]
        objects = self._objects()
        events = self._events()
        first, first_points, first_diag = process_sliders(
            events, objects, objects, sustained=make_sustained(0.8),
            preset=preset, seed=42, slider_config=DEFAULT_SLIDER_CONFIG,
            phrase_info=phrase_info,
        )
        second, second_points, second_diag = process_sliders(
            events, objects, objects, sustained=make_sustained(0.8),
            preset=preset, seed=42, slider_config=DEFAULT_SLIDER_CONFIG,
            phrase_info=phrase_info,
        )
        self.assertEqual(
            [item.to_dict() for item in first],
            [item.to_dict() for item in second],
        )
        self.assertEqual(first_diag.to_dict(), second_diag.to_dict())

    def test_pipeline_reports_shape_counts(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        objects = self._objects()
        events = self._events()
        _, _, diagnostics = process_sliders(
            events, objects, objects, sustained=make_sustained(0.9),
            preset=preset, seed=7, slider_config=DEFAULT_SLIDER_CONFIG,
        )
        self.assertGreaterEqual(diagnostics.accepted_sliders, 0)
        payload = diagnostics.to_dict()
        self.assertIn("shapeCounts", payload)
        self.assertEqual(
            sum(payload["shapeCounts"].values()),
            payload["acceptedSliders"],
        )
        for shape, count in payload["shapeCounts"].items():
            self.assertIn(shape, ("linear", "hook", "arc", "wave", "zigzag", "loop"))

    def test_pipeline_without_phrase_info_is_backward_compatible(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        objects = self._objects()
        events = self._events()
        result_objects, _, diagnostics = process_sliders(
            events, objects, objects, sustained=make_sustained(0.9),
            preset=preset, seed=3, slider_config=DEFAULT_SLIDER_CONFIG,
        )
        self.assertEqual(len(result_objects), len(objects))
        # max_slider_ratio caps accepted sliders (5 objects * 0.25 = 1), and
        # only circles evaluated before the cap count as candidates.
        self.assertGreaterEqual(diagnostics.total_candidates, 1)
        self.assertLessEqual(diagnostics.total_candidates, len(objects))
        self.assertLessEqual(diagnostics.accepted_sliders, 1)

    def test_quality_gate_rejects_pathological_geometry(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        objects = self._objects()
        events = self._events()
        _, _, strict_diagnostics = process_sliders(
            events, objects, objects, sustained=make_sustained(0.9),
            preset=preset, seed=3,
            slider_config=type(DEFAULT_SLIDER_CONFIG)(quality_threshold=99.0, min_slider_ratio=0.0),
        )
        self.assertEqual(strict_diagnostics.accepted_sliders, 0)
        self.assertGreater(strict_diagnostics.rejected_sliders, 0)


class OsuExportTests(unittest.TestCase):
    def test_multisegment_slider_round_trips_through_osu_text(self) -> None:
        # A wave slider (bezier with a red anchor) exported to .osu text must
        # parse back with identical control points and validate cleanly.
        beatmap = ProjectBeatmap(
            title="Wave",
            artist="Artist",
            audio="/audio/test.mp3",
            approach_time=800,
            circle_radius=34,
            objects=[
                ProjectSliderObject(
                    id=1,
                    x=100,
                    y=100,
                    time=1000,
                    end_time=2500,
                    path_type="bezier",
                    control_points=[(150, 130), (180, 120), (180, 120), (250, 180), (300, 200)],
                    repeats=1,
                    pixel_length=220,
                    extra_fields={},
                )
            ],
            extra_fields={},
        )
        hit_objects = project_objects_to_osu_hit_objects(beatmap.objects)
        self.assertEqual(len(hit_objects), 1)
        self.assertIsInstance(hit_objects[0], OsuSliderHitObject)
        slider = hit_objects[0]
        self.assertEqual(slider.curve_type, "bezier")
        self.assertEqual(slider.repeats, 1)

        text = "\n".join(
            [
                "osu file format v14",
                "",
                "[General]",
                "AudioFilename: test.mp3",
                "",
                "[Metadata]",
                "Title:Wave",
                "Artist:Artist",
                "Creator:osu-map-ai",
                "Version:Hard",
                "",
                "[Difficulty]",
                "HPDrainRate:6",
                "CircleSize:4",
                "OverallDifficulty:8",
                "ApproachRate:9",
                "SliderMultiplier:1.6",
                "SliderTickRate:1",
                "",
                "[TimingPoints]",
                "0,500,4,2,1,70,1,0",
                "",
                "[HitObjects]",
                slider.to_line(),
            ]
        )
        parsed = parse_osu_text(text)
        self.assertEqual(len(parsed.sliders), 1)
        parsed_slider = parsed.sliders[0]
        self.assertEqual(
            parsed_slider.control_points,
            [(150, 130), (180, 120), (180, 120), (250, 180), (300, 200)],
            "Red-anchor control points must survive the round trip.",
        )
        self.assertEqual(parsed_slider.repeats, 1)
        validation = validate_parsed_osu_beatmap(parsed)
        self.assertTrue(validation.valid, validation.warnings)

    def test_full_export_pipeline_writes_sliders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_path = root / "map.json"
            analysis_path = root / "analysis.json"
            output_path = root / "map.osu"
            write_json(
                analysis_path,
                {
                    "version": 1,
                    "audio": {"filename": "test.mp3", "durationMs": 30000, "sampleRate": 22050},
                    "rhythm": {"bpm": 120.0, "offsetMs": 0, "beats": [], "onsets": []},
                    "energy": {"frames": [], "quietRegions": [], "highEnergyRegions": []},
                },
            )
            write_json(
                map_path,
                {
                    "title": "Wave",
                    "artist": "Artist",
                    "audio": "/audio/test.mp3",
                    "approachTime": 800,
                    "circleRadius": 34,
                    "objects": [
                        {
                            "id": 1,
                            "type": "slider",
                            "x": 100,
                            "y": 100,
                            "time": 1000,
                            "endTime": 2500,
                            "pathType": "bezier",
                            "controlPoints": [
                                {"x": 150, "y": 130},
                                {"x": 180, "y": 120},
                                {"x": 180, "y": 120},
                                {"x": 250, "y": 180},
                                {"x": 300, "y": 200},
                            ],
                            "repeats": 1,
                            "pixelLength": 220,
                        }
                    ],
                },
            )
            export_osu_file(
                map_path=map_path,
                analysis_path=analysis_path,
                output_path=output_path,
                creator="osu-map-ai",
                version_name="Hard",
            )
            self.assertTrue(output_path.exists())
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("[HitObjects]", text)
            self.assertIn("B|150:130|180:120|180:120|250:180|300:200", text)
            reparsed = parse_osu_text(text)
            self.assertEqual(len(reparsed.sliders), 1)
            self.assertTrue(validate_parsed_osu_beatmap(reparsed).valid)

    def test_import_rejects_sliders_with_legacy_message(self) -> None:
        from tools.map_generator.osu_format.hitobject_converter import osu_to_project_beatmap
        from tools.map_generator.utils import MapGeneratorError

        text = "\n".join(
            [
                "osu file format v14",
                "",
                "[General]",
                "AudioFilename: test.mp3",
                "",
                "[Metadata]",
                "Title:Wave",
                "Artist:Artist",
                "Creator:osu-map-ai",
                "Version:Hard",
                "",
                "[Difficulty]",
                "HPDrainRate:6",
                "CircleSize:4",
                "OverallDifficulty:8",
                "ApproachRate:9",
                "SliderMultiplier:1.6",
                "SliderTickRate:1",
                "",
                "[TimingPoints]",
                "0,500,4,2,1,70,1,0",
                "",
                "[HitObjects]",
                "100,100,1000,2,0,B|150:130|180:120,1,220",
            ]
        )
        parsed = parse_osu_text(text)
        self.assertEqual(len(parsed.sliders), 1)
        with self.assertRaises(MapGeneratorError) as context:
            osu_to_project_beatmap(
                parsed,
                source_filename="map.osu",
                output_path="out.json",
                skip_unsupported=False,
            )
        self.assertIn("slider", str(context.exception).lower())
        # Skip mode drops sliders with a warning instead of failing.
        beatmap, warnings = osu_to_project_beatmap(
            parsed,
            source_filename="map.osu",
            output_path="out.json",
            skip_unsupported=True,
        )
        self.assertEqual(len(beatmap.objects), 0)
        self.assertTrue(any("slider" in warning.lower() for warning in warnings))


class ScorerBackwardCompatibilityTests(unittest.TestCase):
    def test_scorer_works_without_phase21_kwargs(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        score = score_slider_candidate(
            start_x=100,
            start_y=100,
            end_x=300,
            end_y=200,
            control_points=generate_hook_path(
                100, 100, 300, 200, flow_in_deg=30.0, flow_out_deg=45.0
            ),
            path_type="bezier",
            repeats=1,
            pixel_length=120.0,
            sustained_score=0.6,
            energy=0.6,
            previous_distance=90.0,
            previous_angle=0.0,
            entry_angle_deg=30.0,
            exit_angle_deg=45.0,
            preset=preset,
        )
        for value in (
            score.musical_match,
            score.flow,
            score.shape_quality,
            score.comfort,
            score.spacing,
            score.difficulty,
            score.transition_quality,
            score.overall,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)

    def test_scorer_rewards_flow_alignment(self) -> None:
        preset = DIFFICULTY_PRESETS["hard"]
        aligned = score_slider_candidate(
            start_x=100,
            start_y=100,
            end_x=300,
            end_y=200,
            control_points=generate_hook_path(
                100, 100, 300, 200, flow_in_deg=30.0, flow_out_deg=45.0
            ),
            path_type="bezier",
            repeats=1,
            pixel_length=120.0,
            sustained_score=0.6,
            energy=0.6,
            previous_distance=90.0,
            previous_angle=0.0,
            entry_angle_deg=30.0,
            exit_angle_deg=45.0,
            preset=preset,
            shape="hook",
            flow_in_deg=30.0,
            flow_out_deg=45.0,
        )
        misaligned = score_slider_candidate(
            start_x=100,
            start_y=100,
            end_x=300,
            end_y=200,
            control_points=generate_hook_path(
                100, 100, 300, 200, flow_in_deg=30.0, flow_out_deg=45.0
            ),
            path_type="bezier",
            repeats=1,
            pixel_length=120.0,
            sustained_score=0.6,
            energy=0.6,
            previous_distance=90.0,
            previous_angle=0.0,
            entry_angle_deg=30.0,
            exit_angle_deg=45.0,
            preset=preset,
            shape="hook",
            flow_in_deg=200.0,
            flow_out_deg=200.0,
        )
        self.assertGreater(aligned.flow, misaligned.flow)


if __name__ == "__main__":
    unittest.main()
