from __future__ import annotations

from pathlib import Path

from ..analysis_io import load_analysis_json
from ..utils import MapGeneratorError
from ._constants import load_osu_interop_constants
from .models import OsuTimingPoint


def normalize_osu_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip().strip('"')
    if not normalized:
        raise MapGeneratorError("Audio filename must be a non-empty relative path.")
    if normalized.startswith("/") or normalized.startswith("../") or _looks_like_windows_drive(normalized):
        raise MapGeneratorError(f"Audio filename must stay relative inside the mapset: {value}")
    segments = [segment.strip() for segment in normalized.split("/") if segment.strip()]
    if not segments or any(segment in {".", ".."} for segment in segments):
        raise MapGeneratorError(f"Audio filename must stay relative inside the mapset: {value}")
    return "/".join(segments)


def browser_audio_path_from_osu_filename(value: str) -> str:
    return f"/audio/{normalize_osu_relative_path(value)}"


def osu_audio_filename_from_browser_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        raise MapGeneratorError("Project audio path must be a non-empty string.")
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        raise MapGeneratorError(f"Project audio path is missing a filename: {value}")
    return segments[-1]


def build_primary_timing_point(analysis_path: Path) -> tuple[OsuTimingPoint, float, int]:
    analysis = load_analysis_json(analysis_path)
    bpm = analysis.bpm if analysis.bpm > 0 else 120.0
    offset_ms = analysis.offset_ms
    constants = load_osu_interop_constants()["timingDefaults"]
    timing_point = OsuTimingPoint(
        time=offset_ms,
        beat_length=60000.0 / bpm,
        meter=int(constants["meter"]),
        sample_set=int(constants["sampleSetId"]),
        sample_index=int(constants["sampleIndex"]),
        volume=int(constants["volume"]),
        uninherited=int(constants["uninherited"]),
        effects=int(constants["effects"]),
    )
    return timing_point, bpm, offset_ms


def deterministic_archive_timestamp() -> tuple[int, int, int, int, int, int]:
    data = load_osu_interop_constants()["deterministicArchive"]
    return (
        int(data["year"]),
        int(data["month"]),
        int(data["day"]),
        int(data["hour"]),
        int(data["minute"]),
        int(data["second"]),
    )


def _looks_like_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ":" and value[0].isalpha()
