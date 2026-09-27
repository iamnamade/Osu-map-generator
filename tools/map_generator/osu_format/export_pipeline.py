from __future__ import annotations

from pathlib import Path
from typing import Any

from ...text_utils import build_osu_filename as _shared_build_osu_filename
from ..analysis_io import load_json_file
from ..utils import MapGeneratorError
from .difficulty_converter import convert_project_difficulty_to_osu_values, derive_version_name, infer_project_difficulty
from .hitobject_converter import project_objects_to_osu_hit_objects
from .mapset_packager import package_osz_archive
from .metadata_converter import (
    build_editor_section,
    build_general_section,
    build_metadata_section,
    extract_preserved_colours,
    extract_preserved_sections,
    normalize_optional_text,
    sanitize_key_value_section,
)
from .models import (
    OsuExportReport,
    OsuExportResult,
    OsuMapsetExportEntry,
    OsuMapsetExportResult,
    OsuWriterSections,
    ProjectBeatmap,
    ProjectCircleObject,
    ProjectHitObject,
    ProjectSliderObject,
    ProjectSpinnerObject,
)
from .report_writer import write_export_report
from .timing_converter import build_primary_timing_point, osu_audio_filename_from_browser_path
from .validator import validate_parsed_osu_beatmap
from .writer import write_osu_file, write_osu_text
from .parser import parse_osu_text


def export_osu_file(
    *,
    map_path: Path,
    analysis_path: Path,
    output_path: Path,
    report_output_path: Path | None = None,
    creator: str | None = None,
    version_name: str | None = None,
    beatmap_id: str | int | None = None,
    beatmap_set_id: str | int | None = None,
    background_filename: str | None = None,
    title_unicode: str | None = None,
    artist_unicode: str | None = None,
) -> OsuExportResult:
    beatmap = _load_project_beatmap(map_path)
    osu_creator = creator or _read_nested_string(beatmap.extra_fields, ["osu", "creator"]) or "osu-map-ai"
    difficulty_name = infer_project_difficulty(beatmap)
    osu_version_name = version_name or derive_version_name(beatmap, difficulty_name) or "Imported"
    timing_point, bpm, offset_ms = build_primary_timing_point(analysis_path)
    preserved_sections = extract_preserved_sections(beatmap.extra_fields)
    colours = extract_preserved_colours(beatmap.extra_fields)
    difficulty_values = convert_project_difficulty_to_osu_values(beatmap, difficulty_name)
    hit_objects = project_objects_to_osu_hit_objects(beatmap.objects)
    sections = OsuWriterSections(
        general=build_general_section(
            osu_audio_filename_from_browser_path(beatmap.audio),
            preserved_sections["general"],
        ),
        editor=build_editor_section(preserved_sections["editor"]),
        metadata=build_metadata_section(
            beatmap,
            osu_creator,
            osu_version_name,
            normalize_optional_text(beatmap_id if beatmap_id is not None else _read_nested_value(beatmap.extra_fields, ["osu", "beatmapId"])),
            normalize_optional_text(beatmap_set_id if beatmap_set_id is not None else _read_nested_value(beatmap.extra_fields, ["osu", "beatmapSetId"])),
            preserved_sections["metadata"],
            title_unicode=title_unicode,
            artist_unicode=artist_unicode,
        ),
        difficulty={
            **preserved_sections["difficulty"],
            "HPDrainRate": _fixed_decimal(difficulty_values.hp_drain_rate),
            "CircleSize": _fixed_decimal(difficulty_values.circle_size),
            "OverallDifficulty": _fixed_decimal(difficulty_values.overall_difficulty),
            "ApproachRate": _fixed_decimal(difficulty_values.approach_rate),
            "SliderMultiplier": _fixed_decimal(difficulty_values.slider_multiplier),
            "SliderTickRate": _fixed_decimal(difficulty_values.slider_tick_rate),
        },
        events=[
            f'0,0,"{background_filename}",0,0'
            if background_filename
            else ""
        ]
        if background_filename
        else [],
        timing_points=[timing_point],
        colours=colours,
        hit_objects=hit_objects,
    )
    text = write_osu_text(sections)
    parsed_output = parse_osu_text(text)
    validation = validate_parsed_osu_beatmap(parsed_output)
    warnings: list[str] = []
    if bpm == 120.0:
        warnings.append("No positive BPM estimate was available. Export fell back to 120 BPM.")
    report = OsuExportReport(
        source_json_path=map_path.as_posix(),
        output_osu_path=output_path.as_posix(),
        title=beatmap.title,
        artist=beatmap.artist,
        version=osu_version_name,
        object_count=len(hit_objects),
        bpm=bpm,
        offset_ms=offset_ms,
        difficulty_values=difficulty_values,
        warnings=warnings,
        unsupported_project_features=[],
        validation=validation,
        filename=output_path.name,
        audio_filename=sections.general["AudioFilename"],
    )
    resolved_report_output_path = report_output_path or _derive_export_report_path(output_path)
    write_osu_file(output_path, text)
    write_export_report(resolved_report_output_path, report)
    return OsuExportResult(text=text, report=report)


