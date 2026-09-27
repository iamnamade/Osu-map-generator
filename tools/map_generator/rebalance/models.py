from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class SectionQuality:
    """Independent per-section quality analysis used by the rebalancing engine."""

    section_id: int | None
    label: str
    start_ms: int
    end_ms: int
    object_count: int
    star_rating: float
    density: float
    pattern_variety: float
    rhythm_consistency: float
    reading_score: float
    cursor_travel_px: float
    fatigue_average: float
    miss_probability: float
    combo_stability: float
    flow_quality: float
    quality_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "label": self.label,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "objectCount": self.object_count,
            "starRating": _round(self.star_rating),
            "density": _round(self.density),
            "patternVariety": _round(self.pattern_variety),
            "rhythmConsistency": _round(self.rhythm_consistency),
            "readingScore": _round(self.reading_score, 2),
            "cursorTravelPx": _round(self.cursor_travel_px, 2),
            "fatigueAverage": _round(self.fatigue_average),
            "missProbability": _round(self.miss_probability),
            "comboStability": _round(self.combo_stability),
            "flowQuality": _round(self.flow_quality, 2),
            "qualityScore": _round(self.quality_score, 2),
        }


@dataclass(frozen=True)
class RebalanceIssue:
    """A detected weak-area problem with severity, reason, and a suggestion."""

    code: str
    severity: str
    reason: str
    suggestion: str
    section_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "sectionLabel": self.section_label,
        }


@dataclass(frozen=True)
class ObjectAdjustment:
    object_id: int
    object_type: str
    action: str
    reason: str
    before: dict[str, float | int]
    after: dict[str, float | int]
    section_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "objectType": self.object_type,
            "action": self.action,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
            "sectionLabel": self.section_label,
        }


@dataclass(frozen=True)
class SliderAdjustment:
    object_id: int
    action: str
    reason: str
    before: dict[str, float | int]
    after: dict[str, float | int]
    section_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "action": self.action,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
            "sectionLabel": self.section_label,
        }


@dataclass(frozen=True)
class SpinnerAdjustment:
    object_id: int
    action: str
    reason: str
    before: dict[str, int]
    after: dict[str, int]
    section_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectId": self.object_id,
            "action": self.action,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
            "sectionLabel": self.section_label,
        }


@dataclass(frozen=True)
class RebalancePass:
    pass_number: int
    score_before: float
    score_after: float
    issues_found: int
    sections_modified: int
    adjustments_count: int
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "passNumber": self.pass_number,
            "scoreBefore": _round(self.score_before, 2),
            "scoreAfter": _round(self.score_after, 2),
            "issuesFound": self.issues_found,
            "sectionsModified": self.sections_modified,
            "adjustmentsCount": self.adjustments_count,
            "accepted": self.accepted,
        }


@dataclass(frozen=True)
class RebalanceSummary:
    passes_run: int
    early_stopped: bool
    sections_modified: int
    objects_adjusted: int
    sliders_optimized: int
    spinners_adjusted: int
    issues_found: int
    quality_before: float
    quality_after: float
    quality_gain: float
    replay_before: float
    replay_after: float
    replay_gain: float
    cursor_efficiency_before: float
    cursor_efficiency_after: float
    cursor_efficiency_gain: float
    star_rating_before: float
    star_rating_after: float
    weakest_section: str = ""
    strongest_section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passesRun": self.passes_run,
            "earlyStopped": self.early_stopped,
            "sectionsModified": self.sections_modified,
            "objectsAdjusted": self.objects_adjusted,
            "slidersOptimized": self.sliders_optimized,
            "spinnersAdjusted": self.spinners_adjusted,
            "issuesFound": self.issues_found,
            "qualityBefore": _round(self.quality_before, 2),
            "qualityAfter": _round(self.quality_after, 2),
            "qualityGain": _round(self.quality_gain, 2),
            "replayBefore": _round(self.replay_before, 2),
            "replayAfter": _round(self.replay_after, 2),
            "replayGain": _round(self.replay_gain, 2),
            "cursorEfficiencyBefore": _round(self.cursor_efficiency_before),
            "cursorEfficiencyAfter": _round(self.cursor_efficiency_after),
            "cursorEfficiencyGain": _round(self.cursor_efficiency_gain),
            "starRatingBefore": _round(self.star_rating_before, 2),
            "starRatingAfter": _round(self.star_rating_after, 2),
            "weakestSection": self.weakest_section,
            "strongestSection": self.strongest_section,
        }


@dataclass(frozen=True)
class RebalanceReport:
    version: int
    map_title: str
    map_artist: str
    difficulty: str
    seed: int
    sections: list[SectionQuality]
    issues: list[RebalanceIssue]
    object_adjustments: list[ObjectAdjustment]
    slider_adjustments: list[SliderAdjustment]
    spinner_adjustments: list[SpinnerAdjustment]
    passes: list[RebalancePass]
    summary: RebalanceSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "map": {
                "title": self.map_title,
                "artist": self.map_artist,
                "difficulty": self.difficulty,
            },
            "seed": self.seed,
            "sections": [section.to_dict() for section in self.sections],
            "issues": [issue.to_dict() for issue in self.issues],
            "objectAdjustments": [
                adjustment.to_dict() for adjustment in self.object_adjustments
            ],
            "sliderAdjustments": [
                adjustment.to_dict() for adjustment in self.slider_adjustments
            ],
            "spinnerAdjustments": [
                adjustment.to_dict() for adjustment in self.spinner_adjustments
            ],
            "passes": [entry.to_dict() for entry in self.passes],
            "summary": self.summary.to_dict(),
        }
