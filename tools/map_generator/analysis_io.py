from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AudioAnalysis, EnergyFrame, EnergyRegion, TimedStrength
from .utils import MapGeneratorError


def load_json_file(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise MapGeneratorError(
            f"{label} is malformed at {path}: {error.msg} (line {error.lineno}, column {error.colno})"
        ) from error
    except OSError as error:
        raise MapGeneratorError(f"{label} could not be read from {path}: {error}") from error


def load_analysis_json(path: Path) -> AudioAnalysis:
    raw_analysis = load_json_file(path, "Analysis JSON")
    if not isinstance(raw_analysis, dict):
        raise MapGeneratorError(f"Analysis JSON must be an object: {path}")

    audio_section = raw_analysis.get("audio")
    rhythm_section = raw_analysis.get("rhythm")
    energy_section = raw_analysis.get("energy")
    if not isinstance(audio_section, dict):
        raise MapGeneratorError("Audio metadata is missing from the analysis JSON.")
    if not isinstance(rhythm_section, dict):
        raise MapGeneratorError("Rhythm data is missing from the analysis JSON.")
    if not isinstance(energy_section, dict):
        raise MapGeneratorError("Energy data is missing from the analysis JSON.")

    audio_filename = _safe_string(audio_section.get("filename"))
    duration_ms = _safe_int(audio_section.get("durationMs"))
    sample_rate = _safe_int(audio_section.get("sampleRate"))
    if not audio_filename or duration_ms is None or sample_rate is None:
        raise MapGeneratorError("Audio metadata is missing or invalid in the analysis JSON.")

    bpm = _safe_float(rhythm_section.get("bpm"))
    offset_ms = _safe_int(rhythm_section.get("offsetMs"))
    if bpm is None or offset_ms is None:
        raise MapGeneratorError("Rhythm metadata is missing or invalid in the analysis JSON.")

    beats = _parse_timed_strengths(rhythm_section.get("beats"), "beats")
    onsets = _parse_timed_strengths(rhythm_section.get("onsets"), "onsets")
    energy_frames = _parse_energy_frames(energy_section.get("frames"))
    quiet_regions = _parse_energy_regions(energy_section.get("quietRegions"), "quietRegions")
    high_energy_regions = _parse_energy_regions(energy_section.get("highEnergyRegions"), "highEnergyRegions")

    # Read version and enhanced features (v2+)
    analysis_version = _safe_int(raw_analysis.get("version")) or 1
    enhanced_section = raw_analysis.get("enhanced")
    enhanced = None
    if isinstance(enhanced_section, dict) and enhanced_section:
        enhanced = enhanced_section

    return AudioAnalysis(
        audio_filename=audio_filename,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        bpm=bpm,
        offset_ms=offset_ms,
        beats=beats,
        onsets=onsets,
        energy_frames=energy_frames,
        quiet_regions=quiet_regions,
        high_energy_regions=high_energy_regions,
        analysis_version=analysis_version,
        enhanced=enhanced,
    )


def _parse_timed_strengths(raw_items: Any, label: str) -> list[TimedStrength]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise MapGeneratorError(f"Analysis rhythm.{label} must be a list.")

    items: list[TimedStrength] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise MapGeneratorError(f"Analysis rhythm.{label}[{index}] must be an object.")
        time_ms = _safe_int(raw_item.get("timeMs"))
        strength = _safe_float(raw_item.get("strength"))
        if time_ms is None or strength is None:
            raise MapGeneratorError(f"Analysis rhythm.{label}[{index}] is missing timeMs or strength.")
        items.append(TimedStrength(time_ms=time_ms, strength=strength))
    return items


def _parse_energy_frames(raw_items: Any) -> list[EnergyFrame]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise MapGeneratorError("Analysis energy.frames must be a list.")

    items: list[EnergyFrame] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise MapGeneratorError(f"Analysis energy.frames[{index}] must be an object.")
        time_ms = _safe_int(raw_item.get("timeMs"))
        value = _safe_float(raw_item.get("value"))
        if time_ms is None or value is None:
            raise MapGeneratorError(f"Analysis energy.frames[{index}] is missing timeMs or value.")
        items.append(EnergyFrame(time_ms=time_ms, value=value))
    return items


def _parse_energy_regions(raw_items: Any, label: str) -> list[EnergyRegion]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise MapGeneratorError(f"Analysis energy.{label} must be a list.")

    items: list[EnergyRegion] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise MapGeneratorError(f"Analysis energy.{label}[{index}] must be an object.")
        start_ms = _safe_int(raw_item.get("startMs"))
        end_ms = _safe_int(raw_item.get("endMs"))
        average_value = _safe_float(raw_item.get("averageValue"))
        if start_ms is None or end_ms is None or average_value is None:
            raise MapGeneratorError(f"Analysis energy.{label}[{index}] is missing required region fields.")
        items.append(EnergyRegion(start_ms=start_ms, end_ms=end_ms, average_value=average_value))
    return items


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_int(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not numeric.is_integer():
        return None
    return int(numeric)


def _safe_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric
