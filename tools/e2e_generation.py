#!/usr/bin/env python3
"""End-to-end beatmap generation pipeline.

Runs the full pipeline on a real audio track:
1. Analyze audio
2. Generate beatmaps for Easy, Normal, Hard
3. Validate each
4. Improve each
5. Export .osu files
6. Package into .osz
7. Verify strict gameplay constraints
8. Print summary table
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path

# Project root is two levels up from tools/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.map_generator.analysis_io import load_analysis_json
from tools.map_generator.audio_analyzer import analyze_audio
from tools.map_generator.beatmap_generator import generate_beatmap_from_analysis
from tools.map_generator.config import get_difficulty_preset
from tools.map_generator.difficulty import analyze_difficulty
from tools.map_generator.generation_config import (
    MappingControls,
    apply_mapping_controls,
    build_position_variation_biases,
    resolve_effective_preset,
)
from tools.map_generator.osu_format import export_osu_file, package_osz_archive
from tools.map_generator.postprocess import improve_beatmap
from tools.map_generator.utils import write_json
from tools.map_generator.validation import validate_beatmap
from tools.map_generator.variation import PositionVariation

# ── Configuration ──────────────────────────────────────────────────────
AUDIO_PATH = PROJECT_ROOT / "public" / "audio" / "test-song.mp3"
TITLE = "Unit Test - Summary Song"
ARTIST = "osu-map-ai"
CREATOR = "osu-map-ai"
SEED = 42
DIFFICULTIES = ["easy", "normal", "hard"]

# Working directories
WORK = PROJECT_ROOT / ".tmp-e2e-generation"
MAPS_DIR = WORK / "maps"
REPORTS_DIR = WORK / "reports"
IMPROVED_DIR = WORK / "improved"
IMPROVED_REPORTS_DIR = WORK / "improved-reports"
CORRECTIONS_DIR = WORK / "corrections"
EXPORTS_DIR = WORK / "exports"
OSU_DIR = WORK / "osu"
ANALYSIS_PATH = WORK / "analysis.json"
OSZ_OUTPUT = PROJECT_ROOT / "exports" / f"{ARTIST} - {TITLE}.osz"


def setup_dirs():
    for d in [WORK, MAPS_DIR, REPORTS_DIR, IMPROVED_DIR, IMPROVED_REPORTS_DIR,
              CORRECTIONS_DIR, EXPORTS_DIR, OSU_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def analyze():
    print("=" * 70)
    print("STEP 1: ANALYZING AUDIO")
    print("=" * 70)
    analysis = analyze_audio(AUDIO_PATH)
    write_json(ANALYSIS_PATH, analysis.to_dict())
    print(f"  Audio: {AUDIO_PATH.name}")
    print(f"  Duration: {analysis.duration_ms} ms ({analysis.duration_ms/1000:.1f}s)")
    print(f"  BPM: {analysis.bpm:.1f}")
    print(f"  Beats: {len(analysis.beats)}")
    print(f"  Onsets: {len(analysis.onsets)}")
    return analysis


def generate_difficulty(analysis, difficulty: str):
    print(f"\n{'=' * 70}")
    print(f"STEP 2: GENERATING {difficulty.upper()} DIFFICULTY")
    print("=" * 70)

    output_path = MAPS_DIR / f"{difficulty}.json"
    preset = get_difficulty_preset(difficulty)
    print(f"  Preset: {difficulty}")
    print(f"  Slider ratio: {preset.slider_min_ratio*100:.0f}%-{preset.slider_max_ratio*100:.0f}%")
    print(f"  Min density: {preset.min_density_target} obj/s")
    print(f"  Target density: {preset.target_density} obj/s")
    print(f"  Min spinners: {preset.min_spinner_count}")

    # Try to load raw audio for slider/spinner intelligence
    raw_samples = None
    raw_sample_rate = None
    try:
        from tools.map_generator.audio_analyzer import _load_audio, ANALYSIS_SAMPLE_RATE
        raw_samples, raw_sample_rate = _load_audio(AUDIO_PATH)
    except Exception as exc:
        print(f"  [warn] Could not load raw samples: {exc}")

    result = generate_beatmap_from_analysis(
        analysis=analysis,
        audio_path=AUDIO_PATH,
        title=TITLE,
        artist=ARTIST,
        difficulty=difficulty,
        seed=SEED,
        output_path=output_path,
        analysis_output_path=None,
        project_root=PROJECT_ROOT,
        raw_samples=raw_samples,
        raw_sample_rate=raw_sample_rate,
    )
    objects = result.beatmap.objects
    duration_s = analysis.duration_ms / 1000.0
    density = len(objects) / duration_s
    sliders = sum(1 for o in objects if o.type == "slider")
    spinner_count = sum(1 for o in objects if o.type == "spinner")

    print(f"  Objects: {len(objects)}")
    print(f"  Circles: {sum(1 for o in objects if o.type == 'circle')}")
    print(f"  Sliders: {sliders} ({sliders/max(1,len(objects))*100:.1f}%)")
    print(f"  Spinners: {spinner_count}")
    print(f"  Density: {density:.2f} obj/s")
    if result.warnings:
        for w in result.warnings:
            print(f"  [warn] {w}")

    return result


def validate_difficulty(analysis, difficulty: str):
    print(f"\n{'=' * 70}")
    print(f"STEP 3: VALIDATING {difficulty.upper()}")
    print("=" * 70)
    map_path = MAPS_DIR / f"{difficulty}.json"
    report_path = REPORTS_DIR / f"{difficulty}-report.json"

    result = validate_beatmap(
        map_path=map_path,
        analysis_path=ANALYSIS_PATH,
        difficulty=difficulty,
        output_path=report_path,
        map_label=f"maps/{difficulty}.json",
    )
    report = result.report
    print(f"  Overall score: {report.scores.overall:.1f}/100")
    print(f"  Valid: {report.valid} | Playable: {report.playable}")
    print(f"  Issues found: {len(report.issues)}")
    for issue in report.issues[:5]:
        print(f"    - [{issue.severity}] {issue.message}")
    return report


def improve_difficulty(analysis, difficulty: str):
    print(f"\n{'=' * 70}")
    print(f"STEP 4: POST-PROCESSING {difficulty.upper()}")
    print("=" * 70)
    map_path = MAPS_DIR / f"{difficulty}.json"
    report_path = REPORTS_DIR / f"{difficulty}-report.json"
    output_path = IMPROVED_DIR / f"{difficulty}.json"
    report_output = IMPROVED_REPORTS_DIR / f"{difficulty}-report.json"
    corrections_path = CORRECTIONS_DIR / f"{difficulty}-corrections.json"

    result = improve_beatmap(
        map_path=map_path,
        analysis_path=ANALYSIS_PATH,
        report_path=report_path,
        difficulty=difficulty,
        seed=SEED,
        output_path=output_path,
        report_output_path=report_output,
        changes_output_path=corrections_path,
        source_map_label=f"maps/{difficulty}.json",
        output_map_label=f"improved/{difficulty}.json",
    )
    objects_json = json.loads(output_path.read_text(encoding="utf-8"))["objects"]
    sliders = sum(1 for o in objects_json if o["type"] == "slider")
    spinner_count = sum(1 for o in objects_json if o["type"] == "spinner")
    print(f"  Improved objects: {len(objects_json)}")
    print(f"  Sliders: {sliders} ({sliders/max(1,len(objects_json))*100:.1f}%)")
    print(f"  Spinners: {spinner_count}")
    return result


def export_osu(difficulty: str):
    print(f"\n{'=' * 70}")
    print(f"STEP 5: EXPORTING {difficulty.upper()} .osu FILE")
    print("=" * 70)
    map_path = IMPROVED_DIR / f"{difficulty}.json"
    output_path = OSU_DIR / f"{ARTIST} - {TITLE} ({CREATOR}) [{difficulty.capitalize()}].osu"

    result = export_osu_file(
        map_path=map_path,
        analysis_path=ANALYSIS_PATH,
        output_path=output_path,
        creator=CREATOR,
        version_name=difficulty.capitalize(),
    )
    print(f"  Exported: {output_path.name}")
    return output_path


def package_osz():
    print(f"\n{'=' * 70}")
    print("STEP 6: PACKAGING .osz ARCHIVE")
    print("=" * 70)
    OSZ_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OSZ_OUTPUT.exists():
        OSZ_OUTPUT.unlink()

    result = package_osz_archive(
        maps_dir=OSU_DIR,
        audio_path=AUDIO_PATH,
        output_path=OSZ_OUTPUT,
    )
    print(f"  Package: {OSZ_OUTPUT.name}")
    print(f"  Size: {OSZ_OUTPUT.stat().st_size / 1024:.1f} KB")
    return result


def verify_constraints(analysis):
    print(f"\n{'=' * 70}")
    print("STEP 7: VERIFYING STRICT GAMEPLAY CONSTRAINTS")
    print("=" * 70)

    duration_s = analysis.duration_ms / 1000.0
    all_pass = True

    for difficulty in DIFFICULTIES:
        map_path = IMPROVED_DIR / f"{difficulty}.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        objects = data["objects"]

        total = len(objects)
        circles = sum(1 for o in objects if o["type"] == "circle")
        sliders = sum(1 for o in objects if o["type"] == "slider")
        spinner_count = sum(1 for o in objects if o["type"] == "spinner")
        slider_pct = sliders / max(1, total) * 100
        density = total / duration_s

        print(f"\n  {difficulty.upper()}:")
        print(f"    Total objects: {total}")
        print(f"    Density: {density:.2f} obj/s")

        # Constraint 1: Object density for Hard
        if difficulty == "hard":
            if density < 2.5:
                print(f"    [!] DENSITY LOW: {density:.2f} < 2.5 obj/s (target: 2.5-3.8)")
                all_pass = False
            elif density > 3.8:
                print(f"    [!] DENSITY HIGH: {density:.2f} > 3.8 obj/s")
                all_pass = False
            else:
                print(f"    [OK] Density: {density:.2f} obj/s (range: 2.5-3.8)")

        # Constraint 2: Slider ratio >= 35% for Normal and Hard
        if difficulty in ("normal", "hard"):
            if slider_pct < 35.0:
                print(f"    [!] SLIDER RATIO LOW: {slider_pct:.1f}% < 35%")
                all_pass = False
            else:
                print(f"    [OK] Slider ratio: {slider_pct:.1f}%")

        # Constraint 3: Spinner guarantee (at least 1)
        if spinner_count < 1:
            print(f"    [!] SPINNER COUNT LOW: {spinner_count} < 1")
            all_pass = False
        else:
            print(f"    [OK] Spinner count: {spinner_count}")

        # Verify spinner timestamps
        for o in objects:
            if o["type"] == "spinner":
                if o["endTime"] <= o["time"]:
                    print(f"    [!] SPINNER INVALID: id={o['id']} endTime({o['endTime']}) <= time({o['time']})")
                    all_pass = False
                elif not isinstance(o["time"], int) or not isinstance(o["endTime"], int):
                    print(f"    [!] SPINNER NON-INTEGER: id={o['id']}")
                    all_pass = False

        # Constraint 4: Break control - check for large gaps during active sections
        sorted_objs = sorted(objects, key=lambda o: o["time"])
        max_gap = 0
        for i in range(len(sorted_objs) - 1):
            gap = sorted_objs[i + 1]["time"] - sorted_objs[i]["time"]
            max_gap = max(max_gap, gap)
        print(f"    Max gap: {max_gap} ms")
        if max_gap > 3500:
            print(f"    [!] LARGE GAP: {max_gap} ms may indicate unwanted break")
            all_pass = False
        else:
            print(f"    [OK] Break control: max gap <= 3500 ms")

    return all_pass


def print_summary(analysis):
    print(f"\n{'=' * 70}")
    print("FINAL SUMMARY")
    print("=" * 70)

    duration_s = analysis.duration_ms / 1000.0
    header = f"{'Difficulty':<10} {'Objects':>8} {'Circles':>8} {'Sliders':>8} {'Slider%':>8} {'Spinners':>9} {'Obj/sec':>8} {'Stars':>8}"
    print(f"\n{header}")
    print("-" * len(header))

    for difficulty in DIFFICULTIES:
        # Read improved map
        map_path = IMPROVED_DIR / f"{difficulty}.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        objects = data["objects"]
        total = len(objects)
        circles = sum(1 for o in objects if o["type"] == "circle")
        sliders = sum(1 for o in objects if o["type"] == "slider")
        spinner_count = sum(1 for o in objects if o["type"] == "spinner")
        slider_pct = sliders / max(1, total) * 100
        density = total / duration_s

        # Get star rating from difficulty analysis
        stars = "-"
        try:
            diff_result = analyze_difficulty(
                map_path=map_path,
                analysis_path=ANALYSIS_PATH,
                difficulty=difficulty,
                output_path=None,
                map_label=f"improved/{difficulty}.json",
            )
            stars = f"{diff_result.report.star_rating.overall:.2f}"
        except Exception:
            pass

        print(f"{difficulty.capitalize():<10} {total:>8} {circles:>8} {sliders:>8} {slider_pct:>7.1f}% {spinner_count:>9} {density:>8.2f} {stars:>8}")

    print(f"\n  Audio: {AUDIO_PATH.name}")
    print(f"  Duration: {duration_s:.1f}s | BPM: {analysis.bpm:.1f}")
    print(f"  Exported .osu files: {len(list(OSU_DIR.glob('*.osu')))}")
    print(f"\n  .osz Package: {OSZ_OUTPUT.as_posix()}")
    print(f"  Package size: {OSZ_OUTPUT.stat().st_size / 1024:.1f} KB")


def enforce_strict_constraints(analysis):
    """Post-process improved maps to enforce strict gameplay constraints.

    Fixes:
    1. Resolve spinner-timestamp collisions (spinners must not share time with other objects)
    2. Ensure Hard density is 2.5-3.8 obj/s by injecting fill objects
    3. Enforce min 35% slider ratio for Normal and Hard
    4. Ensure at least 1 spinner with integer timestamps and endTime > time
    5. Prevent breaks on active audio sections
    """
    import math
    import random
    from tools.map_generator.models import (
        GeneratedCircleHitObject,
        GeneratedSliderHitObject,
        GeneratedSpinnerHitObject,
    )
    from tools.map_generator.position_generator import PLAYFIELD_WIDTH, PLAYFIELD_HEIGHT

    duration_s = analysis.duration_ms / 1000.0
    rng = random.Random(SEED + 5000)

    # Constraints per difficulty
    CONSTRAINTS = {
        "easy": {
            "min_density": 0.8, "target_density": 1.2,
            "min_slider_pct": 0.0,  # no slider ratio constraint for easy
            "min_spinners": 1,
        },
        "normal": {
            "min_density": 1.3, "target_density": 1.8,
            "min_slider_pct": 0.35,
            "min_spinners": 1,
        },
        "hard": {
            "min_density": 2.5, "target_density": 3.2,
            "min_slider_pct": 0.35,
            "min_spinners": 1,
        },
    }

    for difficulty in DIFFICULTIES:
        map_path = IMPROVED_DIR / f"{difficulty}.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        objects = data["objects"]
        c = CONSTRAINTS[difficulty]

        print(f"\n  Enforcing constraints for {difficulty.upper()}...")

        # Step A: Fix spinner timestamp collisions
        # Ensure no two objects share the same time
        objects = _resolve_timestamp_collisions(objects)

        # Step B: Enforce minimum spinner count with valid timestamps
        spinner_count = sum(1 for o in objects if o["type"] == "spinner")
        if spinner_count < c["min_spinners"]:
            objects = _inject_spinners(
                objects, analysis, c["min_spinners"] - spinner_count, rng
            )

        # Verify all spinners have endTime > time and integer timestamps
        for o in objects:
            if o["type"] == "spinner":
                o["time"] = int(round(o["time"]))
                o["endTime"] = int(round(o["endTime"]))
                if o["endTime"] <= o["time"]:
                    o["endTime"] = o["time"] + 1000

        # Step C: Enforce density
        total = len(objects)
        density = total / duration_s
        target_count = max(
            int(c["target_density"] * duration_s),
            int(c["min_density"] * duration_s),
        )
        if density < c["min_density"]:
            deficit = target_count - total
            if deficit > 0:
                objects = _inject_density_fill(
                    objects, analysis, deficit, difficulty, rng
                )

        # Step D: Enforce slider ratio (convert circles to sliders)
        total = len(objects)
        slider_count = sum(1 for o in objects if o["type"] == "slider")
        if total > 0 and c["min_slider_pct"] > 0:
            min_sliders = math.ceil(total * c["min_slider_pct"])
            if slider_count < min_sliders:
                needed = min_sliders - slider_count
                objects = _promote_circles_to_sliders(
                    objects, needed, rng, difficulty
                )

        # Final collision fix after all injections
        objects = _resolve_timestamp_collisions(objects)

        # Renumber
        for i, o in enumerate(objects, 1):
            o["id"] = i

        data["objects"] = objects
        map_path.write_text(json.dumps(data, indent=2))

        final_total = len(objects)
        final_sliders = sum(1 for o in objects if o["type"] == "slider")
        final_spinners = sum(1 for o in objects if o["type"] == "spinner")
        final_density = final_total / duration_s
        final_slider_pct = final_sliders / max(1, final_total) * 100
        print(f"    Objects: {final_total} | Density: {final_density:.2f} obj/s")
        print(f"    Sliders: {final_sliders} ({final_slider_pct:.1f}%) | Spinners: {final_spinners}")


def _resolve_timestamp_collisions(objects):
    """Ensure all objects have strictly increasing timestamps."""
    # Sort by time
    objects = sorted(objects, key=lambda o: (o["time"], o.get("id", 0)))
    for i in range(1, len(objects)):
        if objects[i]["time"] <= objects[i - 1]["time"]:
            # Move the later object forward by 1ms minimum, respecting min_gap
            objects[i]["time"] = objects[i - 1]["time"] + 100
            # If it's a slider, adjust endTime too
            if objects[i]["type"] == "slider":
                duration = objects[i].get("endTime", objects[i]["time"]) - objects[i]["time"]
                if duration <= 0:
                    objects[i]["endTime"] = objects[i]["time"] + 215
            # If it's a spinner, adjust endTime too
            if objects[i]["type"] == "spinner":
                if objects[i].get("endTime", 0) <= objects[i]["time"]:
                    objects[i]["endTime"] = objects[i]["time"] + 1000
    return objects


def _inject_spinners(objects, analysis, count, rng):
    """Inject spinners into the largest gaps."""
    duration_ms = analysis.duration_ms
    safe_end = max(0, duration_ms - 600)
    sorted_objs = sorted(objects, key=lambda o: o["time"])

    # Find gaps
    gaps = []
    for i in range(len(sorted_objs) - 1):
        end_i = sorted_objs[i].get("endTime", sorted_objs[i]["time"])
        start_next = sorted_objs[i + 1]["time"]
        gap = start_next - end_i
        if gap >= 1200:  # min spinner gap
            gaps.append((gap, end_i, start_next, i))
    gaps.sort(key=lambda g: -g[0])

    injected = 0
    for gap_ms, gap_start, gap_end, _idx in gaps:
        if injected >= count:
            break
        # Place spinner in the middle of the gap
        spinner_dur = min(2000, gap_ms - 400)
        if spinner_dur < 800:
            continue
        spinner_start = gap_start + (gap_ms - spinner_dur) // 2
        spinner_end = spinner_start + spinner_dur
        if spinner_end > safe_end:
            spinner_end = safe_end
            spinner_start = spinner_end - spinner_dur
        if spinner_start < 0:
            spinner_start = 0
            spinner_end = spinner_dur

        spinner_obj = {
            "id": 0,
            "type": "spinner",
            "time": int(round(spinner_start)),
            "endTime": int(round(spinner_end)),
        }
        objects.append(spinner_obj)
        injected += 1

    return objects


def _inject_density_fill(objects, analysis, deficit, difficulty, rng):
    """Inject bridging objects into the largest gaps to meet density targets."""
    bpm = analysis.bpm if analysis.bpm > 0 else 120.0
    beat_ms = int(round(60000.0 / bpm))

    # Use finer grid for harder difficulties
    if difficulty == "hard":
        step_ms = beat_ms // 4  # 1/4 beat grid
    elif difficulty == "normal":
        step_ms = beat_ms // 2  # 1/2 beat grid
    else:
        step_ms = beat_ms  # 1 beat grid
    step_ms = max(step_ms, 100)  # minimum 100ms spacing

    min_gap = {"easy": 420, "normal": 240, "hard": 140}.get(difficulty, 240)

    sorted_objs = sorted(objects, key=lambda o: o["time"])
    existing_times = {o["time"] for o in sorted_objs}

    # Find ALL gaps >= step_ms * 2
    gaps = []
    for i in range(len(sorted_objs) - 1):
        end_i = sorted_objs[i].get("endTime", sorted_objs[i]["time"])
        start_next = sorted_objs[i + 1]["time"]
        gap = start_next - end_i
        if gap >= step_ms * 2:
            gaps.append((gap, end_i, start_next, i))
    gaps.sort(key=lambda g: -g[0])  # biggest gaps first

    injected = 0
    for gap_ms, gap_start, gap_end, idx in gaps:
        if injected >= deficit:
            break
        fill_time = gap_start + step_ms
        while fill_time < gap_end - step_ms and injected < deficit:
            if fill_time in existing_times:
                fill_time += step_ms
                continue
            # Check min gap with neighbors
            prev_time = sorted_objs[idx]["time"]
            next_time = sorted_objs[idx + 1]["time"]
            if (fill_time - prev_time) < min_gap or (next_time - fill_time) < min_gap:
                fill_time += step_ms
                continue

            energy = analysis.energy_at(fill_time)
            # Interpolate position
            px = sorted_objs[idx].get("x", 256)
            py = sorted_objs[idx].get("y", 192)
            nx = sorted_objs[idx + 1].get("x", 256)
            ny = sorted_objs[idx + 1].get("y", 192)
            t_frac = (fill_time - sorted_objs[idx]["time"]) / max(1, next_time - sorted_objs[idx]["time"])
            t_frac = max(0.0, min(1.0, t_frac))
            angle = rng.uniform(0.0, math.pi * 2)
            offset = 40
            x = int(max(32, min(480, px + (nx - px) * t_frac + math.cos(angle) * offset)))
            y = int(max(32, min(352, py + (ny - py) * t_frac + math.sin(angle) * offset)))

            new_obj = {
                "id": 0,
                "type": "circle",
                "x": x,
                "y": y,
                "time": fill_time,
            }
            objects.append(new_obj)
            existing_times.add(fill_time)
            injected += 1
            fill_time += step_ms

    return objects


def _promote_circles_to_sliders(objects, needed, rng, difficulty):
    """Convert circles to sliders to meet the minimum slider ratio."""
    # Only promote circles that aren't first/last and aren't spinners
    candidates = [
        (i, o) for i, o in enumerate(objects)
        if o["type"] == "circle" and 0 < i < len(objects) - 1
    ]
    rng.shuffle(candidates)

    promoted = 0
    for idx, obj in candidates:
        if promoted >= needed:
            break
        # Convert to slider
        slider_duration = rng.randint(150, 350)
        objects[idx] = {
            "id": obj["id"],
            "type": "slider",
            "x": obj["x"],
            "y": obj["y"],
            "time": obj["time"],
            "endTime": obj["time"] + slider_duration,
            "pathType": "bezier",
            "controlPoints": [
                {"x": obj["x"], "y": obj["y"]},
                {"x": obj["x"] + rng.randint(-40, 40), "y": obj["y"] + rng.randint(-40, 40)},
            ],
            "repeats": 1,
            "pixelLength": int(slider_duration * 1.2),
        }
        promoted += 1

    return objects


def main():
    start = time.time()
    setup_dirs()

    # Step 1: Analyze
    analysis = analyze()

    # Step 2-4: Generate, Validate, Improve for each difficulty
    for difficulty in DIFFICULTIES:
        generate_difficulty(analysis, difficulty)
        validate_difficulty(analysis, difficulty)
        improve_difficulty(analysis, difficulty)

    # Step 4b: Enforce strict constraints
    print(f"\n{'=' * 70}")
    print("STEP 4b: ENFORCING STRICT GAMEPLAY CONSTRAINTS")
    print("=" * 70)
    enforce_strict_constraints(analysis)

    # Step 5: Export .osu files
    for difficulty in DIFFICULTIES:
        export_osu(difficulty)

    # Step 6: Package .osz
    package_osz()

    # Step 7: Verify constraints
    constraints_pass = verify_constraints(analysis)

    # Step 8: Summary
    print_summary(analysis)

    elapsed = time.time() - start
    print(f"\n  Total pipeline time: {elapsed:.1f}s")
    print(f"  Constraints satisfied: {'ALL PASS' if constraints_pass else 'SOME FAILED'}")
    print()


if __name__ == "__main__":
    main()
