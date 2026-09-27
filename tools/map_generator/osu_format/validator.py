from __future__ import annotations

from pathlib import Path

from ..utils import MapGeneratorError
from .models import ParsedOsuBeatmap, UnsupportedOsuObjectKind, OsuValidationResult
from .parser import parse_osu_file
from .timing_converter import normalize_osu_relative_path


def validate_osu_file(path: Path) -> OsuValidationResult:
    return validate_parsed_osu_beatmap(parse_osu_file(path))


def validate_parsed_osu_beatmap(parsed: ParsedOsuBeatmap) -> OsuValidationResult:
    warnings = list(parsed.warnings)
    if parsed.format_version <= 0:
        warnings.append("The format header version is invalid.")
    for required_section in ["General", "Metadata", "Difficulty", "TimingPoints", "HitObjects"]:
        if required_section not in parsed.sections_found:
            warnings.append(f"Required section [{required_section}] is missing.")
    audio_filename = parsed.general.get("AudioFilename", "").strip()
    if not audio_filename:
        warnings.append("AudioFilename is required.")
    else:
        try:
            normalize_osu_relative_path(audio_filename)
        except MapGeneratorError as error:
            warnings.append(str(error))
    difficulty_fields = [
        "HPDrainRate",
        "CircleSize",
        "OverallDifficulty",
        "ApproachRate",
        "SliderMultiplier",
        "SliderTickRate",
    ]
    for field_name in difficulty_fields:
        if _parse_optional_float(parsed.difficulty.get(field_name)) is None:
            warnings.append(f"Difficulty field {field_name} is missing or invalid.")
    if not parsed.timing_points:
        warnings.append("At least one timing point is required.")

    for circle in parsed.circles:
        if not (0 <= circle.x <= 512 and 0 <= circle.y <= 384):
            warnings.append(f"Circle at {circle.time}ms is out of bounds.")
        if circle.time < 0:
            warnings.append("Hit object times must be non-negative.")

    for slider in parsed.sliders:
        if not (0 <= slider.x <= 512 and 0 <= slider.y <= 384):
            warnings.append(f"Slider at {slider.time}ms is out of bounds.")
        if slider.time < 0:
            warnings.append("Hit object times must be non-negative.")
        if slider.repeats < 1:
            warnings.append(f"Slider at {slider.time}ms must have at least one repeat.")
        if slider.pixel_length <= 0:
            warnings.append(f"Slider at {slider.time}ms must have a positive length.")
        for point_index, (point_x, point_y) in enumerate(slider.control_points):
            if not (0 <= point_x <= 512 and 0 <= point_y <= 384):
                warnings.append(
                    f"Slider at {slider.time}ms control point {point_index} is out of bounds."
                )

    for spinner in parsed.spinners:
        if spinner.time < 0 or spinner.end_time < 0:
            warnings.append("Spinner times must be non-negative.")
        if spinner.end_time <= spinner.time:
            warnings.append(f"Spinner at {spinner.time}ms must end after it starts.")

    # Ordering and duplicate detection must interleave circles, sliders, and
    # spinners so an object between two others never triggers a spurious
    # "not sorted" warning.
    merged_hit_objects = [
        *[(circle.time, circle.raw_line) for circle in parsed.circles],
        *[(slider.time, slider.raw_line) for slider in parsed.sliders],
        *[(spinner.time, spinner.raw_line) for spinner in parsed.spinners],
    ]
    merged_hit_objects.sort(key=lambda item: item[0])
    seen_lines: set[str] = set()
    previous_time = -1
    for hit_time, raw_line in merged_hit_objects:
        if hit_time < previous_time:
            warnings.append("Hit objects are not sorted by time.")
        previous_time = hit_time
        if raw_line in seen_lines:
            warnings.append(f"Duplicate hit object line detected at {hit_time}ms.")
        seen_lines.add(raw_line)

    return OsuValidationResult(
        valid=len(warnings) == 0,
        warnings=warnings,
        unsupported_counts=_count_unsupported_kinds(parsed),
    )


