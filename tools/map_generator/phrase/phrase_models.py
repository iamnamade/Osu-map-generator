"""Phase 20 phrase-level intelligence: core domain schemas.

A phrase is a structured musical block inside a song section. Phrases carry
acoustic features, a motif identity (for long-range coherence across repeated
sections), a strategy (establish / intensify / release / ...), and a
trajectory (target density / difficulty / entry-exit vectors).

Every model is fully serializable (``to_dict`` / ``from_dict``) with
backward-compatible defaults so older workspace payloads parse cleanly, and
all parsing is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PhraseRelationshipType = Literal[
    "repetition",
    "variation",
    "continuation",
    "escalation",
    "reduction",
    "contrast",
    "call-and-response",
    "transition",
]

PhraseStrategyName = Literal[
    "establish",
    "intensify",
    "release",
    "contrast",
    "recover",
    "transition",
    "neutral",
]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


# ---------------------------------------------------------------------------
# Phrase
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phrase:
    """A single musical phrase block."""

    id: int
    start_ms: int
    end_ms: int
    duration_ms: int
    section_id: int | None
    label: str
    confidence: float
    # Acoustic features
    average_energy: float
    energy_slope: float
    onset_density: float
    beat_density: float
    average_onset_strength: float
    rhythm_complexity: float
    spectral_flux: float
    emphasis_ratio: float
    quiet_ratio: float
    high_energy_ratio: float
    subdivision_ratio: float
    # Motif / strategy
    motif_id: int | None
    strategy: PhraseStrategyName = "neutral"
    # Trajectory targets
    target_density: float = 0.0
    target_difficulty: float = 0.0
    min_gap_ms: int = 0
    target_gap_ms: int = 0
    entry_direction_deg: float | None = None
    exit_direction_deg: float | None = None
    # Relation back to the section-level repetition group when known
    section_repetition_group: int | None = None

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms < self.end_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "durationMs": self.duration_ms,
            "sectionId": self.section_id,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "averageEnergy": round(self.average_energy, 4),
            "energySlope": round(self.energy_slope, 6),
            "onsetDensity": round(self.onset_density, 4),
            "beatDensity": round(self.beat_density, 4),
            "averageOnsetStrength": round(self.average_onset_strength, 4),
            "rhythmComplexity": round(self.rhythm_complexity, 4),
            "spectralFlux": round(self.spectral_flux, 6),
            "emphasisRatio": round(self.emphasis_ratio, 4),
            "quietRatio": round(self.quiet_ratio, 4),
            "highEnergyRatio": round(self.high_energy_ratio, 4),
            "subdivisionRatio": round(self.subdivision_ratio, 4),
            "motifId": self.motif_id,
            "strategy": self.strategy,
            "targetDensity": round(self.target_density, 4),
            "targetDifficulty": round(self.target_difficulty, 4),
            "minGapMs": self.min_gap_ms,
            "targetGapMs": self.target_gap_ms,
            "entryDirectionDeg": _round(self.entry_direction_deg),
            "exitDirectionDeg": _round(self.exit_direction_deg),
            "sectionRepetitionGroup": self.section_repetition_group,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Phrase":
        return cls(
            id=_int(payload.get("id")),
            start_ms=_int(payload.get("startMs")),
            end_ms=_int(payload.get("endMs")),
            duration_ms=_int(payload.get("durationMs")),
            section_id=(
                _int(payload["sectionId"])
                if isinstance(payload.get("sectionId"), (int, float))
                else None
            ),
            label=_string(payload.get("label"), "phrase"),
            confidence=_number(payload.get("confidence"), 0.5),
            average_energy=_number(payload.get("averageEnergy")),
            energy_slope=_number(payload.get("energySlope")),
            onset_density=_number(payload.get("onsetDensity")),
            beat_density=_number(payload.get("beatDensity")),
            average_onset_strength=_number(payload.get("averageOnsetStrength")),
            rhythm_complexity=_number(payload.get("rhythmComplexity")),
            spectral_flux=_number(payload.get("spectralFlux")),
            emphasis_ratio=_number(payload.get("emphasisRatio")),
            quiet_ratio=_number(payload.get("quietRatio")),
            high_energy_ratio=_number(payload.get("highEnergyRatio")),
            subdivision_ratio=_number(payload.get("subdivisionRatio")),
            motif_id=(
                _int(payload["motifId"])
                if isinstance(payload.get("motifId"), (int, float))
                else None
            ),
            strategy=_strategy(payload.get("strategy")),
            target_density=_number(payload.get("targetDensity")),
            target_difficulty=_number(payload.get("targetDifficulty")),
            min_gap_ms=_int(payload.get("minGapMs")),
            target_gap_ms=_int(payload.get("targetGapMs")),
            entry_direction_deg=(
                _number(payload["entryDirectionDeg"])
                if isinstance(payload.get("entryDirectionDeg"), (int, float))
                else None
            ),
            exit_direction_deg=(
                _number(payload["exitDirectionDeg"])
                if isinstance(payload.get("exitDirectionDeg"), (int, float))
                else None
            ),
            section_repetition_group=(
                _int(payload["sectionRepetitionGroup"])
                if isinstance(payload.get("sectionRepetitionGroup"), (int, float))
                else None
            ),
        )


def _strategy(value: Any) -> PhraseStrategyName:
    allowed: set[str] = {
        "establish",
        "intensify",
        "release",
        "contrast",
        "recover",
        "transition",
        "neutral",
    }
    return value if isinstance(value, str) and value in allowed else "neutral"


# ---------------------------------------------------------------------------
# Phrase relationship
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhraseRelationship:
    """A classified relationship between two phrases."""

    id: int
    from_phrase_id: int
    to_phrase_id: int
    relationship_type: PhraseRelationshipType
    similarity: float
    confidence: float
    feature_deltas: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fromPhraseId": self.from_phrase_id,
            "toPhraseId": self.to_phrase_id,
            "relationshipType": self.relationship_type,
            "similarity": round(self.similarity, 4),
            "confidence": round(self.confidence, 4),
            "featureDeltas": {
                key: round(value, 4)
                for key, value in sorted(self.feature_deltas.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PhraseRelationship":
        return cls(
            id=_int(payload.get("id")),
            from_phrase_id=_int(payload.get("fromPhraseId")),
            to_phrase_id=_int(payload.get("toPhraseId")),
            relationship_type=_relationship(payload.get("relationshipType")),
            similarity=_number(payload.get("similarity")),
            confidence=_number(payload.get("confidence"), 0.5),
            feature_deltas={
                str(key): _number(value)
                for key, value in (payload.get("featureDeltas") or {}).items()
            },
        )


def _relationship(value: Any) -> PhraseRelationshipType:
    allowed: set[str] = {
        "repetition",
        "variation",
        "continuation",
        "escalation",
        "reduction",
        "contrast",
        "call-and-response",
        "transition",
    }
    return value if isinstance(value, str) and value in allowed else "continuation"


# ---------------------------------------------------------------------------
# Motif
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Motif:
    """A persistent musical motif shared by repeated phrases."""

    id: int
    phrase_ids: list[int]
    rhythm_signature: list[float]
    density_profile: list[float]
    occurrence_count: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phraseIds": self.phrase_ids,
            "rhythmSignature": [round(value, 4) for value in self.rhythm_signature],
            "densityProfile": [round(value, 4) for value in self.density_profile],
            "occurrenceCount": self.occurrence_count,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Motif":
        return cls(
            id=_int(payload.get("id")),
            phrase_ids=[_int(item) for item in (payload.get("phraseIds") or [])],
            rhythm_signature=[_number(item) for item in (payload.get("rhythmSignature") or [])],
            density_profile=[_number(item) for item in (payload.get("densityProfile") or [])],
            occurrence_count=_int(payload.get("occurrenceCount")),
            label=_string(payload.get("label"), f"Motif {payload.get('id', '')}"),
        )


# ---------------------------------------------------------------------------
# Phrase report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhraseReport:
    """Complete phrase-level analysis for one song."""

    version: int
    audio_path: str
    duration_ms: int
    configuration: dict[str, Any]
    input_signature: str
    phrases: list[Phrase]
    relationships: list[PhraseRelationship]
    motifs: list[Motif]
    trajectory: list[dict[str, float]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "audio": {
                "path": self.audio_path,
                "durationMs": self.duration_ms,
            },
            "configuration": self.configuration,
            "inputSignature": self.input_signature,
            "phrases": [phrase.to_dict() for phrase in self.phrases],
            "relationships": [relationship.to_dict() for relationship in self.relationships],
            "motifs": [motif.to_dict() for motif in self.motifs],
            "trajectory": [
                {key: round(value, 4) for key, value in sorted(point.items())}
                for point in self.trajectory
            ],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PhraseReport":
        audio = payload.get("audio") or {}
        phrases_raw = payload.get("phrases") or []
        relationships_raw = payload.get("relationships") or []
        motifs_raw = payload.get("motifs") or []
        trajectory_raw = payload.get("trajectory") or []
        return cls(
            version=_int(payload.get("version"), 1),
            audio_path=_string(audio.get("path") if isinstance(audio, dict) else None),
            duration_ms=_int(
                audio.get("durationMs") if isinstance(audio, dict) else None
            ),
            configuration=(
                payload["configuration"]
                if isinstance(payload.get("configuration"), dict)
                else {}
            ),
            input_signature=_string(payload.get("inputSignature")),
            phrases=[
                Phrase.from_dict(item)
                for item in phrases_raw
                if isinstance(item, dict)
            ],
            relationships=[
                PhraseRelationship.from_dict(item)
                for item in relationships_raw
                if isinstance(item, dict)
            ],
            motifs=[Motif.from_dict(item) for item in motifs_raw if isinstance(item, dict)],
            trajectory=[
                {str(key): _number(value) for key, value in point.items()}
                for point in trajectory_raw
                if isinstance(point, dict)
            ],
            summary=(
                payload["summary"] if isinstance(payload.get("summary"), dict) else {}
            ),
        )
