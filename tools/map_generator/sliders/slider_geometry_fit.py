"""Production seam between the shape engine and the curve fitter.

Takes the anchors ``generate_shape_path`` produced, clamps them into the playfield
(with the difficulty preset's safety margin), resolves an exact arc length, and
optionally simplifies the anchor chain — degrading to the legacy sampled path if
anything goes wrong.

Why this exists
---------------
Before this module the pipeline estimated slider length by summing 100 sampled
chords (:func:`slider_geometry.compute_slider_length`) and emitted whatever anchors
the shape generator happened to produce, unclamped. That costs more, is less
accurate, and allowed anchors outside the playfield (they were only clamped later,
at serialisation, which meant the declared ``pixel_length`` described a path that
was not the one exported).

Contract
--------
* Every returned control point is inside ``[margin, width - margin] x
  [margin, height - margin]``.
* ``pixel_length`` describes the *emitted* (clamped) geometry, so duration, SV and
  rendering agree.
* This function does not raise. Any failure falls back to the legacy anchors plus
  the legacy sampled length, so a bad shape can never abort a generation run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..position_generator import PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from .curve_fit import FamilyFit, fit_known_family
from .slider_geometry import compute_slider_length
from .slider_models import ControlPoint, SliderPathType


@dataclass(frozen=True)
class ResolvedGeometry:
    """Slider geometry ready for emission."""

    path_type: SliderPathType
    control_points: list[ControlPoint]
    pixel_length: float
    method: str
    max_error: float = 0.0
    simplified: bool = False
    clamped: bool = False
    fallback: bool = False


def clamp_anchor(
    point: tuple[float, float],
    margin: float,
) -> tuple[float, float]:
    """Clamp a point into the playfield box, inset by ``margin`` on every side."""
    lo_x, hi_x = float(margin), PLAYFIELD_WIDTH - float(margin)
    lo_y, hi_y = float(margin), PLAYFIELD_HEIGHT - float(margin)
    if hi_x < lo_x:  # pathological margin: fall back to the playfield itself
        lo_x, hi_x = 0.0, PLAYFIELD_WIDTH
    if hi_y < lo_y:
        lo_y, hi_y = 0.0, PLAYFIELD_HEIGHT
    return (
        min(hi_x, max(lo_x, float(point[0]))),
        min(hi_y, max(lo_y, float(point[1]))),
    )


def resolve_slider_geometry(
    start_x: int,
    start_y: int,
    control_points: Sequence[ControlPoint],
    path_type: SliderPathType,
    *,
    margin: float = 0,
    simplify_tolerance: float = 1.0,
    simplify: bool = True,
) -> ResolvedGeometry:
    """Clamp anchors and resolve path type, control points and exact length.

    Args:
        start_x / start_y: slider head (already placed by the strategy).
        control_points: anchors *excluding* the head, as produced by the shape engine.
        path_type: declared family (``linear``/``bezier``/``perfect``/``catmull``).
        margin: playfield inset for anchors; typically ``DifficultyPreset.safe_margin``.
        simplify_tolerance: max px deviation allowed when collapsing a chain to a cubic.
        simplify: when False, anchors are kept as-is (length still resolved exactly).

    Returns:
        :class:`ResolvedGeometry`; never raises.
    """
    anchors = [(float(cp.x), float(cp.y)) for cp in control_points]
    if not anchors:
        return ResolvedGeometry(path_type, [], 0.0, "empty")

    clamped_anchors: list[tuple[float, float]] = []
    moved = False
    for anchor in anchors:
        clamped = clamp_anchor(anchor, margin)
        if clamped != anchor:
            moved = True
        clamped_anchors.append(clamped)

    try:
        fit: FamilyFit = fit_known_family(
            (float(start_x), float(start_y)),
            clamped_anchors,
            "bezier" if simplify is False and path_type == "catmull" else path_type,
            simplify_tolerance=simplify_tolerance if simplify else 0.0,
        )
        points = [ControlPoint(x=int(round(x)), y=int(round(y))) for x, y in fit.control_points]
        if not points:
            raise ValueError("fit produced no control points")
        return ResolvedGeometry(
            path_type=_coerce_path_type(fit.path_type),
            control_points=points,
            pixel_length=float(fit.length),
            method=fit.method,
            max_error=float(fit.max_error),
            simplified=fit.simplified,
            clamped=moved,
        )
    except Exception:  # noqa: BLE001 - generation must never die on one slider
        # Graceful degradation: emit the clamped anchors with the legacy sampled length.
        points = [ControlPoint(x=int(round(x)), y=int(round(y))) for x, y in clamped_anchors]
        try:
            length = compute_slider_length(points, int(start_x), int(start_y), path_type)
        except Exception:  # noqa: BLE001 - last resort: straight-line distance
            last = clamped_anchors[-1]
            length = ((last[0] - start_x) ** 2 + (last[1] - start_y) ** 2) ** 0.5
        return ResolvedGeometry(
            path_type=path_type,
            control_points=points,
            pixel_length=float(length),
            method="fallback-sampled",
            clamped=moved,
            fallback=True,
        )


_ALLOWED_PATH_TYPES = {"linear", "bezier", "perfect", "catmull"}


def _coerce_path_type(value: str) -> SliderPathType:
    """Keep the emitted family inside the ones the .osu writer can serialise."""
    return value if value in _ALLOWED_PATH_TYPES else "bezier"  # type: ignore[return-value]
