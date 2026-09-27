from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

UnsupportedObjectMode = Literal["reject", "skip"]
UnsupportedOsuObjectKind = Literal["slider", "spinner", "hold", "unknown"]


@dataclass(frozen=True)
class ProjectCircleObject:
    id: int
    x: int
    y: int
    time: int
    extra_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra_fields,
            "id": self.id,
            "type": "circle",
            "x": self.x,
            "y": self.y,
            "time": self.time,
        }


@dataclass(frozen=True)
class ProjectSpinnerObject:
    id: int
    time: int
    end_time: int
    extra_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra_fields,
            "id": self.id,
            "type": "spinner",
            "time": self.time,
            "endTime": self.end_time,
        }


@dataclass(frozen=True)
class ProjectSliderObject:
    id: int
    x: int
    y: int
    time: int
    end_time: int
    path_type: str
    control_points: list[tuple[int, int]]
    repeats: int
    pixel_length: int
    extra_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra_fields,
            "id": self.id,
            "type": "slider",
            "x": self.x,
            "y": self.y,
            "time": self.time,
            "endTime": self.end_time,
            "pathType": self.path_type,
            "controlPoints": [
                {"x": point[0], "y": point[1]} for point in self.control_points
            ],
            "repeats": self.repeats,
            "pixelLength": self.pixel_length,
        }


ProjectHitObject = ProjectCircleObject | ProjectSliderObject | ProjectSpinnerObject


@dataclass(frozen=True)
class ProjectBeatmap:
    title: str
    artist: str
    audio: str
    approach_time: int
    circle_radius: int
    objects: list[ProjectHitObject]
    extra_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra_fields,
            "title": self.title,
            "artist": self.artist,
            "audio": self.audio,
            "approachTime": self.approach_time,
            "circleRadius": self.circle_radius,
            "objects": [item.to_dict() for item in self.objects],
        }


@dataclass(frozen=True)
class OsuTimingPoint:
    time: int
    beat_length: float
    meter: int
    sample_set: int
    sample_index: int
    volume: int
    uninherited: int
    effects: int

    def to_line(self) -> str:
        beat_length_value = round(self.beat_length, 2)
        beat_length_string = (
            f"{beat_length_value:.0f}"
            if float(beat_length_value).is_integer()
            else f"{beat_length_value}"
        )
        return ",".join(
            [
                str(self.time),
                beat_length_string,
                str(self.meter),
                str(self.sample_set),
                str(self.sample_index),
                str(self.volume),
                str(self.uninherited),
                str(self.effects),
            ]
        )


@dataclass(frozen=True)
class OsuCircleHitObject:
    x: int
    y: int
    time: int
    type_flags: int
    hit_sound: int
    hit_sample: str
    new_combo: bool
    raw_line: str

    def to_line(self) -> str:
        return ",".join(
            [
                str(self.x),
                str(self.y),
                str(self.time),
                str(self.type_flags),
                str(self.hit_sound),
                self.hit_sample,
            ]
        )


@dataclass(frozen=True)
class OsuSpinnerHitObject:
    time: int
    end_time: int
    type_flags: int
    hit_sound: int
    new_combo: bool
    raw_line: str

    def to_line(self) -> str:
        return ",".join(
            [
                str(256),
                str(192),
                str(self.time),
                str(self.type_flags),
                str(self.hit_sound),
                str(self.end_time),
            ]
        )


# osu! curve type letters used in slider hit object lines.
OSU_CURVE_LETTERS: dict[str, str] = {
    "linear": "L",
    "bezier": "B",
    "catmull": "C",
    "perfect": "P",
}
OSU_CURVE_TYPES: dict[str, str] = {letter: name for name, letter in OSU_CURVE_LETTERS.items()}


@dataclass(frozen=True)
class OsuSliderHitObject:
    x: int
    y: int
    time: int
    type_flags: int
    hit_sound: int
    curve_type: str
    control_points: list[tuple[int, int]]
    repeats: int
    pixel_length: float
    new_combo: bool
    raw_line: str
    end_time: int | None = None

    def to_line(self) -> str:
        curve_letter = OSU_CURVE_LETTERS.get(self.curve_type, "B")
        point_spec = "|".join(f"{px}:{py}" for px, py in self.control_points)
        length = (
            f"{self.pixel_length:.0f}"
            if float(self.pixel_length).is_integer()
            else f"{self.pixel_length}"
        )
        return ",".join(
            [
                str(self.x),
                str(self.y),
                str(self.time),
                str(self.type_flags),
                str(self.hit_sound),
                f"{curve_letter}|{point_spec}",
                str(self.repeats),
                length,
            ]
        )


