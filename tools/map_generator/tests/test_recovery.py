"""Phase 22 — Spinner intelligence, recovery & fatigue, map dynamics tests."""

from __future__ import annotations

import unittest

from tools.map_generator.config import DIFFICULTY_PRESETS
from tools.map_generator.models import (
    AudioAnalysis,
    EnergyFrame,
    EnergyRegion,
    GeneratedCircleHitObject,
    GeneratedSliderHitObject,
    GeneratedSpinnerHitObject,
    TimedStrength,
)
from tools.map_generator.recovery import (
    analyze_density_harmony,
    compute_fatigue_profile,
    fatigue_at,
    plan_recovery_windows,
    post_spinner_clearance,
    spinner_guidelines,
)
from tools.map_generator.recovery.recovery_report import analyze_recovery_structure
from tools.map_generator.rhythm.rhythm_models import PhraseInfo
from tools.map_generator.sliders.slider_models import SustainedAnalysis
from tools.map_generator.spinners.spinner_analysis import (
    build_spinner_context,
    classify_trigger,
)
from tools.map_generator.spinners.spinner_pipeline import process_spinners


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


def make_circle(object_id: int, time_ms: int, x: int = 128, y: int = 128) -> GeneratedCircleHitObject:
    return GeneratedCircleHitObject(id=object_id, type="circle", x=x, y=y, time=time_ms)


def make_slider(object_id: int, time_ms: int) -> GeneratedSliderHitObject:
    return GeneratedSliderHitObject(
        id=object_id,
        type="slider",
        x=256,
        y=192,
        time=time_ms,
        end_time=time_ms + 400,
        path_type="bezier",
        control_points=[],
        repeats=1,
        pixel_length=120,
    )


def make_phrase(
    phrase_id: int,
    start_ms: int,
    end_ms: int,
    strategy: str,
) -> PhraseInfo:
    return PhraseInfo(
        start_ms=start_ms,
        end_ms=end_ms,
        label="chorus-like",
        confidence=0.9,
        expected_density=2.0,
        density_flexibility=0.5,
        min_gap_ms=200,
        target_gap_ms=400,
        strategy=strategy,
    )


class SpinnerGuidelineTests(unittest.TestCase):
    def test_guidelines_per_difficulty(self) -> None:
        easy = spinner_guidelines("easy")
        hard = spinner_guidelines("hard")
        insane = spinner_guidelines("insane")
        # Higher difficulty demands shorter spinner rests and less recovery.
        self.assertGreaterEqual(easy["min_duration_ms"], hard["min_duration_ms"])
        self.assertGreaterEqual(easy["post_clearance_ms"], hard["post_clearance_ms"])
        self.assertGreaterEqual(hard["min_duration_ms"], insane["min_duration_ms"])

    def test_unknown_difficulty_falls_back_to_normal(self) -> None:
        guidelines = spinner_guidelines("mystery-tier")
        self.assertEqual(guidelines, spinner_guidelines("normal"))


class TriggerClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000)],
            onsets=[1000, 1100],
            default_energy=0.3,
        )
        self.sustained = SustainedAnalysis(
            sustained_regions=[{"startMs": 2000, "endMs": 7000, "averageScore": 0.8}],
            sustained_frames=[
                {"timeMs": time_ms, "sustainedScore": 0.8}
                for time_ms in range(2000, 7001, 250)
            ],
            average_sustained_energy=0.5,
            sustained_ratio=0.2,
        )
        self.context = build_spinner_context(analysis=self.analysis, sustained=self.sustained)

    def test_sustain_trigger_detected_in_sustained_region(self) -> None:
        trigger = classify_trigger(self.context, "sustained", 3000, 6000)
        self.assertEqual(trigger, "sustain")

    def test_fade_out_trigger_detected_on_falling_energy(self) -> None:
        frames = [
            EnergyFrame(time_ms=time_ms, value=max(0.0, 0.6 - time_ms / 1000 * 0.04))
            for time_ms in range(0, 15001, 250)
        ]
        analysis = AudioAnalysis(
            audio_filename="fade.mp3",
            duration_ms=15_000,
            sample_rate=22_050,
            bpm=120.0,
            offset_ms=0,
            beats=[],
            onsets=[TimedStrength(time_ms=500, strength=1.0), TimedStrength(time_ms=600, strength=1.0)],
            energy_frames=frames,
            quiet_regions=[],
            high_energy_regions=[],
        )
        context = build_spinner_context(analysis=analysis)
        trigger = classify_trigger(context, "outro", 8000, 14000)
        self.assertEqual(trigger, "fade_out")

    def test_transition_trigger_for_breaks(self) -> None:
        # A quiet break without sustained content: no sustain trigger, so the
        # break falls through to a structural transition trigger.
        context = build_spinner_context(analysis=self.analysis)
        trigger = classify_trigger(context, "break", 3000, 6000)
        self.assertEqual(trigger, "transition")

    def test_dense_region_has_no_trigger(self) -> None:
        dense_analysis = make_analysis(
            duration_ms=20_000,
            onsets=list(range(1000, 12000, 150)),
            high_energy_regions=[(1000, 12000)],
            default_energy=0.7,
        )
        context = build_spinner_context(analysis=dense_analysis)
        trigger = classify_trigger(context, "dense", 2000, 6000)
        self.assertEqual(trigger, "unknown")


class FatigueStrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_fatigue_rises_with_density_and_jumps(self) -> None:
        # Dense stream of far jumps at 150ms spacing.
        objects = [
            make_circle(index, 1000 + index * 150, x=64 if index % 2 == 0 else 448, y=64 if index % 2 == 0 else 320)
            for index in range(1, 21)
        ]
        profile = compute_fatigue_profile(objects, preset=self.preset)
        self.assertGreater(profile.peak_fatigue, 0.5)
        self.assertGreaterEqual(profile.peak_fatigue_time, objects[1].time)
        self.assertLessEqual(profile.peak_fatigue_time, objects[-1].time)
        self.assertEqual(len(profile.timestamps), len(objects))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in profile.fatigue_scores))

    def test_fatigue_decays_during_wide_gaps(self) -> None:
        # Two dense bursts separated by a 5 second gap: fatigue must decay
        # back toward zero before the second burst.
        first = [
            make_circle(index, 1000 + index * 150, x=64 if index % 2 == 0 else 448, y=64 if index % 2 == 0 else 320)
            for index in range(1, 11)
        ]
        second = [
            make_circle(index + 10, 7000 + index * 150, x=64 if index % 2 == 0 else 448, y=64 if index % 2 == 0 else 320)
            for index in range(1, 11)
        ]
        profile = compute_fatigue_profile(first + second, preset=self.preset)
        # Fatigue right after the first burst should be much higher than at
        # the start of the second burst.
        tail_index = len(first) - 1
        next_index = len(first)
        self.assertGreater(profile.fatigue_scores[tail_index], profile.fatigue_scores[next_index])

    def test_fatigue_at_interpolates_deterministically(self) -> None:
        objects = [
            make_circle(index, 1000 + index * 200, x=64 if index % 2 == 0 else 448, y=64 if index % 2 == 0 else 320)
            for index in range(1, 11)
        ]
        profile = compute_fatigue_profile(objects, preset=self.preset)
        value = fatigue_at(profile, 2500)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_identical_inputs_produce_identical_fatigue(self) -> None:
        objects = [make_circle(index, 1000 + index * 150) for index in range(1, 15)]
        first = compute_fatigue_profile(objects, preset=self.preset)
        second = compute_fatigue_profile(objects, preset=self.preset)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_empty_objects_produce_empty_profile(self) -> None:
        profile = compute_fatigue_profile([], preset=self.preset)
        self.assertEqual(profile.timestamps, [])
        self.assertEqual(profile.peak_fatigue, 0.0)


class RecoveryWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preset = DIFFICULTY_PRESETS["hard"]
        self.objects = [
            make_circle(index, 1000 + index * 150, x=64 if index % 2 == 0 else 448, y=64 if index % 2 == 0 else 320)
            for index in range(1, 41)
        ]

    def test_recovery_window_after_intensify_phrase(self) -> None:
        phrases = [
            make_phrase(1, 0, 4000, "intensify"),
            make_phrase(2, 4000, 8000, "recover"),
        ]
        fatigue = compute_fatigue_profile(self.objects, preset=self.preset)
        windows = plan_recovery_windows(
            self.objects,
            phrase_info=phrases,
            fatigue=fatigue,
            preset=self.preset,
        )
        self.assertGreater(len(windows), 0)
        window = windows[0]
        self.assertEqual(window.reason, "post_intense_phrase")
        self.assertGreater(window.end_time, window.start_time)
        self.assertGreater(window.stamina_reduction_factor, 0.3)

    def test_no_recovery_window_when_strain_is_low(self) -> None:
        phrases = [
            make_phrase(1, 0, 4000, "intensify"),
            make_phrase(2, 4000, 8000, "recover"),
        ]
        # Gentle objects: spacing far apart and close together -> low strain.
        gentle = [make_circle(index, 1000 + index * 600, x=200, y=200) for index in range(1, 11)]
        fatigue = compute_fatigue_profile(gentle, preset=self.preset)
        windows = plan_recovery_windows(
            gentle,
            phrase_info=phrases,
            fatigue=fatigue,
            preset=self.preset,
        )
        self.assertEqual(windows, [])

    def test_recovery_windows_deterministic(self) -> None:
        phrases = [
            make_phrase(1, 0, 4000, "intensify"),
            make_phrase(2, 4000, 8000, "recover"),
        ]
        fatigue = compute_fatigue_profile(self.objects, preset=self.preset)
        first = plan_recovery_windows(
            self.objects,
            phrase_info=phrases,
            fatigue=fatigue,
            preset=self.preset,
        )
        second = plan_recovery_windows(
            self.objects,
            phrase_info=phrases,
            fatigue=fatigue,
            preset=self.preset,
        )
        self.assertEqual(
            [window.to_dict() for window in first],
            [window.to_dict() for window in second],
        )

    def test_no_phrase_info_produces_no_windows(self) -> None:
        fatigue = compute_fatigue_profile(self.objects, preset=self.preset)
        windows = plan_recovery_windows(
            self.objects,
            phrase_info=None,
            fatigue=fatigue,
            preset=self.preset,
        )
        self.assertEqual(windows, [])


class PostSpinnerClearanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preset = DIFFICULTY_PRESETS["normal"]

    def test_enough_clearance_passes(self) -> None:
        ok, reason = post_spinner_clearance(
            3000,
            5000,
            5600,
            preset=self.preset,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_insufficient_clearance_fails(self) -> None:
        ok, reason = post_spinner_clearance(
            3000,
            5000,
            5100,
            preset=self.preset,
        )
        self.assertFalse(ok)
        self.assertIn("clearance", reason)

    def test_no_next_object_passes(self) -> None:
        ok, _ = post_spinner_clearance(3000, 5000, None, preset=self.preset)
        self.assertTrue(ok)

    def test_explicit_clearance_override(self) -> None:
        ok, _ = post_spinner_clearance(
            3000,
            5000,
            5300,
            preset=self.preset,
            min_clearance_ms=200,
        )
        self.assertTrue(ok)
        ok, _ = post_spinner_clearance(
            3000,
            5000,
            5300,
            preset=self.preset,
            min_clearance_ms=400,
        )
        self.assertFalse(ok)


class DensityHarmonyTests(unittest.TestCase):
    def test_intensify_phrase_with_spinner_flood_flags_violation(self) -> None:
        phrases = [make_phrase(1, 0, 8000, "intensify")]
        objects = [make_circle(1, 1000)]
        for index in range(2, 7):
            objects.append(make_circle(index, 1000 + index * 300))
        for index in range(7, 10):
            objects.append(
                GeneratedSpinnerHitObject(
                    id=index,
                    type="spinner",
                    time=3000 + index * 100,
                    end_time=3000 + index * 100 + 800,
                )
            )
        harmony = analyze_density_harmony(objects, phrase_info=phrases, difficulty="hard")
        self.assertGreater(len(harmony["violations"]), 0)
        self.assertIn("intensify", harmony["roles"])

    def test_recover_phrase_allows_spinners(self) -> None:
        phrases = [make_phrase(1, 0, 8000, "recover")]
        objects = [make_circle(1, 1000)]
        objects.append(
            GeneratedSpinnerHitObject(
                id=2,
                type="spinner",
                time=2000,
                end_time=3000,
            )
        )
        harmony = analyze_density_harmony(objects, phrase_info=phrases, difficulty="hard")
        self.assertEqual(harmony["violations"], [])

    def test_no_phrase_info_returns_empty_report(self) -> None:
        objects = [make_circle(1, 1000)]
        harmony = analyze_density_harmony(objects, phrase_info=None, difficulty="hard")
        self.assertEqual(harmony, {"roles": {}, "violations": []})


class RecoveryReportTests(unittest.TestCase):
    def setUp(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_recovery_report_is_deterministic_and_complete(self) -> None:
        import json

        map_path = self.root / "final.json"
        map_payload = {
            "title": "Recovery Test",
            "artist": "Tester",
            "audioDurationMs": 20000,
            "objects": [
                {"id": 1, "type": "circle", "x": 64, "y": 64, "time": 1000},
                {"id": 2, "type": "circle", "x": 448, "y": 320, "time": 1150},
                {"id": 3, "type": "circle", "x": 64, "y": 64, "time": 1300},
                {
                    "id": 4,
                    "type": "spinner",
                    "time": 5000,
                    "endTime": 6500,
                },
                {"id": 5, "type": "circle", "x": 256, "y": 192, "time": 9000},
            ],
        }
        map_path.write_text(json.dumps(map_payload), encoding="utf-8")

        output_path = self.root / "recovery-easy.json"
        first = analyze_recovery_structure(
            map_path=map_path,
            phrase_report_path=None,
            output_path=output_path,
            difficulty="easy",
            force=True,
        )
        second = analyze_recovery_structure(
            map_path=map_path,
            phrase_report_path=None,
            output_path=output_path,
            difficulty="easy",
            force=True,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["spinnerCount"], 1)
        self.assertIn("fatigue", first)
        self.assertIn("recoveryWindows", first)
        self.assertIn("harmony", first)
        self.assertEqual(first["objectTypeCounts"]["spinner"], 1)
        self.assertGreaterEqual(first["avgSpinnerDurationMs"], 1500)
        self.assertGreater(first["fatigue"]["peakFatigue"], 0.0)

    def test_recovery_report_cached_when_output_exists(self) -> None:
        import json

        map_path = self.root / "final.json"
        map_path.write_text(
            json.dumps(
                {
                    "objects": [
                        {"id": 1, "type": "circle", "x": 128, "y": 128, "time": 1000},
                        {"id": 2, "type": "circle", "x": 300, "y": 200, "time": 2000},
                    ]
                }
            ),
            encoding="utf-8",
        )
        output_path = self.root / "recovery-normal.json"
        first = analyze_recovery_structure(
            map_path=map_path,
            phrase_report_path=None,
            output_path=output_path,
            difficulty="normal",
            force=True,
        )
        # Force=False reuses the cached file even if inputs changed.
        map_path.write_text(
            json.dumps({"objects": [{"id": 1, "type": "circle", "x": 1, "y": 1, "time": 10}]}),
            encoding="utf-8",
        )
        second = analyze_recovery_structure(
            map_path=map_path,
            phrase_report_path=None,
            output_path=output_path,
            difficulty="normal",
            force=False,
        )
        self.assertEqual(first, second)


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = make_analysis(
            duration_ms=30_000,
            quiet_regions=[(2000, 7000), (14000, 19000)],
            onsets=[1000, 1100, 8000, 8100, 20000, 20100],
            default_energy=0.42,
        )
        self.sustained = SustainedAnalysis(
            sustained_regions=[
                {"startMs": 2000, "endMs": 7000, "averageScore": 0.8},
                {"startMs": 14000, "endMs": 19000, "averageScore": 0.6},
            ],
            sustained_frames=[
                {"timeMs": time_ms, "sustainedScore": 0.7 if 2000 <= time_ms <= 19000 else 0.2}
                for time_ms in range(2000, 19001, 500)
            ],
            average_sustained_energy=0.4,
            sustained_ratio=0.3,
        )
        self.preset = DIFFICULTY_PRESETS["normal"]
        self.objects = [
            make_circle(1, 1000),
            make_circle(2, 8000),
            make_circle(3, 20000),
        ]

    def test_pipeline_reports_fatigue_and_recovery_diagnostics(self) -> None:
        result_objects, diagnostics = process_spinners(
            self.objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            phrase_info=[
                make_phrase(1, 0, 9000, "intensify"),
                make_phrase(2, 9000, 20000, "recover"),
            ],
        )
        payload = diagnostics.to_dict()
        self.assertIn("fatiguePeak", payload)
        self.assertIn("recoveryWindows", payload)
        self.assertIn("triggerTypeCounts", payload)
        spinners = [item for item in result_objects if item.type == "spinner"]
        if spinners:
            self.assertIn("triggerType", spinners[0].extra_fields)
        # Recovery windows must not overlap any object times.
        for window in payload["recoveryWindows"]:
            window_start = int(window["startTime"])
            window_end = int(window["endTime"])
            for obj in result_objects:
                self.assertFalse(window_start <= obj.time < window_end)

    def test_trigger_gating_blocks_unmotivated_spinners(self) -> None:
        # A dense song with no quiet/sustained regions: no trigger, no spinner.
        # Use a high quality threshold to suppress forced minimum spinners
        # so the test validates pure trigger gating behavior.
        from tools.map_generator.spinners.spinner_pipeline import SpinnerPipelineConfig
        dense_analysis = make_analysis(
            duration_ms=20_000,
            onsets=list(range(1000, 19000, 150)),
            high_energy_regions=[(1000, 19000)],
            default_energy=0.7,
        )
        objects = [make_circle(1, 800), make_circle(2, 19500)]
        _, diagnostics = process_spinners(
            objects,
            analysis=dense_analysis,
            preset=self.preset,
            seed=7,
            spinner_config=SpinnerPipelineConfig(quality_threshold=70.0),
        )
        self.assertEqual(diagnostics.accepted_spinners, 0)

    def test_pipeline_is_deterministic_with_recovery(self) -> None:
        phrase_info = [
            make_phrase(1, 0, 9000, "intensify"),
            make_phrase(2, 9000, 20000, "recover"),
        ]
        first, first_diag = process_spinners(
            self.objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            phrase_info=phrase_info,
        )
        second, second_diag = process_spinners(
            self.objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
            phrase_info=phrase_info,
        )
        self.assertEqual([item.to_dict() for item in first], [item.to_dict() for item in second])
        self.assertEqual(first_diag.to_dict(), second_diag.to_dict())

    def test_backward_compatible_without_phrase_info(self) -> None:
        result_objects, diagnostics = process_spinners(
            self.objects,
            analysis=self.analysis,
            preset=self.preset,
            seed=42,
            sustained=self.sustained,
        )
        payload = diagnostics.to_dict()
        self.assertIn("fatiguePeak", payload)
        self.assertIn("recoveryWindows", payload)
        spinners = [item for item in result_objects if item.type == "spinner"]
        self.assertGreater(len(spinners), 0)


if __name__ == "__main__":
    unittest.main()
