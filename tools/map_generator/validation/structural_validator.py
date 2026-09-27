from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import DifficultyPreset, DIFFICULTY_PRESETS
from ..models import AudioAnalysis
from ..position_generator import PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from .models import ParsedBeatmap, ParsedBeatmapObject, StructuralMetrics, ValidationIssue


@dataclass(frozen=True)
class StructuralValidationResult:
    parsed_beatmap: ParsedBeatmap | None
    metrics: StructuralMetrics
    issues: list[ValidationIssue]


def validate_structural(
    raw_map: Any,
    *,
    map_path: Path,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
) -> StructuralValidationResult:
    issues: list[ValidationIssue] = []
    non_finite_value_count = _count_non_finite_values(raw_map)
    if non_finite_value_count > 0:
        issues.append(
            ValidationIssue(
                code="NON_FINITE_JSON_VALUE",
                severity="critical",
                message="Beatmap JSON contains NaN or Infinity values.",
                category="structural",
                measured_value=float(non_finite_value_count),
                suggestion="Rewrite the beatmap JSON with finite numeric values only.",
            )
        )

    if not isinstance(raw_map, dict):
        issues.append(
            ValidationIssue(
                code="ROOT_NOT_OBJECT",
                severity="critical",
                message="Beatmap root must be a JSON object.",
                category="structural",
                suggestion="Export the beatmap as an object with metadata and an objects array.",
            )
        )
        return StructuralValidationResult(
            parsed_beatmap=None,
            metrics=StructuralMetrics(
                object_count=0,
                valid_object_count=0,
                duplicate_id_count=0,
                duplicate_timestamp_count=0,
                non_finite_value_count=non_finite_value_count,
            ),
            issues=issues,
        )

    title = _expect_non_empty_string(raw_map.get("title"))
    artist = _expect_non_empty_string(raw_map.get("artist"))
    audio_path = _expect_non_empty_string(raw_map.get("audio"))
    approach_time = _expect_positive_finite_number(raw_map.get("approachTime"))
    circle_radius = _expect_positive_finite_number(raw_map.get("circleRadius"))

    if title is None:
        issues.append(
            ValidationIssue(
                code="MISSING_TITLE",
                severity="critical",
                message="Beatmap title must be a non-empty string.",
                category="structural",
                suggestion="Add a non-empty title field to the beatmap root.",
            )
        )
        title = ""

    if artist is None:
        issues.append(
            ValidationIssue(
                code="MISSING_ARTIST",
                severity="critical",
                message="Beatmap artist must be a non-empty string.",
                category="structural",
                suggestion="Add a non-empty artist field to the beatmap root.",
            )
        )
        artist = ""

    if audio_path is None:
        issues.append(
            ValidationIssue(
                code="MISSING_AUDIO_PATH",
                severity="critical",
                message="Beatmap audio path must be a non-empty string.",
                category="structural",
                suggestion="Set the audio field to a browser path such as /audio/test-song.mp3.",
            )
        )
        audio_path = ""

    if approach_time is None:
        issues.append(
            ValidationIssue(
                code="INVALID_APPROACH_TIME",
                severity="critical",
                message="Approach time must be a finite positive number.",
                category="structural",
                suggestion="Use a positive numeric approachTime value.",
            )
        )
        approach_time = float(preset.approach_time_ms)

    if circle_radius is None:
        issues.append(
            ValidationIssue(
                code="INVALID_CIRCLE_RADIUS",
                severity="critical",
                message="Circle radius must be a finite positive number.",
                category="structural",
                suggestion="Use a positive numeric circleRadius value.",
            )
        )
        circle_radius = float(preset.circle_radius)

    raw_objects = raw_map.get("objects")
    if not isinstance(raw_objects, list):
        issues.append(
            ValidationIssue(
                code="OBJECTS_NOT_LIST",
                severity="critical",
                message="Beatmap objects must be a non-empty list.",
                category="structural",
                suggestion="Write an objects array containing at least one circle.",
            )
        )
        raw_objects = []
    elif len(raw_objects) == 0:
        issues.append(
            ValidationIssue(
                code="OBJECTS_EMPTY",
                severity="critical",
                message="Beatmap contains no hit objects.",
                category="structural",
                suggestion="Generate or author at least one circle object.",
            )
        )

    parsed_objects: list[ParsedBeatmapObject] = []
    seen_ids: set[int] = set()
    seen_times: set[int] = set()
    duplicate_id_count = 0
    duplicate_timestamp_count = 0
    previous_time: int | None = None

    for index, raw_object in enumerate(raw_objects):
        if not isinstance(raw_object, dict):
            issues.append(
                ValidationIssue(
                    code="OBJECT_NOT_OBJECT",
                    severity="critical",
                    message=f"Object {index + 1} must be a JSON object.",
                    category="structural",
                    suggestion="Ensure every hit object is an object with id, type, x, y, and time.",
                )
            )
            continue

        object_id = _expect_integer(raw_object.get("id"))
        object_type = raw_object.get("type")
        x_value = _expect_finite_number(raw_object.get("x"))
        y_value = _expect_finite_number(raw_object.get("y"))
        time_value = _expect_integer(raw_object.get("time"))

        if object_id is None:
            issues.append(
                ValidationIssue(
                    code="INVALID_OBJECT_ID",
                    severity="critical",
                    message=f"Object {index + 1} has an invalid numeric id.",
                    category="structural",
                    suggestion="Use integer object ids starting at 1.",
                )
            )
        elif object_id in seen_ids:
            duplicate_id_count += 1
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_OBJECT_ID",
                    severity="error",
                    message=f"Object id {object_id} is duplicated.",
                    category="structural",
                    object_ids=[object_id],
                    suggestion="Give every object a unique sequential id.",
                )
            )
        else:
            seen_ids.add(object_id)

        if object_type not in ("circle", "slider", "spinner"):
            issues.append(
                ValidationIssue(
                    code="UNSUPPORTED_OBJECT_TYPE",
                    severity="critical",
                    message=f"Object {object_id if object_id is not None else index + 1} must use type 'circle', 'slider', or 'spinner'.",
                    category="structural",
                    object_ids=[object_id] if object_id is not None else [],
                    suggestion="Spinners, sliders, and circles are the supported object types.",
                )
            )

        end_time_value = _expect_integer(raw_object.get("endTime"))
        if object_type == "spinner":
            if end_time_value is None:
                issues.append(
                    ValidationIssue(
                        code="INVALID_SPINNER_END_TIME",
                        severity="critical",
                        message=f"Spinner {object_id if object_id is not None else index + 1} must use an integer endTime.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        suggestion="Add an integer endTime to the spinner object.",
                    )
                )
            elif time_value is not None and end_time_value <= time_value:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_END_BEFORE_START",
                        severity="critical",
                        message=f"Spinner {object_id} endTime must be greater than its start time.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        measured_value=float(end_time_value),
                        allowed_value=float(time_value + 1),
                        suggestion="Set spinner endTime after its start time.",
                    )
                )

        if object_type == "spinner":
            # Spinners have no coordinate fields; skip position checks.
            pass
        elif x_value is None or y_value is None:
            issues.append(
                ValidationIssue(
                    code="INVALID_OBJECT_POSITION",
                    severity="critical",
                    message=f"Object {object_id if object_id is not None else index + 1} must use finite x and y coordinates.",
                    category="structural",
                    object_ids=[object_id] if object_id is not None else [],
                    suggestion="Use finite numeric coordinates inside the playfield.",
                )
            )
        else:
            if x_value < 0 or x_value > PLAYFIELD_WIDTH or y_value < 0 or y_value > PLAYFIELD_HEIGHT:
                issues.append(
                    ValidationIssue(
                        code="OBJECT_OUT_OF_BOUNDS",
                        severity="error",
                        message="Object coordinates must stay inside the 512x384 playfield.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        measured_value=max(
                            abs(min(x_value, 0)),
                            abs(max(x_value - PLAYFIELD_WIDTH, 0)),
                            abs(min(y_value, 0)),
                            abs(max(y_value - PLAYFIELD_HEIGHT, 0)),
                        ),
                        allowed_value=0.0,
                        suggestion="Move the object back into the visible playfield area.",
                    )
                )

        if time_value is None:
            issues.append(
                ValidationIssue(
                    code="INVALID_OBJECT_TIME",
                    severity="critical",
                    message=f"Object {object_id if object_id is not None else index + 1} must use an integer millisecond time.",
                    category="structural",
                    object_ids=[object_id] if object_id is not None else [],
                    suggestion="Use integer millisecond timestamps for every object.",
                )
            )
        else:
            if time_value < 0:
                issues.append(
                    ValidationIssue(
                        code="NEGATIVE_OBJECT_TIME",
                        severity="critical",
                        message=f"Object {object_id} occurs before time zero.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        suggestion="Remove negative timing values from the beatmap.",
                    )
                )

            if time_value in seen_times:
                duplicate_timestamp_count += 1
                issues.append(
                    ValidationIssue(
                        code="DUPLICATE_TIMESTAMP",
                        severity="error",
                        message=f"Multiple objects share timestamp {time_value} ms.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        suggestion="Separate duplicate timestamps or remove the overlap.",
                    )
                )
            else:
                seen_times.add(time_value)

            if previous_time is not None and time_value <= previous_time:
                issues.append(
                    ValidationIssue(
                        code="NON_INCREASING_TIMES",
                        severity="error",
                        message="Object times must be strictly increasing.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        allowed_value=float(previous_time + 1),
                        suggestion="Sort objects by time and remove duplicate or reversed timestamps.",
                    )
                )
            previous_time = time_value

            if time_value > analysis.duration_ms:
                issues.append(
                    ValidationIssue(
                        code="OBJECT_AFTER_AUDIO_DURATION",
                        severity="error",
                        message="Object time exceeds the analyzed audio duration.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        measured_value=float(time_value),
                        allowed_value=float(analysis.duration_ms),
                        suggestion="Move or remove objects that extend beyond the audio.",
                    )
                )

            if object_type == "spinner" and end_time_value is not None and end_time_value > analysis.duration_ms:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_END_AFTER_AUDIO_DURATION",
                        severity="error",
                        message="Spinner endTime exceeds the analyzed audio duration.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        end_time_ms=end_time_value,
                        measured_value=float(end_time_value),
                        allowed_value=float(analysis.duration_ms),
                        suggestion="Shorten the spinner so it ends before the audio finishes.",
                    )
                )

            if time_value < preset.start_padding_ms:
                issues.append(
                    ValidationIssue(
                        code="OBJECT_BEFORE_START_PADDING",
                        severity="warning",
                        message="Object occurs before the configured start padding.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        measured_value=float(time_value),
                        allowed_value=float(preset.start_padding_ms),
                        suggestion="Delay the early object or increase the start padding.",
                    )
                )

            safe_end_limit = max(0, analysis.duration_ms - preset.end_padding_ms)
            if time_value > safe_end_limit:
                issues.append(
                    ValidationIssue(
                        code="OBJECT_AFTER_END_PADDING",
                        severity="warning",
                        message="Object occurs inside the configured end padding window.",
                        category="structural",
                        object_ids=[object_id] if object_id is not None else [],
                        start_time_ms=time_value,
                        measured_value=float(time_value),
                        allowed_value=float(safe_end_limit),
                        suggestion="Pull late objects earlier or reduce outro placement.",
                    )
                )

        if object_type == "spinner":
            if None not in (object_id, time_value, end_time_value):
                parsed_objects.append(
                    ParsedBeatmapObject(
                        id=object_id,
                        type="spinner",
                        time=time_value,
                        end_time=end_time_value,
                        extra_fields=_spinner_extra_fields(raw_object),
                    )
                )
        elif None not in (object_id, x_value, y_value, time_value) and object_type == "circle":
            parsed_objects.append(
                ParsedBeatmapObject(
                    id=object_id,
                    type="circle",
                    x=float(x_value),
                    y=float(y_value),
                    time=time_value,
                )
            )
        elif None not in (object_id, x_value, y_value, time_value) and object_type == "slider":
            parsed_objects.append(
                ParsedBeatmapObject(
                    id=object_id,
                    type="slider",
                    x=float(x_value),
                    y=float(y_value),
                    time=time_value,
                    end_time=end_time_value,
                    path_type=_slider_path_type(raw_object),
                    control_points=_slider_control_points(raw_object),
                    repeats=_expect_integer(raw_object.get("repeats")),
                    pixel_length=_expect_finite_number(raw_object.get("pixelLength")),
                    extra_fields=_slider_extra_fields(raw_object),
                )
            )

    valid_object_ids = [object.id for object in parsed_objects]
    sequential_mismatches = [
        object.id
        for expected_id, object in enumerate(parsed_objects, start=1)
        if object.id != expected_id
    ]
    if sequential_mismatches:
        issues.append(
            ValidationIssue(
                code="NON_SEQUENTIAL_OBJECT_IDS",
                severity="error",
                message="Object ids must be sequential starting from 1.",
                category="structural",
                object_ids=sequential_mismatches[:10],
                suggestion="Rewrite object ids as 1..N without gaps.",
            )
        )

    generator_metadata = raw_map.get("generator")
    if generator_metadata is not None:
        if not isinstance(generator_metadata, dict):
            issues.append(
                ValidationIssue(
                    code="INVALID_GENERATOR_METADATA",
                    severity="error",
                    message="Optional generator metadata must be a JSON object when present.",
                    category="structural",
                    suggestion="Write generator metadata as an object or omit it.",
                )
            )
        else:
            _validate_generator_metadata(generator_metadata, issues)

    beatmap_audio_filename = Path(audio_path).name if audio_path else ""
    if beatmap_audio_filename and beatmap_audio_filename != analysis.audio_filename:
        issues.append(
            ValidationIssue(
                code="AUDIO_ANALYSIS_MISMATCH",
                severity="error",
                message="Beatmap audio path does not appear to match the supplied analysis audio.",
                category="structural",
                measured_value=0.0,
                allowed_value=0.0,
                suggestion="Validate the map against an analysis file generated from the same audio.",
            )
        )

    parsed_beatmap = ParsedBeatmap(
        path=map_path.as_posix(),
        title=title,
        artist=artist,
        audio=audio_path,
        approach_time=float(approach_time),
        circle_radius=float(circle_radius),
        objects=parsed_objects,
        generator=generator_metadata if isinstance(generator_metadata, dict) else None,
    )

    return StructuralValidationResult(
        parsed_beatmap=parsed_beatmap,
        metrics=StructuralMetrics(
            object_count=len(raw_objects),
            valid_object_count=len(parsed_objects),
            duplicate_id_count=duplicate_id_count,
            duplicate_timestamp_count=duplicate_timestamp_count,
            non_finite_value_count=non_finite_value_count,
        ),
        issues=issues,
    )


