from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, ensure_existing_file


@dataclass(frozen=True)
class DifficultyObject:
    id: int
    object_type: str
    time: int
    x: float | None = None
    y: float | None = None
    end_time: int | None = None
    repeats: int | None = None
    pixel_length: float | None = None
    control_points: list[tuple[float, float]] = field(default_factory=list)

    @property
    def is_positioned(self) -> bool:
        return self.object_type in ("circle", "slider") and self.x is not None and self.y is not None

    @property
    def duration_ms(self) -> int:
        if self.end_time is None:
            return 0
        return max(0, self.end_time - self.time)


@dataclass(frozen=True)
class LoadedDifficultyMap:
    title: str
    artist: str
    audio: str
    approach_time_ms: int
    circle_radius: int
    objects: list[DifficultyObject]
    generator: dict[str, Any] | None = None

    @property
    def object_count(self) -> int:
        return len(self.objects)


def load_difficulty_map(map_path: Path, *, map_label: str | None = None) -> LoadedDifficultyMap:
    map_file = ensure_existing_file(map_path, "Beatmap file")
    try:
        raw_map = json.loads(map_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MapGeneratorError(f"Beatmap JSON is malformed: {map_file}: {error.msg}") from error
    if not isinstance(raw_map, dict):
        raise MapGeneratorError(f"Beatmap root must be a JSON object: {map_file}")

    title = _string_field(raw_map, "title")
    artist = _string_field(raw_map, "artist")
    audio = _string_field(raw_map, "audio")
    approach_time = _int_field(raw_map, "approachTime")
    circle_radius = _int_field(raw_map, "circleRadius")

    raw_objects = raw_map.get("objects")
    if not isinstance(raw_objects, list):
        raise MapGeneratorError(f"Beatmap objects must be a list: {map_file}")

    objects: list[DifficultyObject] = []
    for raw_object in raw_objects:
        if not isinstance(raw_object, dict):
            raise MapGeneratorError(f"Beatmap object must be a JSON object: {map_file}")
        object_id = _int_field(raw_object, "id")
        object_type = _string_field(raw_object, "type")
        time = _int_field(raw_object, "time")
        if object_type not in ("circle", "slider", "spinner"):
            raise MapGeneratorError(f"Unsupported object type {object_type!r} in {map_file}")
        x = _optional_number(raw_object, "x")
        y = _optional_number(raw_object, "y")
        end_time = _optional_int(raw_object, "endTime")
        repeats = _optional_int(raw_object, "repeats")
        pixel_length = _optional_number(raw_object, "pixelLength")
        control_points = _optional_control_points(raw_object)
        objects.append(
            DifficultyObject(
                id=object_id,
                object_type=object_type,
                time=time,
                x=x,
                y=y,
                end_time=end_time,
                repeats=repeats,
                pixel_length=pixel_length,
                control_points=control_points,
            )
        )

    objects.sort(key=lambda item: (item.time, item.id))
    generator = raw_map.get("generator")
    if generator is not None and not isinstance(generator, dict):
        generator = None
    return LoadedDifficultyMap(
        title=title,
        artist=artist,
        audio=audio,
        approach_time_ms=approach_time,
        circle_radius=circle_radius,
        objects=objects,
        generator=generator,
    )


def load_difficulty_map_from_dict(
    raw_map: dict[str, Any],
    *,
    map_label: str,
) -> LoadedDifficultyMap:
    """Load from an in-memory dict (used by the editor live engine tests)."""
    title = _string_field(raw_map, "title")
    artist = _string_field(raw_map, "artist")
    audio = _string_field(raw_map, "audio")
    approach_time = _int_field(raw_map, "approachTime")
    circle_radius = _int_field(raw_map, "circleRadius")
    raw_objects = raw_map.get("objects")
    if not isinstance(raw_objects, list):
        raise MapGeneratorError(f"Beatmap objects must be a list: {map_label}")
    objects: list[DifficultyObject] = []
    for raw_object in raw_objects:
        if not isinstance(raw_object, dict):
            continue
        try:
            objects.append(
                DifficultyObject(
                    id=_int_field(raw_object, "id"),
                    object_type=_string_field(raw_object, "type"),
                    time=_int_field(raw_object, "time"),
                    x=_optional_number(raw_object, "x"),
                    y=_optional_number(raw_object, "y"),
                    end_time=_optional_int(raw_object, "endTime"),
                    repeats=_optional_int(raw_object, "repeats"),
                    pixel_length=_optional_number(raw_object, "pixelLength"),
                    control_points=_optional_control_points(raw_object),
                )
            )
        except MapGeneratorError:
            continue
    objects.sort(key=lambda item: (item.time, item.id))
    return LoadedDifficultyMap(
        title=title,
        artist=artist,
        audio=audio,
        approach_time_ms=approach_time,
        circle_radius=circle_radius,
        objects=objects,
        generator=raw_map.get("generator") if isinstance(raw_map.get("generator"), dict) else None,
    )


def load_song_sections(sections_path: Path | None) -> list[dict[str, Any]]:
    """Load song sections as raw dicts (startMs/endMs/label) or return empty."""
    if sections_path is None:
        return []
    if not sections_path.exists():
        return []
    try:
        payload = json.loads(sections_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return []
    result: list[dict[str, Any]] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        start = item.get("startMs")
        end = item.get("endMs")
        label = item.get("label")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if not isinstance(label, str) or not label.strip():
            label = "Section"
        result.append(
            {
                "sectionId": item.get("id"),
                "label": label,
                "startMs": int(start),
                "endMs": int(end),
            }
        )
    result.sort(key=lambda item: item["startMs"])
    return result


def _string_field(value: dict[str, Any], key: str) -> str:
    field_value = value.get(key)
    if not isinstance(field_value, str) or not field_value.strip():
        raise MapGeneratorError(f"Beatmap {key} must be a non-empty string.")
    return field_value.strip()


def _int_field(value: dict[str, Any], key: str) -> int:
    field_value = value.get(key)
    if not isinstance(field_value, (int, float)):
        raise MapGeneratorError(f"Beatmap {key} must be an integer.")
    numeric = float(field_value)
    if not numeric.is_integer():
        raise MapGeneratorError(f"Beatmap {key} must be an integer.")
    return int(numeric)


def _optional_int(value: dict[str, Any], key: str) -> int | None:
    field_value = value.get(key)
    if field_value is None:
        return None
    if not isinstance(field_value, (int, float)):
        return None
    numeric = float(field_value)
    if not numeric.is_integer():
        return None
    return int(numeric)


def _optional_number(value: dict[str, Any], key: str) -> float | None:
    field_value = value.get(key)
    if not isinstance(field_value, (int, float)):
        return None
    return float(field_value)


def _optional_control_points(value: dict[str, Any]) -> list[tuple[float, float]]:
    raw_points = value.get("controlPoints")
    if not isinstance(raw_points, list):
        return []
    points: list[tuple[float, float]] = []
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append((float(x), float(y)))
    return points
