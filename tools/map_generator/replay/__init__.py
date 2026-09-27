"""Replay simulation and human play validation engine (Phase 15).

Evaluates generated beatmaps by simulating how a human player would perform
instead of relying only on static difficulty metrics. A configurable virtual
player (Beginner / Intermediate / Advanced / Tournament / Custom) plays a
deterministic replay of the map: cursor travel, per-object hit windows,
combo evolution, pattern recognizability, fatigue, and reading complexity are
all simulated and combined into one replay quality score with a detailed
breakdown.

Everything is deterministic: identical map, analysis, difficulty, seed, and
player profile always produce identical replay results.
"""

from .models import ReplayReport
from .player import PLAYER_PROFILES, resolve_player_profile
from .replay_simulator import (
    format_replay_summary,
    replay_generator_metadata,
    simulate_replay,
)
from .report import load_replay_report, write_replay_report
from .scoring import ReplayScoreWeights, compute_replay_score

__all__ = [
    "PLAYER_PROFILES",
    "ReplayReport",
    "ReplayScoreWeights",
    "compute_replay_score",
    "format_replay_summary",
    "load_replay_report",
    "replay_generator_metadata",
    "resolve_player_profile",
    "simulate_replay",
    "write_replay_report",
]
