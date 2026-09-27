from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionDetectionConfig:
    min_section_duration_ms: int = 6000
    max_section_duration_ms: int = 22000
    boundary_window_ms: int = 2400
    snap_tolerance_ms: int = 260
    boundary_threshold: float = 0.58
    max_boundary_count: int = 12


@dataclass(frozen=True)
class SectionEvaluationConfig:
    boundary_context_ms: int = 1800
    density_low_floor: float = 0.55
    density_medium_floor: float = 1.0
    density_high_floor: float = 1.7


@dataclass(frozen=True)
class HybridSelectionConfig:
    switch_penalty: float = 2.8
    weak_candidate_penalty: float = 6.0
    transition_reward_weight: float = 0.22
    style_reward_weight: float = 0.1
    timing_reward_weight: float = 0.08
    movement_reward_weight: float = 0.06
    rhythm_reward_weight: float = 0.05


@dataclass(frozen=True)
class TransitionOptimizationConfig:
    boundary_object_limit: int = 4
    insertion_enabled: bool = True
    alternate_source_limit: int = 4

    def max_timing_shift_ms(self, difficulty: str) -> int:
        if difficulty == "easy":
            return 60
        if difficulty == "hard":
            return 40
        return 50


@dataclass(frozen=True)
class HybridScoreConfig:
    section_quality_weight: float = 0.50
    transition_quality_weight: float = 0.25
    style_consistency_weight: float = 0.10
    final_python_quality_weight: float = 0.15


@dataclass(frozen=True)
class PromotionRuleConfig:
    minimum_hybrid_score: float = 80.0
    maximum_quality_loss_vs_champion: float = 2.5


@dataclass(frozen=True)
class SectionPipelineConfig:
    detection: SectionDetectionConfig = SectionDetectionConfig()
    evaluation: SectionEvaluationConfig = SectionEvaluationConfig()
    selection: HybridSelectionConfig = HybridSelectionConfig()
    optimization: TransitionOptimizationConfig = TransitionOptimizationConfig()
    scoring: HybridScoreConfig = HybridScoreConfig()
    promotion: PromotionRuleConfig = PromotionRuleConfig()

    def to_dict(self) -> dict[str, object]:
        return {
            "detection": {
                "minSectionDurationMs": self.detection.min_section_duration_ms,
                "maxSectionDurationMs": self.detection.max_section_duration_ms,
                "boundaryWindowMs": self.detection.boundary_window_ms,
                "snapToleranceMs": self.detection.snap_tolerance_ms,
                "boundaryThreshold": round(self.detection.boundary_threshold, 4),
                "maxBoundaryCount": self.detection.max_boundary_count,
            },
            "evaluation": {
                "boundaryContextMs": self.evaluation.boundary_context_ms,
                "densityLowFloor": round(self.evaluation.density_low_floor, 4),
                "densityMediumFloor": round(self.evaluation.density_medium_floor, 4),
                "densityHighFloor": round(self.evaluation.density_high_floor, 4),
            },
            "selection": {
                "switchPenalty": round(self.selection.switch_penalty, 4),
                "weakCandidatePenalty": round(self.selection.weak_candidate_penalty, 4),
                "transitionRewardWeight": round(self.selection.transition_reward_weight, 4),
                "styleRewardWeight": round(self.selection.style_reward_weight, 4),
                "timingRewardWeight": round(self.selection.timing_reward_weight, 4),
                "movementRewardWeight": round(self.selection.movement_reward_weight, 4),
                "rhythmRewardWeight": round(self.selection.rhythm_reward_weight, 4),
            },
            "optimization": {
                "boundaryObjectLimit": self.optimization.boundary_object_limit,
                "insertionEnabled": self.optimization.insertion_enabled,
                "alternateSourceLimit": self.optimization.alternate_source_limit,
            },
            "scoring": {
                "sectionQualityWeight": round(self.scoring.section_quality_weight, 4),
                "transitionQualityWeight": round(self.scoring.transition_quality_weight, 4),
                "styleConsistencyWeight": round(self.scoring.style_consistency_weight, 4),
                "finalPythonQualityWeight": round(self.scoring.final_python_quality_weight, 4),
            },
            "promotion": {
                "minimumHybridScore": round(self.promotion.minimum_hybrid_score, 4),
                "maximumQualityLossVsChampion": round(
                    self.promotion.maximum_quality_loss_vs_champion, 4
                ),
            },
        }
