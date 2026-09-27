from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SpinnerRegionType = Literal["intro", "break", "outro", "transition", "sustained", "dense", "unknown"]

SpinnerTriggerType = Literal["sustain", "fade_out", "transition", "riser", "unknown"]

@dataclass(frozen=True)
class SpinnerCandidate:
    """A candidate musical region that could become a spinner."""

    region_type: SpinnerRegionType
    start_ms: int
    end_ms: int
    duration_ms: int
    musical_score: float  # 0-100 how strongly the music supports a spinner
    sustained_score: float  # 0-100 sustained/ambient content strength
    energy: float  # average normalized energy inside the region
    onset_density: float  # onsets per second inside the region
    gap_before_ms: int | None  # distance from previous object end
    gap_after_ms: int | None  # distance to next object start
    section_label: str | None  # optional section label when section data is available
    # Phase 22: musical trigger that justifies this spinner placement.
    trigger_type: SpinnerTriggerType = "unknown"
    # Phase 22: post-spinner clearance required before the next object.
    min_clearance_ms: int = 400
    # Phase 22: owning phrase id when phrase analysis is available.
    phrase_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "regionType": self.region_type,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "durationMs": self.duration_ms,
            "musicalScore": round(self.musical_score, 2),
            "sustainedScore": round(self.sustained_score, 2),
            "energy": round(self.energy, 4),
            "onsetDensity": round(self.onset_density, 4),
            "gapBeforeMs": self.gap_before_ms,
            "gapAfterMs": self.gap_after_ms,
            "sectionLabel": self.section_label,
            "triggerType": self.trigger_type,
            "minClearanceMs": self.min_clearance_ms,
            "phraseId": self.phrase_id,
        }


@dataclass(frozen=True)
class SpinnerConfig:
    """Difficulty constraints for spinner placement.

    Mirrors the difficulty guidelines exposed by the recovery engine
    (``spinner_guidelines``) as a single dataclass for validation call sites.
    """

    min_duration_ms: int = 1000
    post_clearance_ms: int = 400
    max_spinners_per_map: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "minDurationMs": self.min_duration_ms,
            "postClearanceMs": self.post_clearance_ms,
            "maxSpinnersPerMap": self.max_spinners_per_map,
        }


@dataclass(frozen=True)
class SpinnerQualityScore:
    """Quality metrics for a generated spinner."""

    musical_match: float  # 0-100
    timing_quality: float  # 0-100
    duration_score: float  # 0-100
    transition_quality: float  # 0-100
    difficulty_impact: float  # 0-100
    flow: float  # 0-100
    overall: float  # 0-100


@dataclass
class SpinnerDiagnostics:
    """Diagnostic information about spinner generation."""

    total_candidates: int = 0
    accepted_spinners: int = 0
    rejected_spinners: int = 0
    region_type_counts: dict[str, int] = field(default_factory=dict)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    trigger_type_counts: dict[str, int] = field(default_factory=dict)
    average_duration_ms: float = 0.0
    longest_duration_ms: int = 0
    shortest_duration_ms: int = 0
    average_quality_score: float = 0.0
    average_musical_match: float = 0.0
    average_transition_quality: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    # Phase 22 recovery & fatigue reporting.
    fatigue_peak: float = 0.0
    fatigue_peak_time_ms: int = 0
    recovery_windows: list[dict[str, Any]] = field(default_factory=list)
    harmony: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCandidates": self.total_candidates,
            "acceptedSpinners": self.accepted_spinners,
            "rejectedSpinners": self.rejected_spinners,
            "regionTypeCounts": dict(self.region_type_counts),
            "rejectionReasons": dict(self.rejection_reasons),
            "triggerTypeCounts": dict(self.trigger_type_counts),
            "averageDurationMs": round(self.average_duration_ms, 2),
            "longestDurationMs": self.longest_duration_ms,
            "shortestDurationMs": self.shortest_duration_ms,
            "averageQualityScore": round(self.average_quality_score, 2),
            "averageMusicalMatch": round(self.average_musical_match, 2),
            "averageTransitionQuality": round(self.average_transition_quality, 2),
            "candidates": list(self.candidates),
            "fatiguePeak": round(self.fatigue_peak, 4),
            "fatiguePeakTimeMs": self.fatigue_peak_time_ms,
            "recoveryWindows": list(self.recovery_windows),
            "harmony": self.harmony,
        }


@dataclass(frozen=True)
class SpinnerMusicalContext:
    """Pre-computed musical structure used to evaluate spinner candidates.

    Built once per map from the audio analysis, sustained analysis, and
    optional section analysis. Keeps the decision pipeline deterministic.
    """

    duration_ms: int
    bpm: float
    energy_frames: list[dict[str, Any]] = field(default_factory=list)
    onset_times: list[int] = field(default_factory=list)
    quiet_regions: list[dict[str, Any]] = field(default_factory=list)
    high_energy_regions: list[dict[str, Any]] = field(default_factory=list)
    sustained_regions: list[dict[str, Any]] = field(default_factory=list)
    sustained_frames: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)

    def energy_trend_at(self, start_ms: int, end_ms: int) -> str:
        frames = [
            frame for frame in self.energy_frames if start_ms <= frame["timeMs"] <= end_ms
        ]
        if len(frames) < 2:
            return "steady"
        first_half = sum(float(frame["value"]) for frame in frames[: len(frames) // 2])
        second_half = sum(float(frame["value"]) for frame in frames[len(frames) // 2 :])
        if second_half > first_half * 1.12:
            return "rising"
        if first_half > second_half * 1.12:
            return "falling"
        return "steady"

    def energy_at(self, time_ms: int) -> float:
        if not self.energy_frames:
            return 0.0
        closest = min(
            self.energy_frames,
            key=lambda frame: abs(frame["timeMs"] - time_ms),
        )
        return float(closest["value"])

    def sustained_at(self, time_ms: int, window_ms: int = 120) -> float:
        if not self.sustained_frames:
            return 0.0
        half = window_ms // 2
        nearby = [
            float(frame["sustainedScore"])
            for frame in self.sustained_frames
            if abs(frame["timeMs"] - time_ms) <= half
        ]
        return sum(nearby) / len(nearby) if nearby else 0.0


@dataclass(frozen=True)
class RecoveryWindow:
    """A calm-down pacing window inserted after high-strain gameplay."""

    start_time: int
    end_time: int
    stamina_reduction_factor: float = 0.5
    reason: str = "post_intense_stream"
    phrase_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "startTime": self.start_time,
            "endTime": self.end_time,
            "staminaReductionFactor": round(self.stamina_reduction_factor, 4),
            "reason": self.reason,
            "phraseId": self.phrase_id,
        }


@dataclass(frozen=True)
class FatigueProfile:
    """Cumulative player fatigue curve (normalized 0.0 to 1.0)."""

    timestamps: list[int]
    fatigue_scores: list[float]  # normalized 0.0-1.0
    peak_fatigue_time: int
    peak_fatigue: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamps": list(self.timestamps),
            "fatigueScores": [round(value, 4) for value in self.fatigue_scores],
            "peakFatigueTime": self.peak_fatigue_time,
            "peakFatigue": round(self.peak_fatigue, 4),
        }

    @classmethod
    def empty(cls) -> "FatigueProfile":
        return cls(timestamps=[], fatigue_scores=[], peak_fatigue_time=0, peak_fatigue=0.0)