def _validate_generator_metadata(
    generator_metadata: dict[str, Any],
    issues: list[ValidationIssue],
) -> None:
    name = generator_metadata.get("name")
    version = generator_metadata.get("version")
    difficulty = generator_metadata.get("difficulty")
    seed = generator_metadata.get("seed")

    if name is not None and not isinstance(name, str):
        issues.append(
            ValidationIssue(
                code="INVALID_GENERATOR_NAME",
                severity="warning",
                message="Generator metadata name should be a string.",
                category="structural",
            )
        )

    if version is not None and _expect_integer(version) is None:
        issues.append(
            ValidationIssue(
                code="INVALID_GENERATOR_VERSION",
                severity="warning",
                message="Generator metadata version should be an integer.",
                category="structural",
            )
        )

    if difficulty is not None and difficulty not in DIFFICULTY_PRESETS:
        issues.append(
            ValidationIssue(
                code="INVALID_GENERATOR_DIFFICULTY",
                severity="warning",
                message="Generator difficulty metadata is not recognized.",
                category="structural",
                suggestion="Use easy, normal, or hard in generator metadata.",
            )
        )

    if seed is not None and _expect_integer(seed) is None:
        issues.append(
            ValidationIssue(
                code="INVALID_GENERATOR_SEED",
                severity="warning",
                message="Generator metadata seed should be an integer.",
                category="structural",
            )
        )