@dataclass(frozen=True)
class OsuUnsupportedHitObject:
    kind: UnsupportedOsuObjectKind
    line_index: int
    line: str
    time: int | None
    type_flags: int


@dataclass(frozen=True)
class ParsedOsuBeatmap:
    format_version: int
    sections_found: list[str]
    general: dict[str, str]
    editor: dict[str, str]
    metadata: dict[str, str]
    difficulty: dict[str, str]
    events: list[str]
    timing_points: list[OsuTimingPoint]
    colours: list[str]
    circles: list[OsuCircleHitObject]
    spinners: list[OsuSpinnerHitObject] = field(default_factory=list)
    sliders: list[OsuSliderHitObject] = field(default_factory=list)
    unsupported_hit_objects: list[OsuUnsupportedHitObject] = field(default_factory=list)
    extra_sections: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    background_filename: str | None = None


@dataclass(frozen=True)
class OsuValidationResult:
    valid: bool
    warnings: list[str]
    unsupported_counts: dict[UnsupportedOsuObjectKind, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "warnings": list(self.warnings),
            "unsupportedCounts": dict(self.unsupported_counts),
        }


@dataclass(frozen=True)
class OsuDifficultyValues:
    hp_drain_rate: float
    circle_size: float
    overall_difficulty: float
    approach_rate: float
    slider_multiplier: float
    slider_tick_rate: float

    def to_dict(self) -> dict[str, float]:
        return {
            "hpDrainRate": self.hp_drain_rate,
            "circleSize": self.circle_size,
            "overallDifficulty": self.overall_difficulty,
            "approachRate": self.approach_rate,
            "sliderMultiplier": self.slider_multiplier,
            "sliderTickRate": self.slider_tick_rate,
        }


@dataclass(frozen=True)
class OsuExportReport:
    source_json_path: str
    output_osu_path: str
    title: str
    artist: str
    version: str
    object_count: int
    bpm: float
    offset_ms: int
    difficulty_values: OsuDifficultyValues
    warnings: list[str]
    unsupported_project_features: list[str]
    validation: OsuValidationResult
    filename: str
    audio_filename: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "sourceJsonPath": self.source_json_path,
            "outputOsuPath": self.output_osu_path,
            "title": self.title,
            "artist": self.artist,
            "difficultyVersion": self.version,
            "objectCount": self.object_count,
            "bpm": round(self.bpm, 3),
            "offsetMs": self.offset_ms,
            "difficultyValues": self.difficulty_values.to_dict(),
            "warnings": list(self.warnings),
            "unsupportedProjectFeatures": list(self.unsupported_project_features),
            "validation": self.validation.to_dict(),
            "filename": self.filename,
            "audioFilename": self.audio_filename,
        }


@dataclass(frozen=True)
class OsuImportReport:
    source_osu_path: str
    format_version: int
    sections_found: list[str]
    metadata: dict[str, Any]
    circle_count: int
    slider_count: int
    spinner_count: int
    hold_count: int
    unsupported_count: int
    skipped_count: int
    timing_point_count: int
    conversion_warnings: list[str]
    output_json_path: str
    validation: OsuValidationResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "sourceOsuPath": self.source_osu_path,
            "formatVersion": self.format_version,
            "sectionsFound": list(self.sections_found),
            "metadata": self.metadata,
            "circleCount": self.circle_count,
            "sliderCount": self.slider_count,
            "spinnerCount": self.spinner_count,
            "holdCount": self.hold_count,
            "unsupportedCount": self.unsupported_count,
            "skippedCount": self.skipped_count,
            "timingPointCount": self.timing_point_count,
            "conversionWarnings": list(self.conversion_warnings),
            "outputJsonPath": self.output_json_path,
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class OsuExportResult:
    text: str
    report: OsuExportReport


@dataclass(frozen=True)
class OsuImportResult:
    beatmap: ProjectBeatmap
    report: OsuImportReport


@dataclass(frozen=True)
class OsuMapsetExportEntry:
    map_path: str
    osu_path: str
    report_path: str


@dataclass(frozen=True)
class OsuMapsetExportResult:
    entries: list[OsuMapsetExportEntry]
    package_path: str | None


@dataclass(frozen=True)
class OszPackageResult:
    output_path: str
    archived_files: list[str]


@dataclass
class OsuWriterSections:
    general: dict[str, str] = field(default_factory=dict)
    editor: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    difficulty: dict[str, str] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    timing_points: list[OsuTimingPoint] = field(default_factory=list)
    colours: list[str] = field(default_factory=list)
    hit_objects: list[OsuCircleHitObject | OsuSliderHitObject | OsuSpinnerHitObject] = field(default_factory=list)
