from __future__ import annotations

from typing import Any

from ..models import AudioAnalysis
from ..sections.section_models import SongSection
from ..sliders.slider_models import SustainedAnalysis
from .spinner_models import (
    SpinnerMusicalContext,
    SpinnerRegionType,
    SpinnerTriggerType,
)

SPINNER_FRIENDLY_LABELS = {
    "intro-like",
    "outro-like",
    "break-like",
    "quiet",
    "build-up",
    "instrumental",
    "bridge-like",
}
SPINNER_UNFRIENDLY_LABELS = {
    "drop-like",
    "chorus-like",
    "verse-like",
}


def build_spinner_context(
    *,
    analysis: AudioAnalysis,
    sustained: SustainedAnalysis | None = None,
    sections: list[SongSection] | None = None,
) -> SpinnerMusicalContext:
    """Build the deterministic musical context used by the spinner engine.

    Combines the core audio analysis (energy, onsets, regions), the sustained
    content analysis from Phase 11, and optional section detection from the
    section pipeline. Every value is derived purely from the supplied data so
    the decision pipeline stays deterministic.
    """
    energy_frames = [
        {"timeMs": frame.time_ms, "value": float(frame.value)}
        for frame in analysis.energy_frames
    ]
    onset_times = [event.time_ms for event in analysis.onsets]

    quiet_regions = [
        {"startMs": region.start_ms, "endMs": region.end_ms, "averageValue": float(region.average_value)}
        for region in analysis.quiet_regions
    ]
    high_energy_regions = [
        {"startMs": region.start_ms, "endMs": region.end_ms, "averageValue": float(region.average_value)}
        for region in analysis.high_energy_regions
    ]

    sustained_regions: list[dict[str, Any]] = []
    sustained_frames: list[dict[str, Any]] = []
    if sustained is not None:
        sustained_regions = [
            {
                "startMs": int(region["startMs"]),
                "endMs": int(region["endMs"]),
                "averageScore": float(region["averageScore"]),
            }
            for region in sustained.sustained_regions
        ]
        sustained_frames = [
            {
                "timeMs": int(frame["timeMs"]),
                "sustainedScore": float(frame["sustainedScore"]),
            }
            for frame in sustained.sustained_frames
        ]

    section_dicts: list[dict[str, Any]] = []
    if sections:
        section_dicts = [
            {
                "id": section.id,
                "startMs": section.start_ms,
                "endMs": section.end_ms,
                "label": section.label,
                "averageEnergy": float(section.average_energy),
                "energyTrend": section.energy_trend,
                "onsetDensity": float(section.onset_density),
                "confidence": float(section.confidence),
            }
            for section in sections
        ]

    return SpinnerMusicalContext(
        duration_ms=analysis.duration_ms,
        bpm=float(analysis.bpm) if analysis.bpm and analysis.bpm > 0 else 120.0,
        energy_frames=energy_frames,
        onset_times=onset_times,
        quiet_regions=quiet_regions,
        high_energy_regions=high_energy_regions,
        sustained_regions=sustained_regions,
        sustained_frames=sustained_frames,
        sections=section_dicts,
    )


def classify_region(
    context: SpinnerMusicalContext,
    start_ms: int,
    end_ms: int,
) -> SpinnerRegionType:
    """Classify a candidate time range into a spinner-supporting region type.

    Order of checks:
    1. Intro (before ~8% of the song, low energy)
    2. Outro (after ~88% of the song, falling or low energy)
    3. Quiet break (mostly inside quiet regions with low onset density)
    4. Sustained content (strong sustained/ambient score)
    5. Build-up / transition (rising energy, moderate onsets)
    6. Dense rhythm (high onset density -> unsuitable)
    """
    if end_ms <= start_ms:
        return "unknown"

    duration_ms = end_ms - start_ms
    average_energy = _average_energy_in(context, start_ms, end_ms)
    onset_density = _onset_density_in(context, start_ms, end_ms)
    sustained_score = _average_sustained_in(context, start_ms, end_ms)
    quiet_ratio = _quiet_ratio_in(context, start_ms, end_ms)
    high_ratio = _high_energy_ratio_in(context, start_ms, end_ms)

    song_ratio_start = start_ms / max(1, context.duration_ms)
    song_ratio_end = end_ms / max(1, context.duration_ms)

    if song_ratio_start < 0.08 and average_energy < 0.4:
        return "intro"
    if song_ratio_end > 0.88 and (average_energy < 0.45 or _energy_trend_in(context, start_ms, end_ms) == "falling"):
        return "outro"
    if quiet_ratio >= 0.5 and onset_density < 1.0:
        return "break"
    if sustained_score >= 0.45 and onset_density < 1.2:
        return "sustained"
    if average_energy < 0.42 and onset_density < 1.0:
        return "transition"
    if onset_density >= 1.6 and high_ratio >= 0.4:
        return "dense"

    # Fall back to section labels when available
    label = _section_label_at(context, start_ms, end_ms)
    if label in SPINNER_FRIENDLY_LABELS:
        return "transition"
    if label in SPINNER_UNFRIENDLY_LABELS:
        return "dense"

    return "unknown"


