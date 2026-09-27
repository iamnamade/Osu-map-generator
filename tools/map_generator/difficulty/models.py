from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class DifficultyMapInfo:
    path: str
    title: str
    artist: str
    difficulty: str
    object_count: int
    duration_ms: int
    approach_time_ms: int
    circle_radius: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "artist": self.artist,
            "difficulty": self.difficulty,
            "objectCount": self.object_count,
            "durationMs": self.duration_ms,
            "approachTimeMs": self.approach_time_ms,
            "circleRadius": self.circle_radius,
        }


@dataclass(frozen=True)
class DifficultyTarget:
    name: str
    star_range: tuple[float, float]
    density_target: float
    jump_target: float
    speed_target: float
    reading_target: float
    tolerance: float

    @property
    def star_center(self) -> float:
        return (self.star_range[0] + self.star_range[1]) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "starRange": {"min": round(self.star_range[0], 2), "max": round(self.star_range[1], 2)},
            "starCenter": round(self.star_center, 2),
            "densityTarget": round(self.density_target, 3),
            "jumpTarget": round(self.jump_target, 3),
            "speedTarget": round(self.speed_target, 3),
            "readingTarget": round(self.reading_target, 3),
            "tolerance": round(self.tolerance, 3),
        }


@dataclass(frozen=True)
class RawMetrics:
    object_count: int
    circle_count: int
    slider_count: int
    spinner_count: int
    active_duration_ms: int
    objects_per_second: float
    circle_density: float
    slider_density: float
    spinner_frequency_per_minute: float
    average_gap_ms: float
    minimum_gap_ms: int
    maximum_gap_ms: int
    gap_standard_deviation_ms: float
    average_jump_distance: float
    maximum_jump_distance: float
    jump_distance_standard_deviation: float
    average_cursor_velocity_pps: float
    maximum_cursor_velocity_pps: float
    average_cursor_acceleration_pps2: float
    angle_complexity: float
    direction_change_count: int
    longest_stream_length: int
    longest_burst_length: int
    average_slider_length_ms: float
    average_slider_velocity_pps: float
    average_slider_repeats: float
    slider_complexity: float
    average_reaction_time_ms: float
    minimum_reaction_time_ms: int
    recovery_window_count: int
    pattern_variation: float
    stamina_demand: float
    rhythm_complexity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectCount": self.object_count,
            "circleCount": self.circle_count,
            "sliderCount": self.slider_count,
            "spinnerCount": self.spinner_count,
            "activeDurationMs": self.active_duration_ms,
            "objectsPerSecond": round(self.objects_per_second, 4),
            "circleDensity": round(self.circle_density, 4),
            "sliderDensity": round(self.slider_density, 4),
            "spinnerFrequencyPerMinute": round(self.spinner_frequency_per_minute, 4),
            "averageGapMs": round(self.average_gap_ms, 4),
            "minimumGapMs": self.minimum_gap_ms,
            "maximumGapMs": self.maximum_gap_ms,
            "gapStandardDeviationMs": round(self.gap_standard_deviation_ms, 4),
            "averageJumpDistance": round(self.average_jump_distance, 4),
            "maximumJumpDistance": round(self.maximum_jump_distance, 4),
            "jumpDistanceStandardDeviation": round(self.jump_distance_standard_deviation, 4),
            "averageCursorVelocityPps": round(self.average_cursor_velocity_pps, 4),
            "maximumCursorVelocityPps": round(self.maximum_cursor_velocity_pps, 4),
            "averageCursorAccelerationPps2": round(self.average_cursor_acceleration_pps2, 4),
            "angleComplexity": round(self.angle_complexity, 4),
            "directionChangeCount": self.direction_change_count,
            "longestStreamLength": self.longest_stream_length,
            "longestBurstLength": self.longest_burst_length,
            "averageSliderLengthMs": round(self.average_slider_length_ms, 4),
            "averageSliderVelocityPps": round(self.average_slider_velocity_pps, 4),
            "averageSliderRepeats": round(self.average_slider_repeats, 4),
            "sliderComplexity": round(self.slider_complexity, 4),
            "averageReactionTimeMs": round(self.average_reaction_time_ms, 4),
            "minimumReactionTimeMs": self.minimum_reaction_time_ms,
            "recoveryWindowCount": self.recovery_window_count,
            "patternVariation": round(self.pattern_variation, 4),
            "staminaDemand": round(self.stamina_demand, 4),
            "rhythmComplexity": round(self.rhythm_complexity, 4),
        }


