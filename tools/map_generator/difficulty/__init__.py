"""Difficulty intelligence and custom star rating engine (Phase 13).

This package evaluates the *why* of map difficulty: raw metrics, per-section
and per-pattern difficulty, reading/rhythm/aim/stamina analysis, timeline
curves, a modular star rating model, gameplay analytics from simulated play,
adaptive rebalancing proposals, diagnostics, and a full difficulty report.

Everything is deterministic: identical map, analysis, sections, and seed
produce identical reports.
"""

from .analyzer import DifficultyAnalysisResult, analyze_difficulty
from .models import DifficultyReport
from .rebalancer import RebalancePlan, plan_rebalancing
from .targets import (
    DIFFICULTY_TARGETS,
    DifficultyTarget,
    build_custom_target,
    get_difficulty_target,
    resolve_target_for_preset,
)

__all__ = [
    "DIFFICULTY_TARGETS",
    "DifficultyAnalysisResult",
    "DifficultyReport",
    "DifficultyTarget",
    "RebalancePlan",
    "analyze_difficulty",
    "build_custom_target",
    "get_difficulty_target",
    "plan_rebalancing",
    "resolve_target_for_preset",
]
