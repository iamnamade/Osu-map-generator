"""Extensible object-placement strategies, keyed by game mode.

P2.1: the generator core resolves positions through ``PlacementStrategy`` so a
new game mode can be added by registering a subclass instead of editing the
placement pipeline. ``position_generator.generate_positions`` remains the
public entry point and defaults to the standard osu! strategy.
"""

from __future__ import annotations

from ..utils import MapGeneratorError
from .base import PlacementContext, PlacementStrategy, PositionGenerationResult
from .osu_modes import OsuCatchPlacementStrategy, OsuManiaPlacementStrategy
from .osu_standard import OsuStandardPlacementStrategy

DEFAULT_PLACEMENT_STRATEGY = "standard"

_PLACEMENT_STRATEGIES: dict[str, PlacementStrategy] = {}


def register_placement_strategy(strategy: PlacementStrategy, *, replace: bool = False) -> None:
    """Register a placement strategy under its ``name``.

    Raises ``MapGeneratorError`` when a different strategy already owns the
    name (pass ``replace=True`` to override intentionally).
    """
    if not replace and strategy.name in _PLACEMENT_STRATEGIES:
        raise MapGeneratorError(f"Placement strategy '{strategy.name}' is already registered.")
    _PLACEMENT_STRATEGIES[strategy.name] = strategy


def get_placement_strategy(name: str = DEFAULT_PLACEMENT_STRATEGY) -> PlacementStrategy:
    try:
        return _PLACEMENT_STRATEGIES[name]
    except KeyError as error:
        available = ", ".join(sorted(_PLACEMENT_STRATEGIES))
        raise MapGeneratorError(
            f'Unknown placement strategy "{name}". Available: {available or "none"}.'
        ) from error


def list_placement_strategies() -> tuple[str, ...]:
    return tuple(sorted(_PLACEMENT_STRATEGIES))


register_placement_strategy(OsuStandardPlacementStrategy())
register_placement_strategy(OsuCatchPlacementStrategy())
register_placement_strategy(OsuManiaPlacementStrategy())

__all__ = [
    "DEFAULT_PLACEMENT_STRATEGY",
    "OsuCatchPlacementStrategy",
    "OsuManiaPlacementStrategy",
    "OsuStandardPlacementStrategy",
    "PlacementContext",
    "PlacementStrategy",
    "PositionGenerationResult",
    "get_placement_strategy",
    "list_placement_strategies",
    "register_placement_strategy",
]
