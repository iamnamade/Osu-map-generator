from __future__ import annotations

from .osu_standard import OsuStandardPlacementStrategy


class OsuCatchPlacementStrategy(OsuStandardPlacementStrategy):
    """osu!catch placement hook.

    Catch reuses the standard horizontal lane choice for fruit and hyperdash,
    but the catcher's plate row is fixed vertically, so only ``y`` differs.
    Override ``transform_position`` further (or ``generate``) once the catch
    engine's hyperdash/banana rules are implemented.
    """

    name = "catch"
    mode = "catch"

    def transform_position(self, x: float, y: float) -> tuple[float, float]:
        return x, self.playfield_height / 2.0


class OsuManiaPlacementStrategy(OsuStandardPlacementStrategy):
    """osu!mania placement hook.

    Mania quantizes the standard x coordinate into fixed columns; ``y`` is
    unused by the client but kept so the object schema stays stable. Override
    ``generate`` when a native column/note engine replaces this mapping.
    """

    name = "mania"
    mode = "mania"

    def __init__(self, columns: int = 4) -> None:
        if columns < 1:
            raise ValueError("osu!mania placement requires at least one column.")
        self.columns = columns

    def transform_position(self, x: float, y: float) -> tuple[float, float]:
        column_width = self.playfield_width / self.columns
        column = min(self.columns - 1, max(0, int(x / column_width)))
        return (column + 0.5) * column_width, y
