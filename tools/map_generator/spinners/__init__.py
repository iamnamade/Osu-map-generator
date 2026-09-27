from __future__ import annotations

from .spinner_models import (
    SpinnerCandidate,
    SpinnerConfig,
    SpinnerDiagnostics,
    SpinnerMusicalContext,
    SpinnerQualityScore,
    SpinnerRegionType,
    SpinnerTriggerType,
)
from .spinner_analysis import build_spinner_context, classify_region, classify_trigger, region_musical_score
from .spinner_decision import calculate_fatigue_profile, evaluate_spinner_region, validate_spinner
from .spinner_duration import compute_spinner_window
from .spinner_scorer import score_spinner_candidate
from .spinner_pipeline import DEFAULT_SPINNER_CONFIG, SpinnerPipelineConfig, process_spinners

__all__ = [
    "DEFAULT_SPINNER_CONFIG",
    "SpinnerCandidate",
    "SpinnerConfig",
    "SpinnerDiagnostics",
    "SpinnerMusicalContext",
    "SpinnerPipelineConfig",
    "SpinnerQualityScore",
    "SpinnerRegionType",
    "SpinnerTriggerType",
    "build_spinner_context",
    "calculate_fatigue_profile",
    "classify_region",
    "classify_trigger",
    "compute_spinner_window",
    "evaluate_spinner_region",
    "process_spinners",
    "region_musical_score",
    "score_spinner_candidate",
    "validate_spinner",
]
