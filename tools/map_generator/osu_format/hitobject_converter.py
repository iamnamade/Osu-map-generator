from __future__ import annotations

from typing import Any

from ..utils import MapGeneratorError
from .difficulty_converter import ar_to_project_approach_time, circle_size_to_project_radius
from .models import (
    OSU_CURVE_LETTERS,
    OsuCircleHitObject,
    OsuSliderHitObject,
    OsuSpinnerHitObject,
    ParsedOsuBeatmap,
    ProjectBeatmap,
    ProjectCircleObject,
    ProjectHitObject,
    ProjectSliderObject,
    ProjectSpinnerObject,
)
from .timing_converter import browser_audio_path_from_osu_filename


def project_objects_to_osu_circles(objects: list[ProjectCircleObject]) -> list[OsuCircleHitObject]:
    ordered = sorted(objects, key=lambda item: (item.time, item.id))
    seen_ids: set[int] = set()
    previous_time = -1
    output: list[OsuCircleHitObject] = []
    for item in ordered:
        if item.id in seen_ids:
            raise MapGeneratorError("Every exported hit object must keep a unique integer id.")
        if item.time <= previous_time:
            raise MapGeneratorError("Exported .osu hit objects must be strictly increasing in time.")
        if not (0 <= item.x <= 512 and 0 <= item.y <= 384):
            raise MapGeneratorError(f"Hit object {item.id} is outside the 512x384 playfield.")
        previous_time = item.time
        seen_ids.add(item.id)
        osu_metadata = item.extra_fields.get("osu")
        hit_sound = (
            int(osu_metadata.get("hitSound"))
            if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("hitSound"), int)
            else 0
        )
        hit_sample = (
            _normalize_hit_sample(str(osu_metadata.get("hitSample")))
            if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("hitSample"), str)
            else "0:0:0:0:"
        )
        new_combo = (
            bool(osu_metadata.get("newCombo"))
            if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("newCombo"), bool)
            else False
        )
        type_flags = 1 | (4 if new_combo else 0)
        output.append(
            OsuCircleHitObject(
                x=item.x,
                y=item.y,
                time=item.time,
                type_flags=type_flags,
                hit_sound=hit_sound,
                hit_sample=hit_sample,
                new_combo=new_combo,
                raw_line="",
            )
        )
    return output


def project_objects_to_osu_hit_objects(
    objects: list[ProjectHitObject],
) -> list[OsuCircleHitObject | OsuSliderHitObject | OsuSpinnerHitObject]:
    """Convert project objects (circles, sliders, spinners) into .osu lines."""
    ordered = sorted(objects, key=lambda item: (item.time, item.id))
    seen_ids: set[int] = set()
    previous_time = -1
    output: list[OsuCircleHitObject | OsuSliderHitObject | OsuSpinnerHitObject] = []
    for item in ordered:
        if item.id in seen_ids:
            raise MapGeneratorError("Every exported hit object must keep a unique integer id.")
        if item.time <= previous_time:
            raise MapGeneratorError("Exported .osu hit objects must be strictly increasing in time.")
        previous_time = item.time
        seen_ids.add(item.id)
        osu_metadata = item.extra_fields.get("osu")
        hit_sound = _read_hit_sound(osu_metadata)
        new_combo = (
            bool(osu_metadata.get("newCombo"))
            if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("newCombo"), bool)
            else False
        )
        if isinstance(item, ProjectSpinnerObject):
            type_flags = 8 | (4 if new_combo else 0)
            # Enforce integer timestamps and strict endTime > time.
            spinner_time = int(round(item.time))
            spinner_end_time = int(round(item.end_time))
            if spinner_end_time <= spinner_time:
                spinner_end_time = spinner_time + 1000  # 1-second minimum
            output.append(
                OsuSpinnerHitObject(
                    time=spinner_time,
                    end_time=spinner_end_time,
                    type_flags=type_flags,
                    hit_sound=hit_sound,
                    new_combo=new_combo,
                    raw_line="",
                )
            )
        elif isinstance(item, ProjectSliderObject):
            # Clamp coordinates into the playfield.
            slider_x = max(0.0, min(512.0, float(item.x)))
            slider_y = max(0.0, min(384.0, float(item.y)))
            # Ensure pixel_length is positive to avoid zero-length sliders.
            pixel_length = max(1.0, float(item.pixel_length)) if item.pixel_length is not None else 1.0
            # Ensure slider end_time is valid and integer.
            slider_end_time = int(round(item.end_time))
            slider_time = int(round(item.time))
            if slider_end_time <= slider_time:
                slider_end_time = slider_time + max(100, int(pixel_length))
            type_flags = 2 | (4 if new_combo else 0)
            output.append(
                OsuSliderHitObject(
                    x=slider_x,
                    y=slider_y,
                    time=slider_time,
                    type_flags=type_flags,
                    hit_sound=hit_sound,
                    curve_type=item.path_type,
                    control_points=[
                        (
                            max(0, min(512, int(pt[0]))),
                            max(0, min(384, int(pt[1]))),
                        )
                        for pt in item.control_points
                    ],
                    repeats=max(1, item.repeats),
                    pixel_length=pixel_length,
                    new_combo=new_combo,
                    raw_line="",
                    end_time=slider_end_time,
                )
            )
        else:
            if not (0 <= item.x <= 512 and 0 <= item.y <= 384):
                raise MapGeneratorError(f"Hit object {item.id} is outside the 512x384 playfield.")
            hit_sample = (
                _normalize_hit_sample(str(osu_metadata.get("hitSample")))
                if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("hitSample"), str)
                else "0:0:0:0:"
            )
            type_flags = 1 | (4 if new_combo else 0)
            output.append(
                OsuCircleHitObject(
                    x=item.x,
                    y=item.y,
                    time=int(round(item.time)),
                    type_flags=type_flags,
                    hit_sound=hit_sound,
                    hit_sample=hit_sample,
                    new_combo=new_combo,
                    raw_line="",
                )
            )
    return output


