from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SliderPathType = Literal["bezier", "linear", "catmull", "perfect"]

# Phase 21: expressive slider shape families. A shape maps to an osu path
# type plus a deterministic multi-segment geometry (see slider_geometry).
SliderShape = Literal["linear", "hook", "arc", "wave", "zigzag", "loop"]


@dataclass(frozen=True)
class ControlPoint:
    x: int
    y: int

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class SliderCandidate:
    """A candidate timing that could become a slider instead of a circle."""

    event_index: int
    time_ms: int
    length_ms: int
    end_time_ms: int
    energy: float
    sustained_score: float
    slider_probability: float
    preferred_path_type: SliderPathType
    preferred_repeats: int
    preferred_pixel_length: int
    # Phase 21: expressive shape family chosen at decision time.
    preferred_shape: SliderShape = "linear"
    # Phase 21: curvature factor (0-1) chosen at decision time.
    preferred_curvature: float = 0.3
    # Phase 21: phrase strategy context that shaped this candidate ("intensify",
    # "recover", ... or None when no phrase structure is available).
    phrase_strategy: str | None = None


@dataclass(frozen=True)
class SustainedAnalysis:
    """Results of sustained audio content analysis."""

    sustained_regions: list[dict[str, Any]] = field(default_factory=list)
    sustained_frames: list[dict[str, Any]] = field(default_factory=list)
    average_sustained_energy: float = 0.0
    sustained_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sustainedRegions": self.sustained_regions,
            "sustainedFrames": self.sustained_frames,
            "averageSustainedEnergy": round(self.average_sustained_energy, 4),
            "sustainedRatio": round(self.sustained_ratio, 4),
        }


@dataclass(frozen=True)
class SliderQualityScore:
    """Quality metrics for a generated slider."""

    musical_match: float  # 0-100
    flow: float  # 0-100
    shape_quality: float  # 0-100
    comfort: float  # 0-100
    spacing: float  # 0-100
    difficulty: float  # 0-100
    transition_quality: float  # 0-100
    overall: float  # 0-100


@dataclass
class SliderDiagnostics:
    """Diagnostic information about slider generation."""

    total_candidates: int = 0
    accepted_sliders: int = 0
    rejected_sliders: int = 0
    path_type_counts: dict[str, int] = field(default_factory=dict)
    average_length_px: float = 0.0
    average_repeats: float = 1.0
    average_quality_score: float = 0.0
    repeat_distribution: dict[int, int] = field(default_factory=dict)
    # Phase 21: accepted shape family distribution.
    shape_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCandidates": self.total_candidates,
            "acceptedSliders": self.accepted_sliders,
            "rejectedSliders": self.rejected_sliders,
            "pathTypeCounts": dict(self.path_type_counts),
            "averageLengthPx": round(self.average_length_px, 2),
            "averageRepeats": round(self.average_repeats, 2),
            "averageQualityScore": round(self.average_quality_score, 2),
            "repeatDistribution": dict(self.repeat_distribution),
            "shapeCounts": dict(self.shape_counts),
        }