@dataclass(frozen=True)
class ReadingMetrics:
    spacing_complexity: float
    stacking_count: int
    overlap_count: int
    visual_clutter: float
    approach_timing_ratio: float
    direction_ambiguity: float
    pattern_recognition_demand: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "spacingComplexity": round(self.spacing_complexity, 4),
            "stackingCount": self.stacking_count,
            "overlapCount": self.overlap_count,
            "visualClutter": round(self.visual_clutter, 4),
            "approachTimingRatio": round(self.approach_timing_ratio, 4),
            "directionAmbiguity": round(self.direction_ambiguity, 4),
            "patternRecognitionDemand": round(self.pattern_recognition_demand, 4),
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class RhythmMetrics:
    syncopation_ratio: float
    subdivision_variety: float
    rhythm_switch_count: int
    timing_consistency: float
    tempo_change_count: int
    offbeat_ratio: float
    triplet_count: int
    burst_count: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "syncopationRatio": round(self.syncopation_ratio, 4),
            "subdivisionVariety": round(self.subdivision_variety, 4),
            "rhythmSwitchCount": self.rhythm_switch_count,
            "timingConsistency": round(self.timing_consistency, 4),
            "tempoChangeCount": self.tempo_change_count,
            "offbeatRatio": round(self.offbeat_ratio, 4),
            "tripletCount": self.triplet_count,
            "burstCount": self.burst_count,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class AimMetrics:
    distance_demand: float
    speed_demand: float
    precision_demand: float
    angle_demand: float
    sharp_turn_count: int
    flow_quality: float
    micro_adjustment_count: int
    large_jump_count: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "distanceDemand": round(self.distance_demand, 4),
            "speedDemand": round(self.speed_demand, 4),
            "precisionDemand": round(self.precision_demand, 4),
            "angleDemand": round(self.angle_demand, 4),
            "sharpTurnCount": self.sharp_turn_count,
            "flowQuality": round(self.flow_quality, 4),
            "microAdjustmentCount": self.micro_adjustment_count,
            "largeJumpCount": self.large_jump_count,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class StaminaMetrics:
    continuous_activity_ms: int
    high_density_duration_ms: int
    stream_duration_ms: int
    rest_frequency: float
    slider_workload: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "continuousActivityMs": self.continuous_activity_ms,
            "highDensityDurationMs": self.high_density_duration_ms,
            "streamDurationMs": self.stream_duration_ms,
            "restFrequency": round(self.rest_frequency, 4),
            "sliderWorkload": round(self.slider_workload, 4),
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class PatternDifficulty:
    pattern: str
    start_ms: int
    end_ms: int
    object_count: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "objectCount": self.object_count,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class DifficultyCurvePoint:
    time_ms: int
    difficulty_score: float
    density: float
    speed: float
    flow: float
    reading: float
    rhythm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeMs": self.time_ms,
            "difficultyScore": round(self.difficulty_score, 4),
            "density": round(self.density, 4),
            "speed": round(self.speed, 4),
            "flow": round(self.flow, 4),
            "reading": round(self.reading, 4),
            "rhythm": round(self.rhythm, 4),
        }


@dataclass(frozen=True)
class SectionDifficulty:
    section_id: int | None
    label: str
    start_ms: int
    end_ms: int
    difficulty_score: float
    density: float
    speed: float
    reading: float
    rhythm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "label": self.label,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "difficultyScore": round(self.difficulty_score, 4),
            "density": round(self.density, 4),
            "speed": round(self.speed, 4),
            "reading": round(self.reading, 4),
            "rhythm": round(self.rhythm, 4),
        }


@dataclass(frozen=True)
class ObjectDifficulty:
    object_id: int
    object_type: str
    time_ms: int
    score: float
    contribution: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "objectType": self.object_type,
            "timeMs": self.time_ms,
            "score": round(self.score, 4),
            "contribution": round(self.contribution, 4),
        }


@dataclass(frozen=True)
class StarRating:
    overall: float
    aim: float
    speed: float
    reading: float
    rhythm: float
    stamina: float
    technical: float
    breakdown: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 2),
            "aim": round(self.aim, 2),
            "speed": round(self.speed, 2),
            "reading": round(self.reading, 2),
            "rhythm": round(self.rhythm, 2),
            "stamina": round(self.stamina, 2),
            "technical": round(self.technical, 2),
            "breakdown": {
                key: round(value, 4) if isinstance(value, float) else value
                for key, value in sorted(self.breakdown.items())
            },
        }


@dataclass(frozen=True)
class PlayerSimulation:
    cursor_travel_px: float
    reaction_difficulty: float
    miss_probability: float
    combo_stability: float
    recovery_ability: float
    cursor_fatigue: float
    stream_fatigue: float
    reading_stress: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursorTravelPx": round(self.cursor_travel_px, 2),
            "reactionDifficulty": round(self.reaction_difficulty, 4),
            "missProbability": round(self.miss_probability, 4),
            "comboStability": round(self.combo_stability, 4),
            "recoveryAbility": round(self.recovery_ability, 4),
            "cursorFatigue": round(self.cursor_fatigue, 4),
            "streamFatigue": round(self.stream_fatigue, 4),
            "readingStress": round(self.reading_stress, 4),
        }


