from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


@dataclass(frozen=True)
class ReplayPlayerProfile:
    """Configurable virtual player model.

    All values are deterministic inputs to the simulation. Higher aim/rhythm
    precision and consistency mean a stronger player; fatigue growth and
    recovery speed control how stamina behaves across the map.
    """

    name: str
    label: str
    reaction_time_ms: float
    cursor_speed_pps: float
    aim_precision: float
    rhythm_precision: float
    fatigue_growth: float
    recovery_speed: float
    consistency: float
    pattern_memory: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "reactionTimeMs": _round(self.reaction_time_ms),
            "cursorSpeedPps": _round(self.cursor_speed_pps),
            "aimPrecision": _round(self.aim_precision),
            "rhythmPrecision": _round(self.rhythm_precision),
            "fatigueGrowth": _round(self.fatigue_growth),
            "recoverySpeed": _round(self.recovery_speed),
            "consistency": _round(self.consistency),
            "patternMemory": _round(self.pattern_memory),
        }


@dataclass(frozen=True)
class CursorSegment:
    from_object_id: int
    to_object_id: int
    start_ms: int
    end_ms: int
    distance_px: float
    velocity_pps: float
    acceleration_pps2: float
    angle_deg: float
    required_velocity_pps: float
    penalty: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fromObjectId": self.from_object_id,
            "toObjectId": self.to_object_id,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "distancePx": _round(self.distance_px, 2),
            "velocityPps": _round(self.velocity_pps, 2),
            "accelerationPps2": _round(self.acceleration_pps2, 2),
            "angleDeg": _round(self.angle_deg, 2),
            "requiredVelocityPps": _round(self.required_velocity_pps, 2),
            "penalty": _round(self.penalty),
        }


@dataclass(frozen=True)
class CursorSimulation:
    total_travel_px: float
    average_velocity_pps: float
    peak_velocity_pps: float
    average_acceleration_pps2: float
    sharp_turn_count: int
    efficiency: float
    segments: list[CursorSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalTravelPx": _round(self.total_travel_px, 2),
            "averageVelocityPps": _round(self.average_velocity_pps, 2),
            "peakVelocityPps": _round(self.peak_velocity_pps, 2),
            "averageAccelerationPps2": _round(self.average_acceleration_pps2, 2),
            "sharpTurnCount": self.sharp_turn_count,
            "efficiency": _round(self.efficiency),
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class HitEvent:
    object_id: int
    object_type: str
    time_ms: int
    offset_ms: float
    result: str
    demand: float
    fatigue: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "objectType": self.object_type,
            "timeMs": self.time_ms,
            "offsetMs": _round(self.offset_ms, 2),
            "result": self.result,
            "demand": _round(self.demand),
            "fatigue": _round(self.fatigue),
        }


@dataclass(frozen=True)
class HitSimulationResult:
    events: list[HitEvent]
    expected_accuracy: float
    expected_misses: float
    full_combo_chance: float
    result_counts: dict[str, int]
    timing_consistency: float
    peak_stress_ms: int


@dataclass(frozen=True)
class ComboStats:
    combo_breaks: int
    max_combo: int
    expected_combo_pct: float
    recovery_time_ms: float
    miss_clusters: int
    isolated_misses: int
    stream_failures: int
    average_combo_before_break: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "comboBreaks": self.combo_breaks,
            "maxCombo": self.max_combo,
            "expectedComboPct": _round(self.expected_combo_pct),
            "recoveryTimeMs": _round(self.recovery_time_ms, 2),
            "missClusters": self.miss_clusters,
            "isolatedMisses": self.isolated_misses,
            "streamFailures": self.stream_failures,
            "averageComboBeforeBreak": _round(self.average_combo_before_break, 2),
        }


@dataclass(frozen=True)
class PatternRecognizability:
    kind: str
    label: str
    count: int
    recognizability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "count": self.count,
            "recognizability": _round(self.recognizability),
        }


@dataclass(frozen=True)
class PatternTransition:
    from_ms: int
    to_ms: int
    from_kind: str
    to_kind: str
    angle_deg: float
    penalty: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fromMs": self.from_ms,
            "toMs": self.to_ms,
            "fromKind": self.from_kind,
            "toKind": self.to_kind,
            "angleDeg": _round(self.angle_deg, 2),
            "penalty": _round(self.penalty),
        }


@dataclass(frozen=True)
class PatternRecognitionResult:
    patterns: list[PatternRecognizability]
    transitions: list[PatternTransition]
    overall_recognizability: float
    transition_penalty: float
    hardest_pattern: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "patterns": [item.to_dict() for item in self.patterns],
            "transitions": [item.to_dict() for item in self.transitions],
            "overallRecognizability": _round(self.overall_recognizability),
            "transitionPenalty": _round(self.transition_penalty),
            "hardestPattern": self.hardest_pattern,
        }