def export_osu_mapset(
    *,
    maps_dir: Path,
    analysis_path: Path,
    audio_path: Path,
    output_dir: Path,
    package_path: Path | None = None,
) -> OsuMapsetExportResult:
    map_files = sorted(maps_dir.glob("*.json"))
    if not map_files:
        raise MapGeneratorError(f"No project beatmap JSON files were found in {maps_dir}")
    beatmaps = [(path, _load_project_beatmap(path)) for path in map_files]
    first_title = beatmaps[0][1].title
    first_artist = beatmaps[0][1].artist
    first_audio = beatmaps[0][1].audio
    for path, beatmap in beatmaps[1:]:
        if beatmap.title != first_title or beatmap.artist != first_artist or beatmap.audio != first_audio:
            raise MapGeneratorError(
                f"Mapset export requires consistent title, artist, and audio. {path.name} does not match the first selected map."
            )

    planned_exports: list[tuple[Path, Path, str, str]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, beatmap in beatmaps:
        difficulty_name = infer_project_difficulty(beatmap)
        version_name = derive_version_name(beatmap, difficulty_name) or path.stem
        creator = _read_nested_string(beatmap.extra_fields, ["osu", "creator"]) or "osu-map-ai"
        filename = _build_osu_filename(beatmap.artist, beatmap.title, creator, version_name)
        planned_exports.append((path, output_dir / filename, creator, version_name))

    _remove_stale_mapset_outputs(output_dir, {output_path.name for _, output_path, _, _ in planned_exports})

    entries: list[OsuMapsetExportEntry] = []
    for path, output_path, creator, version_name in planned_exports:
        export_osu_file(
            map_path=path,
            analysis_path=analysis_path,
            output_path=output_path,
            creator=creator,
            version_name=version_name,
        )
        entries.append(
            OsuMapsetExportEntry(
                map_path=path.as_posix(),
                osu_path=output_path.as_posix(),
                report_path=_derive_export_report_path(output_path).as_posix(),
            )
        )

    package_result = (
        package_osz_archive(
            maps_dir=output_dir,
            audio_path=audio_path,
            output_path=package_path,
        )
        if package_path is not None
        else None
    )
    return OsuMapsetExportResult(
        entries=entries,
        package_path=package_result.output_path if package_result else None,
    )


def _load_project_beatmap(path: Path) -> ProjectBeatmap:
    raw_data = load_json_file(path, "Project beatmap JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Project beatmap JSON must be an object: {path}")
    title = _required_string(raw_data.get("title"), "title")
    artist = _required_string(raw_data.get("artist"), "artist")
    audio = _required_string(raw_data.get("audio"), "audio")
    approach_time = _required_integer(raw_data.get("approachTime"), "approachTime")
    circle_radius = _required_integer(raw_data.get("circleRadius"), "circleRadius")
    raw_objects = raw_data.get("objects")
    if not isinstance(raw_objects, list) or not raw_objects:
        raise MapGeneratorError(f"Project beatmap must contain at least one object: {path}")
    objects: list[ProjectHitObject] = []
    for index, raw_object in enumerate(raw_objects, start=1):
        if not isinstance(raw_object, dict):
            raise MapGeneratorError(f"Project beatmap object {index} must be an object: {path}")
        object_type = raw_object.get("type")
        if object_type == "spinner":
            objects.append(
                ProjectSpinnerObject(
                    id=_required_integer(raw_object.get("id"), f"objects[{index}].id"),
                    time=_required_integer(raw_object.get("time"), f"objects[{index}].time"),
                    end_time=_required_integer(raw_object.get("endTime"), f"objects[{index}].endTime"),
                    extra_fields=_sanitize_extra_fields(raw_object, {"id", "type", "time", "endTime"}),
                )
            )
        elif object_type == "circle":
            objects.append(
                ProjectCircleObject(
                    id=_required_integer(raw_object.get("id"), f"objects[{index}].id"),
                    x=_required_integer(raw_object.get("x"), f"objects[{index}].x"),
                    y=_required_integer(raw_object.get("y"), f"objects[{index}].y"),
                    time=_required_integer(raw_object.get("time"), f"objects[{index}].time"),
                    extra_fields=_sanitize_extra_fields(raw_object, {"id", "type", "x", "y", "time"}),
                )
            )
        elif object_type == "slider":
            objects.append(
                ProjectSliderObject(
                    id=_required_integer(raw_object.get("id"), f"objects[{index}].id"),
                    x=_required_integer(raw_object.get("x"), f"objects[{index}].x"),
                    y=_required_integer(raw_object.get("y"), f"objects[{index}].y"),
                    time=_required_integer(raw_object.get("time"), f"objects[{index}].time"),
                    end_time=_required_integer(raw_object.get("endTime"), f"objects[{index}].endTime"),
                    path_type=str(raw_object.get("pathType", "bezier")),
                    control_points=_parse_control_points(raw_object.get("controlPoints"), index),
                    repeats=_required_integer(raw_object.get("repeats"), f"objects[{index}].repeats"),
                    pixel_length=_required_integer(raw_object.get("pixelLength"), f"objects[{index}].pixelLength"),
                    extra_fields=_sanitize_extra_fields(
                        raw_object,
                        {"id", "type", "x", "y", "time", "endTime", "pathType", "controlPoints", "repeats", "pixelLength"},
                    ),
                )
            )
        else:
            raise MapGeneratorError(f"Unsupported project object type {object_type!r} in {path}.")
    return ProjectBeatmap(
        title=title,
        artist=artist,
        audio=audio,
        approach_time=approach_time,
        circle_radius=circle_radius,
        objects=objects,
        extra_fields=_sanitize_extra_fields(raw_data, {"title", "artist", "audio", "approachTime", "circleRadius", "objects"}),
    )


def _sanitize_extra_fields(raw_data: dict[str, Any], excluded_keys: set[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in raw_data.items():
        if key in excluded_keys:
            continue
        if _is_json_value(value):
            output[key] = value
    return output


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return float(value) == float(value) and float(value) not in (float("inf"), float("-inf"))
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _read_nested_string(value: dict[str, Any], path: list[str]) -> str | None:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current.strip() if isinstance(current, str) and current.strip() else None


def _read_nested_value(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _required_string(value: Any, label: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise MapGeneratorError(f"Project beatmap field {label} is missing or invalid.")


def _parse_control_points(value: Any, index: int) -> list[tuple[int, int]]:
    if not isinstance(value, list) or not value:
        raise MapGeneratorError(f"Hit object {index} must contain control points.")
    output: list[tuple[int, int]] = []
    for point_index, raw_point in enumerate(value):
        if not isinstance(raw_point, dict):
            raise MapGeneratorError(f"Hit object {index} control point {point_index} must be an object.")
        output.append(
            (
                _required_integer(raw_point.get("x"), f"objects[{index}].controlPoints[{point_index}].x"),
                _required_integer(raw_point.get("y"), f"objects[{index}].controlPoints[{point_index}].y"),
            )
        )
    return output


def _required_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MapGeneratorError(f"Project beatmap field {label} is missing or invalid.")
    numeric = float(value)
    if not numeric.is_integer():
        raise MapGeneratorError(f"Project beatmap field {label} must be an integer.")
    return int(numeric)


def _fixed_decimal(value: float) -> str:
    rounded = round(value, 2)
    return f"{rounded:.0f}" if float(rounded).is_integer() else str(rounded)


def _derive_export_report_path(output_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "public" / "exports" / "reports" / f"{output_path.stem}-export.json"


def _remove_stale_mapset_outputs(output_dir: Path, expected_names: set[str]) -> None:
    for existing_path in output_dir.glob("*.osu"):
        if existing_path.name in expected_names:
            continue
        existing_path.unlink(missing_ok=True)
        _derive_export_report_path(existing_path).unlink(missing_ok=True)


def _build_osu_filename(artist: str, title: str, creator: str, version_name: str) -> str:
    # Delegates to the shared sanitizer so filenames match the local API (I4).
    return _shared_build_osu_filename(artist, title, creator, version_name)
