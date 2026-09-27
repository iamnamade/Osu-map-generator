from __future__ import annotations

from pathlib import Path

from ..utils import MapGeneratorError, ensure_existing_file
from .models import (
    OSU_CURVE_TYPES,
    OsuCircleHitObject,
    OsuSliderHitObject,
    OsuSpinnerHitObject,
    OsuTimingPoint,
    OsuUnsupportedHitObject,
    ParsedOsuBeatmap,
)


def parse_osu_file(path: Path) -> ParsedOsuBeatmap:
    osu_file = ensure_existing_file(path, "osu beatmap file")
    try:
        text = osu_file.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise MapGeneratorError(f"Could not read osu beatmap file from {path}: {error}") from error
    return parse_osu_text(text)


def parse_osu_text(text: str) -> ParsedOsuBeatmap:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header_line = next((line.strip() for line in lines if line.strip()), "")
    if not header_line:
        raise MapGeneratorError("The .osu file is empty.")
    lowered_header = header_line.lower()
    if not lowered_header.startswith("osu file format v"):
        raise MapGeneratorError("The .osu file is missing a valid format header.")
    try:
        format_version = int(header_line.split("v", maxsplit=1)[1].strip())
    except (IndexError, ValueError) as error:
        raise MapGeneratorError("The .osu file format header is malformed.") from error

    sections_found: list[str] = []
    section_set: set[str] = set()
    general: dict[str, str] = {}
    editor: dict[str, str] = {}
    metadata: dict[str, str] = {}
    difficulty: dict[str, str] = {}
    events: list[str] = []
    timing_points: list[OsuTimingPoint] = []
    colours: list[str] = []
    circles: list[OsuCircleHitObject] = []
    sliders: list[OsuSliderHitObject] = []
    spinners: list[OsuSpinnerHitObject] = []
    unsupported_hit_objects: list[OsuUnsupportedHitObject] = []
    extra_sections: dict[str, list[str]] = {}
    warnings: list[str] = []
    background_filename: str | None = None
    current_section = ""

    for line_index, raw_line in enumerate(lines, start=1):
        trimmed = raw_line.strip()
        if not trimmed or trimmed.startswith("//"):
            continue
        if trimmed.lower().startswith("osu file format v"):
            continue
        if trimmed.startswith("[") and trimmed.endswith("]"):
            current_section = trimmed[1:-1].strip()
            if current_section not in section_set:
                sections_found.append(current_section)
                section_set.add(current_section)
            if current_section not in {
                "General",
                "Editor",
                "Metadata",
                "Difficulty",
                "Events",
                "TimingPoints",
                "Colours",
                "HitObjects",
            }:
                extra_sections.setdefault(current_section, [])
            continue

        if current_section == "General":
            _parse_key_value_line(raw_line, general, current_section, line_index)
        elif current_section == "Editor":
            _parse_key_value_line(raw_line, editor, current_section, line_index)
        elif current_section == "Metadata":
            _parse_key_value_line(raw_line, metadata, current_section, line_index)
        elif current_section == "Difficulty":
            _parse_key_value_line(raw_line, difficulty, current_section, line_index)
        elif current_section == "Events":
            events.append(raw_line)
            if background_filename is None:
                background_filename = _parse_background_filename(raw_line)
        elif current_section == "TimingPoints":
            timing_points.append(_parse_timing_point(raw_line, line_index))
        elif current_section == "Colours":
            colours.append(trimmed)
        elif current_section == "HitObjects":
            parsed_object = _parse_hit_object(raw_line, line_index)
            if isinstance(parsed_object, OsuCircleHitObject):
                circles.append(parsed_object)
            elif isinstance(parsed_object, OsuSliderHitObject):
                sliders.append(parsed_object)
            elif isinstance(parsed_object, OsuSpinnerHitObject):
                spinners.append(parsed_object)
            else:
                unsupported_hit_objects.append(parsed_object)
        else:
            if current_section:
                extra_sections.setdefault(current_section, []).append(raw_line)
            else:
                warnings.append(f"Ignored line outside a section at line {line_index}.")

    circles.sort(key=lambda item: (item.time, item.x, item.y))
    sliders.sort(key=lambda item: (item.time, item.x, item.y))
    spinners.sort(key=lambda item: item.time)
    return ParsedOsuBeatmap(
        format_version=format_version,
        sections_found=sections_found,
        general=general,
        editor=editor,
        metadata=metadata,
        difficulty=difficulty,
        events=events,
        timing_points=timing_points,
        colours=colours,
        circles=circles,
        sliders=sliders,
        spinners=spinners,
        unsupported_hit_objects=unsupported_hit_objects,
        extra_sections=extra_sections,
        warnings=warnings,
        background_filename=background_filename,
    )


def _parse_key_value_line(
    raw_line: str,
    output: dict[str, str],
    section_name: str,
    line_index: int,
) -> None:
    separator_index = raw_line.find(":")
    if separator_index < 0:
        raise MapGeneratorError(f"[{section_name}] line {line_index} is missing a key/value separator.")
    key = raw_line[:separator_index].strip()
    value = raw_line[separator_index + 1 :].strip()
    if not key:
        raise MapGeneratorError(f"[{section_name}] line {line_index} is missing a key.")
    output[key] = value


