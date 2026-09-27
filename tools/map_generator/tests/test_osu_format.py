from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.map_generator.osu_format import (
    export_osu_file,
    export_osu_mapset,
    import_osu_file,
    package_osz_archive,
    parse_osu_text,
)
from tools.map_generator.osu_format.difficulty_converter import (
    project_approach_time_to_ar,
    project_radius_to_circle_size,
)
from tools.map_generator.osu_format.timing_converter import build_primary_timing_point
from tools.map_generator.osu_format.validator import validate_parsed_osu_beatmap
from tools.map_generator.utils import MapGeneratorError


class OsuFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[3]
        tmp_root = self.workspace_root / ".tmp-osu-tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="osu-format-", dir=tmp_root))
        self.tracked_paths: set[Path] = set()

        self.analysis_path = self.temp_dir / "test-analysis.json"
        self.analysis_path.write_text(
            json.dumps(make_analysis_json(), indent=2),
            encoding="utf-8",
        )
        self.audio_path = self.temp_dir / "test-song.mp3"
        self.audio_path.write_bytes(b"ID3")
        self.map_path = self.temp_dir / "test-song-normal.json"
        self.map_path.write_text(
            json.dumps(make_project_beatmap(), indent=2),
            encoding="utf-8",
        )

        self.imported_manifest_path = (
            self.workspace_root / "public" / "maps" / "imported" / "index.json"
        )
        self.imported_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.original_manifest = (
            self.imported_manifest_path.read_text(encoding="utf-8")
            if self.imported_manifest_path.exists()
            else None
        )

    def tearDown(self) -> None:
        if self.original_manifest is None:
            self.imported_manifest_path.unlink(missing_ok=True)
        else:
            self.imported_manifest_path.write_text(
                self.original_manifest,
                encoding="utf-8",
            )

        for path in sorted(self.tracked_paths, key=lambda item: len(item.parts), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parser_handles_comments_metadata_and_timing_points(self) -> None:
        parsed = parse_osu_text(make_circle_only_osu_text())

        self.assertEqual(parsed.format_version, 14)
        self.assertEqual(parsed.metadata["Title"], "Imported Song")
        self.assertEqual(parsed.background_filename, "bg.png")
        self.assertEqual(len(parsed.timing_points), 1)
        self.assertEqual(len(parsed.circles), 2)
        self.assertIn("General", parsed.sections_found)
        self.assertIn("HitObjects", parsed.sections_found)

    def test_validator_flags_coordinate_and_timestamp_failures(self) -> None:
        parsed = parse_osu_text(make_invalid_osu_text())
        validation = validate_parsed_osu_beatmap(parsed)

        self.assertFalse(validation.valid)
        self.assertIn("Circle at -10ms is out of bounds.", validation.warnings)
        self.assertIn("Hit object times must be non-negative.", validation.warnings)

    def test_validator_flags_invalid_audio_filename_paths(self) -> None:
        parsed = parse_osu_text(make_invalid_audio_osu_text())
        validation = validate_parsed_osu_beatmap(parsed)

        self.assertFalse(validation.valid)
        self.assertIn(
            "Audio filename must stay relative inside the mapset: ../outside/test-song.mp3",
            validation.warnings,
        )

    def test_export_round_trip_is_deterministic_and_preserves_objects(self) -> None:
        output_path = self.temp_dir / "exports" / "phase8-roundtrip.osu"
        round_trip_path = self.temp_dir / "exports" / "phase8-roundtrip.json"
        self.track(output_path)
        self.track(round_trip_path)
        self.track(self.export_report_path(output_path))
        self.track(self.import_report_path(round_trip_path))

        first = export_osu_file(
            map_path=self.map_path,
            analysis_path=self.analysis_path,
            output_path=output_path,
            creator="osu-map-ai",
            version_name="Hybrid Normal",
        )
        second = export_osu_file(
            map_path=self.map_path,
            analysis_path=self.analysis_path,
            output_path=output_path,
            creator="osu-map-ai",
            version_name="Hybrid Normal",
        )
        imported = import_osu_file(
            input_path=output_path,
            output_path=round_trip_path,
            unsupported_mode="reject",
        )
        round_trip_json = json.loads(round_trip_path.read_text(encoding="utf-8"))

        self.assertEqual(first.text, second.text)
        self.assertEqual(first.text, output_path.read_text(encoding="utf-8"))
        self.assertTrue(first.report.validation.valid)
        self.assertEqual(
            [
                (item["x"], item["y"], item["time"])
                for item in round_trip_json["objects"]
            ],
            [
                (item["x"], item["y"], item["time"])
                for item in make_project_beatmap()["objects"]
            ],
        )
        self.assertEqual(imported.beatmap.title, "Test Song")
        self.assertEqual(imported.beatmap.artist, "Unknown Artist")
        self.assertEqual(imported.beatmap.audio, "/audio/test-song.mp3")

    def test_spinner_objects_round_trip_through_export_and_import(self) -> None:
        spinner_map_path = self.temp_dir / "test-song-spinner.json"
        spinner_map_path.write_text(
            json.dumps(make_project_beatmap_with_spinner(), indent=2),
            encoding="utf-8",
        )
        output_path = self.temp_dir / "exports" / "phase12-spinner.osu"
        round_trip_path = self.temp_dir / "exports" / "phase12-spinner.json"
        self.track(output_path)
        self.track(round_trip_path)
        self.track(self.export_report_path(output_path))
        self.track(self.import_report_path(round_trip_path))

        exported = export_osu_file(
            map_path=spinner_map_path,
            analysis_path=self.analysis_path,
            output_path=output_path,
            creator="osu-map-ai",
            version_name="Normal",
        )
        imported = import_osu_file(
            input_path=output_path,
            output_path=round_trip_path,
            unsupported_mode="reject",
        )
        round_trip_json = json.loads(round_trip_path.read_text(encoding="utf-8"))

        self.assertTrue(exported.report.validation.valid)
        self.assertEqual(imported.report.spinner_count, 1)
        self.assertEqual(imported.report.circle_count, 3)
        spinner_line = next(
            line
            for line in exported.text.splitlines()
            if "256,192" in line and ",8," in line
        )
        self.assertIn(",5000", spinner_line)
        spinner_object = next(
            item for item in round_trip_json["objects"] if item["type"] == "spinner"
        )
        self.assertEqual(spinner_object["time"], 4400)
        self.assertEqual(spinner_object["endTime"], 5000)

    def test_import_reject_and_skip_modes_report_unsupported_objects(self) -> None:
        unsupported_path = self.temp_dir / "unsupported.osu"
        unsupported_path.write_text(make_unsupported_osu_text(), encoding="utf-8")
        imported_output = (
            self.workspace_root
            / "public"
            / "maps"
            / "imported"
            / f"{self.temp_dir.name}-imported.json"
        )
        self.track(imported_output)
        self.track(self.import_report_path(imported_output))

        with self.assertRaises(MapGeneratorError):
            import_osu_file(
                input_path=unsupported_path,
                output_path=self.temp_dir / "reject.json",
                unsupported_mode="reject",
            )

        imported = import_osu_file(
            input_path=unsupported_path,
            output_path=imported_output,
            unsupported_mode="skip",
        )
        imported_json = json.loads(imported_output.read_text(encoding="utf-8"))
        manifest = json.loads(self.imported_manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(imported.report.slider_count, 1)
        self.assertEqual(imported.report.skipped_count, 1)
        self.assertEqual(len(imported_json["objects"]), 1)
        self.assertTrue(
            any(
                item["path"] == f"/maps/imported/{imported_output.name}"
                for item in manifest["maps"]
            )
        )

    def test_package_osz_archive_is_deterministic_and_rejects_audio_mismatch(self) -> None:
        export_dir = self.temp_dir / "mapset"
        output_easy = export_dir / "phase8-easy.osu"
        output_hard = export_dir / "phase8-hard.osu"
        archive_path = self.temp_dir / "phase8-test-song.osz"
        self.track(output_easy)
        self.track(output_hard)
        self.track(archive_path)
        self.track(self.export_report_path(output_easy))
        self.track(self.export_report_path(output_hard))

        export_osu_file(
            map_path=self.map_path,
            analysis_path=self.analysis_path,
            output_path=output_easy,
            creator="osu-map-ai",
            version_name="Hybrid Easy",
        )
        export_osu_file(
            map_path=self.map_path,
            analysis_path=self.analysis_path,
            output_path=output_hard,
            creator="osu-map-ai",
            version_name="Hybrid Hard",
        )

        package_result = package_osz_archive(
            maps_dir=export_dir,
            audio_path=self.audio_path,
            output_path=archive_path,
        )

        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()

        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(package_result.archived_files, names)
        self.assertIn("test-song.mp3", names)

        mismatched_audio = self.temp_dir / "other-song.mp3"
        mismatched_audio.write_bytes(b"ID3")
        with self.assertRaises(MapGeneratorError):
            package_osz_archive(
                maps_dir=export_dir,
                audio_path=mismatched_audio,
                output_path=self.temp_dir / "bad.osz",
            )

    def test_mapset_export_rejects_metadata_mismatch(self) -> None:
        maps_dir = self.temp_dir / "maps"
        maps_dir.mkdir(parents=True, exist_ok=True)
        first_map = maps_dir / "first.json"
        second_map = maps_dir / "second.json"
        first_map.write_text(
            json.dumps(make_project_beatmap(), indent=2),
            encoding="utf-8",
        )
        second_map.write_text(
            json.dumps(make_project_beatmap(title="Different Song"), indent=2),
            encoding="utf-8",
        )

        with self.assertRaises(MapGeneratorError):
            export_osu_mapset(
                maps_dir=maps_dir,
                analysis_path=self.analysis_path,
                audio_path=self.audio_path,
                output_dir=self.temp_dir / "bad-mapset",
            )

    def test_mapset_export_keeps_hybrid_version_names_from_real_map_metadata(self) -> None:
        maps_dir = self.temp_dir / "hybrid-maps"
        maps_dir.mkdir(parents=True, exist_ok=True)
        for difficulty in ("easy", "normal", "hard"):
            (maps_dir / f"{difficulty}.json").write_text(
                json.dumps(make_real_hybrid_project_beatmap(difficulty), indent=2),
                encoding="utf-8",
            )

        output_dir = self.temp_dir / "hybrid-mapset"
        output_dir.mkdir(parents=True, exist_ok=True)
        stale_output_path = output_dir / "Unknown Artist - Test Song (osu-map-ai) [Easy].osu"
        stale_output_path.write_text("legacy", encoding="utf-8")
        stale_report_path = self.export_report_path(stale_output_path)
        stale_report_path.parent.mkdir(parents=True, exist_ok=True)
        stale_report_path.write_text("legacy", encoding="utf-8")
        result = export_osu_mapset(
            maps_dir=maps_dir,
            analysis_path=self.analysis_path,
            audio_path=self.audio_path,
            output_dir=output_dir,
        )
        exported_names = {
            Path(entry.osu_path).name
            for entry in result.entries
        }

        self.assertEqual(
            exported_names,
            {
                "Unknown Artist - Test Song (osu-map-ai) [Hybrid Easy].osu",
                "Unknown Artist - Test Song (osu-map-ai) [Hybrid Normal].osu",
                "Unknown Artist - Test Song (osu-map-ai) [Hybrid Hard].osu",
            },
        )
        self.assertFalse(stale_output_path.exists())
        self.assertFalse(stale_report_path.exists())

        for entry in result.entries:
            self.track(Path(entry.osu_path))
            self.track(Path(entry.report_path))

    def test_difficulty_and_timing_conversions_stay_in_expected_ranges(self) -> None:
        timing_point, bpm, offset_ms = build_primary_timing_point(self.analysis_path)
        circle_size = project_radius_to_circle_size(40)
        approach_rate = project_approach_time_to_ar(950)

        self.assertGreaterEqual(circle_size, 0.0)
        self.assertLessEqual(circle_size, 10.0)
        self.assertGreaterEqual(approach_rate, 0.0)
        self.assertLessEqual(approach_rate, 10.0)
        self.assertAlmostEqual(timing_point.beat_length, 60000.0 / bpm)
        self.assertEqual(offset_ms, 300)
        self.assertEqual(timing_point.time, 300)

    def track(self, path: Path) -> None:
        self.tracked_paths.add(path)

    def export_report_path(self, output_path: Path) -> Path:
        return (
            self.workspace_root
            / "public"
            / "exports"
            / "reports"
            / f"{output_path.stem}-export.json"
        )

    def import_report_path(self, output_path: Path) -> Path:
        return (
            self.workspace_root
            / "public"
            / "imports"
            / "reports"
            / f"{output_path.stem}-import.json"
        )


def make_analysis_json() -> dict[str, object]:
    return {
        "version": 1,
        "audio": {
            "filename": "test-song.mp3",
            "durationMs": 6000,
            "sampleRate": 22050,
        },
        "rhythm": {
            "bpm": 120.0,
            "offsetMs": 300,
            "beats": [
                {"timeMs": 300, "strength": 1.0},
                {"timeMs": 800, "strength": 0.8},
                {"timeMs": 1300, "strength": 0.9},
            ],
            "onsets": [
                {"timeMs": 300, "strength": 1.0},
                {"timeMs": 1000, "strength": 0.7},
                {"timeMs": 1400, "strength": 0.85},
            ],
        },
        "energy": {
            "frames": [
                {"timeMs": 0, "value": 0.2},
                {"timeMs": 300, "value": 0.4},
                {"timeMs": 600, "value": 0.3},
            ],
            "quietRegions": [
                {"startMs": 0, "endMs": 900, "averageValue": 0.25},
            ],
            "highEnergyRegions": [
                {"startMs": 900, "endMs": 1800, "averageValue": 0.65},
            ],
        },
    }


def make_project_beatmap(
    *,
    title: str = "Test Song",
    artist: str = "Unknown Artist",
) -> dict[str, object]:
    return {
        "title": title,
        "artist": artist,
        "audio": "/audio/test-song.mp3",
        "approachTime": 950,
        "circleRadius": 40,
        "editor": {
            "sourceType": "hybrid",
            "sourceDifficulty": "normal",
        },
        "objects": [
            {"id": 1, "type": "circle", "x": 96, "y": 96, "time": 1000},
            {"id": 2, "type": "circle", "x": 256, "y": 192, "time": 1400},
            {"id": 3, "type": "circle", "x": 420, "y": 144, "time": 1800},
        ],
    }


def make_project_beatmap_with_spinner() -> dict[str, object]:
    return {
        "title": "Test Song",
        "artist": "Unknown Artist",
        "audio": "/audio/test-song.mp3",
        "approachTime": 950,
        "circleRadius": 40,
        "editor": {
            "sourceType": "hybrid",
            "sourceDifficulty": "normal",
        },
        "objects": [
            {"id": 1, "type": "circle", "x": 96, "y": 96, "time": 1000},
            {"id": 2, "type": "circle", "x": 256, "y": 192, "time": 1400},
            {"id": 3, "type": "spinner", "time": 4400, "endTime": 5000},
            {"id": 4, "type": "circle", "x": 420, "y": 144, "time": 5600},
        ],
    }


def make_circle_only_osu_text() -> str:
    return """osu file format v14

// parser should ignore comments
[General]
AudioFilename: test-song.mp3

[Metadata]
Title: Imported Song
Artist: Unit Test Artist
Creator: osu-map-ai
Version: Edited Normal

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 6
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[Events]
0,0,"bg.png",0,0

[TimingPoints]
300,500,4,2,0,70,1,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
256,192,1400,5,0,0:0:0:0:
"""


def make_unsupported_osu_text() -> str:
    return """osu file format v14

[General]
AudioFilename: test-song.mp3

[Metadata]
Title: Unsupported Song
Artist: Unit Test Artist
Creator: osu-map-ai
Version: Hard

[Difficulty]
HPDrainRate: 6
CircleSize: 4
OverallDifficulty: 7
ApproachRate: 7
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
0,500,4,2,0,70,1,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
256,192,1400,2,0,B|320:192|384:128,1,200
"""


def make_invalid_osu_text() -> str:
    return """osu file format v14

[General]
AudioFilename: bad.mp3

[Metadata]
Title: Broken
Artist: Unit Test
Creator: osu-map-ai
Version: Broken

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 5
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
0,500,4,2,0,70,1,0

[HitObjects]
640,96,-10,1,0,0:0:0:0:
"""


def make_invalid_audio_osu_text() -> str:
    return """osu file format v14

[General]
AudioFilename: ../outside/test-song.mp3

[Metadata]
Title: Invalid Audio
Artist: Unit Test
Creator: osu-map-ai
Version: Broken

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 5
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
0,500,4,2,0,70,1,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
"""


def make_real_hybrid_project_beatmap(difficulty: str) -> dict[str, object]:
    return {
        "title": "Test Song",
        "artist": "Unknown Artist",
        "audio": "/audio/test-song.mp3",
        "approachTime": 1200 if difficulty == "easy" else 950 if difficulty == "normal" else 720,
        "circleRadius": 46 if difficulty == "easy" else 40 if difficulty == "normal" else 34,
        "objects": [
            {"id": 1, "type": "circle", "x": 96, "y": 96, "time": 1000},
            {"id": 2, "type": "circle", "x": 256, "y": 192, "time": 1400},
        ],
        "hybrid": {
            "version": 1,
            "difficulty": difficulty,
            "sectionCount": 2,
            "sourceCandidates": [1, 3],
            "transitionCorrections": 0,
        },
    }


if __name__ == "__main__":
    unittest.main()
