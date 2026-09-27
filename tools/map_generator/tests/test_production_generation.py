#!/usr/bin/env python3
"""Production beatmap generation: run full pipeline on a real song,
export .osu files and package .osz for direct import into osu!."""
from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = SCRIPT_DIR.parent.parent
PROJECT_ROOT = TOOLS_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.map_generator.audio_analyzer import analyze_audio, _load_audio
from tools.map_generator.beatmap_generator import generate_beatmap_from_analysis
from tools.map_generator.config import get_difficulty_preset
from tools.map_generator.generation_config import (
    apply_mapping_controls,
    build_position_variation_biases,
    resolve_mapping_controls,
)
from tools.map_generator.osu_format.export_pipeline import export_osu_file
from tools.map_generator.osu_format.mapset_packager import package_osz_archive
from tools.map_generator.postprocess import improve_beatmap
from tools.map_generator.utils import write_json
from tools.map_generator.validation import validate_beatmap

# ── Configuration ──────────────────────────────────────────────────────
AUDIO_PATH = PROJECT_ROOT / "workspaces" / "eecb8987-a5d0-4202-8f99-96f11cb4dc0f" / "source" / "source-audio.mp3"
WORKSPACE_ROOT = PROJECT_ROOT / "exports" / "dagdagani-beatmap"
DIFFICULTIES = ["easy", "normal", "hard"]
TITLE = "dagdagani"
ARTIST = "dagdagani"
CREATOR = "osu-map-ai"
ROOT_SEED = 42

# Slider ratio targets
SLIDER_TARGETS = {
    "easy":   {"min": 15.0, "max": 40.0},
    "normal": {"min": 30.0, "max": 50.0},
    "hard":   {"min": 30.0, "max": 55.0},
}

# Density targets (objects per second of active audio)
DENSITY_TARGETS = {
    "easy":   {"min": 0.6, "target": 1.0},
    "normal": {"min": 1.0, "target": 1.6},
    "hard":   {"min": 1.8, "target": 3.0},
}


def build_dirs(root: Path) -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for name in [
        "analysis",
        "maps/generated", "maps/improved",
        "reports/generated", "reports/improved",
        "exports/osu", "exports/mapset", "exports/mapsets",
    ]:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        dirs[name] = d
    return dirs


def count_objects(data: dict) -> dict:
    objs = data.get("objects", [])
    circles = sum(1 for o in objs if o.get("type") == "circle")
    sliders = sum(1 for o in objs if o.get("type") == "slider")
    spinners = sum(1 for o in objs if o.get("type") == "spinner")
    total = len(objs)
    return {
        "total": total,
        "circles": circles,
        "sliders": sliders,
        "spinners": spinners,
        "slider_pct": sliders / total * 100 if total else 0,
        "spinner_pct": spinners / total * 100 if total else 0,
    }


def compute_density(data: dict, analysis_data: dict) -> float:
    """Compute objects per second of active audio."""
    objs = data.get("objects", [])
    if len(objs) < 2:
        return 0.0
    active_ms = objs[-1]["time"] - objs[0]["time"]
    active_s = active_ms / 1000.0
    return len(objs) / active_s if active_s > 0 else 0.0


def print_counts(label: str, counts: dict) -> None:
    print(
        f"{label} {counts['total']:3d} objects "
        f"({counts['circles']:3d} circles, {counts['sliders']:3d} sliders, "
        f"{counts['spinners']:2d} spinners, "
        f"{counts['slider_pct']:5.1f}% sliders)"
    )


