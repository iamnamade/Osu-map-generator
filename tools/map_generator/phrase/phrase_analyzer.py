"""Phase 20 phrase boundary detection & relationship engine.

Subdivides song sections into structured phrase blocks using onset density,
energy gradients, spectral changes, and beat subdivisions, then classifies
phrase relationships (repetition, variation, continuation, escalation,
reduction, contrast, call-and-response, transition) from acoustic feature
correlation.

Everything is deterministic: identical audio analysis + section analysis
always produce the identical phrase report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import AudioAnalysis
from ..sections.section_models import SongSection
from ..utils import clamp
from .phrase_models import (
    Phrase,
    PhraseRelationship,
    PhraseRelationshipType,
)


@dataclass(frozen=True)
class PhraseDetectionConfig:
    """Tunable phrase segmentation parameters."""

    min_phrase_duration_ms: int = 6000
    max_phrase_duration_ms: int = 26000
    boundary_window_ms: int = 1600
    boundary_threshold: float = 0.5
    subdivision_min_confidence: float = 0.45
    relationship_similarity_high: float = 0.85
    relationship_similarity_low: float = 0.45
    max_phrase_count: int = 24

    def to_dict(self) -> dict[str, Any]:
        return {
            "minPhraseDurationMs": self.min_phrase_duration_ms,
            "maxPhraseDurationMs": self.max_phrase_duration_ms,
            "boundaryWindowMs": self.boundary_window_ms,
            "boundaryThreshold": round(self.boundary_threshold, 4),
            "subdivisionMinConfidence": round(self.subdivision_min_confidence, 4),
            "relationshipSimilarityHigh": round(self.relationship_similarity_high, 4),
            "relationshipSimilarityLow": round(self.relationship_similarity_low, 4),
            "maxPhraseCount": self.max_phrase_count,
        }


DEFAULT_PHRASE_CONFIG = PhraseDetectionConfig()


def detect_phrase_boundaries(
    analysis: AudioAnalysis,
    section: SongSection,
    config: PhraseDetectionConfig = DEFAULT_PHRASE_CONFIG,
) -> list[int]:
    """Return boundary times (ms) that split ``section`` into phrases.

    Candidates are beat/onset anchors inside the section. Each anchor is
    scored with a before/after feature snapshot (energy, onset density,
    spectral flux proxy, beat density). The highest-scoring anchors that
    respect min/max phrase durations are kept in time order.

    Returns interior boundaries only (the section start/end are implied).
    """
    section_start = section.start_ms
    section_end = section.end_ms
    duration = section_end - section_start

    if duration <= config.min_phrase_duration_ms * 2:
        return []

    anchors = sorted(
        {
            marker.time_ms
            for marker in analysis.beats + analysis.onsets
            if section_start + config.min_phrase_duration_ms
            <= marker.time_ms
            <= section_end - config.min_phrase_duration_ms
        }
    )
    scored: list[tuple[float, int]] = []
    for time_ms in anchors:
        score = _score_boundary(analysis, time_ms, section_start, section_end, config)
        if score is not None and score >= config.boundary_threshold:
            scored.append((score, time_ms))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[int] = []
    for score, time_ms in scored:
        if len(selected) >= config.max_phrase_count - 1:
            break
        if any(
            abs(time_ms - existing) < config.min_phrase_duration_ms
            for existing in selected
        ):
            continue
        # Respect max duration: adding this boundary must not create a
        # phrase longer than max_phrase_duration_ms with the neighbors.
        neighbors = sorted([section_start, *selected, time_ms, section_end])
        if any(
            neighbors[index + 1] - neighbors[index] > config.max_phrase_duration_ms
            for index in range(len(neighbors) - 1)
        ):
            continue
        selected.append(time_ms)
        # Keep scoring deterministic regardless of later additions.
        selected.sort()
    return selected


def _score_boundary(
    analysis: AudioAnalysis,
    time_ms: int,
    section_start: int,
    section_end: int,
    config: PhraseDetectionConfig,
) -> float | None:
    from ..sections.feature_extractor import extract_boundary_snapshot

    half = config.boundary_window_ms
    before = extract_boundary_snapshot(
        analysis,
        start_ms=max(section_start, time_ms - half),
        end_ms=time_ms,
    )
    after = extract_boundary_snapshot(
        analysis,
        start_ms=time_ms,
        end_ms=min(section_end, time_ms + half),
    )
    energy_delta = abs(after.average_energy - before.average_energy)
    density_delta = abs(after.onset_density - before.onset_density)
    beat_delta = abs(after.beat_density - before.beat_density)
    strength_delta = abs(after.average_onset_strength - before.average_onset_strength)
    emphasis_delta = abs(after.emphasis_ratio - before.emphasis_ratio)
    # Spectral flux proxy: absolute energy slope difference across the window.
    flux_delta = abs(after.energy_slope - before.energy_slope) * 1600
    score = clamp(
        energy_delta * 1.35
        + density_delta * 0.22
        + beat_delta * 0.16
        + strength_delta * 0.4
        + emphasis_delta * 0.24
        + flux_delta * 0.05,
        0.0,
        1.0,
    )
    return score


def build_phrases(
    analysis: AudioAnalysis,
    sections: list[SongSection],
    config: PhraseDetectionConfig = DEFAULT_PHRASE_CONFIG,
) -> list[Phrase]:
    """Build Phrase objects for every section using detected boundaries."""
    phrases: list[Phrase] = []
    phrase_id = 1
    for section in sections:
        boundaries = detect_phrase_boundaries(analysis, section, config)
        times = [section.start_ms, *boundaries, section.end_ms]
        for index in range(len(times) - 1):
            start = times[index]
            end = times[index + 1]
            if end - start < 500:
                continue
            features = _phrase_features(analysis, start, end)
            phrases.append(
                Phrase(
                    id=phrase_id,
                    start_ms=start,
                    end_ms=end,
                    duration_ms=end - start,
                    section_id=section.id,
                    label=_phrase_label(section, features),
                    confidence=round(
                        clamp(section.confidence * 0.6 + features["coherence"] * 0.4, 0.1, 0.99),
                        4,
                    ),
                    average_energy=features["average_energy"],
                    energy_slope=features["energy_slope"],
                    onset_density=features["onset_density"],
                    beat_density=features["beat_density"],
                    average_onset_strength=features["average_onset_strength"],
                    rhythm_complexity=features["rhythm_complexity"],
                    spectral_flux=features["spectral_flux"],
                    emphasis_ratio=features["emphasis_ratio"],
                    quiet_ratio=features["quiet_ratio"],
                    high_energy_ratio=features["high_energy_ratio"],
                    subdivision_ratio=features["subdivision_ratio"],
                    motif_id=None,
                    section_repetition_group=section.repetition_group,
                )
            )
            phrase_id += 1
    return phrases


def _phrase_features(
    analysis: AudioAnalysis,
    start_ms: int,
    end_ms: int,
) -> dict[str, float]:
    from ..sections.feature_extractor import extract_boundary_snapshot

    duration_ms = max(1, end_ms - start_ms)
    snapshot = extract_boundary_snapshot(analysis, start_ms=start_ms, end_ms=end_ms)
    first_half = extract_boundary_snapshot(
        analysis,
        start_ms=start_ms,
        end_ms=start_ms + max(1, duration_ms // 2),
    )
    second_half = extract_boundary_snapshot(
        analysis,
        start_ms=start_ms + max(1, duration_ms // 2),
        end_ms=end_ms,
    )
    energy_slope = second_half.average_energy - first_half.average_energy
    rhythm_complexity = min(
        1.0,
        (
            abs(snapshot.onset_density - snapshot.beat_density) * 0.18
            + snapshot.average_onset_strength * 0.4
            + abs(energy_slope) * 6.0
        ),
    )
    subdivision_ratio = (
        snapshot.onset_density / snapshot.beat_density
        if snapshot.beat_density > 0
        else 0.0
    )
    flux = abs(second_half.energy_slope - first_half.energy_slope) * 800
    # A phrase is "coherent" when its local features are stable: low slope
    # deltas and moderate subdivision noise.
    coherence = clamp(
        1.0
        - abs(energy_slope) * 2.2
        - min(1.0, abs(subdivision_ratio - 1.0)) * 0.3
        - min(1.0, flux) * 0.2,
        0.0,
        1.0,
    )
    return {
        "average_energy": round(snapshot.average_energy, 4),
        "energy_slope": round(energy_slope, 6),
        "onset_density": round(snapshot.onset_density, 4),
        "beat_density": round(snapshot.beat_density, 4),
        "average_onset_strength": round(snapshot.average_onset_strength, 4),
        "rhythm_complexity": round(rhythm_complexity, 4),
        "spectral_flux": round(flux, 6),
        "emphasis_ratio": round(snapshot.emphasis_ratio, 4),
        "quiet_ratio": round(snapshot.quiet_ratio, 4),
        "high_energy_ratio": round(snapshot.high_energy_ratio, 4),
        "subdivision_ratio": round(subdivision_ratio, 4),
        "coherence": round(coherence, 4),
    }


def _phrase_label(section: SongSection, features: dict[str, float]) -> str:
    base = section.label if section.label and section.label != "unknown" else "phrase"
    energy = features["average_energy"]
    if energy < 0.28 or features["quiet_ratio"] >= 0.45:
        return f"{base}-quiet"
    if features["onset_density"] >= 1.25 and features["emphasis_ratio"] >= 0.55:
        return f"{base}-peak"
    if features["energy_slope"] > 0.03:
        return f"{base}-rise"
    if features["energy_slope"] < -0.03:
        return f"{base}-fall"
    return base


# ---------------------------------------------------------------------------
# Relationship classification
# ---------------------------------------------------------------------------

_FEATURE_KEYS = (
    "average_energy",
    "onset_density",
    "beat_density",
    "average_onset_strength",
    "rhythm_complexity",
    "emphasis_ratio",
    "quiet_ratio",
    "high_energy_ratio",
    "subdivision_ratio",
)


def _feature_vector(phrase: Phrase) -> list[float]:
    return [float(getattr(phrase, key)) for key in _FEATURE_KEYS]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def classify_phrase_relationships(
    phrases: list[Phrase],
    config: PhraseDetectionConfig = DEFAULT_PHRASE_CONFIG,
) -> list[PhraseRelationship]:
    """Classify pairwise phrase relationships from feature correlation.

    Compares every ordered pair; consecutive pairs get directional labels
    (continuation / escalation / reduction / transition), while separated
    pairs get structural labels (repetition / variation / contrast /
    call-and-response). Only relationships above a similarity floor are kept.
    """
    relationships: list[PhraseRelationship] = []
    relationship_id = 1
    vectors = {phrase.id: _feature_vector(phrase) for phrase in phrases}
    ids = [phrase.id for phrase in phrases]
    for left_index, left_id in enumerate(ids):
        for right_index in range(left_index + 1, len(ids)):
            right_id = ids[right_index]
            left = phrases[left_index]
            right = phrases[right_index]
            similarity = _cosine_similarity(vectors[left_id], vectors[right_id])
            if similarity < config.relationship_similarity_low:
                continue
            consecutive = right_index == left_index + 1
            relationship_type, confidence = _classify_pair(
                left=left,
                right=right,
                similarity=similarity,
                consecutive=consecutive,
                config=config,
            )
            deltas = {
                key: round(float(getattr(right, key)) - float(getattr(left, key)), 4)
                for key in _FEATURE_KEYS
            }
            relationships.append(
                PhraseRelationship(
                    id=relationship_id,
                    from_phrase_id=left_id,
                    to_phrase_id=right_id,
                    relationship_type=relationship_type,
                    similarity=round(similarity, 4),
                    confidence=round(confidence, 4),
                    feature_deltas=deltas,
                )
            )
            relationship_id += 1
    return relationships


def _classify_pair(
    *,
    left: Phrase,
    right: Phrase,
    similarity: float,
    consecutive: bool,
    config: PhraseDetectionConfig,
) -> tuple[PhraseRelationshipType, float]:
    high = config.relationship_similarity_high
    energy_delta = right.average_energy - left.average_energy
    density_delta = right.onset_density - left.onset_density

    if consecutive:
        if similarity >= high:
            # Near-identical adjacent phrases = continuation.
            return "continuation", 0.5 + similarity * 0.4
        if energy_delta > 0.06 or density_delta > 0.25:
            return "escalation", 0.55 + abs(energy_delta) * 2.0
        if energy_delta < -0.06 or density_delta < -0.25:
            return "reduction", 0.55 + abs(energy_delta) * 2.0
        # A short bridging phrase between contrasting neighbors.
        if min(left.duration_ms, right.duration_ms) < 7000:
            return "transition", 0.5
        return "variation", 0.5 + similarity * 0.3

    if similarity >= high:
        return "repetition", 0.55 + similarity * 0.4
    # Call-and-response: similar content separated by one other phrase.
    if similarity >= 0.62:
        return "call-and-response", 0.5 + similarity * 0.3
    return "contrast", 0.5 + (high - similarity) * 0.6


def build_phrase_report_data(
    analysis: AudioAnalysis,
    sections: list[SongSection],
    config: PhraseDetectionConfig = DEFAULT_PHRASE_CONFIG,
) -> tuple[list[Phrase], list[PhraseRelationship]]:
    """Run the full phrase segmentation + relationship pipeline."""
    phrases = build_phrases(analysis, sections, config)
    relationships = classify_phrase_relationships(phrases, config)
    return phrases, relationships