def _expect_non_empty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _expect_positive_finite_number(value: Any) -> float | None:
    return numeric_value if (numeric_value := _expect_finite_number(value)) is not None and numeric_value > 0 else None


def _expect_finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None

    numeric_value = float(value)
    return numeric_value if math.isfinite(numeric_value) else None


def _expect_integer(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None

    numeric_value = float(value)
    if not math.isfinite(numeric_value) or not numeric_value.is_integer():
        return None

    return int(numeric_value)


def _spinner_extra_fields(raw_object: dict[str, Any]) -> dict[str, Any]:
    known_keys = {"id", "type", "x", "y", "time", "endTime"}
    return {
        key: value
        for key, value in raw_object.items()
        if key not in known_keys and _is_plain_value(value)
    }


def _slider_path_type(raw_object: dict[str, Any]) -> str | None:
    path_type = raw_object.get("pathType")
    if isinstance(path_type, str) and path_type in ("linear", "bezier", "perfect", "catmull"):
        return path_type
    return None


def _slider_control_points(raw_object: dict[str, Any]) -> list[dict[str, float]]:
    raw_points = raw_object.get("controlPoints")
    if not isinstance(raw_points, list):
        return []
    points: list[dict[str, float]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        x = item.get("x")
        y = item.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append({"x": float(x), "y": float(y)})
    return points


def _slider_extra_fields(raw_object: dict[str, Any]) -> dict[str, Any]:
    known_keys = {
        "id",
        "type",
        "x",
        "y",
        "time",
        "endTime",
        "pathType",
        "controlPoints",
        "repeats",
        "pixelLength",
    }
    return {
        key: value
        for key, value in raw_object.items()
        if key not in known_keys and _is_plain_value(value)
    }


def _is_plain_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str, int, float)):
        return True
    if isinstance(value, list):
        return all(_is_plain_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_plain_value(item) for key, item in value.items())
    return False


def _count_non_finite_values(value: Any) -> int:
    if isinstance(value, (int, float)):
        return 0 if math.isfinite(float(value)) else 1

    if isinstance(value, list):
        return sum(_count_non_finite_values(item) for item in value)

    if isinstance(value, dict):
        return sum(_count_non_finite_values(item) for item in value.values())

    return 0