def _read_hit_sound(osu_metadata: Any) -> int:
    if isinstance(osu_metadata, dict) and isinstance(osu_metadata.get("hitSound"), int):
        return int(osu_metadata.get("hitSound"))
    return 0


def _with_sequential_id(item: ProjectHitObject, new_id: int) -> ProjectHitObject:
    """Return a copy of the project object with a renumbered sequential id."""
    if isinstance(item, ProjectSpinnerObject):
        return ProjectSpinnerObject(
            id=new_id,
            time=item.time,
            end_time=item.end_time,
            extra_fields=dict(item.extra_fields),
        )
    if isinstance(item, ProjectSliderObject):
        return ProjectSliderObject(
            id=new_id,
            x=item.x,
            y=item.y,
            time=item.time,
            end_time=item.end_time,
            path_type=item.path_type,
            control_points=list(item.control_points),
            repeats=item.repeats,
            pixel_length=item.pixel_length,
            extra_fields=dict(item.extra_fields),
        )
    return ProjectCircleObject(
        id=new_id,
        x=item.x,
        y=item.y,
        time=item.time,
        extra_fields=dict(item.extra_fields),
    )


def osu_to_project_beatmap(
    parsed: ParsedOsuBeatmap,
    *,
    source_filename: str,
    output_path: str,
    skip_unsupported: bool,
) -> tuple[ProjectBeatmap, list[str]]:
    warnings = list(parsed.warnings)
    # Sliders parse successfully but are not importable yet (the project
    # format only supports circles + spinners). Preserve the legacy rejection
    # so import behavior is unchanged.
    slider_count = len(parsed.sliders)
    if slider_count > 0 and not skip_unsupported:
        raise MapGeneratorError(
            f"Unsupported hit object types were found: {slider_count} slider{'s' if slider_count != 1 else ''}. "
            "Re-run with --unsupported skip to import circles and spinners only."
        )
    if slider_count > 0 and skip_unsupported:
        warnings.append(
            f"Skipped {slider_count} slider{'s' if slider_count != 1 else ''} while importing circles only."
        )
    unsupported_count = len(parsed.unsupported_hit_objects)
    if unsupported_count > 0 and not skip_unsupported:
        raise MapGeneratorError(_build_unsupported_reject_message(parsed))
    if unsupported_count > 0 and skip_unsupported:
        warnings.append(
            f"Skipped {unsupported_count} unsupported hit object{'s' if unsupported_count != 1 else ''} while importing circles only."
        )

    title = parsed.metadata.get("Title", "").strip() or "Imported Beatmap"
    artist = parsed.metadata.get("Artist", "").strip() or "Unknown Artist"
    version = parsed.metadata.get("Version", "").strip() or "Imported"
    audio_filename = parsed.general.get("AudioFilename", "").strip()
    if not audio_filename:
        raise MapGeneratorError("AudioFilename is required.")
    approach_rate = _parse_optional_float(parsed.difficulty.get("ApproachRate"))
    overall_difficulty = _parse_optional_float(parsed.difficulty.get("OverallDifficulty"))
    circle_size = _parse_optional_float(parsed.difficulty.get("CircleSize"))
    if circle_size is None:
        raise MapGeneratorError("CircleSize is required for circle-only import.")
    approach_time = ar_to_project_approach_time(approach_rate if approach_rate is not None else overall_difficulty if overall_difficulty is not None else 5.0)
    circle_radius = circle_size_to_project_radius(circle_size)
    project_objects: list[ProjectHitObject] = [
        ProjectCircleObject(
            id=index + 1,
            x=item.x,
            y=item.y,
            time=item.time,
            extra_fields={
                "osu": {
                    "hitSound": item.hit_sound,
                    "hitSample": item.hit_sample,
                    "newCombo": item.new_combo,
                    "typeFlags": item.type_flags,
                }
            },
        )
        for index, item in enumerate(parsed.circles)
    ]
    for index, item in enumerate(parsed.spinners):
        project_objects.append(
            ProjectSpinnerObject(
                id=len(parsed.circles) + index + 1,
                time=item.time,
                end_time=item.end_time,
                extra_fields={
                    "osu": {
                        "hitSound": item.hit_sound,
                        "newCombo": item.new_combo,
                        "typeFlags": item.type_flags,
                    }
                },
            )
        )
    # Keep the imported object list sorted by time so ids stay sequential for
    # downstream structural validation, matching exported map ordering.
    project_objects.sort(key=lambda item: (item.time, item.id))
    project_objects = [
        _with_sequential_id(item, new_id)
        for new_id, item in enumerate(project_objects, start=1)
    ]
    beatmap = ProjectBeatmap(
        title=title,
        artist=artist,
        audio=browser_audio_path_from_osu_filename(audio_filename),
        approach_time=approach_time,
        circle_radius=circle_radius,
        objects=project_objects,
        extra_fields={
            "osu": {
                "formatVersion": parsed.format_version,
                "sourceFilename": source_filename,
                "creator": parsed.metadata.get("Creator"),
                "beatmapVersion": version,
                "source": parsed.metadata.get("Source"),
                "tags": parsed.metadata.get("Tags"),
                "titleUnicode": parsed.metadata.get("TitleUnicode"),
                "artistUnicode": parsed.metadata.get("ArtistUnicode"),
                "beatmapId": parsed.metadata.get("BeatmapID"),
                "beatmapSetId": parsed.metadata.get("BeatmapSetID"),
                "audioFilename": audio_filename,
                "backgroundFilename": parsed.background_filename,
                "general": dict(parsed.general),
                "editor": dict(parsed.editor),
                "metadata": dict(parsed.metadata),
                "difficulty": dict(parsed.difficulty),
                "colours": list(parsed.colours),
                "events": list(parsed.events),
                "importWarnings": list(warnings),
                "outputJsonPath": output_path,
            }
        },
    )
    return beatmap, warnings


def _build_unsupported_reject_message(parsed: ParsedOsuBeatmap) -> str:
    counts = {
        "slider": sum(1 for item in parsed.unsupported_hit_objects if item.kind == "slider"),
        "hold": sum(1 for item in parsed.unsupported_hit_objects if item.kind == "hold"),
        "unknown": sum(1 for item in parsed.unsupported_hit_objects if item.kind == "unknown"),
    }
    fragments = [
        f"{counts['slider']} slider{'s' if counts['slider'] != 1 else ''}" if counts["slider"] else "",
        f"{counts['hold']} hold object{'s' if counts['hold'] != 1 else ''}" if counts["hold"] else "",
        f"{counts['unknown']} unknown object{'s' if counts['unknown'] != 1 else ''}" if counts["unknown"] else "",
    ]
    filtered = [item for item in fragments if item]
    if not filtered:
        return "Unsupported hit object types were found."
    return f"Unsupported hit object types were found: {', '.join(filtered)}. Re-run with --unsupported skip to import circles and spinners only."


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _normalize_hit_sample(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return "0:0:0:0:"
    parts = trimmed.split(":")
    while len(parts) < 5:
        parts.append("")
    return ":".join(parts[:5])
