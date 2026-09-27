from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.map_generator.sections.candidate_section_evaluator import (
    evaluate_candidate_reports,
)
from tools.map_generator.sections.hybrid_assembler import assemble_hybrid_map
from tools.map_generator.sections.hybrid_selector import select_section_sources
from tools.map_generator.sections.section_analyzer import build_section_analysis
from tools.map_generator.sections.section_config import SectionPipelineConfig
from tools.map_generator.sections.section_models import (
    CandidateSectionEvaluation,
    CandidateSectionReport,
    HybridSectionSelection,
    MapObject,
    SectionIssue,
    SectionMetrics,
    SectionScores,
    SectionState,
    SongSection,
)
from tools.map_generator.sections.section_pipeline import (
    analyze_sections,
    assemble_hybrid,
    evaluate_candidate_sections,
    load_section_analysis,
)
from tools.map_generator.sections.transition_analyzer import analyze_transition


class SectionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp(prefix="sections-test-"))
        self.project_root = self.temporary_directory / "project"
        self.public_root = self.project_root / "public"
        (self.public_root / "audio").mkdir(parents=True, exist_ok=True)
        (self.public_root / "analysis").mkdir(parents=True, exist_ok=True)
        self.audio_path = self.public_root / "audio" / "test-song.mp3"
        self.audio_path.write_bytes(b"ID3")
        self.analysis_path = self.public_root / "analysis" / "test-song-analysis.json"
        self.analysis_path.write_text(
            json.dumps(make_analysis_json(), indent=2),
            encoding="utf-8",
        )
        self.config = SectionPipelineConfig()

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory, ignore_errors=True)

    def test_section_analysis_is_deterministic_and_covers_audio(self) -> None:
        sections_path = self.public_root / "sections" / "test-song-sections.json"
        first = analyze_sections(
            audio_path=self.audio_path,
            analysis_path=self.analysis_path,
            output_path=sections_path,
            project_root=self.project_root,
            config=self.config,
            force=True,
        )
        second = analyze_sections(
            audio_path=self.audio_path,
            analysis_path=self.analysis_path,
            output_path=sections_path,
            project_root=self.project_root,
            config=self.config,
            force=False,
        )

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(
            [section.start_ms for section in first.section_analysis.sections],
            [section.start_ms for section in second.section_analysis.sections],
        )
        self.assertGreaterEqual(len(first.section_analysis.sections), 2)
        self.assertEqual(first.section_analysis.sections[0].start_ms, 0)
        self.assertEqual(
            first.section_analysis.sections[-1].end_ms,
            make_analysis_json()["audio"]["durationMs"],
        )
        for left, right in zip(
            first.section_analysis.sections,
            first.section_analysis.sections[1:],
        ):
            self.assertLess(left.start_ms, left.end_ms)
            self.assertEqual(left.end_ms, right.start_ms)

    def test_section_analysis_accepts_workspace_audio_with_browser_override(self) -> None:
        workspace_root = self.temporary_directory / "workspaces" / "workspace-123"
        workspace_audio_path = workspace_root / "source" / "source-audio.mp3"
        workspace_audio_path.parent.mkdir(parents=True, exist_ok=True)
        workspace_audio_path.write_bytes(b"ID3")
        sections_path = workspace_root / "sections" / "sections.json"
        browser_audio_path = "/api/workspaces/workspace-123/source-audio/source-audio.mp3"

        result = analyze_sections(
            audio_path=workspace_audio_path,
            analysis_path=self.analysis_path,
            output_path=sections_path,
            project_root=self.project_root,
            config=self.config,
            force=True,
            audio_browser_path_override=browser_audio_path,
        )

        self.assertEqual(result.section_analysis.audio_path, browser_audio_path)
        payload = json.loads(sections_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["audio"]["path"], browser_audio_path)

    def test_candidate_section_evaluation_supports_resume_and_force(self) -> None:
        section_analysis = build_section_analysis(
            audio_path=self.audio_path,
            analysis_path=self.analysis_path,
            project_root=self.project_root,
            input_signature="sections-signature",
            config=self.config,
        )
        candidates_root = self.public_root / "candidates" / "test-song" / "normal"
        write_candidate_directory(candidates_root, 1, make_candidate_map(1, 90))
        output_dir = self.public_root / "section-reports" / "test-song" / "normal"

        first = evaluate_candidate_reports(
            section_analysis=section_analysis,
            analysis_path=self.analysis_path,
            candidates_root=candidates_root,
            difficulty="normal",
            output_dir=output_dir,
            input_signature="evaluation-signature",
            config=self.config,
            force=False,
        )
        second = evaluate_candidate_reports(
            section_analysis=section_analysis,
            analysis_path=self.analysis_path,
            candidates_root=candidates_root,
            difficulty="normal",
            output_dir=output_dir,
            input_signature="evaluation-signature",
            config=self.config,
            force=False,
        )
        forced = evaluate_candidate_reports(
            section_analysis=section_analysis,
            analysis_path=self.analysis_path,
            candidates_root=candidates_root,
            difficulty="normal",
            output_dir=output_dir,
            input_signature="evaluation-signature",
            config=self.config,
            force=True,
        )

        self.assertEqual(first.regenerated_count, 1)
        self.assertEqual(second.reused_count, 1)
        self.assertEqual(forced.regenerated_count, 1)
        self.assertEqual(len(first.reports[0].sections), len(section_analysis.sections))

    def test_dynamic_programming_selector_can_reject_greedy_patchwork(self) -> None:
        sections = [
          SongSection(1, 0, 6000, 6000, "verse-like", 0.7, 0.4, "steady", 1.0, 1.0, 0.3, 1, "medium"),
          SongSection(2, 6000, 12000, 6000, "chorus-like", 0.8, 0.72, "steady", 1.4, 1.6, 0.6, 2, "high"),
        ]
        candidate_a = make_candidate_report(
            candidate_index=1,
            section_scores=[93.0, 91.0],
            entry_positions=[(140, 120), (180, 150)],
            exit_positions=[(180, 150), (220, 170)],
        )
        candidate_b = make_candidate_report(
            candidate_index=2,
            section_scores=[90.0, 92.0],
            entry_positions=[(140, 120), (470, 360)],
            exit_positions=[(180, 150), (500, 360)],
        )

        selections = select_section_sources(
            sections=sections,
            candidate_reports=[candidate_a, candidate_b],
            config=self.config.selection,
        )

        self.assertEqual([selection.source_candidate for selection in selections], [1, 1])

    def test_transition_analyzer_flags_speed_violations(self) -> None:
        left_section = SongSection(1, 0, 6000, 6000, "verse-like", 0.7, 0.4, "steady", 1.0, 1.0, 0.3, 1, "medium")
        right_section = SongSection(2, 6000, 12000, 6000, "chorus-like", 0.8, 0.72, "steady", 1.4, 1.6, 0.6, 2, "high")
        transition = analyze_transition(
            boundary_index=1,
            left_section=left_section,
            right_section=right_section,
            from_candidate=1,
            to_candidate=2,
            left_objects=[MapObject(1, 20, 20, 5900)],
            right_objects=[MapObject(2, 500, 360, 6000)],
            preset=__import__("tools.map_generator.config", fromlist=["DIFFICULTY_PRESETS"]).DIFFICULTY_PRESETS["normal"],
        )

        self.assertIn("excessive-cursor-speed", transition.issues)
        self.assertIn(transition.classification, {"unsafe", "critical"})

    def test_small_hybrid_assembly_keeps_sequential_ids_and_source_maps_unchanged(self) -> None:
        sections_path = self.public_root / "sections" / "test-song-sections.json"
        sections_result = analyze_sections(
            audio_path=self.audio_path,
            analysis_path=self.analysis_path,
            output_path=sections_path,
            project_root=self.project_root,
            config=self.config,
            force=True,
        )
        candidates_root = self.public_root / "candidates" / "test-song" / "normal"
        candidate_one_path = write_candidate_directory(
            candidates_root,
            1,
            make_candidate_map(1, 120),
        )
        write_candidate_directory(candidates_root, 2, make_candidate_map(2, 340))
        original_candidate_json = candidate_one_path.read_text(encoding="utf-8")
        section_reports_dir = self.public_root / "section-reports" / "test-song" / "normal"
        evaluate_candidate_sections(
            sections_path=sections_path,
            analysis_path=self.analysis_path,
            candidates_root=candidates_root,
            difficulty="normal",
            output_dir=section_reports_dir,
            config=self.config,
            force=True,
        )
        result = assemble_hybrid(
            song_slug="test-song",
            title="Test Song",
            artist="Unit Test",
            audio_path=self.audio_path,
            analysis_path=self.analysis_path,
            sections_path=sections_path,
            section_reports_dir=section_reports_dir,
            candidates_root=candidates_root,
            difficulty="normal",
            output_map=self.public_root / "maps" / "hybrid" / "test-song-normal.json",
            output_report=self.public_root / "reports" / "hybrid" / "test-song-normal-report.json",
            assembly_report_path=self.public_root / "hybrids" / "test-song-normal-assembly.json",
            transition_log_path=self.public_root / "hybrids" / "test-song-normal-transitions.json",
            project_root=self.project_root,
            config=self.config,
        )

        hybrid_map = json.loads(
            (self.public_root / "maps" / "hybrid" / "test-song-normal.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [item["id"] for item in hybrid_map["objects"]],
            list(range(1, len(hybrid_map["objects"]) + 1)),
        )
        self.assertEqual(candidate_one_path.read_text(encoding="utf-8"), original_candidate_json)
        self.assertTrue(result.assembly_report.valid)
        self.assertTrue(result.assembly_report.playable)
        self.assertTrue(result.assembly_report.scores.overall_hybrid_score <= 100.0)


def make_analysis_json() -> dict[str, object]:
    return {
        "version": 1,
        "audio": {
            "filename": "test-song.mp3",
            "durationMs": 12000,
            "sampleRate": 22050,
        },
        "rhythm": {
            "bpm": 120.0,
            "offsetMs": 0,
            "beats": [
                {"timeMs": time_ms, "strength": 0.9 if time_ms % 2000 == 0 else 0.6}
                for time_ms in range(0, 12001, 1000)
            ],
            "onsets": [
                {"timeMs": time_ms, "strength": 0.8 if time_ms % 2000 == 0 else 0.55}
                for time_ms in range(500, 11501, 1000)
            ],
        },
        "energy": {
            "frames": [
                {"timeMs": 0, "value": 0.24},
                {"timeMs": 1000, "value": 0.26},
                {"timeMs": 2000, "value": 0.28},
                {"timeMs": 3000, "value": 0.30},
                {"timeMs": 4000, "value": 0.34},
                {"timeMs": 5000, "value": 0.39},
                {"timeMs": 6000, "value": 0.68},
                {"timeMs": 7000, "value": 0.73},
                {"timeMs": 8000, "value": 0.76},
                {"timeMs": 9000, "value": 0.74},
                {"timeMs": 10000, "value": 0.72},
                {"timeMs": 11000, "value": 0.68},
            ],
            "quietRegions": [{"startMs": 0, "endMs": 2500, "averageValue": 0.25}],
            "highEnergyRegions": [{"startMs": 6000, "endMs": 11000, "averageValue": 0.72}],
        },
    }


def make_candidate_map(candidate_index: int, x_offset: int) -> dict[str, object]:
    return {
        "title": "Test Song",
        "artist": "Unit Test",
        "audio": "/audio/test-song.mp3",
        "approachTime": 950,
        "circleRadius": 40,
        "objects": [
            {"id": 1, "type": "circle", "x": x_offset, "y": 120, "time": 1000},
            {"id": 2, "type": "circle", "x": x_offset + 40, "y": 140, "time": 2000},
            {"id": 3, "type": "circle", "x": x_offset + 80, "y": 160, "time": 3000},
            {"id": 4, "type": "circle", "x": x_offset + 120, "y": 180, "time": 4000},
            {"id": 5, "type": "circle", "x": x_offset + 160, "y": 200, "time": 5000},
            {"id": 6, "type": "circle", "x": x_offset + 140, "y": 220, "time": 6500},
            {"id": 7, "type": "circle", "x": x_offset + 180, "y": 240, "time": 7500},
            {"id": 8, "type": "circle", "x": x_offset + 120, "y": 260, "time": 8500},
            {"id": 9, "type": "circle", "x": x_offset + 160, "y": 280, "time": 9500},
            {"id": 10, "type": "circle", "x": x_offset + 200, "y": 300, "time": 10500},
        ],
    }


def write_candidate_directory(
    candidates_root: Path,
    candidate_index: int,
    improved_map: dict[str, object],
) -> Path:
    candidate_dir = candidates_root / f"candidate-{candidate_index:03d}"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    improved_map_path = candidate_dir / "improved-map.json"
    improved_map_path.write_text(json.dumps(improved_map, indent=2), encoding="utf-8")
    (candidate_dir / "candidate-summary.json").write_text(
        json.dumps(
            {
                "version": 1,
                "candidate": {"index": candidate_index},
                "status": {
                    "valid": True,
                    "playable": True,
                    "eligible": True,
                    "rejectionReasons": [],
                },
                "scores": {
                    "qualityScore": 88.0 + candidate_index,
                    "improvedOverall": 88.0 + candidate_index,
                    "stabilityScore": 76.0,
                },
                "stability": {"score": 76.0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return improved_map_path


def make_candidate_report(
    *,
    candidate_index: int,
    section_scores: list[float],
    entry_positions: list[tuple[int, int]],
    exit_positions: list[tuple[int, int]],
) -> CandidateSectionReport:
    sections: list[CandidateSectionEvaluation] = []
    for index, score in enumerate(section_scores, start=1):
        sections.append(
            CandidateSectionEvaluation(
                section_id=index,
                start_ms=(index - 1) * 6000,
                end_ms=index * 6000,
                label="verse-like" if index == 1 else "chorus-like",
                source_candidate=candidate_index,
                scores=SectionScores(
                    structural=96.0,
                    timing=94.0,
                    rhythm=93.0,
                    movement=92.0,
                    readability=95.0,
                    spatial_balance=90.0,
                    repetition=88.0,
                    density_consistency=89.0,
                    difficulty_consistency=90.0,
                    transition_readiness=91.0,
                    overall=score,
                ),
                metrics=SectionMetrics(
                    object_count=5,
                    objects_per_second=0.83,
                    average_object_gap_ms=1000.0,
                    minimum_object_gap_ms=1000,
                    maximum_object_gap_ms=1000,
                    average_jump_distance=100.0,
                    maximum_jump_distance=120.0,
                    average_cursor_speed=180.0,
                    maximum_cursor_speed=240.0,
                    timing_confidence=0.92,
                    beat_alignment=0.95,
                    onset_alignment=0.93,
                    spatial_coverage=0.5,
                    center_usage=0.35,
                    edge_usage=0.18,
                    repetition_count=0,
                    stacking_count=0,
                    warning_count=0,
                    error_count=0,
                    local_difficulty_behavior="balanced",
                    energy_to_density_ratio=0.42,
                    entry_direction_deg=10.0,
                    exit_direction_deg=28.0,
                ),
                issues=[],
                entry_state=SectionState(
                    object_id=index,
                    time_ms=(index - 1) * 6000 + 400,
                    x=entry_positions[index - 1][0],
                    y=entry_positions[index - 1][1],
                    direction_deg=12.0,
                    cursor_speed_pps=160.0,
                    gap_ms=1000,
                    density=0.83,
                    region="r2c2",
                ),
                exit_state=SectionState(
                    object_id=index * 10,
                    time_ms=index * 6000 - 400,
                    x=exit_positions[index - 1][0],
                    y=exit_positions[index - 1][1],
                    direction_deg=25.0,
                    cursor_speed_pps=175.0,
                    gap_ms=1000,
                    density=0.83,
                    region="r2c3",
                ),
            )
        )
    return CandidateSectionReport(
        version=1,
        candidate_index=candidate_index,
        difficulty="normal",
        input_signature=f"candidate-{candidate_index}",
        status={"eligible": True},
        summary={"candidateQuality": 90.0, "candidateStability": 80.0},
        sections=sections,
    )


if __name__ == "__main__":
    unittest.main()