def classify_trigger(
    context: SpinnerMusicalContext,
    region_type: SpinnerRegionType,
    start_ms: int,
    end_ms: int,
) -> SpinnerTriggerType:
    """Classify the musical trigger that justifies a spinner here.

    Phase 22: spinners should only appear where the music provides a real
    trigger — a continuous sustain, a fade-out tail, a structural transition,
    or a noise riser. Deterministic: derived purely from the context features.

    Returns one of ``sustain``, ``fade_out``, ``transition``, ``riser``, or
    ``unknown`` when the region has no identifiable trigger.
    """
    if end_ms <= start_ms:
        return "unknown"

    sustained_score = _average_sustained_in(context, start_ms, end_ms)
    energy_trend = _energy_trend_in(context, start_ms, end_ms)
    average_energy = _average_energy_in(context, start_ms, end_ms)
    onset_density = _onset_density_in(context, start_ms, end_ms)

    # Continuous sustain / ambient pad is the strongest musical justification.
    if sustained_score >= 0.5 and onset_density < 1.0:
        return "sustain"

    # Fade-out tails: falling energy, low onset activity.
    if energy_trend == "falling" and average_energy < 0.5 and onset_density < 1.0:
        return "fade_out"

    # Noise risers / build-ups: rising energy before a structural peak.
    if energy_trend == "rising" and onset_density < 1.4:
        return "riser"

    # Intro/outro/break and label-backed transitions remain "transition".
    if region_type in ("intro", "outro", "break", "transition"):
        return "transition"

    if region_type == "sustained":
        return "sustain"

    return "unknown"


def region_musical_score(context: SpinnerMusicalContext, region_type: SpinnerRegionType, start_ms: int, end_ms: int) -> float:
    """Compute a 0-100 score describing how strongly the music supports a spinner here."""
    if end_ms <= start_ms:
        return 0.0

    average_energy = _average_energy_in(context, start_ms, end_ms)
    onset_density = _onset_density_in(context, start_ms, end_ms)
    sustained_score = _average_sustained_in(context, start_ms, end_ms)
    quiet_ratio = _quiet_ratio_in(context, start_ms, end_ms)
    high_ratio = _high_energy_ratio_in(context, start_ms, end_ms)

    score = 0.0

    if region_type == "intro":
        score = 55 + (1.0 - min(average_energy, 0.4) / 0.4) * 25
    elif region_type == "outro":
        score = 58 + (1.0 - min(average_energy, 0.45) / 0.45) * 22
    elif region_type == "break":
        score = 62 + quiet_ratio * 28
    elif region_type == "sustained":
        score = 60 + sustained_score * 35
    elif region_type == "transition":
        score = 50 + max(0.0, 0.5 - onset_density) * 30 + quiet_ratio * 15
    elif region_type == "dense":
        score = 12 - high_ratio * 10
    else:
        score = 18

    # Onset density directly lowers suitability: dense rhythm cannot host a spinner.
    if onset_density > 1.4:
        score -= (onset_density - 1.4) * 30

    return max(0.0, min(100.0, score))


def _average_energy_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [frame for frame in context.energy_frames if start_ms <= frame["timeMs"] <= end_ms]
    if not frames:
        return context.energy_at((start_ms + end_ms) // 2)
    return sum(float(frame["value"]) for frame in frames) / len(frames)


def _average_sustained_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [
        frame for frame in context.sustained_frames if start_ms <= frame["timeMs"] <= end_ms
    ]
    if not frames:
        return context.sustained_at((start_ms + end_ms) // 2)
    return sum(float(frame["sustainedScore"]) for frame in frames) / len(frames)


def _onset_density_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    count = sum(1 for time_ms in context.onset_times if start_ms <= time_ms <= end_ms)
    seconds = max(1.0, (end_ms - start_ms) / 1000)
    return count / seconds


def _quiet_ratio_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [frame for frame in context.energy_frames if start_ms <= frame["timeMs"] <= end_ms]
    if not frames:
        return 0.0
    low_count = sum(1 for frame in frames if float(frame["value"]) < 0.22)
    return low_count / len(frames)


def _high_energy_ratio_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> float:
    frames = [frame for frame in context.energy_frames if start_ms <= frame["timeMs"] <= end_ms]
    if not frames:
        return 0.0
    high_count = sum(1 for frame in frames if float(frame["value"]) >= 0.6)
    return high_count / len(frames)


def _energy_trend_in(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> str:
    frames = [frame for frame in context.energy_frames if start_ms <= frame["timeMs"] <= end_ms]
    if len(frames) < 2:
        return "steady"
    first_half = sum(float(frame["value"]) for frame in frames[: len(frames) // 2])
    second_half = sum(float(frame["value"]) for frame in frames[len(frames) // 2 :])
    if second_half > first_half * 1.12:
        return "rising"
    if first_half > second_half * 1.12:
        return "falling"
    return "steady"


def _section_label_at(context: SpinnerMusicalContext, start_ms: int, end_ms: int) -> str | None:
    best: dict[str, Any] | None = None
    best_overlap = 0
    for section in context.sections:
        overlap_start = max(start_ms, int(section["startMs"]))
        overlap_end = min(end_ms, int(section["endMs"]))
        overlap = max(0, overlap_end - overlap_start)
        if overlap > best_overlap:
            best = section
            best_overlap = overlap
    if best is None:
        return None
    if best_overlap < max(200, int((end_ms - start_ms) * 0.2)):
        return None
    return str(best["label"])