def main() -> int:
    t0 = time.monotonic()

    dirs = build_dirs(WORKSPACE_ROOT)
    analysis_path = dirs["analysis"] / "analysis.json"

    # ── Stage 1: Analyze audio ──────────────────────────────────────────
    print(f"[1/6] Analyzing audio: {AUDIO_PATH.name}")
    if not AUDIO_PATH.exists():
        print(f"  ERROR: Audio file not found: {AUDIO_PATH}")
        return 1
    analysis = analyze_audio(AUDIO_PATH)
    write_json(analysis_path, analysis.to_dict())

    raw_samples, raw_sample_rate = _load_audio(AUDIO_PATH)
    duration_s = analysis.duration_ms / 1000.0
    print(f"      -> {analysis_path}  ({duration_s:.1f}s, {len(raw_samples)} samples, {analysis.bpm:.0f} BPM)")

    # ── Stage 2: Generate base maps ─────────────────────────────────────
    print(f"\n[2/6] Generating base maps ({', '.join(DIFFICULTIES)})")
    for difficulty in DIFFICULTIES:
        preset = get_difficulty_preset(difficulty)
        controls = resolve_mapping_controls("balanced", None)
        adjusted = apply_mapping_controls(preset, controls)
        variation = build_position_variation_biases(controls)
        out = dirs["maps/generated"] / f"{difficulty}.json"
        print(f"      {difficulty}... ", end="", flush=True)
        gen_result = generate_beatmap_from_analysis(
            analysis=analysis,
            audio_path=AUDIO_PATH,
            title=TITLE,
            artist=ARTIST,
            difficulty=difficulty,
            seed=ROOT_SEED,
            output_path=out,
            analysis_output_path=None,
            project_root=PROJECT_ROOT,
            preset=adjusted,
            base_variation=variation,
            raw_samples=raw_samples,
            raw_sample_rate=raw_sample_rate,
            browser_audio_path_override=f"/source/source-audio.mp3",
        )
        if gen_result.warnings:
            for w in gen_result.warnings:
                print(f"\n        WARNING: {w}")
        data = json.loads(out.read_text(encoding="utf-8"))
        counts = count_objects(data)
        density = compute_density(data, analysis.to_dict())
        print_counts("->", counts)
        # Check slider ratio
        t = SLIDER_TARGETS[difficulty]
        slider_ok = t["min"] <= counts["slider_pct"] <= t["max"]
        slider_flag = "OK" if slider_ok else f"OUTSIDE [{t['min']:.0f}-{t['max']:.0f}%]"
        print(f"        density: {density:.2f} obj/s, slider ratio: {counts['slider_pct']:.1f}% [{slider_flag}]")

    # ── Stage 2b: Validate base maps ────────────────────────────────────
    print(f"\n[2b/6] Validating base maps")
    for difficulty in DIFFICULTIES:
        gen_map = dirs["maps/generated"] / f"{difficulty}.json"
        gen_report = dirs["reports/generated"] / f"{difficulty}-report.json"
        print(f"      {difficulty}... ", end="", flush=True)
        validate_beatmap(
            map_path=gen_map,
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=gen_report,
            map_label=f"maps/generated/{difficulty}.json",
        )
        # Quick report summary
        rpt = json.loads(gen_report.read_text(encoding="utf-8"))
        score = rpt.get("overallScore", rpt.get("overall_score", "?"))
        print(f"OK (score: {score})")

    # ── Stage 3: Post-process (improve) ─────────────────────────────────
    print(f"\n[3/6] Post-processing (improvement pass)")
    for difficulty in DIFFICULTIES:
        gen_map = dirs["maps/generated"] / f"{difficulty}.json"
        gen_report = dirs["reports/generated"] / f"{difficulty}-report.json"
        imp_map = dirs["maps/improved"] / f"{difficulty}.json"
        imp_report = dirs["reports/improved"] / f"{difficulty}-report.json"
        imp_changes = dirs["reports/improved"] / f"{difficulty}-changes.json"
        preset = get_difficulty_preset(difficulty)
        controls = resolve_mapping_controls("balanced", None)
        preset = apply_mapping_controls(preset, controls)
        print(f"      {difficulty}... ", end="", flush=True)
        improve_beatmap(
            map_path=gen_map,
            analysis_path=analysis_path,
            report_path=gen_report,
            difficulty=difficulty,
            seed=ROOT_SEED,
            output_path=imp_map,
            report_output_path=imp_report,
            changes_output_path=imp_changes,
            source_map_label=f"maps/generated/{difficulty}.json",
            output_map_label=f"maps/improved/{difficulty}.json",
            preset=preset,
        )
        data = json.loads(imp_map.read_text(encoding="utf-8"))
        counts = count_objects(data)
        density = compute_density(data, analysis.to_dict())
        print_counts("->", counts)
        t = SLIDER_TARGETS[difficulty]
        slider_ok = t["min"] <= counts["slider_pct"] <= t["max"]
        slider_flag = "OK" if slider_ok else f"OUTSIDE [{t['min']:.0f}-{t['max']:.0f}%]"
        d = DENSITY_TARGETS[difficulty]
        density_ok = density >= d["min"]
        density_flag = "OK" if density_ok else f"LOW (target {d['min']:.1f}+ obj/s)"
        print(f"        slider: {counts['slider_pct']:.1f}% [{slider_flag}], density: {density:.2f} obj/s [{density_flag}]")

    # ── Stage 4: Export .osu files ───────────────────────────────────────
    print(f"\n[4/6] Exporting .osu files")
    osu_dir = dirs["exports/osu"]
    osu_files = []
    for difficulty in DIFFICULTIES:
        imp_map = dirs["maps/improved"] / f"{difficulty}.json"
        version = difficulty.capitalize()
        osu_name = f"{ARTIST} - {TITLE} ({CREATOR}) [{version}].osu"
        osu_path = osu_dir / osu_name
        export_osu_file(
            map_path=imp_map,
            analysis_path=analysis_path,
            output_path=osu_path,
            creator=CREATOR,
            version_name=version,
        )
        osu_files.append(osu_path)
        line_count = len(osu_path.read_text(encoding="utf-8").splitlines())
        print(f"      -> {osu_name}  ({line_count} lines)")

    # ── Stage 5: Package .osz ────────────────────────────────────────────
    print(f"\n[5/6] Packaging .osz archive")
    mapset_name = f"{ARTIST} - {TITLE}"
    mapset_dir = dirs["exports/mapset"] / mapset_name
    mapset_dir.mkdir(parents=True, exist_ok=True)
    audio_copy = mapset_dir / AUDIO_PATH.name
    shutil.copy2(AUDIO_PATH, audio_copy)
    for osu in osu_files:
        shutil.copy2(osu, mapset_dir / osu.name)

    osz_path = dirs["exports/mapsets"] / f"{mapset_name}.osz"
    result = package_osz_archive(
        maps_dir=mapset_dir,
        audio_path=audio_copy,
        output_path=osz_path,
    )
    osz_size_kb = osz_path.stat().st_size / 1024
    print(f"      -> {osz_path}  ({osz_size_kb:.0f} KB)")
    print(f"      Archived: {', '.join(result.archived_files)}")

    # ── Stage 6: Summary ────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    print(f"\n[6/6] Done in {elapsed:.1f}s\n")

    print("=" * 72)
    print("  FINAL RESULTS")
    print("=" * 72)
    print(f"  Song: {ARTIST} - {TITLE} ({duration_s:.1f}s, {analysis.bpm:.0f} BPM)")
    print(f"  Audio: {AUDIO_PATH.name}")
    print("-" * 72)
    all_ok = True
    for difficulty in DIFFICULTIES:
        imp_map = dirs["maps/improved"] / f"{difficulty}.json"
        data = json.loads(imp_map.read_text(encoding="utf-8"))
        counts = count_objects(data)
        density = compute_density(data, analysis.to_dict())
        t = SLIDER_TARGETS[difficulty]
        d = DENSITY_TARGETS[difficulty]
        slider_ok = t["min"] <= counts["slider_pct"] <= t["max"]
        density_ok = d["min"] <= density <= d["target"] * 1.5
        status = "OK" if (slider_ok and density_ok) else "FAIL"
        if not (slider_ok and density_ok):
            all_ok = False
        print(
            f"  {difficulty:8s}: {counts['total']:3d} obj | "
            f"{counts['circles']:3d} circles | {counts['sliders']:3d} sliders | "
            f"{counts['spinners']:2d} spinners | "
            f"slider={counts['slider_pct']:5.1f}% [{t['min']:.0f}-{t['max']:.0f}%] | "
            f"density={density:.2f} obj/s [{d['min']:.1f}+ target] | "
            f"{status}"
        )
    print("-" * 72)
    verdict = "ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"
    print(f"  Verdict: {verdict}")
    print(f"  .osz output: {osz_path}")
    print(f"  Import into osu! via File > Import.\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
