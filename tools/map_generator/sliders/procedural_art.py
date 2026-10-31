"""Procedural slider art for quiet song sections.

Long rhythm gaps and low-energy passages are where a map stops being about
reading density and starts being about looking good.  Instead of emitting
another straight jump or gentle arc, the slider pipeline can stamp a
recognisable figure -- a heart, a star, or a spiral -- built from parametric
mathematics.

Every shape is sampled into Bezier anchors (``B|`` path type).  The public
generators return figures *centred* on ``(center_x, center_y)``; the slider
pipeline calls :meth:`SliderArtGenerator.align_to_head` so the figure's first
anchor is the slider head, because an osu! path starts at the head and runs
through its control points.

Bounds
------
Anchors are confined to ``[48, 464] x [48, 336]`` -- the 512x384 playfield inset
by 48 px -- which keeps art clear of the HUD edges.  Clamping alone would flatten
a shape drawn near a corner, so :meth:`SliderArtGenerator.fit_scale_to_head`
works out the largest scale whose head-anchored figure still fits, and clamping
remains only as a final numeric guarantee.  A heart at the edge stays a heart,
just a smaller one.

Parametric forms
----------------
* Heart -- the classic cardioid-like curve ``x = 16 sin^3 t``,
  ``y = -(13 cos t - 5 cos 2t - 2 cos 3t - cos 4t)``, normalised so ``scale`` is
  the pixel half-extent and Y inverted for osu!'s downward-positive axis.
* Star -- N points at alternating outer/inner radii, first point straight up.
* Spiral -- Archimedean ``r = a + b*theta`` with ``a = 0`` and ``b`` chosen so
  the spiral reaches ``max_radius`` after the requested number of rotations.
"""

from __future__ import annotations

import math
import random

import numpy as np

#: Playfield inset that art anchors are confined to (512x384 minus 48 px).
ART_MIN_X = 48.0
ART_MAX_X = 464.0
ART_MIN_Y = 48.0
ART_MAX_Y = 336.0

#: Heart anchors: 15-20 keeps the curve faithful without bloating the .osu line.
DEFAULT_HEART_POINTS = 18
#: A five-pointed star needs two anchors per point.
DEFAULT_STAR_POINTS = 5
#: Spiral anchors; enough to read as a curve at gameplay scale.
DEFAULT_SPIRAL_POINTS = 22

#: Shape names this generator can produce.
ART_SHAPES: tuple[str, ...] = ("heart", "star", "spiral")