@dataclass(frozen=True)
class ReplaySimulation:
    full_combo_chance: float
    expected_accuracy: float
    expected_misses: float
    highest_stress_section_ms: int
    hardest_pattern: str
    most_difficult_transition_ms: int
    simulated_playcount: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "fullComboChance": round(self.full_combo_chance, 4),
            "expectedAccuracy": round(self.expected_accuracy, 4),
            "expectedMisses": round(self.expected_misses, 4),
            "highestStressSectionMs": self.highest_stress_section_ms,
            "hardestPattern": self.hardest_pattern,
            "mostDifficultTransitionMs": self.most_difficult_transition_ms,
            "simulatedPlaycount": self.simulated_playcount,
        }


@dataclass(frozen=True)
class GameplayAnalytics:
    estimated_miss_probability: float
    estimated_combo_stability: float
    estimated_player_stress: float
    recovery_window_count: int
    average_recovery_window_ms: float
    hardest_passage_ms: int
    simulated_playcount: int
    player: PlayerSimulation | None = None
    replay: ReplaySimulation | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "estimatedMissProbability": round(self.estimated_miss_probability, 4),
            "estimatedComboStability": round(self.estimated_combo_stability, 4),
            "estimatedPlayerStress": round(self.estimated_player_stress, 4),
            "recoveryWindowCount": self.recovery_window_count,
            "averageRecoveryWindowMs": round(self.average_recovery_window_ms, 4),
            "hardestPassageMs": self.hardest_passage_ms,
            "simulatedPlaycount": self.simulated_playcount,
        }
        if self.player is not None:
            payload["player"] = self.player.to_dict()
        if self.replay is not None:
            payload["replay"] = self.replay.to_dict()
        return payload


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    severity: str
    message: str
    measured_value: float | None = None
    allowed_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.measured_value is not None:
            payload["measuredValue"] = round(self.measured_value, 4)
        if self.allowed_value is not None:
            payload["allowedValue"] = round(self.allowed_value, 4)
        return payload


@dataclass(frozen=True)
class DifficultyDiagnostics:
    difficulty_histogram: dict[str, int]
    object_contribution: list[ObjectDifficulty]
    hardest_patterns: list[PatternDifficulty]
    hardest_section: SectionDifficulty | None
    difficulty_variance: float
    star_calculation_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "difficultyHistogram": self.difficulty_histogram,
            "objectContribution": [item.to_dict() for item in self.object_contribution],
            "hardestPatterns": [item.to_dict() for item in self.hardest_patterns],
            "hardestSection": self.hardest_section.to_dict() if self.hardest_section else None,
            "difficultyVariance": round(self.difficulty_variance, 4),
            "starCalculationSummary": self.star_calculation_summary,
        }


@dataclass(frozen=True)
class DifficultyReport:
    version: int
    map: DifficultyMapInfo
    target: DifficultyTarget
    metrics: RawMetrics
    reading: ReadingMetrics
    rhythm: RhythmMetrics
    aim: AimMetrics
    stamina: StaminaMetrics
    patterns: list[PatternDifficulty]
    sections: list[SectionDifficulty]
    heatmap: list[dict[str, Any]]
    curve: list[DifficultyCurvePoint]
    object_difficulty: list[ObjectDifficulty]
    star_rating: StarRating
    gameplay: GameplayAnalytics
    verification: list[VerificationIssue]
    diagnostics: DifficultyDiagnostics
    recommended_player_level: str
    consistency_score: float
    peak_difficulty: float
    average_difficulty: float
    confidence_score: float
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "map": self.map.to_dict(),
            "target": self.target.to_dict(),
            "metrics": self.metrics.to_dict(),
            "reading": self.reading.to_dict(),
            "rhythm": self.rhythm.to_dict(),
            "aim": self.aim.to_dict(),
            "stamina": self.stamina.to_dict(),
            "patterns": [item.to_dict() for item in self.patterns],
            "sections": [item.to_dict() for item in self.sections],
            "heatmap": self.heatmap,
            "curve": [item.to_dict() for item in self.curve],
            "objectDifficulty": [item.to_dict() for item in self.object_difficulty],
            "starRating": self.star_rating.to_dict(),
            "gameplay": self.gameplay.to_dict(),
            "verification": [item.to_dict() for item in self.verification],
            "diagnostics": self.diagnostics.to_dict(),
            "recommendedPlayerLevel": self.recommended_player_level,
            "consistencyScore": round(self.consistency_score, 4),
            "peakDifficulty": round(self.peak_difficulty, 4),
            "averageDifficulty": round(self.average_difficulty, 4),
            "confidenceScore": round(self.confidence_score, 4),
            "signature": self.signature,
        }
