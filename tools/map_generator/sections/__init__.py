"""Deterministic section-aware analysis and hybrid-map assembly."""

from .hybrid_report import compare_hybrid_reports
from .section_pipeline import (
    analyze_sections,
    assemble_hybrid,
    evaluate_candidate_sections,
    run_hybrid_all,
)

__all__ = [
    "analyze_sections",
    "assemble_hybrid",
    "compare_hybrid_reports",
    "evaluate_candidate_sections",
    "run_hybrid_all",
]
