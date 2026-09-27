"""Adaptive rebalancing engine (Phase 16).

Automatically improves generated beatmaps after generation, difficulty
evaluation, and replay simulation by making targeted adjustments to object
placement, spacing, sliders, and spinners without regenerating the map.

The engine splits the map into logical sections, scores each one, detects weak
areas (difficulty spikes, empty sections, repetitive patterns, awkward
spacing, stream overload, rhythm inconsistency, poor slider usage, spinner
overuse, pacing changes), and then runs iterative improvement passes:
analyze -> improve -> re-evaluate -> compare. Passes stop early once no
meaningful gain is achieved and only the best version is kept.

Everything is deterministic: identical map, reports, difficulty, seed, and
options always produce the identical improved map and report.
"""

from .engine import MapEvaluation, RebalanceOutcome, run_rebalance
from .models import (
    ObjectAdjustment,
    RebalanceIssue,
    RebalancePass,
    RebalanceReport,
    RebalanceSummary,
    SectionQuality,
    SliderAdjustment,
    SpinnerAdjustment,
)
from .report import (
    format_rebalance_summary,
    load_rebalance_report,
    rebalance_generator_metadata,
    write_rebalance_report,
)

__all__ = [
    "MapEvaluation",
    "ObjectAdjustment",
    "RebalanceIssue",
    "RebalanceOutcome",
    "RebalancePass",
    "RebalanceReport",
    "RebalanceSummary",
    "SectionQuality",
    "SliderAdjustment",
    "SpinnerAdjustment",
    "format_rebalance_summary",
    "load_rebalance_report",
    "rebalance_generator_metadata",
    "run_rebalance",
    "write_rebalance_report",
]
