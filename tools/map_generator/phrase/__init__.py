"""Phase 20 phrase-level intelligence: detection, motifs, trajectory, report."""

from .motif_engine import (
    DEFAULT_MOTIF_CONFIG,
    Motif,
    MotifEngineConfig,
    assign_all_strategies,
    build_motifs,
    strategy_generation_multipliers,
)
from .phrase_analyzer import (
    DEFAULT_PHRASE_CONFIG,
    PhraseDetectionConfig,
    build_phrase_report_data,
    classify_phrase_relationships,
    detect_phrase_boundaries,
)
from .phrase_models import (
    Motif as MotifModel,
    Phrase,
    PhraseRelationship,
    PhraseReport,
)
from .phrase_pipeline import (
    DEFAULT_PHRASE_PIPELINE_CONFIG,
    PhraseAnalysisRunResult,
    PhrasePipelineConfig,
    analyze_phrase_structure,
    build_phrase_rhythm_info,
    load_phrase_report,
    phrase_generator_metadata,
)
from .trajectory_planner import (
    DEFAULT_TRAJECTORY_CONFIG,
    TrajectoryConfig,
    build_trajectory_points,
    density_multiplier_at,
    difficulty_multiplier_at,
    full_trajectory_plan,
    movement_multiplier_at,
    plan_trajectory,
)

__all__ = [
    "DEFAULT_MOTIF_CONFIG",
    "DEFAULT_PHRASE_CONFIG",
    "DEFAULT_PHRASE_PIPELINE_CONFIG",
    "DEFAULT_TRAJECTORY_CONFIG",
    "Motif",
    "MotifEngineConfig",
    "MotifModel",
    "Phrase",
    "PhraseAnalysisRunResult",
    "PhraseDetectionConfig",
    "PhrasePipelineConfig",
    "PhraseRelationship",
    "PhraseReport",
    "TrajectoryConfig",
    "analyze_phrase_structure",
    "assign_all_strategies",
    "build_motifs",
    "build_phrase_report_data",
    "build_phrase_rhythm_info",
    "build_trajectory_points",
    "classify_phrase_relationships",
    "density_multiplier_at",
    "detect_phrase_boundaries",
    "difficulty_multiplier_at",
    "full_trajectory_plan",
    "load_phrase_report",
    "movement_multiplier_at",
    "phrase_generator_metadata",
    "plan_trajectory",
    "strategy_generation_multipliers",
]