def _parse_timing_point(raw_line: str, line_index: int) -> OsuTimingPoint:
    fields = [field.strip() for field in raw_line.split(",")]
    if len(fields) < 8:
        raise MapGeneratorError(f"[TimingPoints] line {line_index} is incomplete.")
    return OsuTimingPoint(
        time=_parse_required_integer(fields[0], f"[TimingPoints] line {line_index} time"),
        beat_length=_parse_required_number(fields[1], f"[TimingPoints] line {line_index} beatLength"),
        meter=_parse_required_integer(fields[2], f"[TimingPoints] line {line_index} meter"),
        sample_set=_parse_required_integer(fields[3], f"[TimingPoints] line {line_index} sampleSet"),
        sample_index=_parse_required_integer(fields[4], f"[TimingPoints] line {line_index} sampleIndex"),
        volume=_parse_required_integer(fields[5], f"[TimingPoints] line {line_index} volume"),
        uninherited=_parse_required_integer(fields[6], f"[TimingPoints] line {line_index} uninherited"),
        effects=_parse_required_integer(fields[7], f"[TimingPoints] line {line_index} effects"),
    )


def _parse_hit_object(
    raw_line: str, line_index: int
) -> OsuCircleHitObject | OsuSliderHitObject | OsuSpinnerHitObject | OsuUnsupportedHitObject:
    fields = [field.strip() for field in raw_line.split(",")]
    if len(fields) < 5:
        raise MapGeneratorError(f"[HitObjects] line {line_index} is incomplete.")
    x = _parse_required_integer(fields[0], f"[HitObjects] line {line_index} x")
    y = _parse_required_integer(fields[1], f"[HitObjects] line {line_index} y")
    time = _parse_required_integer(fields[2], f"[HitObjects] line {line_index} time")
    type_flags = _parse_required_integer(fields[3], f"[HitObjects] line {line_index} type")
    hit_sound = _parse_required_integer(fields[4], f"[HitObjects] line {line_index} hitSound")
    is_circle = (type_flags & 1) != 0
    is_slider = (type_flags & 2) != 0
    is_spinner = (type_flags & 8) != 0
    is_hold = (type_flags & 128) != 0
    if is_circle and not is_slider and not is_spinner and not is_hold:
        hit_sample = _normalize_hit_sample(",".join(fields[5:]) if len(fields) > 5 else "0:0:0:0:")
        return OsuCircleHitObject(
            x=x,
            y=y,
            time=time,
            type_flags=type_flags,
            hit_sound=hit_sound,
            hit_sample=hit_sample,
            new_combo=(type_flags & 4) != 0,
            raw_line=raw_line,
        )
    if is_slider and not is_circle and not is_spinner and not is_hold:
        if len(fields) < 8:
            raise MapGeneratorError(
                f"[HitObjects] line {line_index} is incomplete (slider curve data missing)."
            )
        curve_spec = fields[5]
        slides = _parse_required_integer(fields[6], f"[HitObjects] line {line_index} slides")
        pixel_length = _parse_required_number(fields[7], f"[HitObjects] line {line_index} length")
        curve_type, control_points = _parse_slider_curve(curve_spec, line_index)
        return OsuSliderHitObject(
            x=x,
            y=y,
            time=time,
            type_flags=type_flags,
            hit_sound=hit_sound,
            curve_type=curve_type,
            control_points=control_points,
            repeats=slides,
            pixel_length=pixel_length,
            new_combo=(type_flags & 4) != 0,
            raw_line=raw_line,
        )
    if is_spinner and not is_slider and not is_circle and not is_hold:
        if len(fields) < 6:
            raise MapGeneratorError(f"[HitObjects] line {line_index} is incomplete (spinner end time missing).")
        end_time = _parse_required_integer(fields[5], f"[HitObjects] line {line_index} endTime")
        return OsuSpinnerHitObject(
            time=time,
            end_time=end_time,
            type_flags=type_flags,
            hit_sound=hit_sound,
            new_combo=(type_flags & 4) != 0,
            raw_line=raw_line,
        )
    return OsuUnsupportedHitObject(
        kind="slider"
        if is_slider
        else "hold"
        if is_hold
        else "unknown",
        line_index=line_index,
        line=raw_line,
        time=time,
        type_flags=type_flags,
    )


def _parse_slider_curve(spec: str, line_index: int) -> tuple[str, list[tuple[int, int]]]:
    """Parse a slider curve spec like ``B|100:100|200:200``."""
    parts = [part.strip() for part in spec.split("|")]
    if not parts or len(parts[0]) != 1 or not parts[0].isalpha():
        raise MapGeneratorError(f"[HitObjects] line {line_index} has an invalid slider curve type.")
    letter = parts[0].upper()
    curve_type = OSU_CURVE_TYPES.get(letter, "bezier")
    control_points: list[tuple[int, int]] = []
    for part in parts[1:]:
        if not part:
            continue
        coordinates = part.split(":")
        if len(coordinates) != 2:
            raise MapGeneratorError(f"[HitObjects] line {line_index} has a malformed slider control point.")
        control_points.append(
            (
                _parse_required_integer(coordinates[0], f"[HitObjects] line {line_index} curve x"),
                _parse_required_integer(coordinates[1], f"[HitObjects] line {line_index} curve y"),
            )
        )
    if not control_points:
        raise MapGeneratorError(f"[HitObjects] line {line_index} slider has no control points.")
    return curve_type, control_points


def _parse_background_filename(raw_line: str) -> str | None:
    fields = [field.strip() for field in raw_line.split(",")]
    if len(fields) < 3 or fields[0] != "0":
        return None
    raw_filename = fields[2].strip('"')
    return raw_filename.strip() or None


def _normalize_hit_sample(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return "0:0:0:0:"
    parts = trimmed.split(":")
    while len(parts) < 5:
        parts.append("")
    return ":".join(parts[:5])


def _parse_required_number(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise MapGeneratorError(f"{label} must be numeric.") from error
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise MapGeneratorError(f"{label} must be finite.")
    return parsed


def _parse_required_integer(value: str, label: str) -> int:
    parsed = _parse_required_number(value, label)
    if not float(parsed).is_integer():
        raise MapGeneratorError(f"{label} must be an integer.")
    return int(parsed)