def validate_project_beatmap_compatibility(raw_map: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    required_map_keys = {
        "title": str,
        "artist": str,
        "audio": str,
        "approachTime": int,
        "circleRadius": int,
        "objects": list,
    }
    for key, expected_type in required_map_keys.items():
        value = raw_map.get(key)
        if not isinstance(value, expected_type):
            warnings.append(f"Project beatmap field {key} is missing or invalid.")
    objects = raw_map.get("objects")
    if not isinstance(objects, list) or not objects:
        warnings.append("Project beatmap must contain at least one hit object.")
        return warnings

    seen_ids: set[int] = set()
    seen_times: set[int] = set()
    for index, item in enumerate(objects, start=1):
        if not isinstance(item, dict):
            warnings.append(f"Hit object {index} is not an object.")
            continue
        object_id = item.get("id")
        object_type = item.get("type")
        x = item.get("x")
        y = item.get("y")
        time = item.get("time")
        if not isinstance(object_id, int):
            warnings.append(f"Hit object {index} id is invalid.")
            continue
        if object_id in seen_ids:
            warnings.append(f"Hit object {object_id} is duplicated.")
        seen_ids.add(object_id)
        if object_type not in ("circle", "slider", "spinner"):
            warnings.append(f"Hit object {object_id} uses unsupported type {object_type!r}.")
            continue
        if object_type == "slider":
            end_time = item.get("endTime")
            path_type = item.get("pathType")
            control_points = item.get("controlPoints")
            repeats = item.get("repeats")
            pixel_length = item.get("pixelLength")
            if (
                not isinstance(x, int)
                or not isinstance(y, int)
                or not isinstance(time, int)
                or not isinstance(end_time, int)
            ):
                warnings.append(f"Hit object {object_id} has invalid coordinate or time values.")
                continue
            if not (0 <= x <= 512 and 0 <= y <= 384):
                warnings.append(f"Hit object {object_id} is outside the 512x384 playfield.")
            if time < 0:
                warnings.append(f"Hit object {object_id} has a negative target time.")
            if not isinstance(path_type, str) or not isinstance(repeats, int) or not isinstance(pixel_length, int):
                warnings.append(f"Hit object {object_id} has invalid slider geometry fields.")
            if not isinstance(control_points, list) or not control_points:
                warnings.append(f"Hit object {object_id} must contain control points.")
            if time in seen_times:
                warnings.append(f"Hit object {object_id} duplicates a timestamp at {time}ms.")
            seen_times.add(time)
            continue
        if object_type == "spinner":
            end_time = item.get("endTime")
            if not isinstance(time, int) or not isinstance(end_time, int):
                warnings.append(f"Hit object {object_id} has invalid time or endTime values.")
                continue
            if end_time <= time:
                warnings.append(f"Hit object {object_id} spinner endTime must be after its start.")
            if time < 0:
                warnings.append(f"Hit object {object_id} has a negative target time.")
            if time in seen_times:
                warnings.append(f"Hit object {object_id} duplicates a timestamp at {time}ms.")
            seen_times.add(time)
            continue
        if not isinstance(x, int) or not isinstance(y, int) or not isinstance(time, int):
            warnings.append(f"Hit object {object_id} has invalid coordinate or time values.")
            continue
        if not (0 <= x <= 512 and 0 <= y <= 384):
            warnings.append(f"Hit object {object_id} is outside the 512x384 playfield.")
        if time < 0:
            warnings.append(f"Hit object {object_id} has a negative target time.")
        if time in seen_times:
            warnings.append(f"Hit object {object_id} duplicates a timestamp at {time}ms.")
        seen_times.add(time)
    return warnings


def _count_unsupported_kinds(parsed: ParsedOsuBeatmap) -> dict[UnsupportedOsuObjectKind, int]:
    counts: dict[UnsupportedOsuObjectKind, int] = {
        "slider": 0,
        "spinner": 0,
        "hold": 0,
        "unknown": 0,
    }
    for item in parsed.unsupported_hit_objects:
        counts[item.kind] += 1
    return counts


def _parse_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed
