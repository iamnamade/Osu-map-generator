from __future__ import annotations

import unittest

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    EnergyRegion,
    GeneratedCircleHitObject,
    TimedStrength,
)
from tools.map_generator.sliders.slider_models import SustainedAnalysis
from tools.map_generator.spinners.spinner_analysis import (
    build_spinner_context,
    classify_region,
    region_musical_score,
)
from tools.map_generator.spinners.spinner_decision import (
    calculate_fatigue_profile,
    evaluate_spinner_region,
    validate_spinner,
)
from tools.map_generator.spinners.spinner_models import SpinnerConfig
from tools.map_generator.spinners.spinner_duration import compute_spinner_window
from tools.map_generator.spinners.spinner_pipeline import (
    DEFAULT_SPINNER_CONFIG,
    SpinnerPipelineConfig,
    process_spinners,
)
from tools.map_generator.spinners.spinner_scorer import score_spinner_candidate


def make_analysis(
    *,
    duration_ms: int = 30_000,
    bpm: float = 120.0,
    quiet_regions: list[tuple[int, int]] | None = None,
    high_energy_regions: list[tuple[int, int]] | None = None,
    onsets: list[int] | None = None,
    default_energy: float = 0.3,
) -> AudioAnalysis:
    quiet_regions = quiet_regions or []
    high_energy_regions = high_energy_regions or []
    onsets = onsets or []
    frames: list[EnergyFrame] = []

    for time_ms in range(0, duration_ms + 1, 100):
        energy_value = default_energy
        for start, end in high_energy_regions:
            if start <= time_ms <= end:
                energy_value = 0.9
        for start, end in quiet_regions:
            if start <= time_ms <= end:
                energy_value = 0.08
        frames.append(EnergyFrame(time_ms=time_ms, value=energy_value))

    return AudioAnalysis(
        audio_filename="test-song.mp3",
        duration_ms=duration_ms,
        sample_rate=22_050,
        bpm=bpm,
        offset_ms=0,
        beats=[TimedStrength(time_ms=time_ms, strength=1.0) for time_ms in onsets],
        onsets=[TimedStrength(time_ms=time_ms, strength=1.0) for time_ms in onsets],
        energy_frames=frames,
        quiet_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=0.08)
            for start, end in quiet_regions
        ],
        high_energy_regions=[
            EnergyRegion(start_ms=start, end_ms=end, average_value=0.9)
            for start, end in high_energy_regions
        ],
    )


def make_circle(object_id: int, time_ms: int) -> GeneratedCircleHitObject:
    return GeneratedCircleHitObject(
        id=object_id,
        type="circle",
        x=128,
        y=128,
        time=time_ms,
    )


class SpinnerRegionClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        # A song with a quiet break in the middle and a quiet intro/outro.
        # default_energy=0.3 keeps the intro region (0-1500ms) below the 0.4
        # energy threshold so it classifies as "intro".
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000), (25000, 29000)],
            onsets=[1000, 1100, 9000, 9100, 9200],
            default_energy=0.3,
        )
        self.context = build_spinner_context(analysis=self.analysis)

    def test_quiet_break_classified_as_break(self) -> None:
        region_type = classify_region(self.context, 3000, 6000)
        self.assertEqual(region_type, "break")

    def test_intro_region_classified_as_intro(self) -> None:
        region_type = classify_region(self.context, 0, 1500)
        self.assertEqual(region_type, "intro")

    def test_outro_region_classified_as_outro(self) -> None:
        region_type = classify_region(self.context, 26000, 28500)
        self.assertEqual(region_type, "outro")

    def test_dense_rhythm_region_never_classified_as_spinner_friendly(self) -> None:
        dense_analysis = make_analysis(
            duration_ms=20_000,
            onsets=list(range(1000, 12000, 200)),
            high_energy_regions=[(1000, 12000)],
            default_energy=0.7,
        )
        context = build_spinner_context(analysis=dense_analysis)
        region_type = classify_region(context, 2000, 6000)
        self.assertIn(region_type, ("dense", "unknown"))

    def test_musical_score_is_bounded(self) -> None:
        score = region_musical_score(self.context, "break", 3000, 6000)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


class SpinnerDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000)],
            onsets=[1000, 1100],
            default_energy=0.4,
        )
        self.context = build_spinner_context(analysis=self.analysis)
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_suitable_gap_produces_candidate(self) -> None:
        candidate = evaluate_spinner_region(
            gap_start_ms=3000,
            gap_end_ms=6500,
            context=self.context,
            preset=self.preset,
        )
        self.assertIsNotNone(candidate)
        if candidate is not None:
            self.assertEqual(candidate.region_type, "break")
            self.assertGreaterEqual(candidate.musical_score, 45.0)

    def test_tiny_gap_never_produces_candidate(self) -> None:
        candidate = evaluate_spinner_region(
            gap_start_ms=3000,
            gap_end_ms=3400,
            context=self.context,
            preset=self.preset,
        )
        self.assertIsNone(candidate)

    def test_dense_gap_never_produces_candidate(self) -> None:
        dense_analysis = make_analysis(
            duration_ms=20_000,
            onsets=list(range(1000, 12000, 150)),
            high_energy_regions=[(1000, 12000)],
            default_energy=0.7,
        )
        context = build_spinner_context(analysis=dense_analysis)
        candidate = evaluate_spinner_region(
            gap_start_ms=2000,
            gap_end_ms=6000,
            context=context,
            preset=self.preset,
        )
        self.assertIsNone(candidate)


class SpinnerDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000)],
            onsets=[1000, 1100],
            default_energy=0.4,
        )
        self.context = build_spinner_context(analysis=self.analysis)
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_window_respects_gap_and_recovery(self) -> None:
        window = compute_spinner_window(
            gap_start_ms=3000,
            gap_end_ms=6000,
            context=self.context,
            preset=self.preset,
        )
        self.assertIsNotNone(window)
        if window is not None:
            start_ms, end_ms = window
            self.assertGreater(end_ms, start_ms)
            self.assertGreaterEqual(end_ms - start_ms, self.preset.spinner_min_duration_ms)
            self.assertLessEqual(end_ms, 6000 - self.preset.spinner_recovery_after_ms)
            self.assertGreaterEqual(start_ms, 3000 + self.preset.spinner_entry_buffer_ms)

    def test_gap_too_small_returns_none(self) -> None:
        window = compute_spinner_window(
            gap_start_ms=3000,
            gap_end_ms=3600,
            context=self.context,
            preset=self.preset,
        )
        self.assertIsNone(window)

    def test_difficulty_scaling_shapes_duration(self) -> None:
        easy_window = compute_spinner_window(
            gap_start_ms=3000,
            gap_end_ms=6000,
            context=self.context,
            preset=DIFFICULTY_PRESETS["easy"],
        )
        hard_window = compute_spinner_window(
            gap_start_ms=3000,
            gap_end_ms=6000,
            context=self.context,
            preset=DIFFICULTY_PRESETS["hard"],
        )
        if easy_window is not None and hard_window is not None:
            self.assertLessEqual(
                easy_window[1] - easy_window[0],
                hard_window[1] - hard_window[0],
            )


class SpinnerPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000), (14000, 19000)],
            onsets=[1000, 1100, 8000, 8100, 20000, 20100, 22000],
            default_energy=0.42,
        )
        self.sustained = SustainedAnalysis(
            sustained_regions=[
                {"startMs": 2000, "endMs": 7000, "averageScore": 0.7},
                {"startMs": 14000, "endMs": 19000, "averageScore": 0.6},
            ],
            sustained_frames=[
                {"timeMs": time_ms, "sustainedScore": 0.6 if 2000 <= time_ms <= 7000 else 0.2}
                for time_ms in range(2000, 19001, 500)
            ],
            average_sustained_energy=0.4,
            sustained_ratio=0.25,
        )
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_process_spinners_inserts_spinners_into_gaps(self) -> None:
        objects = [
            make_circle(1, 1000),
            make_circle(2, 8000),
            make_circle(3, 20000),
        ]
        result_objects, diagnostics = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            spinner_config=DEFAULT_SPINNER_CONFIG,
        )

        spinners = [item for item in result_objects if item.type == "spinner"]
        self.assertGreater(len(spinners), 0)
        self.assertEqual(diagnostics.accepted_spinners, len(spinners))
        self.assertEqual(diagnostics.accepted_spinners + diagnostics.rejected_spinners, diagnostics.total_candidates)

        # Spinners must never overlap existing objects.
        for spinner in spinners:
            self.assertGreater(spinner.time, 1000)
            for obj in objects:
                self.assertNotIn(
                    obj.time,
                    range(spinner.time, spinner.end_time + 1),
                )

        # Ids must remain sequential.
        self.assertEqual(
            [item.id for item in result_objects],
            list(range(1, len(result_objects) + 1)),
        )

    def test_process_spinners_is_deterministic(self) -> None:
        objects = [
            make_circle(1, 1000),
            make_circle(2, 8000),
            make_circle(3, 20000),
        ]
        first, first_diag = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=7,
            sustained=self.sustained,
        )
        second, second_diag = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=7,
            sustained=self.sustained,
        )
        self.assertEqual(
            [item.to_dict() for item in first],
            [item.to_dict() for item in second],
        )
        self.assertEqual(first_diag.to_dict(), second_diag.to_dict())

    def test_spinner_disabled_returns_unchanged(self) -> None:
        objects = [make_circle(1, 1000), make_circle(2, 8000)]
        result_objects, diagnostics = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            spinner_config=SpinnerPipelineConfig(spinner_enabled=False),
        )
        self.assertEqual(result_objects, objects)
        self.assertEqual(diagnostics.accepted_spinners, 0)

    def test_quality_threshold_can_reject_spinners(self) -> None:
        objects = [
            make_circle(1, 1000),
            make_circle(2, 8000),
            make_circle(3, 20000),
        ]
        _, strict_diagnostics = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            spinner_config=SpinnerPipelineConfig(quality_threshold=99.0),
        )
        self.assertEqual(strict_diagnostics.accepted_spinners, 0)
        self.assertGreater(strict_diagnostics.rejected_spinners, 0)

    def test_diagnostics_summarize_durations_and_quality(self) -> None:
        objects = [
            make_circle(1, 1000),
            make_circle(2, 8000),
            make_circle(3, 20000),
        ]
        _, diagnostics = process_spinners(
            objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
        )
        payload = diagnostics.to_dict()
        self.assertGreater(payload["longestDurationMs"], 0)
        self.assertGreater(payload["shortestDurationMs"], 0)
        self.assertGreaterEqual(payload["averageDurationMs"], 0)
        self.assertGreaterEqual(payload["averageQualityScore"], 0)


class SpinnerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SpinnerConfig(min_duration_ms=800, post_clearance_ms=400, max_spinners_per_map=5)

    def _candidate(self, start_ms: int = 3000, end_ms: int = 5000) -> Any:
        from tools.map_generator.spinners.spinner_models import SpinnerCandidate
        return SpinnerCandidate(
            region_type="break",
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=end_ms - start_ms,
            musical_score=80.0,
            sustained_score=0.6,
            energy=0.2,
            onset_density=0.1,
            gap_before_ms=None,
            gap_after_ms=None,
            section_label="break-like",
            trigger_type="sustain",
            min_clearance_ms=400,
        )

    def test_valid_spinner_passes(self) -> None:
        self.assertTrue(validate_spinner(self._candidate(), 5800, self.config))

    def test_too_short_spinner_rejected(self) -> None:
        self.assertFalse(validate_spinner(self._candidate(start_ms=3000, end_ms=3400), 5800, self.config))

    def test_insufficient_post_clearance_rejected(self) -> None:
        self.assertFalse(validate_spinner(self._candidate(), 5100, self.config))

    def test_no_next_object_allowed(self) -> None:
        self.assertTrue(validate_spinner(self._candidate(), None, self.config))

    def test_higher_min_clearance_on_candidate_wins(self) -> None:
        candidate = self._candidate()
        candidate = candidate.__class__(
            region_type=candidate.region_type,
            start_ms=candidate.start_ms,
            end_ms=candidate.end_ms,
            duration_ms=candidate.duration_ms,
            musical_score=candidate.musical_score,
            sustained_score=candidate.sustained_score,
            energy=candidate.energy,
            onset_density=candidate.onset_density,
            gap_before_ms=candidate.gap_before_ms,
            gap_after_ms=candidate.gap_after_ms,
            section_label=candidate.section_label,
            trigger_type=candidate.trigger_type,
            min_clearance_ms=800,
        )
        # 600ms clearance is enough for config (400) but not the candidate (800).
        self.assertFalse(validate_spinner(candidate, 5600, self.config))


class FatigueCalculationTests(unittest.TestCase):
    def test_fatigue_normalizes_and_tracks_peak(self) -> None:
        timestamps = [1000.0, 1150.0, 1300.0, 5000.0]
        distances = [100.0, 200.0, 400.0, 50.0]
        profile = calculate_fatigue_profile(timestamps, distances, decay_lambda=0.001)
        self.assertEqual(len(profile.timestamps), 4)
        self.assertEqual(len(profile.fatigue_scores), 4)
        self.assertAlmostEqual(max(profile.fatigue_scores), 1.0, places=4)
        self.assertGreaterEqual(profile.peak_fatigue_time, 1150)
        self.assertLessEqual(profile.peak_fatigue_time, 1300)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in profile.fatigue_scores))

    def test_fatigue_decays_across_wide_gap(self) -> None:
        # Dense first burst, wide gap, then a gentle object: strain must decay.
        timestamps = [1000.0, 1150.0, 1300.0, 6000.0]
        distances = [200.0, 200.0, 200.0, 50.0]
        profile = calculate_fatigue_profile(timestamps, distances, decay_lambda=0.001)
        self.assertGreater(profile.fatigue_scores[2], profile.fatigue_scores[3])

    def test_mismatched_inputs_return_empty(self) -> None:
        profile = calculate_fatigue_profile([1000.0], [1.0, 2.0])
        self.assertEqual(profile.timestamps, [])
        profile = calculate_fatigue_profile([], [])
        self.assertEqual(profile.fatigue_scores, [])

    def test_fatigue_is_deterministic(self) -> None:
        timestamps = [1000.0, 1150.0, 1300.0, 1500.0]
        distances = [100.0, 200.0, 300.0, 150.0]
        first = calculate_fatigue_profile(timestamps, distances)
        second = calculate_fatigue_profile(timestamps, distances)
        self.assertEqual(first.to_dict(), second.to_dict())


class SpinnerScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000)],
            onsets=[1000, 1100],
            default_energy=0.4,
        )
        self.context = build_spinner_context(analysis=self.analysis)
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_well_supported_candidate_scores_high(self) -> None:
        candidate = evaluate_spinner_region(
            gap_start_ms=3000,
            gap_end_ms=6000,
            context=self.context,
            preset=self.preset,
        )
        self.assertIsNotNone(candidate)
        if candidate is None:
            return
        quality = score_spinner_candidate(
            candidate=candidate,
            context=self.context,
            preset=self.preset,
            previous_object_end_ms=2000,
            next_object_time_ms=7000,
        )
        self.assertGreater(quality.overall, 45.0)
        for value in (
            quality.musical_match,
            quality.timing_quality,
            quality.duration_score,
            quality.transition_quality,
            quality.difficulty_impact,
            quality.flow,
            quality.overall,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)


if __name__ == "__main__":
    unittest.main()
