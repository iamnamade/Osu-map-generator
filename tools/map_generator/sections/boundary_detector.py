from __future__ import annotations

from dataclasses import dataclass

from ..models import AudioAnalysis
from ..utils import clamp
from .feature_extractor import extract_boundary_snapshot, nearest_anchor_time
from .section_config import SectionDetectionConfig
from .section_models import SectionBoundary


@dataclass(frozen=True)
class RawBoundaryCandidate:
    time_ms: int
    confidence: float
    reason: str
    supporting_feature_changes: dict[str, float]


def detect_section_boundaries(
    analysis: AudioAnalysis,
    config: SectionDetectionConfig,
) -> list[SectionBoundary]:
    anchors = sorted(
        {
            marker.time_ms
            for marker in analysis.beats + analysis.onsets
            if config.min_section_duration_ms
            <= marker.time_ms
            <= analysis.duration_ms - config.min_section_duration_ms
        }
    )
    raw_candidates = [
        candidate
        for time_ms in anchors
        if (candidate := _score_boundary(analysis, time_ms, config)) is not None
    ]
    selected = _select_candidates(raw_candidates, config, analysis.duration_ms)
    boundaries: list[SectionBoundary] = []
    for candidate in selected[: config.max_boundary_count]:
        snapped_to = nearest_anchor_time(
            analysis,
            time_ms=candidate.time_ms,
            max_distance_ms=config.snap_tolerance_ms,
        )
        if snapped_to is None:
            boundaries.append(
                SectionBoundary(
                    raw_time_ms=candidate.time_ms,
                    final_time_ms=candidate.time_ms,
                    confidence=candidate.confidence,
                    reason=candidate.reason,
                    supporting_feature_changes=candidate.supporting_feature_changes,
                    snapped=False,
                )
            )
            continue
        snapped_time, snapped_type, snap_distance = snapped_to
        boundaries.append(
            SectionBoundary(
                raw_time_ms=candidate.time_ms,
                final_time_ms=snapped_time,
                confidence=candidate.confidence,
                reason=candidate.reason,
                supporting_feature_changes=candidate.supporting_feature_changes,
                snapped=snapped_time != candidate.time_ms,
                snapped_to=f"strong-{snapped_type}" if snap_distance > 0 else snapped_type,
                snap_distance_ms=snap_distance,
            )
        )

    deduped: list[SectionBoundary] = []
    previous_time = -1
    for boundary in sorted(boundaries, key=lambda item: item.final_time_ms):
        if boundary.final_time_ms <= previous_time:
            continue
        if (
            deduped
            and boundary.final_time_ms - deduped[-1].final_time_ms
            < config.min_section_duration_ms
        ):
            if boundary.confidence > deduped[-1].confidence:
                deduped[-1] = boundary
            continue
        deduped.append(boundary)
        previous_time = boundary.final_time_ms
    return deduped


def _score_boundary(
    analysis: AudioAnalysis,
    time_ms: int,
    config: SectionDetectionConfig,
) -> RawBoundaryCandidate | None:
    half_window_ms = config.boundary_window_ms
    before = extract_boundary_snapshot(
        analysis,
        start_ms=max(0, time_ms - half_window_ms),
        end_ms=time_ms,
    )
    after = extract_boundary_snapshot(
        analysis,
        start_ms=time_ms,
        end_ms=min(analysis.duration_ms, time_ms + half_window_ms),
    )
    feature_changes = {
        "energyDelta": abs(after.average_energy - before.average_energy),
        "densityDelta": abs(after.onset_density - before.onset_density),
        "beatDelta": abs(after.beat_density - before.beat_density),
        "strengthDelta": abs(after.average_onset_strength - before.average_onset_strength),
        "quietFlip": abs(after.quiet_ratio - before.quiet_ratio),
        "highEnergyFlip": abs(after.high_energy_ratio - before.high_energy_ratio),
        "emphasisDelta": abs(after.emphasis_ratio - before.emphasis_ratio),
        "slopeDelta": abs(after.energy_slope - before.energy_slope) * 1200,
    }
    confidence = clamp(
        feature_changes["energyDelta"] * 1.6
        + feature_changes["densityDelta"] * 0.2
        + feature_changes["beatDelta"] * 0.12
        + feature_changes["strengthDelta"] * 0.45
        + feature_changes["quietFlip"] * 0.55
        + feature_changes["highEnergyFlip"] * 0.55
        + feature_changes["emphasisDelta"] * 0.28
        + feature_changes["slopeDelta"] * 0.06,
        0.0,
        1.0,
    )
    if confidence < config.boundary_threshold:
        return None
    dominant_feature = max(feature_changes.items(), key=lambda item: item[1])[0]
    reasons = {
        "energyDelta": "Large energy change",
        "densityDelta": "Large onset-density change",
        "beatDelta": "Large beat-density change",
        "strengthDelta": "Strong onset-strength change",
        "quietFlip": "Quiet-region contrast change",
        "highEnergyFlip": "High-energy-region contrast change",
        "emphasisDelta": "Event-emphasis profile change",
        "slopeDelta": "Energy-slope change",
    }
    return RawBoundaryCandidate(
        time_ms=time_ms,
        confidence=confidence,
        reason=reasons.get(dominant_feature, "Mixed musical feature change"),
        supporting_feature_changes=feature_changes,
    )


def _select_candidates(
    candidates: list[RawBoundaryCandidate],
    config: SectionDetectionConfig,
    duration_ms: int,
) -> list[RawBoundaryCandidate]:
    if not candidates:
        return []
    selected: list[RawBoundaryCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.time_ms):
        if not selected:
            selected.append(candidate)
            continue
        previous = selected[-1]
        if candidate.time_ms - previous.time_ms < config.min_section_duration_ms:
            if candidate.confidence > previous.confidence:
                selected[-1] = candidate
            continue
        selected.append(candidate)

    if (
        selected
        and duration_ms - selected[-1].time_ms > config.max_section_duration_ms
        and len(candidates) > len(selected)
    ):
        tail_candidates = [
            candidate
            for candidate in candidates
            if candidate.time_ms > selected[-1].time_ms
        ]
        if tail_candidates:
            selected.append(max(tail_candidates, key=lambda item: item.confidence))
    return selected
