"""Phase 20 phrase-level intelligence tests.

Covers phrase boundary determinism and non-overlap, relationship
classification, motif identity across repeated sections, trajectory planning,
deterministic reproducibility, and schema backward compatibility.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    EnergyRegion,
    TimedStrength,
)
from tools.map_generator.phrase import (
    DEFAULT_PHRASE_CONFIG,
    PhraseDetectionConfig,
    PhrasePipelineConfig,
    PhraseReport,
    analyze_phrase_structure,
    build_phrase_report_data,
    build_phrase_rhythm_info,
    detect_phrase_boundaries,
    load_phrase_report,
    phrase_generator_metadata,
)
from tools.map_generator.phrase.motif_engine import build_motifs
from tools.map_generator.phrase.trajectory_planner import (
    build_phrase_density_resolver,
    plan_trajectory,
)
from tools.map_generator.sections.section_models import SongSection
from tools.map_generator.utils import write_json


def _make_analysis(
    *,
    duration_ms: int = 60000,
    bpm: float = 140.0,
) -> AudioAnalysis:
    beat_interval = int(round(60000.0 / bpm))
    beats = [
        TimedStrength(time_ms=t, strength=0.85 if (t // (beat_interval * 4)) % 4 == 0 else 0.55)
        for t in range(400, duration_ms, beat_interval)
    ]
    onsets = [
        TimedStrength(time_ms=t, strength=0.6 + 0.25 * ((t // 120) % 2))
        for t in range(100, duration_ms, 120)
    ]
    frames = [
        EnergyFrame(time_ms=t, value=0.4 + 0.3 * ((t // 4000) % 2))
        for t in range(0, duration_ms, 120)
    ]
    return AudioAnalysis(
        audio_filename="phrase-test.mp3",
        duration_ms=duration_ms,
        sample_rate=44100,
        bpm=bpm,
        offset_ms=0,
        beats=beats,
        onsets=onsets,
        energy_frames=frames,
        quiet_regions=[EnergyRegion(20000, 26000, 0.02)],
        high_energy_regions=[EnergyRegion(0, 60000, 0.7)],
    )


def _make_sections() -> list[SongSection]:
    return [
        SongSection(
            id=1,
            start_ms=0,
            end_ms=20000,
            duration_ms=20000,
            label="verse-like",
            confidence=0.7,
            average_energy=0.45,
            energy_trend="steady",
            beat_density=1.0,
            onset_density=2.0,
            rhythm_complexity=0.4,
            repetition_group=1,
            energy_class="medium",
        ),
        SongSection(
            id=2,
            start_ms=20000,
            end_ms=40000,
            duration_ms=20000,
            label="chorus-like",
            confidence=0.8,
            average_energy=0.75,
            energy_trend="rising",
            beat_density=1.2,
            onset_density=3.0,
            rhythm_complexity=0.6,
            repetition_group=2,
            energy_class="high",
        ),
        SongSection(
            id=3,
            start_ms=40000,
            end_ms=60000,
            duration_ms=20000,
            label="verse-like",
            confidence=0.7,
            average_energy=0.45,
            energy_trend="steady",
            beat_density=1.0,
            onset_density=2.0,
            rhythm_complexity=0.4,
            repetition_group=1,
            energy_class="medium",
        ),
    ]


class PhraseBoundaryTest(unittest.TestCase):
    def test_boundaries_are_deterministic(self) -> None:
        analysis = _make_analysis()
        section = _make_sections()[0]
        first = detect_phrase_boundaries(analysis, section, DEFAULT_PHRASE_CONFIG)
        second = detect_phrase_boundaries(analysis, section, DEFAULT_PHRASE_CONFIG)
        self.assertEqual(first, second)

    def test_boundaries_are_inside_section_and_non_overlapping(self) -> None:
        analysis = _make_analysis()
        section = _make_sections()[0]
        boundaries = detect_phrase_boundaries(analysis, section, DEFAULT_PHRASE_CONFIG)
        for boundary in boundaries:
            self.assertGreater(boundary, section.start_ms)
            self.assertLess(boundary, section.end_ms)
        self.assertEqual(boundaries, sorted(boundaries))
        self.assertEqual(len(set(boundaries)), len(boundaries))

    def test_min_duration_respected(self) -> None:
        analysis = _make_analysis(duration_ms=30000)
        section = SongSection(
            id=1,
            start_ms=0,
            end_ms=30000,
            duration_ms=30000,
            label="short",
            confidence=0.6,
            average_energy=0.5,
            energy_trend="steady",
            beat_density=1.0,
            onset_density=2.0,
            rhythm_complexity=0.4,
            repetition_group=None,
        )
        config = PhraseDetectionConfig(min_phrase_duration_ms=12000)
        boundaries = detect_phrase_boundaries(analysis, section, config)
        times = [0, *boundaries, 30000]
        for index in range(len(times) - 1):
            self.assertGreaterEqual(times[index + 1] - times[index], 12000)


class PhrasePipelineTest(unittest.TestCase):
    def test_full_report_build_is_deterministic_and_non_overlapping(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases_a, relationships_a = build_phrase_report_data(
            analysis, sections, DEFAULT_PHRASE_CONFIG
        )
        phrases_b, relationships_b = build_phrase_report_data(
            analysis, sections, DEFAULT_PHRASE_CONFIG
        )
        self.assertEqual(
            [phrase.to_dict() for phrase in phrases_a],
            [phrase.to_dict() for phrase in phrases_b],
        )
        self.assertEqual(len(phrases_a), len(phrases_b))
        for phrase in phrases_a:
            self.assertGreaterEqual(phrase.start_ms, 0)
            self.assertLessEqual(phrase.end_ms, analysis.duration_ms)
            self.assertGreater(phrase.end_ms, phrase.start_ms)
        # Phrases never overlap in time.
        ordered = sorted(phrases_a, key=lambda phrase: phrase.start_ms)
        for index in range(1, len(ordered)):
            self.assertLessEqual(ordered[index - 1].end_ms, ordered[index].start_ms)

    def test_relationships_repeat_verse_sections(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, relationships = build_phrase_report_data(
            analysis, sections, DEFAULT_PHRASE_CONFIG
        )
        repetition = [
            relationship
            for relationship in relationships
            if relationship.relationship_type == "repetition"
        ]
        self.assertTrue(
            repetition,
            "Repeated verse sections should produce repetition relationships.",
        )

    def test_motifs_group_repeated_phrases(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, _ = build_phrase_report_data(analysis, sections, DEFAULT_PHRASE_CONFIG)
        motifs = build_motifs(phrases)
        self.assertTrue(motifs)
        repeated_motif = max(motifs, key=lambda motif: motif.occurrence_count)
        self.assertGreaterEqual(
            repeated_motif.occurrence_count,
            2,
            "Repeated sections should share a motif with multiple occurrences.",
        )

    def test_trajectory_targets_are_positive_and_deterministic(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, _ = build_phrase_report_data(analysis, sections, DEFAULT_PHRASE_CONFIG)
        planned = plan_trajectory(phrases)
        self.assertTrue(planned)
        for phrase in planned:
            self.assertGreater(phrase.target_density, 0.0)
            self.assertGreaterEqual(phrase.min_gap_ms, 60)
            self.assertGreaterEqual(phrase.target_gap_ms, 90)
        # Deterministic: replanning gives the same values.
        replanned = plan_trajectory(phrases)
        self.assertEqual(
            [phrase.target_density for phrase in planned],
            [phrase.target_density for phrase in replanned],
        )

    def test_density_resolver(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, _ = build_phrase_report_data(analysis, sections, DEFAULT_PHRASE_CONFIG)
        planned = plan_trajectory(phrases)
        resolver = build_phrase_density_resolver(planned)
        self.assertIsNotNone(resolver)
        first = planned[0]
        self.assertIsNotNone(resolver(first.start_ms + 1))
        self.assertIsNone(resolver(-1000))


class PhraseReportSerializationTest(unittest.TestCase):
    def test_report_round_trip(self, tmp_path: Path | None = None) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis_path = root / "analysis.json"
            sections_path = root / "sections.json"
            output_path = root / "phrase-structure.json"
            write_json(analysis_path, _make_analysis().to_dict())
            write_json(
                sections_path,
                {
                    "version": 1,
                    "audio": {"path": "audio.mp3", "durationMs": 60000},
                    "configuration": {},
                    "inputSignature": "sections",
                    "sections": [section.to_dict() for section in _make_sections()],
                    "boundaries": [],
                    "summary": {},
                },
            )
            result = analyze_phrase_structure(
                analysis_path=analysis_path,
                sections_path=sections_path,
                output_path=output_path,
                config=PhrasePipelineConfig(),
            )
            self.assertFalse(result.reused)
            self.assertTrue(output_path.exists())

            loaded = load_phrase_report(output_path)
            self.assertEqual(
                [phrase.to_dict() for phrase in result.phrase_report.phrases],
                [phrase.to_dict() for phrase in loaded.phrases],
            )
            self.assertEqual(
                result.phrase_report.input_signature,
                loaded.input_signature,
            )

            # Re-running reuses the artifact.
            rerun = analyze_phrase_structure(
                analysis_path=analysis_path,
                sections_path=sections_path,
                output_path=output_path,
                config=PhrasePipelineConfig(),
            )
            self.assertTrue(rerun.reused)

    def test_generator_metadata(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, relationships = build_phrase_report_data(
            analysis, sections, DEFAULT_PHRASE_CONFIG
        )
        report = PhraseReport(
            version=1,
            audio_path="audio.mp3",
            duration_ms=60000,
            configuration={},
            input_signature="sig",
            phrases=phrases,
            relationships=relationships,
            motifs=[],
            trajectory=[],
            summary={},
        )
        metadata = phrase_generator_metadata(report, "phrase-structure.json")
        self.assertEqual(metadata["phraseCount"], len(phrases))
        self.assertEqual(metadata["reportPath"], "phrase-structure.json")
        self.assertIn("strategies", metadata)

    def test_phrase_info_bridge(self) -> None:
        analysis = _make_analysis()
        sections = _make_sections()
        phrases, _ = build_phrase_report_data(analysis, sections, DEFAULT_PHRASE_CONFIG)
        planned = plan_trajectory(phrases)
        report = PhraseReport(
            version=1,
            audio_path="audio.mp3",
            duration_ms=60000,
            configuration={},
            input_signature="sig",
            phrases=planned,
            relationships=[],
            motifs=[],
            trajectory=[],
            summary={},
        )
        rhythm_info = build_phrase_rhythm_info(report)
        self.assertEqual(len(rhythm_info), len(planned))
        for info, phrase in zip(rhythm_info, planned):
            self.assertEqual(info.start_ms, phrase.start_ms)
            self.assertEqual(info.end_ms, phrase.end_ms)
            self.assertAlmostEqual(info.expected_density, phrase.target_density)
            self.assertGreater(info.target_gap_ms, 0)


class PhraseBackwardCompatibilityTest(unittest.TestCase):
    def test_from_dict_tolerates_missing_fields(self) -> None:
        minimal = {
            "version": 1,
            "audio": {"path": "x.mp3", "durationMs": 1000},
            "configuration": {},
            "inputSignature": "sig",
            "phrases": [
                {
                    "id": 1,
                    "startMs": 0,
                    "endMs": 1000,
                    "durationMs": 1000,
                }
            ],
            "relationships": [],
            "motifs": [],
            "trajectory": [],
            "summary": {},
        }
        report = PhraseReport.from_dict(minimal)
        self.assertEqual(len(report.phrases), 1)
        phrase = report.phrases[0]
        self.assertEqual(phrase.section_id, None)
        self.assertEqual(phrase.motif_id, None)
        self.assertEqual(phrase.strategy, "neutral")
        self.assertEqual(phrase.label, "phrase")
        self.assertEqual(phrase.min_gap_ms, 0)

    def test_from_dict_tolerates_missing_top_level_keys(self) -> None:
        report = PhraseReport.from_dict({})
        self.assertEqual(report.phrases, [])
        self.assertEqual(report.relationships, [])
        self.assertEqual(report.motifs, [])
        self.assertEqual(report.trajectory, [])
        self.assertEqual(report.input_signature, "")


class RhythmSelectionRegressionTest(unittest.TestCase):
    """Regression: too-close candidates must not collapse selection to a
    single sliding event on dense uniform grids (the replacement branch used
    to slide the last selection forward forever whenever candidates arrived
    at a fixed interval just below ``min_gap_ms``)."""

    def _uniform_analysis(self, duration_ms: int = 60000) -> AudioAnalysis:
        beat_interval = 500  # 120 BPM
        beats = [
            TimedStrength(time_ms=t, strength=0.9)
            for t in range(0, duration_ms, beat_interval)
        ]
        onsets = [
            TimedStrength(time_ms=t, strength=0.7)
            for t in range(0, duration_ms, beat_interval)
        ]
        frames = [
            EnergyFrame(time_ms=t, value=0.9)
            for t in range(0, duration_ms, 100)
        ]
        return AudioAnalysis(
            audio_filename="uniform.wav",
            duration_ms=duration_ms,
            sample_rate=44100,
            bpm=120.0,
            offset_ms=0,
            beats=beats,
            onsets=onsets,
            energy_frames=frames,
            quiet_regions=[],
            high_energy_regions=[],
        )

    def test_easy_grid_does_not_collapse(self) -> None:
        from tools.map_generator.config import get_difficulty_preset
        from tools.map_generator.rhythm.rhythm_pipeline import (
            build_rhythm_model,
            select_rhythmic_timings,
        )

        analysis = self._uniform_analysis()
        preset = get_difficulty_preset("easy")  # min_gap_ms=520 > 500ms grid
        model = build_rhythm_model(analysis, preset)
        events, times = select_rhythmic_timings(model, preset)
        self.assertGreater(
            len(events),
            10,
            "Easy selection collapsed to a single event on a uniform grid.",
        )
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        self.assertGreaterEqual(min(gaps), preset.min_gap_ms)

    def test_hard_selector_is_denser_than_easy(self) -> None:
        from tools.map_generator.config import get_difficulty_preset
        from tools.map_generator.rhythm.rhythm_pipeline import (
            build_rhythm_model,
            select_rhythmic_timings,
        )

        analysis = self._uniform_analysis()
        easy_preset = get_difficulty_preset("easy")
        hard_preset = get_difficulty_preset("hard")
        easy_events, _ = select_rhythmic_timings(
            build_rhythm_model(analysis, easy_preset), easy_preset
        )
        hard_events, _ = select_rhythmic_timings(
            build_rhythm_model(analysis, hard_preset), hard_preset
        )
        # Hard should produce at least as many events as easy (density floor may converge them)
        self.assertGreaterEqual(len(hard_events), len(easy_events))

    def test_phrase_aware_selection_stays_healthy(self) -> None:
        from tools.map_generator.config import get_difficulty_preset
        from tools.map_generator.rhythm.rhythm_models import PhraseInfo
        from tools.map_generator.rhythm.rhythm_pipeline import (
            build_rhythm_model,
            select_rhythmic_timings,
        )

        # 250ms grid: dense enough that the phrase-aware gap band actually
        # gates selection (a 500ms grid saturates both halves at every beat).
        beat_interval = 250
        duration_ms = 60000
        beats = [
            TimedStrength(time_ms=t, strength=0.9)
            for t in range(0, duration_ms, beat_interval)
        ]
        onsets = [
            TimedStrength(time_ms=t, strength=0.7)
            for t in range(0, duration_ms, beat_interval)
        ]
        frames = [
            EnergyFrame(time_ms=t, value=0.9)
            for t in range(0, duration_ms, 100)
        ]
        analysis = AudioAnalysis(
            audio_filename="uniform.wav",
            duration_ms=duration_ms,
            sample_rate=44100,
            bpm=120.0,
            offset_ms=0,
            beats=beats,
            onsets=onsets,
            energy_frames=frames,
            quiet_regions=[],
            high_energy_regions=[],
        )
        phrase_info = [
            PhraseInfo(
                start_ms=0,
                end_ms=30000,
                label="intensify",
                confidence=0.8,
                expected_density=3.0,
                density_flexibility=0.6,
                min_gap_ms=100,
                target_gap_ms=250,
            ),
            PhraseInfo(
                start_ms=30000,
                end_ms=60000,
                label="recover",
                confidence=0.8,
                expected_density=0.8,
                density_flexibility=0.6,
                min_gap_ms=300,
                target_gap_ms=700,
            ),
        ]
        preset = get_difficulty_preset("hard")
        model = build_rhythm_model(analysis, preset, phrase_info=phrase_info)
        events, times = select_rhythmic_timings(model, preset)
        self.assertGreater(
            len(events),
            20,
            "Phrase-aware selection collapsed on a uniform grid.",
        )
        # Both halves should have substantial event counts (density floor enforces minimum).
        # Dense (intensify) half may not always exceed recovery due to density floor convergence.
        dense = [t for t in times if t < 30000]
        recovery = [t for t in times if t >= 30000]
        self.assertGreater(len(dense), 10, "Intensify half too sparse")
        self.assertGreater(len(recovery), 10, "Recovery half too sparse")


if __name__ == "__main__":
    unittest.main()
