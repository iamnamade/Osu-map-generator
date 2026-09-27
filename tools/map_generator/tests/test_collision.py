"""Phase 23 — Anti-overlap collision engine tests.

Covers the geometry primitives, the shared raw-JSON overlap detector, the
collision validator integration, the rebalancer's ``resolve_collisions`` pass,
the evolution ``COLLISION_FREE`` hard gate, radius-aware stacking, the
postprocessing clearance fix, and determinism / backward compatibility.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.evolution.final_ranking import run_quality_gates
from tools.map_generator.geometry.collision import (
    PERFECT_STACK_PX,
    STACK_TIME_WINDOW_MS,
    clamp_to_playfield,
    detect_map_overlaps,
    discs_clearance,
    discs_overlap,
    point_polyline_distance,
    polyline_polyline_distance,
)
from tools.map_generator.rebalance.collisions import resolve_collisions
from tools.map_generator.rebalance.patterns import stack_overlap_distance, unstack_objects
from tools.map_generator.validation.beatmap_validator import validate_beatmap
from tools.map_generator.validation.collision_validator import validate_collisions
from tools.map_generator.validation.models import ParsedBeatmap, ParsedBeatmapObject

from .test_validation import make_analysis


def make_circle(object_id: int, x: int, y: int, time_ms: int) -> dict:
    return {"id": object_id, "type": "circle", "x": x, "y": y, "time": time_ms}


def make_slider(
    object_id: int,
    x: int,
    y: int,
    time_ms: int,
    control_points: list[tuple[int, int]],
    path_type: str = "linear",
) -> dict:
    return {
        "id": object_id,
        "type": "slider",
        "x": x,
        "y": y,
        "time": time_ms,
        "pathType": path_type,
        "controlPoints": [{"x": px, "y": py} for px, py in control_points],
        "repeats": 1,
        "pixelLength": 200.0,
        "endTime": time_ms + 500,
    }


def make_parsed(objects: list[ParsedBeatmapObject], difficulty: str = "normal") -> ParsedBeatmap:
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


class CollisionPrimitiveTests(unittest.TestCase):
    def test_discs_clearance_is_radius_aware(self) -> None:
        # Centers 100px apart, radius 40 each: clearance = 100 - 80 = 20.
        self.assertAlmostEqual(discs_clearance(0, 0, 40, 100, 0, 40), 20.0, places=6)
        # Overlapping discs give negative clearance (overlap depth).
        self.assertAlmostEqual(discs_clearance(0, 0, 40, 70, 0, 40), -10.0, places=6)
        # Larger circles overlap at the same center distance.
        self.assertTrue(discs_overlap(0, 0, 60, 100, 0, 60))
        self.assertFalse(discs_overlap(0, 0, 40, 100, 0, 40))

    def test_discs_overlap_respects_margin(self) -> None:
        # Clear by exactly 2px; margin of 4 makes it an overlap.
        self.assertFalse(discs_overlap(0, 0, 40, 82, 0, 40))
        self.assertTrue(discs_overlap(0, 0, 40, 82, 0, 40, margin_px=4.0))

    def test_point_polyline_distance(self) -> None:
        path = [(0.0, 0.0), (100.0, 0.0)]
        self.assertAlmostEqual(point_polyline_distance(50, 30, path), 30.0, places=6)
        self.assertAlmostEqual(point_polyline_distance(120, 0, path), 20.0, places=6)

    def test_polyline_polyline_distance_crossing_is_zero(self) -> None:
        horizontal = [(0.0, 50.0), (100.0, 50.0)]
        vertical = [(50.0, 0.0), (50.0, 100.0)]
        self.assertEqual(polyline_polyline_distance(horizontal, vertical), 0.0)
        parallel = [(0.0, 20.0), (100.0, 20.0)]
        self.assertAlmostEqual(
            polyline_polyline_distance(horizontal, parallel), 30.0, places=6
        )

    def test_clamp_to_playfield(self) -> None:
        x, y = clamp_to_playfield(-50.0, 400.0, 40.0)
        self.assertEqual(x, 40.0)
        self.assertEqual(y, 344.0)


class RadiusAwareStackingTests(unittest.TestCase):
    def test_overlap_threshold_scales_with_radius(self) -> None:
        easy = DIFFICULTY_PRESETS["easy"]
        hard = DIFFICULTY_PRESETS["hard"]
        self.assertGreater(
            stack_overlap_distance(easy.circle_radius),
            stack_overlap_distance(hard.circle_radius),
        )
        self.assertAlmostEqual(
            stack_overlap_distance(easy.circle_radius),
            easy.circle_radius * 2.0 + 4.0,
            places=2,
        )

    def test_legacy_fallback_without_radius(self) -> None:
        # Old workspaces without a circle radius keep the fixed 34px behavior.
        self.assertEqual(stack_overlap_distance(None), 34.0)
        self.assertEqual(stack_overlap_distance(0), 34.0)

    def test_unstack_uses_radius_aware_distance(self) -> None:
        # Two discs 60px apart: overlap for easy (radius 47.4 -> 98.8 threshold)
        # but clean for hard (radius ~30 -> 64 threshold)... build both cases.
        easy_radius = DIFFICULTY_PRESETS["easy"].circle_radius
        hard_radius = DIFFICULTY_PRESETS["hard"].circle_radius
        # 80px apart: overlapping for easy's big circles, clean for hard's.
        gap = 80.0
        self.assertLess(gap, easy_radius * 2.0 + 4.0)
        self.assertGreater(gap, hard_radius * 2.0 + 4.0)

        easy_map = {
            "circleRadius": easy_radius,
            "objects": [
                {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                {"id": 2, "type": "circle", "x": 180, "y": 100, "time": 1250},
            ],
        }
        _, easy_adjustments = unstack_objects(map_dict=easy_map, sections=[])
        self.assertEqual(len(easy_adjustments), 1)
        self.assertEqual(easy_adjustments[0].action, "unstack")

        hard_map = {
            "circleRadius": hard_radius,
            "objects": [
                {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                {"id": 2, "type": "circle", "x": 180, "y": 100, "time": 1250},
            ],
        }
        _, hard_adjustments = unstack_objects(map_dict=hard_map, sections=[])
        self.assertEqual(len(hard_adjustments), 0)


class DetectMapOverlapsTests(unittest.TestCase):
    def test_disc_disc_overlap(self) -> None:
        objects = [
            make_circle(1, 100, 100, 1000),
            make_circle(2, 130, 100, 1250),
        ]
        records = detect_map_overlaps(objects, 40.0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "disc-disc")
        self.assertEqual(records[0]["left_id"], 1)
        self.assertEqual(records[0]["right_id"], 2)
        self.assertAlmostEqual(records[0]["clearance_px"], 30.0 - 80.0, places=6)

    def test_clear_discs_are_not_flagged(self) -> None:
        objects = [
            make_circle(1, 100, 100, 1000),
            make_circle(2, 300, 100, 1250),
        ]
        self.assertEqual(detect_map_overlaps(objects, 40.0), [])

    def test_disc_vs_slider_body(self) -> None:
        # Horizontal slider along y=100; circle 20px below the path.
        objects = [
            make_slider(1, 100, 100, 1000, [(300, 100)]),
            make_circle(2, 200, 120, 1250),
        ]
        records = detect_map_overlaps(objects, 40.0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "disc-slider")
        self.assertAlmostEqual(records[0]["clearance_px"], 20.0 - 80.0, places=5)

    def test_slider_slider_crossing(self) -> None:
        objects = [
            make_slider(1, 100, 100, 1000, [(300, 100)]),
            make_slider(2, 200, 50, 1250, [(200, 300)]),
        ]
        records = detect_map_overlaps(objects, 40.0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "slider-slider")
        self.assertLess(records[0]["clearance_px"], 0.0)

    def test_intentional_time_separated_stack_not_flagged(self) -> None:
        # Same spot, far apart in time: legal osu! notation.
        objects = [
            make_circle(1, 200, 200, 0),
            make_circle(2, 200, 200, 2000),
        ]
        self.assertGreater(2000, STACK_TIME_WINDOW_MS)
        records = detect_map_overlaps(objects, 40.0)
        self.assertEqual(records, [])

    def test_objects_beyond_time_window_not_compared(self) -> None:
        objects = [
            make_circle(1, 100, 100, 0),
            make_circle(2, 120, 100, 3000),
        ]
        self.assertEqual(detect_map_overlaps(objects, 40.0), [])

    def test_detection_is_deterministic(self) -> None:
        objects = [
            make_circle(1, 100, 100, 1000),
            make_slider(2, 100, 100, 1250, [(300, 100)]),
            make_circle(3, 90, 110, 1500),
        ]
        first = [r["left_id"] for r in detect_map_overlaps(objects, 40.0)]
        second = [r["left_id"] for r in detect_map_overlaps(objects, 40.0)]
        self.assertEqual(first, second)


class CollisionValidatorTests(unittest.TestCase):
    def test_validator_emits_collision_overlap_issues(self) -> None:
        parsed = make_parsed(
            [
                ParsedBeatmapObject(id=1, type="circle", time=1000, x=100, y=100),
                ParsedBeatmapObject(id=2, type="circle", time=1250, x=130, y=100),
            ]
        )
        result = validate_collisions(parsed)
        self.assertEqual(result.overlap_count, 1)
        self.assertEqual(result.issues[0].code, "COLLISION_OVERLAP")
        self.assertEqual(result.issues[0].severity, "error")
        self.assertEqual(result.issues[0].object_ids, [1, 2])

    def test_validator_clean_map_has_no_issues(self) -> None:
        parsed = make_parsed(
            [
                ParsedBeatmapObject(id=1, type="circle", time=1000, x=100, y=100),
                ParsedBeatmapObject(id=2, type="circle", time=1250, x=300, y=100),
            ]
        )
        result = validate_collisions(parsed)
        self.assertEqual(result.overlap_count, 0)
        self.assertEqual(result.issues, [])

    def test_validate_beatmap_includes_collision_issues(self) -> None:
        analysis = make_analysis(duration_ms=6000, beats=[1000, 2000, 3000, 4000])
        beatmap_json = {
            "title": "Test Song",
            "artist": "Unknown Artist",
            "audio": "/audio/test-song.mp3",
            "approachTime": 950,
            "circleRadius": 40,
            "objects": [
                {"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000},
                {"id": 2, "type": "circle", "x": 130, "y": 100, "time": 1250},
                {"id": 3, "type": "circle", "x": 300, "y": 140, "time": 3000},
            ],
            "generator": {"difficulty": "normal", "seed": 42},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = temp_path / "map.json"
            analysis_path = temp_path / "analysis.json"
            map_path.write_text(json.dumps(beatmap_json), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis.to_dict()), encoding="utf-8")
            report = validate_beatmap(
                map_path=map_path,
                analysis_path=analysis_path,
                difficulty="normal",
                map_label="public/maps/generated/test-map.json",
            ).report

        codes = [issue.code for issue in report.issues]
        self.assertIn("COLLISION_OVERLAP", codes)


class ResolveCollisionsTests(unittest.TestCase):
    def test_nudges_later_object_clear(self) -> None:
        map_dict = {
            "circleRadius": 40.0,
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 130, 100, 1250),
            ],
        }
        out, adjustments = resolve_collisions(map_dict=map_dict, sections=[])
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0].action, "resolve_collision")
        self.assertEqual(adjustments[0].object_id, 2)
        self.assertEqual(detect_map_overlaps(out["objects"], 40.0), [])
        # Original input is untouched (deep copy semantics).
        self.assertEqual(map_dict["objects"][1]["x"], 130)

    def test_slider_control_points_translate_with_nudge(self) -> None:
        map_dict = {
            "circleRadius": 40.0,
            "objects": [
                make_slider(1, 100, 100, 1000, [(300, 100)]),
                make_circle(2, 200, 120, 1250),
            ],
        }
        out, adjustments = resolve_collisions(map_dict=map_dict, sections=[])
        self.assertEqual(len(adjustments), 1)
        resolved = out["objects"][1]
        self.assertEqual(resolved["type"], "circle")
        self.assertEqual(detect_map_overlaps(out["objects"], 40.0), [])
        # The slider's control points keep their absolute coordinates (the
        # circle was nudged, not the slider): the slider must be unchanged.
        slider = next(item for item in out["objects"] if item["type"] == "slider")
        self.assertEqual(slider["controlPoints"][0], {"x": 300, "y": 100})

    def test_nudged_slider_translates_control_points(self) -> None:
        # Two sliders crossing: the later slider gets nudged, and its control
        # points must move by the same delta so the path stays coherent.
        map_dict = {
            "circleRadius": 40.0,
            "objects": [
                make_slider(1, 100, 100, 1000, [(300, 100)]),
                make_slider(2, 200, 50, 1250, [(200, 300)]),
            ],
        }
        out, adjustments = resolve_collisions(map_dict=map_dict, sections=[])
        self.assertEqual(len(adjustments), 1)
        left = next(item for item in out["objects"] if item["id"] == 1)
        right = next(item for item in out["objects"] if item["id"] == 2)
        self.assertEqual(left["controlPoints"][0], {"x": 300, "y": 100})
        delta_x = right["x"] - 200
        delta_y = right["y"] - 50
        self.assertEqual(
            right["controlPoints"][0],
            {"x": round(200 + delta_x, 2), "y": round(300 + delta_y, 2)},
        )
        self.assertEqual(detect_map_overlaps(out["objects"], 40.0), [])

    def test_clean_map_returns_unchanged(self) -> None:
        map_dict = {
            "circleRadius": 40.0,
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 300, 100, 1250),
            ],
        }
        out, adjustments = resolve_collisions(map_dict=map_dict, sections=[])
        self.assertEqual(adjustments, [])
        self.assertIs(out, map_dict)

    def test_legacy_map_without_radius_untouched(self) -> None:
        map_dict = {
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 130, 100, 1250),
            ],
        }
        out, adjustments = resolve_collisions(map_dict=map_dict, sections=[])
        self.assertEqual(adjustments, [])
        self.assertIs(out, map_dict)

    def test_resolution_is_deterministic(self) -> None:
        def run() -> list[tuple[int, int]]:
            map_dict = {
                "circleRadius": 40.0,
                "objects": [
                    make_circle(1, 100, 100, 1000),
                    make_circle(2, 120, 100, 1250),
                    make_slider(3, 100, 100, 1500, [(300, 100)]),
                ],
            }
            out, _ = resolve_collisions(map_dict=map_dict, sections=[])
            return [(int(o["id"]), int(o["x"]), int(o["y"])) for o in out["objects"]]

        self.assertEqual(run(), run())


class EvolutionCollisionGateTests(unittest.TestCase):
    def _gate_report(self, map_dict: dict) -> list:
        difficulty_report = SimpleNamespace(
            target=SimpleNamespace(name="normal"),
            metrics=SimpleNamespace(
                average_gap_ms=400.0,
                object_count=len(map_dict.get("objects", [])),
            ),
            sections=[],
            reading=None,
            aim=None,
        )
        return run_quality_gates(
            difficulty_report=difficulty_report,
            replay_report=None,
            validation_report=None,
            map_dict=map_dict,
        )

    def test_collision_free_gate_rejects_overlapping_map(self) -> None:
        map_dict = {
            "circleRadius": 40.0,
            "approachTime": 950,
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 130, 100, 1250),
            ],
        }
        gates = self._gate_report(map_dict)
        gate = next(gate for gate in gates if gate.code == "COLLISION_FREE")
        self.assertTrue(gate.mandatory)
        self.assertFalse(gate.passed)

    def test_collision_free_gate_passes_after_resolution(self) -> None:
        map_dict = {
            "circleRadius": 40.0,
            "approachTime": 950,
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 130, 100, 1250),
            ],
        }
        resolved, _ = resolve_collisions(map_dict=map_dict, sections=[])
        gates = self._gate_report(resolved)
        gate = next(gate for gate in gates if gate.code == "COLLISION_FREE")
        self.assertTrue(gate.passed)

    def test_collision_free_gate_passes_without_radius(self) -> None:
        # Legacy maps without a circle radius cannot be checked and must pass.
        map_dict = {
            "approachTime": 950,
            "objects": [
                make_circle(1, 100, 100, 1000),
                make_circle(2, 130, 100, 1250),
            ],
        }
        gates = self._gate_report(map_dict)
        gate = next(gate for gate in gates if gate.code == "COLLISION_FREE")
        self.assertTrue(gate.passed)


class PostprocessClearanceTests(unittest.TestCase):
    def test_offset_for_clearance_pushes_further_in_tight_gap(self) -> None:
        from tools.map_generator.postprocess.density_corrector import _offset_for_clearance

        previous = {"x": 120, "y": 180}
        next_object = {"x": 240, "y": 200}
        midpoint_x = (120 + 240) / 2
        midpoint_y = (180 + 200) / 2
        span_x = 240 - 120
        span_y = 200 - 180
        span_length = (span_x**2 + span_y**2) ** 0.5
        normal_x = -span_y / span_length
        normal_y = span_x / span_length

        required = _offset_for_clearance(
            previous_object=previous,
            next_object=next_object,
            midpoint_x=midpoint_x,
            midpoint_y=midpoint_y,
            normal_x=normal_x,
            normal_y=normal_y,
            sign=1.0,
            clearance=40.0 * 2.0 + 12.0,
        )
        self.assertIsNotNone(required)
        # The midpoint is ~60px from each neighbor, so clearing 92px requires
        # a healthy perpendicular offset.
        self.assertGreater(required, 60.0)

    def test_offset_for_clearance_stays_zero_in_wide_gap(self) -> None:
        from tools.map_generator.postprocess.density_corrector import _offset_for_clearance

        previous = {"x": 100, "y": 100}
        next_object = {"x": 400, "y": 100}
        required = _offset_for_clearance(
            previous_object=previous,
            next_object=next_object,
            midpoint_x=250.0,
            midpoint_y=100.0,
            normal_x=0.0,
            normal_y=1.0,
            sign=1.0,
            clearance=92.0,
        )
        self.assertEqual(required, 0.0)


if __name__ == "__main__":
    unittest.main()
