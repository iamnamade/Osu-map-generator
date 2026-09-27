"""Candidate evolution and self-evaluation engine (Phase 14).

The generator no longer trusts the first map it produces. Instead it:

1. Generates several deterministic candidates with controlled variation.
2. Runs difficulty intelligence, validation, and a simulated player on each.
3. Scores every candidate on quality, flow, rhythm, movement, patterns,
   sliders, spinners, reading, playability, consistency, and confidence.
4. Runs up to two improvement passes against the difficulty target.
5. Ranks the leaderboard and promotes the Champion.
6. Emits comparison tables, heatmaps, replay simulation, and diagnostics.

Everything is deterministic: identical audio, analysis, seed, settings, and
difficulty always produce the same candidate ranking and Champion.
"""

from .evolution_pipeline import (
    MAX_EVOLUTION_PASSES,
    CandidateEvolutionResult,
    run_candidate_evolution,
    run_candidate_evolution_all,
)
from .models import EvolutionReport
from .report_writer import (
    format_evolution_comparison,
    load_evolution_report,
    write_evolution_report,
)

__all__ = [
    "MAX_EVOLUTION_PASSES",
    "CandidateEvolutionResult",
    "EvolutionReport",
    "format_evolution_comparison",
    "load_evolution_report",
    "run_candidate_evolution",
    "run_candidate_evolution_all",
    "write_evolution_report",
]
