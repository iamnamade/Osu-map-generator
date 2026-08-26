from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SelectedEventSource = Literal["beat", "onset", "merged"]


@dataclass(frozen=True)
class TimedStrength:
    time_ms: int
    strength: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeMs": self.time_ms,
            "strength": round(self.strength, 4),
        }


@dataclass(frozen=True)
class EnergyFrame:
    time_ms: int
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeMs": self.time_ms,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class EnergyRegion:
    start_ms: int
    end_ms: int
    average_value: float

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms <= self.end_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "averageValue": round(self.average_value, 4),
        }


@dataclass(frozen=True)
class AudioAnalysis:
    audio_filename: str
    duration_ms: int
    sample_rate: int
    bpm: float
    offset_ms: int
    beats: list[TimedStrength]
    onsets: list[TimedStrength]
    energy_frames: list[EnergyFrame]
    quiet_regions: list[EnergyRegion]
    high_energy_regions: list[EnergyRegion]
    analysis_version: int = 1
    enhanced: dict[str, Any] | None = None

    def energy_at(self, time_ms: int) -> float:
        if not self.energy_frames:
            return 0.0

        closest_frame = min(
            self.energy_frames,
            key=lambda frame: abs(frame.time_ms - time_ms),
        )
        return closest_frame.value

    def in_quiet_region(self, time_ms: int) -> bool:
        return any(region.contains(time_ms) for region in self.quiet_regions)

    def in_high_energy_region(self, time_ms: int) -> bool:
        return any(region.contains(time_ms) for region in self.high_energy_regions)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.analysis_version,
            "audio": {
                "filename": self.audio_filename,
                "durationMs": self.duration_ms,
                "sampleRate": self.sample_rate,
            },
            "rhythm": {
                "bpm": round(self.bpm, 3),
                "offsetMs": self.offset_ms,
                "beats": [beat.to_dict() for beat in self.beats],
                "onsets": [onset.to_dict() for onset in self.onsets],
            },
            "energy": {
                "frames": [frame.to_dict() for frame in self.energy_frames],
                "quietRegions": [region.to_dict() for region in self.quiet_regions],
                "highEnergyRegions": [region.to_dict() for region in self.high_energy_regions],
            },
        }
        if self.enhanced:
            payload["enhanced"] = self.enhanced
        return payload


@dataclass(frozen=True)
class SelectedEvent:
    time_ms: int
    source: SelectedEventSource
    strength: float
    energy: float
    confidence: float
    is_emphasis: bool


@dataclass(frozen=True)
class HitObjectPoint:
    x: int
    y: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
        }


@dataclass(frozen=True)
class GeneratedCircleHitObject:
    id: int
    type: Literal["circle"]
    x: int
    y: int
    time: int
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "time": self.time,
            **self.extra_fields,
        }


@dataclass(frozen=True)
class GeneratedSliderHitObject:
    id: int
    type: Literal["slider"]
    x: int
    y: int
    time: int
    end_time: int
    path_type: Literal["bezier", "linear", "catmull", "perfect"]
    control_points: list[HitObjectPoint]
    repeats: int
    pixel_length: int
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "time": self.time,
            "endTime": self.end_time,
            "pathType": self.path_type,
            "controlPoints": [point.to_dict() for point in self.control_points],
            "repeats": self.repeats,
            "pixelLength": self.pixel_length,
            **self.extra_fields,
        }


@dataclass(frozen=True)
class GeneratedSpinnerHitObject:
    id: int
    type: Literal["spinner"]
    time: int
    end_time: int
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "time": self.time,
            "endTime": self.end_time,
            **self.extra_fields,
        }


GeneratedHitObject = (
    GeneratedCircleHitObject | GeneratedSliderHitObject | GeneratedSpinnerHitObject
)


@dataclass(frozen=True)
class BeatmapExport:
    title: str
    artist: str
    audio: str
    approach_time: int
    circle_radius: int
    objects: list[GeneratedHitObject]
    generator: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "audio": self.audio,
            "approachTime": self.approach_time,
            "circleRadius": self.circle_radius,
            "objects": [item.to_dict() for item in self.objects],
            "generator": self.generator,
        }


@dataclass(frozen=True)
class GenerationDiagnostics:
    min_object_gap_ms: int
    max_object_gap_ms: int
    average_object_gap_ms: float
    min_jump_distance: float
    max_jump_distance: float
    average_jump_distance: float
    highest_cursor_speed: float
    rejected_candidates: int
    detected_beats: int
    detected_onsets: int
    selected_objects: int


@dataclass(frozen=True)
class GenerationResult:
    analysis: AudioAnalysis
    selected_events: list[SelectedEvent]
    beatmap: BeatmapExport
    diagnostics: GenerationDiagnostics
    rhythm_quality_score: float | None = None
    rhythm_subdivision_count: int | None = None
    rhythm_tempo_confidence: float | None = None
    rhythm_diagnostics: dict[str, Any] | None = None
    slider_diagnostics: dict[str, Any] | None = None
    spinner_diagnostics: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
