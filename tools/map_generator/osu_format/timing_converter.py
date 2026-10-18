from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any, Sequence

from ..analysis_io import load_analysis_json
from ..models import AudioAnalysis
from ..utils import MapGeneratorError
from ..sliders import sv_calibration
from ._constants import load_osu_interop_constants
from .models import OsuTimingPoint, ProjectSliderObject

# Local-BPM regions whose estimates differ by less than this much from the
# global BPM are considered "same tempo" for the single-point fast path.
_SAME_TEMPO_BPM_TOLERANCE = 5.0
# Regions below this confidence carry unreliable local BPM estimates and are
# skipped instead of producing a timing point that would fight the audio.
_MIN_REGION_CONFIDENCE = 0.45
# Only merge regions when the local estimate is backed by at least a few beats.
_MIN_REGION_BEAT_COUNT = 4
# Minimum distance between two exported uninherited points (osu! rejects
# timing points that are effectively duplicates).
_MIN_POINT_SEPARATION_MS = 500


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


def build_timing_points(analysis_path: Path) -> tuple[list[OsuTimingPoint], float, int]:
    """Build the full uninherited timing-point list for an analysis.

    P0.1 (Phase 6 roadmap): when the enhanced analysis detected multiple
    stable tempo regions, emit one uninherited timing point per region so the
    exported map tracks tempo changes instead of flattening to a single
    global BPM. When the track is tempo-stable (or no region data exists),
    fall back to the historical single-point output so deterministic
    single-tempo exports remain byte-identical.
    """
    analysis = load_analysis_json(analysis_path)
    constants = load_osu_interop_constants()["timingDefaults"]
    global_bpm = analysis.bpm if analysis.bpm > 0 else 120.0
    offset_ms = analysis.offset_ms

    def _make_point(time_ms: int, bpm: float) -> OsuTimingPoint:
        return OsuTimingPoint(
            time=max(0, int(time_ms)),
            beat_length=60000.0 / bpm,
            meter=int(constants["meter"]),
            sample_set=int(constants["sampleSetId"]),
            sample_index=int(constants["sampleIndex"]),
            volume=int(constants["volume"]),
            uninherited=int(constants["uninherited"]),
            effects=int(constants["effects"]),
        )

    regions = _load_stable_bpm_regions(analysis)
    if len(regions) <= 1:
        primary, _bpm, _offset = build_primary_timing_point(analysis_path)
        return [primary], global_bpm, offset_ms

    points: list[OsuTimingPoint] = []
    for region in regions:
        if not points:
            points.append(_make_point(region[0], region[1]))
            continue
        last_point = points[-1]
        last_bpm = 60000.0 / last_point.beat_length if last_point.beat_length > 0 else global_bpm
        if region[0] - last_point.time < _MIN_POINT_SEPARATION_MS:
            continue
        if abs(region[1] - last_bpm) < _SAME_TEMPO_BPM_TOLERANCE:
            continue
        points.append(_make_point(region[0], region[1]))

    if not points:
        primary, _bpm, _offset = build_primary_timing_point(analysis_path)
        return [primary], global_bpm, offset_ms

    return points, global_bpm, offset_ms


def _load_stable_bpm_regions(analysis: AudioAnalysis) -> list[tuple[int, float]]:
    """Extract confident, stable local-BPM regions from enhanced analysis.

    Returns an ordered list of ``(start_ms, bpm)`` tuples. The first region
    is always replaced by the analysis-level offset anchor so the primary
    timing point keeps its historical anchor time.
    """
    enhanced = analysis.enhanced
    if not isinstance(enhanced, dict):
        return []
    raw_regions = enhanced.get("bpmRegions")
    if not isinstance(raw_regions, list):
        return []

    regions: list[tuple[int, float]] = []
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            continue
        start_ms = raw_region.get("startMs")
        bpm = raw_region.get("bpm")
        confidence = raw_region.get("confidence")
        beat_count = raw_region.get("beatCount")
        if not isinstance(start_ms, (int, float)) or not isinstance(bpm, (int, float)):
            continue
        if not isinstance(confidence, (int, float)) or not isinstance(beat_count, (int, float)):
            continue
        if bpm <= 0 or confidence < _MIN_REGION_CONFIDENCE or beat_count < _MIN_REGION_BEAT_COUNT:
            continue
        regions.append((int(start_ms), float(bpm)))

    if not regions:
        return []
    regions.sort(key=lambda item: item[0])
    # Anchor the first point at the global offset for a stable map start.
    regions[0] = (max(0, analysis.offset_ms), regions[0][1])
    return regions


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


