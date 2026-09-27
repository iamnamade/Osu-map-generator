from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, ensure_parent_directory, write_json
from .hitobject_converter import osu_to_project_beatmap
from .models import OsuImportReport, OsuImportResult
from .parser import parse_osu_file
from .report_writer import write_import_report
from .validator import validate_parsed_osu_beatmap, validate_project_beatmap_compatibility


def import_osu_file(
    *,
    input_path: Path,
    output_path: Path,
    unsupported_mode: str = "reject",
) -> OsuImportResult:
    if unsupported_mode not in {"reject", "skip"}:
        raise MapGeneratorError("--unsupported must be either reject or skip.")
    parsed = parse_osu_file(input_path)
    validation = validate_parsed_osu_beatmap(parsed)
    beatmap, warnings = osu_to_project_beatmap(
        parsed,
        source_filename=input_path.name,
        output_path=output_path.as_posix(),
        skip_unsupported=unsupported_mode == "skip",
    )
    raw_output = beatmap.to_dict()
    compatibility_warnings = validate_project_beatmap_compatibility(raw_output)
    if compatibility_warnings:
        raise MapGeneratorError("Imported project beatmap failed compatibility validation:\n" + "\n".join(compatibility_warnings))
    write_json(output_path, raw_output)
    report = OsuImportReport(
        source_osu_path=input_path.as_posix(),
        format_version=parsed.format_version,
        sections_found=parsed.sections_found,
        metadata={
            "title": beatmap.title,
            "artist": beatmap.artist,
            "version": parsed.metadata.get("Version", "Imported"),
            "creator": parsed.metadata.get("Creator"),
            "audioFilename": parsed.general.get("AudioFilename", ""),
        },
        circle_count=len(parsed.circles),
        slider_count=len(parsed.sliders),
        spinner_count=len(parsed.spinners),
        hold_count=sum(1 for item in parsed.unsupported_hit_objects if item.kind == "hold"),
        unsupported_count=len(parsed.unsupported_hit_objects),
        skipped_count=(
            len(parsed.sliders) + len(parsed.unsupported_hit_objects)
            if unsupported_mode == "skip"
            else 0
        ),
        timing_point_count=len(parsed.timing_points),
        conversion_warnings=[*warnings, *compatibility_warnings],
        output_json_path=output_path.as_posix(),
        validation=validation,
    )
    write_import_report(_derive_import_report_path(output_path), report)
    _update_imported_manifest_if_needed(output_path, beatmap)
    return OsuImportResult(beatmap=beatmap, report=report)


def _derive_import_report_path(output_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "public" / "imports" / "reports" / f"{output_path.stem}-import.json"


def _update_imported_manifest_if_needed(output_path: Path, beatmap: Any) -> None:
    project_root = Path(__file__).resolve().parents[3]
    imported_root = (project_root / "public" / "maps" / "imported").resolve()
    try:
        relative_output = output_path.resolve().relative_to(imported_root)
    except ValueError:
        return
    if relative_output.parts and len(relative_output.parts) > 1:
        return
    manifest_path = imported_root / "index.json"
    manifest = {
        "version": 1,
        "maps": [],
    }
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("maps"), list):
                manifest = existing
        except (OSError, json.JSONDecodeError):
            manifest = {"version": 1, "maps": []}
    maps = [
        item
        for item in manifest.get("maps", [])
        if isinstance(item, dict) and item.get("path") != f"/maps/imported/{relative_output.name}"
    ]
    maps.append(
        {
            "id": f"imported-{relative_output.stem}",
            "label": beatmap.title,
            "path": f"/maps/imported/{relative_output.name}",
            "kind": "imported",
            "group": "Imported Maps",
            "description": f"Imported circle-only osu!standard map for {beatmap.title}.",
            "difficulty": _infer_manifest_difficulty(beatmap),
            "analysisPath": "/analysis/test-song-analysis.json"
            if beatmap.audio == "/audio/test-song.mp3"
            else None,
            "importReportPath": f"/imports/reports/{relative_output.stem}-import.json",
        }
    )
    manifest["maps"] = sorted(maps, key=lambda item: str(item.get("label", "")).lower())
    ensure_parent_directory(manifest_path)
    write_json(manifest_path, manifest)


def _infer_manifest_difficulty(beatmap: Any) -> str | None:
    if not isinstance(beatmap.extra_fields, dict):
        return None
    osu_data = beatmap.extra_fields.get("osu")
    if not isinstance(osu_data, dict):
        return None
    version_name = osu_data.get("beatmapVersion")
    if not isinstance(version_name, str):
        return None
    lowered = version_name.lower()
    if "easy" in lowered:
        return "easy"
    if "hard" in lowered:
        return "hard"
    if "normal" in lowered:
        return "normal"
    return None
