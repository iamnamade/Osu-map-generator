from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class BpmRegion:
    """A region of the song with a consistent local BPM estimate."""

    start_ms: int
    end_ms: int
    bpm: float
    confidence: float
    beat_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "bpm": round(self.bpm, 3),
            "confidence": round(self.confidence, 4),
            "beatCount": self.beat_count,
        }

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms < self.end_ms


SubdivisionLevel = Literal["none", "half", "quarter", "eighth", "sixteenth"]


@dataclass(frozen=True)
class SubdivisionInfo:
    """Detected subdivision level for a specific time window."""

    start_ms: int
    end_ms: int
    level: SubdivisionLevel
    confidence: float
    grid_times_ms: list[int]
    average_alignment_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "level": self.level,
            "confidence": round(self.confidence, 4),
            "gridTimesMs": self.grid_times_ms[:50],  # limit output size
            "averageAlignmentScore": round(self.average_alignment_score, 4),
        }


PhraseLabel = Literal[
    "intro-like",
    "verse-like",
    "build-up",
    "chorus-like",
    "drop-like",
    "break-like",
    "bridge-like",
    "outro-like",
    "instrumental",
    "quiet",
    "unknown",
]


@dataclass(frozen=True)
class PhraseInfo:
    """A musical phrase with density and timing expectations."""

    start_ms: int
    end_ms: int
    label: PhraseLabel
    confidence: float
    expected_density: float  # objects per second target
    density_flexibility: float  # how much density can vary (0=rigid, 1=loose)
    min_gap_ms: int  # minimum gap within this phrase
    target_gap_ms: int  # preferred gap within this phrase
    # Phase 20/21: mapping strategy (establish / intensify / release /
    # contrast / recover / transition / neutral). Consumed by slider shaping
    # so slider length/curvature respond to the phrase narrative.
    strategy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "expectedDensity": round(self.expected_density, 4),
            "densityFlexibility": round(self.density_flexibility, 4),
            "minGapMs": self.min_gap_ms,
            "targetGapMs": self.target_gap_ms,
            "strategy": self.strategy,
        }

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms < self.end_ms


@dataclass(frozen=True)
class TimingCandidate:
    """A single candidate timing point with confidence."""

    time_ms: int
    source: Literal["beat", "onset", "subdivision", "emphasis", "fill"]
    strength: float
    confidence: float
    alignment_score: float  # how well this aligns with beat grid
    density_fit: float  # how well this fits the local density target
    phase: str  # "strong", "weak", "filler", "rejected"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeMs": self.time_ms,
            "source": self.source,
            "strength": round(self.strength, 4),
            "confidence": round(self.confidence, 4),
            "alignmentScore": round(self.alignment_score, 4),
            "densityFit": round(self.density_fit, 4),
            "phase": self.phase,
        }


@dataclass(frozen=True)
class TimingQualityScore:
    """Quality evaluation for a set of selected timings."""

    overall_quality: float  # 0-100
    beat_alignment: float  # 0-100
    onset_alignment: float  # 0-100
    density_consistency: float  # 0-100
    gap_uniformity: float  # 0-100 (penalize very uneven gaps)
    subdivision_usage: float  # 0-100
    coverage_ratio: float  # how much of the song is covered vs silent gaps
    long_gap_count: int
    rejected_timing_count: int
    accepted_timing_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "overallQuality": round(self.overall_quality, 3),
            "beatAlignment": round(self.beat_alignment, 3),
            "onsetAlignment": round(self.onset_alignment, 3),
            "densityConsistency": round(self.density_consistency, 3),
            "gapUniformity": round(self.gap_uniformity, 3),
            "subdivisionUsage": round(self.subdivision_usage, 3),
            "coverageRatio": round(self.coverage_ratio, 4),
            "longGapCount": self.long_gap_count,
            "rejectedTimingCount": self.rejected_timing_count,
            "acceptedTimingCount": self.accepted_timing_count,
        }


@dataclass(frozen=True)
class RhythmDiagnostics:
    """Full diagnostic report for the rhythm intelligence engine."""

    version: int = 2
    bpm_regions: list[BpmRegion] = field(default_factory=list)
    subdivisions: list[SubdivisionInfo] = field(default_factory=list)
    phrases: list[PhraseInfo] = field(default_factory=list)
    global_tempo_confidence: float = 0.0
    global_bpm: float = 0.0
    timing_candidates: list[TimingCandidate] = field(default_factory=list)
    timing_quality: TimingQualityScore | None = None
    rejected_timings: list[TimingCandidate] = field(default_factory=list)
    accepted_timings: list[TimingCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "bpmRegions": [region.to_dict() for region in self.bpm_regions],
            "subdivisions": [sub.to_dict() for sub in self.subdivisions],
            "phrases": [phrase.to_dict() for phrase in self.phrases],
            "globalTempoConfidence": round(self.global_tempo_confidence, 4),
            "globalBpm": round(self.global_bpm, 3),
            "timingCandidates": [c.to_dict() for c in self.timing_candidates],
            "timingQuality": self.timing_quality.to_dict() if self.timing_quality else None,
            "rejectedTimings": [c.to_dict() for c in self.rejected_timings],
            "acceptedTimings": [c.to_dict() for c in self.accepted_timings],
        }


@dataclass(frozen=True)
class EnhancedAudioFeatures:
    """Extended audio features that supplement the base AudioAnalysis."""

    spectral_flux: list[float]
    spectral_flux_times_ms: list[int]
    multi_band_onset_strengths: dict[str, list[float]]
    local_bpm_estimates: list[tuple[int, float, float]]  # (time_ms, bpm, confidence)
    tempo_stability: float  # 0-1, how stable tempo is across the song
    dominant_frequencies: list[float] | None = None


@dataclass
class RhythmModel:
    """Complete multi-layer rhythm model for a song.

    This is the core output of the rhythm intelligence engine, combining
    all signals into a unified model that drives event selection.
    """

    analysis: Any = None  # AudioAnalysis, imported lazily
    enhanced_features: EnhancedAudioFeatures | None = None
    bpm_regions: list[BpmRegion] = field(default_factory=list)
    subdivisions: list[SubdivisionInfo] = field(default_factory=list)
    silent_regions: list[tuple[int, int]] = field(default_factory=list)
    density_targets: list[tuple[int, float]] = field(default_factory=list)
    phrase_info: list[PhraseInfo] = field(default_factory=list)
    tempo_confidence: float = 0.0
    diagnostics: Any = None  # RhythmDiagnostics, set later
    rhythm_config: Any = None
    preset: Any = None  # DifficultyPreset