class SliderArtGenerator:
    """Parametric shape generator for decorative sliders.

    Parameters
    ----------
    rng:
        Source of randomness for :meth:`generate_random`.  The slider pipeline
        passes its seeded ``random.Random`` so art shapes stay reproducible.
    margin:
        Inset used when fitting shapes to the playfield.
    """

    def __init__(self, *, rng: random.Random | None = None, margin: float = 48.0) -> None:
        self._rng = rng if rng is not None else random.Random()
        self.margin = float(margin)
        # The art bounds are a floor: a preset margin smaller than 48 px would let
        # figures touch the HUD, so the effective inset is never below them. A
        # larger preset margin tightens the box symmetrically.
        inset_x = max(ART_MIN_X, self.margin)
        inset_y = max(ART_MIN_Y, self.margin)
        self._min_x = inset_x
        self._max_x = max(inset_x + 1.0, 512.0 - inset_x)
        self._min_y = inset_y
        self._max_y = max(inset_y + 1.0, 384.0 - inset_y)

    # ------------------------------------------------------------------
    # Bounds helpers
    # ------------------------------------------------------------------
    def _clamp(self, x: float, y: float) -> tuple[float, float]:
        return (
            float(min(max(x, self._min_x), self._max_x)),
            float(min(max(y, self._min_y), self._max_y)),
        )

    def _clamp_points(
        self, points: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        return [self._clamp(x, y) for x, y in points]

    def _fit_radius(self, center_x: float, center_y: float, radius: float) -> float:
        """Shrink ``radius`` so a figure *centred* here stays clear of the edges."""
        radius = abs(float(radius))
        cx = min(max(float(center_x), self._min_x), self._max_x)
        cy = min(max(float(center_y), self._min_y), self._max_y)
        available = min(cx - self._min_x, self._max_x - cx, cy - self._min_y, self._max_y - cy)
        # Never collapse to zero: a tiny shape still beats an invalid slider.
        return float(max(1.0, min(radius, available)))

    # ------------------------------------------------------------------
    # Unclamped parametric forms
    # ------------------------------------------------------------------
    def _raw_heart(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        count: int,
    ) -> list[tuple[float, float]]:
        t = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False)
        # Parametric heart, normalised by 16 so `radius` maps to pixels directly.
        x_units = np.sin(t) ** 3
        y_units = -(
            13.0 * np.cos(t)
            - 5.0 * np.cos(2.0 * t)
            - 2.0 * np.cos(3.0 * t)
            - np.cos(4.0 * t)
        ) / 16.0
        return [
            (float(center_x + x_units[i] * radius), float(center_y + y_units[i] * radius))
            for i in range(count)
        ]

    def _raw_star(
        self,
        center_x: float,
        center_y: float,
        outer: float,
        inner: float,
        points_count: int,
    ) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        step = math.pi / points_count
        for index in range(2 * points_count):
            # Start at -90 degrees so the first point aims up the playfield.
            angle = -math.pi / 2.0 + index * step
            radius = outer if index % 2 == 0 else inner
            points.append(
                (
                    float(center_x + math.cos(angle) * radius),
                    float(center_y + math.sin(angle) * radius),
                )
            )
        return points

    def _raw_spiral(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        turns: float,
        count: int,
    ) -> list[tuple[float, float]]:
        theta_max = 2.0 * math.pi * max(0.25, float(turns))
        b = radius / theta_max  # a = 0, so the spiral starts at the centre
        theta = np.linspace(0.0, theta_max, count)
        r = b * theta
        return [
            (
                float(center_x + r[i] * math.cos(theta[i])),
                float(center_y + r[i] * math.sin(theta[i])),
            )
            for i in range(count)
        ]

    def _raw_shape(
        self,
        shape: str,
        center_x: float,
        center_y: float,
        radius: float,
        *,
        point_count: int | None = None,
        rotations: float = 2.5,
    ) -> list[tuple[float, float]]:
        """Unclamped figure at ``radius``; the basis for scale fitting."""
        radius = float(radius)
        if shape == "heart":
            count = int(min(20, max(15, point_count or DEFAULT_HEART_POINTS)))
            points = self._raw_heart(center_x, center_y, radius, count)
            return points + [points[0]]  # close the outline
        if shape == "star":
            count = max(3, int(point_count or DEFAULT_STAR_POINTS))
            points = self._raw_star(center_x, center_y, radius, radius * 0.382, count)
            return points + [points[0]]
        if shape == "spiral":
            count = max(4, int(point_count or DEFAULT_SPIRAL_POINTS))
            return self._raw_spiral(center_x, center_y, radius, rotations, count)
        raise ValueError(
            f"Unknown art shape {shape!r}; expected one of: {', '.join(ART_SHAPES)}"
        )

    # ------------------------------------------------------------------
    # Shapes
    # ------------------------------------------------------------------
    def generate_heart(
        self,
        center_x: float,
        center_y: float,
        scale: float,
        *,
        point_count: int = DEFAULT_HEART_POINTS,
    ) -> list[tuple[float, float]]:
        """Sample the parametric heart curve into Bezier anchors.

        ``scale`` is the pixel half-extent: the result spans roughly
        ``2 * scale`` wide and tall around ``(center_x, center_y)``.
        """
        count = int(min(20, max(15, point_count)))
        radius = self._fit_radius(center_x, center_y, scale)
        return self._clamp_points(self._raw_shape("heart", center_x, center_y, radius, point_count=count))

    def generate_star(
        self,
        center_x: float,
        center_y: float,
        outer_radius: float,
        inner_radius: float,
        *,
        point_count: int = DEFAULT_STAR_POINTS,
    ) -> list[tuple[float, float]]:
        """Build an N-pointed star from alternating outer/inner radii."""
        points_count = max(3, int(point_count))
        outer = self._fit_radius(center_x, center_y, outer_radius)
        inner = float(min(max(abs(inner_radius), 1.0), outer))

        points: list[tuple[float, float]] = []
        step = math.pi / points_count
        for index in range(2 * points_count):
            # Start at -90 degrees so the first point aims up the playfield.
            angle = -math.pi / 2.0 + index * step
            radius = outer if index % 2 == 0 else inner
            points.append(
                (float(center_x + math.cos(angle) * radius), float(center_y + math.sin(angle) * radius))
            )
        points.append(points[0])
        return self._clamp_points(points)

    def generate_spiral(
        self,
        center_x: float,
        center_y: float,
        max_radius: float,
        rotations: float,
        *,
        point_count: int = DEFAULT_SPIRAL_POINTS,
    ) -> list[tuple[float, float]]:
        """Sample an Archimedean spiral ``r = a + b*theta``.

        ``a`` is fixed at 0 and ``b = max_radius / (2*pi*rotations)`` so the
        spiral reaches ``max_radius`` after exactly ``rotations`` turns.
        """
        count = max(4, int(point_count))
        radius = self._fit_radius(center_x, center_y, max_radius)
        return self._clamp_points(
            self._raw_shape("spiral", center_x, center_y, radius, point_count=count, rotations=rotations)
        )

    # ------------------------------------------------------------------
    # Placement helpers
    # ------------------------------------------------------------------
    def fit_scale_to_head(
        self,
        shape: str,
        head_x: float,
        head_y: float,
        scale: float,
        *,
        rotations: float = 2.5,
    ) -> float:
        """Largest scale whose *head-anchored* figure fits inside the art bounds.

        The figures are generated centred, but the pipeline anchors them by
        putting the first point on the slider head.  That translation is what
        makes "fit a radius around the centre" wrong: a figure fitting neatly
        around the head can still overrun the edge once its first point is moved
        onto it.  All shapes are proportional to their radius, so the ceiling is
        a single ratio per side -- computed once on the unit figure.
        """
        unit = self._raw_shape(shape, 0.0, 0.0, 1.0, rotations=rotations)
        if not unit:
            return 0.0
        limit = abs(float(scale))
        offsets = (
            ([p[0] - unit[0][0] for p in unit], float(head_x), self._min_x, self._max_x),
            ([p[1] - unit[0][1] for p in unit], float(head_y), self._min_y, self._max_y),
        )
        for values, head, low, high in offsets:
            lowest, highest = min(values), max(values)
            if lowest < -1e-9:
                limit = min(limit, (low - head) / lowest)
            if highest > 1e-9:
                limit = min(limit, (high - head) / highest)
        return max(0.0, limit)

    def align_to_head(
        self,
        points: list[tuple[float, float]],
        head_x: float,
        head_y: float,
    ) -> list[tuple[float, float]]:
        """Translate a figure so its first anchor sits on the slider head.

        The generators return figures *centred* on ``(center_x, center_y)``,
        but an osu! slider path starts at the head and runs through its control
        points.  Drawing a centred figure would open with a spoke from the head
        to the outline, so the figure is translated instead: the head becomes
        the first anchor and the rest of the shape unfolds from it (for a
        spiral that means the head is the centre it winds out of).

        Callers that size the figure with :meth:`fit_scale_to_head` land inside
        the bounds exactly; the shift-and-clamp fallback here only handles
        degenerate input.
        """
        if not points:
            return []
        dx = float(head_x) - points[0][0]
        dy = float(head_y) - points[0][1]
        moved = [(x + dx, y + dy) for x, y in points]

        xs = [p[0] for p in moved]
        ys = [p[1] for p in moved]
        shift_x = 0.0
        if min(xs) < self._min_x:
            shift_x = self._min_x - min(xs)
        elif max(xs) > self._max_x:
            shift_x = self._max_x - max(xs)
        shift_y = 0.0
        if min(ys) < self._min_y:
            shift_y = self._min_y - min(ys)
        elif max(ys) > self._max_y:
            shift_y = self._max_y - max(ys)

        return self._clamp_points([(x + shift_x, y + shift_y) for x, y in moved])

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def generate_shape(
        self,
        shape: str,
        center_x: float,
        center_y: float,
        *,
        scale: float = 80.0,
    ) -> list[tuple[float, float]]:
        """Generate a named shape (``heart``/``star``/``spiral``) at ``scale``."""
        return self._clamp_points(self._raw_shape(shape, center_x, center_y, abs(float(scale))))

    def generate_random(
        self,
        center_x: float,
        center_y: float,
        *,
        scale: float = 80.0,
    ) -> tuple[str, list[tuple[float, float]]]:
        """Pick a shape at random and generate it around ``(center_x, center_y)``.

        Returns ``(shape_name, control_points)``.
        """
        shape = self._rng.choice(ART_SHAPES)
        return shape, self.generate_shape(shape, center_x, center_y, scale=scale)
