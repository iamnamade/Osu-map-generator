"""Deterministic multi-candidate generation and tournament selection."""

from .candidate_pipeline import (
    compare_tournament_reports,
    inspect_candidate_summary,
    run_candidate_tournament,
    run_candidate_tournament_all,
)

__all__ = [
    "compare_tournament_reports",
    "inspect_candidate_summary",
    "run_candidate_tournament",
    "run_candidate_tournament_all",
]
