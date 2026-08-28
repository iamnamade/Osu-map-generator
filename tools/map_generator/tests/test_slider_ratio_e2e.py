"""End-to-end slider ratio verification test.

Generates test maps for Easy, Normal, and Hard difficulties using
synthetic audio and verifies that the slider ratio meets the 30-45% target.
"""

from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

import numpy as np


def _generate_test_wav(path: Path, duration_s: float = 30.0, sample_rate: int = 22050) -> None:
    """Generate a synthetic WAV with sustained pads + percussive hits.

    The sustained sine waves ensure the sustained analysis detects
    slider candidates; the percussive clicks give the beat detector
    timing events to place objects on.
    """
    total_samples = int(duration_s * sample_rate)
    t = np.linspace(0, duration_s, total_samples, dtype=np.float64)

    # --- Sustained pad layers (vocal/synth/guitar simulation) ---
    pad = np.zeros_like(t)
    for freq in (220.0, 330.0, 440.0, 660.0):
        pad += 0.12 * np.sin(2 * np.pi * freq * t)
    pad *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.8 * t)

    # --- Percussive hits at 120 BPM (every 0.5s) ---
    clicks = np.zeros_like(t)
    bpm = 120.0
    beat_interval_s = 60.0 / bpm
    for beat_i in range(int(duration_s / beat_interval_s)):
        hit_time = beat_i * beat_interval_s
        hit_sample = int(hit_time * sample_rate)
        click_len = min(800, total_samples - hit_sample)
        if click_len > 0:
            env = np.exp(-np.linspace(0, 8, click_len))
            freq = 800.0 if beat_i % 4 == 0 else 600.0
            clicks[hit_sample:hit_sample + click_len] += (
                0.35 * env * np.sin(2 * np.pi * freq * np.linspace(0, click_len / sample_rate, click_len))
            )

    mix = pad + clicks
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix / peak * 0.9

    samples_int = np.clip(mix * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples_int.tobytes())


def _count_objects(objects: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        t = obj.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def _verify_slider_ratio(
    counts: dict[str, int],
    difficulty: str,
    min_ratio: float,
    max_ratio: float,
) -> tuple[bool, str]:
    total = sum(counts.values())
    sliders = counts.get("slider", 0)
    circles = counts.get("circle", 0)
    spinners = counts.get("spinner", 0)
    ratio = sliders / total if total > 0 else 0.0

    lines = [
        f"  Difficulty: {difficulty}",
        f"  Total objects: {total}",
        f"  Circles: {circles}",
        f"  Sliders: {sliders}",
        f"  Spinners: {spinners}",
        f"  Slider ratio: {ratio:.1%} (target: {min_ratio:.0%}-{max_ratio:.0%})",
    ]

    passed = min_ratio <= ratio <= max_ratio
    status = "PASS" if passed else "FAIL"
    lines.insert(0, f"  [{status}]")
    return passed, "\n".join(lines)


def main() -> None:
    from ..beatmap_generator import generate_beatmap
    from ..config import get_difficulty_preset

    results: list[tuple[str, bool, str]] = []

    project_root = Path(__file__).resolve().parents[2]
    public_audio_dir = project_root / "public" / "audio"
    public_audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = public_audio_dir / "slider_ratio_test.wav"
    _generate_test_wav(wav_path, duration_s=30.0)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        for difficulty, min_ratio, max_ratio in [
            ("easy", 0.15, 0.35),
            ("normal", 0.30, 0.50),
            ("hard", 0.30, 0.50),
        ]:
            preset = get_difficulty_preset(difficulty)
            output_path = tmp / f"map_{difficulty}.json"
            analysis_path = tmp / f"analysis_{difficulty}.json"

            print(f"\n--- Generating {difficulty.upper()} difficulty ---")

            result = generate_beatmap(
                audio_path=wav_path,
                title=f"Slider Test {difficulty.title()}",
                artist="Test Artist",
                difficulty=difficulty,
                seed=42,
                output_path=output_path,
                analysis_output_path=analysis_path,
                project_root=project_root,
            )

            with open(output_path, "r", encoding="utf-8") as f:
                map_data = json.load(f)

            counts = _count_objects(map_data.get("objects", []))
            passed, detail = _verify_slider_ratio(counts, difficulty, min_ratio, max_ratio)
            results.append((difficulty, passed, detail))
            print(detail)

            if result.slider_diagnostics:
                sd = result.slider_diagnostics
                print(f"  Slider diagnostics: {sd.get('acceptedSliders', 0)} accepted, "
                      f"{sd.get('rejectedSliders', 0)} rejected, "
                      f"{sd.get('totalCandidates', 0)} candidates")

    print("\n" + "=" * 60)
    print("SLIDER RATIO VERIFICATION SUMMARY")
    print("=" * 60)
    all_passed = True
    for diff, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {diff}")
        if not passed:
            all_passed = False
            print(detail)

    if all_passed:
        print("\n[PASS] All difficulties meet the slider ratio targets.")
    else:
        print("\n[FAIL] Some difficulties did NOT meet the slider ratio targets.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
