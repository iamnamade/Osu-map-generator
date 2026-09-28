#!/usr/bin/env python3
"""End-to-end beatmap generation: analyze audio, generate 3 difficulties,
export .osu files, and package into .osz."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = SCRIPT_DIR.parent.parent  # tools/
PROJECT_ROOT = TOOLS_ROOT.parent       # project root

# Add project root to sys.path so imports work
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
from tools.map_generator.osu_format.export_pipeline import (
    export_osu_file,
)
from tools.map_generator.osu_format.mapset_packager import (
    package_osz_archive,
)
from tools.map_generator.postprocess import improve_beatmap
from tools.map_generator.utils import write_json
from tools.map_generator.validation import validate_beatmap

# ── Configuration ──────────────────────────────────────────────────────
AUDIO_PATH = PROJECT_ROOT / "public" / "audio" / "test-song.mp3"
WORKSPACE_ROOT = TOOLS_ROOT / ".tmp-e2e-generation" / "e2e-slider-test"
DIFFICULTIES = ["easy", "normal", "hard"]
TITLE = "Test Song"
ARTIST = "Unit Test"
CREATOR = "osu-map-ai"
ROOT_SEED = 42


def build_dirs(root: Path) -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for name in [
        "analysis",
        "maps/generated", "maps/improved",
        "reports/generated", "reports/improved",
        "exports/osu",
        "exports/mapset",
        "exports/mapsets",
    ]:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        dirs[name] = d
    return dirs


def count_objects(data: dict) -> tuple[int, int, int]:
    objs = data.get("objects", [])
    circles = sum(1 for o in objs if o.get("type") == "circle")
    sliders = sum(1 for o in objs if o.get("type") == "slider")
    total = len(objs)
    return total, circles, sliders


def print_counts(label: str, data: dict) -> None:
    total, circles, sliders = count_objects(data)
    ratio = sliders / total * 100 if total else 0
    print(f"{label} {total} objects ({circles} circles, {sliders} sliders, {ratio:.1f}%)")


def _run_pipeline() -> int:
    t0 = time.monotonic()

    dirs = build_dirs(WORKSPACE_ROOT)
    analysis_path = dirs["analysis"] / "analysis.json"

    # ── Stage 1: Analyze audio + load raw samples ──────────────────────
    print(f"[1/6] Analyzing audio: {AUDIO_PATH.name}")
    analysis = analyze_audio(AUDIO_PATH)
    write_json(analysis_path, analysis.to_dict())

    raw_samples, raw_sample_rate = _load_audio(AUDIO_PATH)
    print(f"      -> {analysis_path}  ({analysis.duration_ms} ms, {len(raw_samples)} samples)")

    # ── Stage 2: Generate base maps for each difficulty ────────────────
    print(f"\n[2/6] Generating base maps ({', '.join(DIFFICULTIES)})")
    for difficulty in DIFFICULTIES:
        preset = get_difficulty_preset(difficulty)
        controls = resolve_mapping_controls("balanced", None)
        adjusted = apply_mapping_controls(preset, controls)
        print(f"      [debug] {difficulty}: slider_min_ratio={getattr(adjusted, 'slider_min_ratio', 'MISSING')}, slider_max_ratio={adjusted.slider_max_ratio}")
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
            browser_audio_path_override=f"/public/audio/{AUDIO_PATH.name}",
        )
        if hasattr(gen_result, 'warnings') and gen_result.warnings:
            for w in gen_result.warnings:
                print(f"      WARNING: {w}")
        data = json.loads(out.read_text(encoding="utf-8"))
        print_counts("->", data)

    # ── Stage 2b: Validate base maps (needed by improve_beatmap) ──────
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
        print("OK")

    # ── Stage 3: Post-process (improve) each difficulty ────────────────
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
        print_counts("->", data)

    # ── Stage 4: Export .osu files ─────────────────────────────────────
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

    # ── Stage 5: Package .osz ──────────────────────────────────────────
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
    print(f"      -> {osz_path}")
    print(f"      Archived: {', '.join(result.archived_files)}")

    # ── Stage 6: Summary ──────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    print(f"\n[6/6] Done in {elapsed:.1f}s\n")
    print("=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)
    for difficulty in DIFFICULTIES:
        imp_map = dirs["maps/improved"] / f"{difficulty}.json"
        data = json.loads(imp_map.read_text(encoding="utf-8"))
        total, circles, sliders = count_objects(data)
        ratio = sliders / total * 100 if total else 0
        min_ratio = 35.0 if difficulty in ("normal", "hard") else 15.0
        status = "OK" if ratio >= min_ratio else f"LOW (need {min_ratio:.0f}%)"
        print(f"  {difficulty:8s}: {total:4d} objects | {circles:4d} circles | {sliders:4d} sliders | {ratio:5.1f}% slider ratio [{status}]")
    print("=" * 60)
    print(f"\n  .osz output: {osz_path}")
    print(f"  Import this file directly into osu! via File > Import.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full generation end-to-end harness.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the .tmp-e2e-generation scratch directory for inspection.",
    )
    args = parser.parse_args(argv)

    # P2.2: clear the transient workspace before and after the run so repeated
    # harness executions do not leak tools/.tmp-e2e-generation.
    if not args.keep:
        shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)
    try:
        return _run_pipeline()
    finally:
        if not args.keep:
            shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
