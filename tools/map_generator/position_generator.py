"""Public placement entry point (P2.1).

Placement now lives behind the ``PlacementStrategy`` abstraction in
``placement/``. This module stays the stable import surface: it re-exports the
standard playfield constants, the ``_Point`` helper, and the classic algorithm
helpers used by the pattern pipeline, and routes ``generate_positions`` through
the registered strategy (osu!standard by default).

Pass ``strategy=`` to ``generate_positions`` (or subclass ``PlacementStrategy``)
to place objects for another game mode.
"""

from __future__ import annotations

from typing import Any

from .config import DifficultyPreset
from .models import SelectedEvent
from .placement import (
    DEFAULT_PLACEMENT_STRATEGY,
    PlacementContext,
    PlacementStrategy,
    get_placement_strategy,
)
from .placement.osu_standard import (  # noqa: F401  (re-exported for compatibility)
    PLAYFIELD_CENTER,
    PLAYFIELD_HEIGHT,
    PLAYFIELD_WIDTH,
    OsuStandardPlacementStrategy,
    PositionGenerationResult,
    _Point,
    _base_angle,
    _build_candidates,
    _clamp_point,
    _distance,
    _first_point,
    _inside_safe_area,
    _is_near_edge,
    _needs_center_recovery,
    _next_point,
    _quadrant,
    _score_candidate,
)
from .variation import PositionVariation


def generate_positions(
    events: list[SelectedEvent],
    preset: DifficultyPreset,
    seed: int,
    *,
    variation: PositionVariation | None = None,
    pattern_config: Any | None = None,
    analysis: Any | None = None,
    strategy: PlacementStrategy | None = None,
) -> PositionGenerationResult:
    """Generate positions for hit objects using a registered strategy.

    Defaults to the standard osu! strategy, which preserves the historical
    pattern-intelligence and classic jump-curve behaviour. Future game modes
    pass their own ``strategy`` instance.
    """
    resolved = strategy or get_placement_strategy(DEFAULT_PLACEMENT_STRATEGY)
    context = PlacementContext(
        events=events,
        preset=preset,
        seed=seed,
        variation=variation or PositionVariation(),
        pattern_config=pattern_config,
        analysis=analysis,
    )
    return resolved.generate(context)