# ---------------------------------------------------------------------------
# Inherited (green) timing points so sliders play at the speed they were drawn
# ---------------------------------------------------------------------------
#
# Without these, a slider's real duration in the client is
# `pixel_length / (SliderMultiplier * 100) * beat_length`, which has nothing to do
# with the `end_time` the generator chose. Emitting one inherited point per distinct
# slider velocity makes the exported map match its own geometry.

#: |SV - 1| below this needs no inherited point: the default multiplier already is 1.
_SV_IDENTITY_EPSILON = 1e-3


def build_slider_velocity_points(
    objects: Sequence[Any],
    timing_points: Sequence[OsuTimingPoint],
    *,
    slider_multiplier: float,
) -> list[OsuTimingPoint]:
    """Inherited timing points making every slider's duration match its geometry.

    The active beat length is resolved per slider, so a map with detected BPM regions
    gets per-region velocities and therefore per-region SV — the multiplier adapts to
    tempo changes instead of assuming a single global BPM.

    Returns an empty list when there are no sliders, no usable durations, or every
    slider already sits at SV = 1.
    """
    if not timing_points or slider_multiplier <= 0:
        return []

    sliders = [obj for obj in objects if isinstance(obj, ProjectSliderObject)]
    if not sliders:
        return []

    anchors = sorted((point for point in timing_points if point.uninherited == 1), key=lambda p: p.time)
    if not anchors:
        return []
    anchor_times = [point.time for point in anchors]

    constants = load_osu_interop_constants()["timingDefaults"]
    points: list[OsuTimingPoint] = []
    active_sv: float | None = None

    for slider in sorted(sliders, key=lambda item: item.time):
        duration_ms = float(slider.end_time) - float(slider.time)
        if duration_ms <= 0 or slider.pixel_length <= 0:
            continue

        index = bisect.bisect_right(anchor_times, int(slider.time)) - 1
        beat_length = anchors[index].beat_length
        if beat_length <= 0:
            continue

        try:
            velocity = sv_calibration.path_velocity(
                float(slider.pixel_length), int(slider.repeats), duration_ms
            )
            base = sv_calibration.base_slider_velocity(float(slider_multiplier), float(beat_length))
            sv = sv_calibration.sv_multiplier(velocity, base)
        except ValueError:
            continue

        if abs(sv - 1.0) < _SV_IDENTITY_EPSILON:
            active_sv = 1.0
            continue
        if active_sv is not None and abs(sv - active_sv) < _SV_IDENTITY_EPSILON:
            continue  # same speed as the point already in force: no line needed

        active_sv = sv
        points.append(
            OsuTimingPoint(
                time=int(slider.time),
                beat_length=round(-100.0 / sv, 4),
                meter=int(constants["meter"]),
                sample_set=int(constants["sampleSetId"]),
                sample_index=int(constants["sampleIndex"]),
                volume=int(constants["volume"]),
                uninherited=0,
                effects=int(constants["effects"]),
            )
        )
    return points


def merge_timing_points(
    uninherited: Sequence[OsuTimingPoint],
    inherited: Sequence[OsuTimingPoint],
) -> list[OsuTimingPoint]:
    """Interleave both timing-point kinds, uninherited first at equal times.

    osu! applies the last point at or before a time, so a red line and a green line
    sharing a timestamp must be written red-first or the SV would be swallowed by the
    tempo reset.
    """
    return sorted(
        [*uninherited, *inherited],
        key=lambda point: (point.time, -point.uninherited),
    )
