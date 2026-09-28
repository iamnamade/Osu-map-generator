from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..config import DifficultyPreset
from ..models import GeneratedHitObject, SelectedEvent
from ..variation import PositionVariation


@dataclass(frozen=True)
class PositionGenerationResult:
    """Resolved object positions plus the rejected-candidate diagnostic."""

    objects: list[GeneratedHitObject]
    rejected_candidates: int


@dataclass(frozen=True)
class PlacementContext:
    """Everything a placement strategy needs to resolve object coordinates.

    Bundling the inputs keeps the strategy signature stable as future game
    modes need extra context (e.g. a catch/mania difficulty knob) without
    changing every call site.
    """

    events: list[SelectedEvent]
    preset: DifficultyPreset
    seed: int
    variation: PositionVariation = field(default_factory=PositionVariation)
    pattern_config: Any | None = None
    analysis: Any | None = None


class PlacementStrategy(ABC):
    """Extensible seam for mode-specific hit-object placement.

    The engine's timing/event selection is mode-agnostic; only the coordinate
    resolution differs between game modes. Subclass this and override
    ``generate`` (and the ``transform_position`` hook for simple lane/column
    mappings) to add a mode:

    * ``OsuStandardPlacementStrategy`` — the default 512x384 osu!standard
      placement (see ``osu_standard.py``).
    * osu!catch — reuse standard horizontal placement and map ``y`` to the
      catch lane with ``transform_position`` (fruit/hyperdash coordinates).
    * osu!mania — map ``x`` to a column center with ``transform_position``
      (column quantization over the selected events).

    Strategies are registered by ``name`` in ``placement/__init__.py`` so new
    modes can be resolved without editing the generator core.
    """

    #: Registry key, e.g. ``"standard"``.
    name: str = "standard"
    #: Game mode this strategy resolves coordinates for.
    mode: str = "osu"

    @property
    @abstractmethod
    def playfield_width(self) -> float:
        """Width of the coordinate space objects are placed in."""

    @property
    @abstractmethod
    def playfield_height(self) -> float:
        """Height of the coordinate space objects are placed in."""

    @abstractmethod
    def generate(self, context: PlacementContext) -> PositionGenerationResult:
        """Resolve object positions for the given events."""

    def transform_position(self, x: float, y: float) -> tuple[float, float]:
        """Map a resolved standard position into this mode's coordinate space.

        The default is the identity mapping (osu!standard). Modes that only
        differ by coordinate mapping (catch lanes, mania columns) can override
        this instead of reimplementing the whole placement engine.
        """
        return x, y