@dataclass(frozen=True)
class FatigueSample:
    time_ms: int
    fatigue: float
    section_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeMs": self.time_ms,
            "fatigue": _round(self.fatigue),
            "sectionLabel": self.section_label,
        }


@dataclass(frozen=True)
class FatigueCurve:
    samples: list[FatigueSample]
    average: float
    peak: float
    recovery_episodes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": [sample.to_dict() for sample in self.samples],
            "average": _round(self.average),
            "peak": _round(self.peak),
            "recoveryEpisodes": self.recovery_episodes,
        }


@dataclass(frozen=True)
class ReadingSimulation:
    score: float
    spacing: float
    time_spacing: float
    angle_variation: float
    pattern_repetition: float
    visual_clutter: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": _round(self.score, 2),
            "spacing": _round(self.spacing),
            "timeSpacing": _round(self.time_spacing),
            "angleVariation": _round(self.angle_variation),
            "patternRepetition": _round(self.pattern_repetition),
            "visualClutter": _round(self.visual_clutter),
        }


@dataclass(frozen=True)
class SectionReplayResult:
    section_id: int | None
    label: str
    start_ms: int
    end_ms: int
    object_count: int
    miss_rate: float
    accuracy: float
    fatigue_peak: float
    reading_demand: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "label": self.label,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "objectCount": self.object_count,
            "missRate": _round(self.miss_rate),
            "accuracy": _round(self.accuracy),
            "fatiguePeak": _round(self.fatigue_peak),
            "readingDemand": _round(self.reading_demand),
        }


@dataclass(frozen=True)
class ReplayScoreBreakdown:
    accuracy_prediction: float
    miss_prediction: float
    combo_stability: float
    reading: float
    cursor_efficiency: float
    fatigue: float
    rhythm_consistency: float
    overall: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracyPrediction": _round(self.accuracy_prediction, 2),
            "missPrediction": _round(self.miss_prediction, 2),
            "comboStability": _round(self.combo_stability, 2),
            "reading": _round(self.reading, 2),
            "cursorEfficiency": _round(self.cursor_efficiency, 2),
            "fatigue": _round(self.fatigue, 2),
            "rhythmConsistency": _round(self.rhythm_consistency, 2),
            "overall": _round(self.overall, 2),
        }


@dataclass(frozen=True)
class ReplayReport:
    version: int
    map_title: str
    map_artist: str
    difficulty: str
    object_count: int
    duration_ms: int
    bpm: float
    approach_time_ms: int
    player: ReplayPlayerProfile
    seed: int
    cursor: CursorSimulation
    hit_events: list[HitEvent]
    expected_accuracy: float
    expected_misses: float
    full_combo_chance: float
    result_counts: dict[str, int]
    timing_consistency: float
    peak_stress_ms: int
    combo: ComboStats
    patterns: PatternRecognitionResult
    fatigue: FatigueCurve
    reading: ReadingSimulation
    sections: list[SectionReplayResult]
    weakest_sections: list[SectionReplayResult]
    strongest_sections: list[SectionReplayResult]
    score_breakdown: ReplayScoreBreakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "map": {
                "title": self.map_title,
                "artist": self.map_artist,
                "difficulty": self.difficulty,
                "objectCount": self.object_count,
                "durationMs": self.duration_ms,
                "bpm": _round(self.bpm, 2),
                "approachTimeMs": self.approach_time_ms,
            },
            "player": self.player.to_dict(),
            "seed": self.seed,
            "cursor": self.cursor.to_dict(),
            "hitEvents": [event.to_dict() for event in self.hit_events],
            "expectedAccuracy": _round(self.expected_accuracy),
            "expectedMisses": _round(self.expected_misses, 2),
            "fullComboChance": _round(self.full_combo_chance),
            "resultCounts": self.result_counts,
            "timingConsistency": _round(self.timing_consistency),
            "peakStressMs": self.peak_stress_ms,
            "combo": self.combo.to_dict(),
            "patterns": self.patterns.to_dict(),
            "fatigue": self.fatigue.to_dict(),
            "reading": self.reading.to_dict(),
            "sections": [section.to_dict() for section in self.sections],
            "weakestSections": [section.to_dict() for section in self.weakest_sections],
            "strongestSections": [section.to_dict() for section in self.strongest_sections],
            "scoreBreakdown": self.score_breakdown.to_dict(),
        }
