"""MAP slider curve fitting, ported from osu!dreamer.

Extracted from ``osu-dreamer`` (jb2170):
``osu_dreamer/data/beatmap/slider/{decode_slider,fit_bezier,fit_arc,slider_prior}.py``
and ``osu_dreamer/osu/bezier.py``. See ``docs/OSU_DREAMER_FORENSIC_ANALYSIS.md`` §3.5, §7.1, §8.2.

What this does
--------------
Given a dense slider path (the kind ``slider_geometry.generate_shape_path`` produces), pick the
simplest *osu!-representable* curve family that explains it, and report the path's exact arc
length. Every candidate is scored with a MAP objective

    cost(type) = SSE_geo / (2 * noise_scale**2) - log P(type)

where ``P(type)`` is the empirical frequency of that slider type in ranked maps. Candidates are
visited in order of increasing prior penalty, and the search stops as soon as the penalty alone
exceeds the best cost (valid because ``SSE >= 0``).

Two deliberate departures from upstream:

1. **Geometric error, not parameter residual.** Upstream scores ``SSE`` at a fixed parameter
   (``t = linspace(0, 1, L)``), which is only meaningful if you already know the correct
   parameterisation. Since the renderer only cares about the *path*, we score the sum of squared
   distances from each input point to the nearest point on the candidate curve. That makes
   ``P`` / ``L`` / ``B`` / poly candidates comparable, and stops a degenerate control polygon
   from scoring well by looping over the input.
2. **Chord-length parameterisation.** ``fit_bezier_curve`` fits with both uniform and chord-length
   parameters and keeps whichever is geometrically better. Uniform is exact for parameter-uniform
   input (what upstream's own cursor signal produces); chord-length is far more stable for
   arbitrarily-resampled input, and never makes a curve longer than its control polygon suggests.

Dependencies: ``numpy`` + stdlib only. Upstream's ``scipy.special.comb`` is replaced by
``math.comb``; ``scipy.special.zeta`` is closed-form (s == 4) or a tail-corrected series.

Input contract: any monotone sampling of the path works. If in doubt, use
:func:`resample_by_arclength`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Iterator, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Prior constants
# ---------------------------------------------------------------------------

#: Top-level slider-type counts measured over the upstream training corpus.
#: Re-measure these on our own exports before trusting them here.
TYPE_COUNTS: dict[str, int] = {
    "P": 938141,   # perfect circle arc
    "L": 672639,   # single straight line
    "PL": 165541,  # poly-line
    "PB": 73003,   # poly-bezier
    "B": 55957,    # single bezier
}

#: Segment count of a poly-line / poly-bezier follows ``P(m) ~ m**-ZETA_S`` for ``m >= 2``.
ZETA_S = 4

#: Single-bezier control-point count is a cubic spike over a geometric tail.
B_CUBIC_WEIGHT = 0.5991
B_TAIL_DECAY = 0.7431

#: Expected cursor noise in osu! pixels. Larger trusts the prior more (simpler sliders).
NOISE_SCALE = 16.0

#: Largest single-bezier control count / poly segment count considered.
MAX_BEZIER_CTRL = 8
MAX_SEGMENTS = 16

#: Candidates whose mean squared geometric error is within this (px², so ~0.5 px RMS) of the
#: best are treated as visually identical, and the one with the fewest control points wins.
#: Not in upstream: without it an exact single cubic can lose to an equally exact 2-segment
#: poly-bezier, because the corpus prior happens to like ``PB/2`` more than ``B/3``.
EQUIVALENCE_MSQE = 0.25

#: Scoring subsamples long paths to this many points; the objective is scaled back to the
#: full point count so costs stay comparable across input sizes.
SCORE_MAX_POINTS = 96

#: osu!'s own limit for a "perfect" (circular-arc) slider.
MAX_ARC_RADIUS = 320.0

_TOTAL = sum(TYPE_COUNTS.values())
_LOG_TYPE = {k: math.log(v / _TOTAL) for k, v in TYPE_COUNTS.items()}


def _zeta(s: float) -> float:
    """Riemann zeta for the (small integer) exponents we use."""
    if s == 4:
        return math.pi ** 4 / 90.0
    n = 100_000
    return math.fsum(j ** -s for j in range(1, n)) + n ** (1 - s) / (s - 1)


def _zeta_log_pmf(k: int, k_min: int) -> float:
    """``log P(k)`` for a zeta distribution truncated to the support ``k >= k_min``."""
    norm = _zeta(ZETA_S) - sum(j ** -ZETA_S for j in range(1, k_min))
    return -ZETA_S * math.log(k) - math.log(norm)


def log_prior_arc() -> float:
    return _LOG_TYPE["P"]


def log_prior_single_bezier(n_ctrl: int) -> float:
    """log-prior of a single bezier with ``n_ctrl`` control points (2 == straight line)."""
    if n_ctrl <= 2:
        return _LOG_TYPE["L"]
    w, q = B_CUBIC_WEIGHT, B_TAIL_DECAY
    log_tail = math.log(1 - w) + math.log(1 - q) + (n_ctrl - 3) * math.log(q)
    if n_ctrl == 4:
        log_w = math.log(w)
        hi = max(log_w, log_tail)
        log_degree = hi + math.log(math.exp(log_w - hi) + math.exp(log_tail - hi))
    else:
        log_degree = log_tail
    return _LOG_TYPE["B"] + log_degree


def log_prior_poly(n_segments: int, all_lines: bool) -> float:
    key = "PL" if all_lines else "PB"
    return _LOG_TYPE[key] + _zeta_log_pmf(n_segments, k_min=2)


# ---------------------------------------------------------------------------
# Bezier primitives
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _binom_row(degree: int) -> tuple[float, ...]:
    """Binomial coefficients for one degree. Cached: degrees are small and few."""
    return tuple(float(math.comb(degree, k)) for k in range(degree + 1))


def _bernstein(t: np.ndarray, n_ctrl: int) -> np.ndarray:
    """Bernstein basis matrix ``(len(t), n_ctrl)`` mapping control points to curve points."""
    d = n_ctrl - 1
    coeff = np.array(_binom_row(d))
    exponents = np.arange(n_ctrl)
    return coeff * t[:, None] ** exponents * (1 - t[:, None]) ** (d - exponents)


def bezier_points(ctrl: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Evaluate a bezier with control points ``ctrl`` (2, N) at parameters ``t`` -> (2, T)."""
    ctrl = np.asarray(ctrl, dtype=float)
    return ctrl @ _bernstein(np.asarray(t, dtype=float), ctrl.shape[1]).T


@lru_cache(maxsize=None)
def _gauss_legendre(n_nodes: int) -> tuple[np.ndarray, np.ndarray]:
    """Nodes/weights for ``[-1, 1]``. Cached: ``leggauss`` does an eigensolve and costs ~300 µs,
    which would otherwise dominate every length query for a degree we already know."""
    nodes, weights = np.polynomial.legendre.leggauss(n_nodes)
    return nodes, weights


#: Upper bound on the degree handled by the pure-Python integrator. Every cubic (and
#: every line/quadratic) slider takes that path: numpy dispatch on 8-10 element arrays
#: costs more than the arithmetic itself (~23 us vs ~5 us per length query).
_PY_LENGTH_MAX_DEGREE = 8


@lru_cache(maxsize=None)
def _gl_plain(n_nodes: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Gauss-Legendre nodes mapped to ``[0, 1]`` and weights pre-halved, as plain tuples."""
    nodes, weights = _gauss_legendre(n_nodes)
    return (
        tuple(0.5 * (float(node) + 1.0) for node in nodes),
        tuple(0.5 * float(weight) for weight in weights),
    )


def _bezier_length_xy(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Scalar Gauss-Legendre arc length: ``L = poly_degree * integral |B(t) . V| dt``.

    With ``n_ctrl`` control points the curve has ``poly_degree = n_ctrl - 1``, and its
    derivative is a degree-``poly_degree - 1`` curve over the ``poly_degree`` difference
    vectors ``V_j = P_{j+1} - P_j``. Pure floats: no arrays, no numpy dispatch.
    """
    n_ctrl = len(xs)
    if n_ctrl < 2:
        return 0.0
    poly_degree = n_ctrl - 1
    derivative_degree = poly_degree - 1  # >= 0; a straight line has derivative degree 0
    coefficients = _binom_row(derivative_degree)
    ts, weights = _gl_plain(max(2, int(5 * math.sqrt(n_ctrl))))
    vx = [xs[i + 1] - xs[i] for i in range(poly_degree)]
    vy = [ys[i + 1] - ys[i] for i in range(poly_degree)]

    total = 0.0
    for t, weight in zip(ts, weights):
        complement = 1.0 - t
        bx = 0.0
        by = 0.0
        for j in range(poly_degree):
            basis = coefficients[j] * t ** j * complement ** (derivative_degree - j)
            bx += basis * vx[j]
            by += basis * vy[j]
        total += weight * math.hypot(bx, by)
    return total * poly_degree


def bezier_length(ctrl: np.ndarray) -> float:
    """Arc length via Gauss-Legendre quadrature of the hodograph.

    A degree-d curve has a degree-(d-1) derivative, so this is exact up to node count;
    ``5*sqrt(d)`` nodes (10 for a cubic) is upstream's accuracy heuristic. Measured against a
    200k-sample polyline, the cubic case is within 3.6e-3 px.
    """
    ctrl = np.asarray(ctrl, dtype=float)
    n_ctrl = ctrl.shape[1]
    if n_ctrl < 2:
        return 0.0
    if n_ctrl <= _PY_LENGTH_MAX_DEGREE:
        return _bezier_length_xy(ctrl[0].tolist(), ctrl[1].tolist())
    n_nodes = max(2, int(5 * math.sqrt(n_ctrl)))
    nodes, weights = _gauss_legendre(n_nodes)
    t = 0.5 * (nodes + 1.0)
    hodo = (n_ctrl - 1) * (ctrl[:, 1:] - ctrl[:, :-1])
    speed = np.linalg.norm(bezier_points(hodo, t), axis=0)
    return 0.5 * float((weights * speed).sum())


@dataclass(frozen=True)
class BezierFit:
    """A fitted bezier segment (control points only)."""

    control_points: np.ndarray  # (2, N)

    @cached_property
    def length(self) -> float:
        return bezier_length(self.control_points)

    def at(self, t: np.ndarray) -> np.ndarray:
        return bezier_points(self.control_points, t)


def _as_points(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if points.ndim != 2:
        raise ValueError("points must be 2-dimensional")
    if points.shape[0] != 2:
        points = points.T
    if points.shape[0] != 2 or points.shape[1] < 2:
        raise ValueError(f"points must have shape (2, L) with L >= 2, got {points.shape}")
    return points


def _chord_params(points: np.ndarray) -> np.ndarray:
    """Normalised cumulative chord length in ``[0, 1]`` — the standard fitting parameter."""
    seg = np.linalg.norm(np.diff(points, axis=1), axis=0)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.linspace(0.0, 1.0, points.shape[1])
    return cum / total


def fit_bezier_segment(
    points: np.ndarray,
    n_ctrl: int,
    constrain_start: bool = False,
    constrain_end: bool = False,
    params: np.ndarray | None = None,
) -> tuple[BezierFit, float]:
    """Least-squares bezier fit to ``points`` (2, L).

    Solved in closed form via the Bernstein basis (the "initial guess" only parameterises
    the constrained least-squares system). Endpoints can be pinned so that adjacent
    poly-bezier segments stay joined. ``params`` defaults to normalised chord length.

    Returns the curve and its *parameter-space* SSE; use :func:`geometric_sse` if you want
    a number that is comparable across curve families.
    """
    points = _as_points(points)
    length = points.shape[1]
    n_ctrl = max(2, min(int(n_ctrl), length))

    if params is None:
        t = _chord_params(points)
    else:
        t = np.asarray(params, dtype=float)
        if t.shape != (length,):
            raise ValueError(f"params must have shape ({length},), got {t.shape}")
    basis = _bernstein(t, n_ctrl)  # L x n_ctrl

    # initial guess: control points linearly interpolated between the data endpoints
    c0 = np.linspace(points[:, 0], points[:, -1], n_ctrl)  # n_ctrl x 2

    free = np.ones(n_ctrl, dtype=bool)
    if constrain_start:
        free[0] = False
    if constrain_end:
        free[-1] = False
    selector = np.eye(n_ctrl)[:, free]  # n_ctrl x f

    a = basis @ selector  # L x f
    y = points.T - basis @ c0  # L x 2
    try:
        z = np.linalg.solve(a.T @ a, a.T @ y)
    except np.linalg.LinAlgError:
        # singular => infinitely many solutions; pinv yields the minimal-norm one
        z = np.linalg.pinv(a) @ y
    control = c0 + selector @ z  # n_ctrl x 2

    sse = float(((basis @ control - points.T) ** 2).sum())
    return BezierFit(control.T), sse


def _dense_samples(curves: Sequence[BezierFit], n_points: int) -> np.ndarray:
    """Dense sample of a (possibly multi-segment) curve, spread over segments by length."""
    if len(curves) == 1:
        return curves[0].at(np.linspace(0.0, 1.0, n_points))
    lengths = np.array([c.length for c in curves])
    total = float(lengths.sum())
    if total <= 0:
        return curves[0].at(np.linspace(0.0, 1.0, n_points))
    counts = np.maximum(2, np.round(lengths / total * n_points).astype(int))
    return np.concatenate([c.at(np.linspace(0.0, 1.0, k)) for c, k in zip(curves, counts)], axis=1)


def _nearest_dist2(curves: Sequence[BezierFit], points: np.ndarray, n_dense: int) -> np.ndarray:
    """Squared distance from each point to the nearest point on ``curves``.

    Nearest-neighbour on a dense sample, then one parabolic step on ``d²(t)`` so the result is
    not quantised to the sample spacing (which is what sets the floor for a noise-free fit).
    """
    ts = np.linspace(0.0, 1.0, n_dense)
    dense = _dense_samples(curves, n_dense)
    d2 = (
        (points ** 2).sum(0)[:, None]
        + (dense ** 2).sum(0)[None, :]
        - 2.0 * points.T @ dense
    )
    idx = d2.argmin(axis=1)
    best = d2[np.arange(points.shape[1]), idx]

    # refine only for single segments; poly segments are short enough that the dense sample
    # already resolves them
    if len(curves) == 1:
        lo = np.clip(idx - 1, 0, n_dense - 1)
        hi = np.clip(idx + 1, 0, n_dense - 1)
        t0, t1, t2 = ts[lo], ts[idx], ts[hi]
        d0 = ((points - curves[0].at(t0)) ** 2).sum(0)
        d1 = best
        d2v = ((points - curves[0].at(t2)) ** 2).sum(0)
        denom = (t1 - t0) * (d1 - d2v) - (t1 - t2) * (d1 - d0)
        safe = np.abs(denom) > 1e-18
        vertex = np.where(
            safe,
            t1
            - 0.5
            * ((t1 - t0) ** 2 * (d1 - d2v) - (t1 - t2) ** 2 * (d1 - d0))
            / np.where(safe, denom, 1.0),
            t1,
        )
        vertex = np.clip(vertex, np.minimum(t0, t2), np.maximum(t0, t2))
        refined = ((points - curves[0].at(vertex)) ** 2).sum(0)
        best = np.minimum(best, refined)

    return np.maximum(best, 0.0)


def geometric_sse(
    curves: Sequence[BezierFit] | BezierFit,
    points: np.ndarray,
    samples: int | None = None,
) -> float:
    """Sum of squared distances from each input point to the nearest point on the curve.

    This is the objective that actually matters: a slider is rendered from its path, so the
    parameterisation used to build the control points is not observable.

    Paths longer than :data:`SCORE_MAX_POINTS` are scored on an evenly-spaced subsample and
    scaled back up, so the result means "summed squared error over the whole path" either way.
    """
    if isinstance(curves, BezierFit):
        curves = [curves]
    points = _as_points(points)
    n_total = points.shape[1]
    if n_total > SCORE_MAX_POINTS:
        idx = np.unique(np.linspace(0, n_total - 1, SCORE_MAX_POINTS).astype(int))
        points = points[:, idx]
    n_pts = points.shape[1]
    n_dense = samples if samples is not None else min(1000, max(128, 4 * n_pts))
    sse = float(_nearest_dist2(curves, points, n_dense).sum())
    return sse * (n_total / n_pts)


def max_geometric_error(curves: Sequence[BezierFit] | BezierFit, points: np.ndarray) -> float:
    """Worst-case (not summed) distance from an input point to the curve, in pixels."""
    if isinstance(curves, BezierFit):
        curves = [curves]
    points = _as_points(points)
    n_pts = points.shape[1]
    n_dense = min(4000, max(256, 8 * n_pts))
    return float(np.sqrt(_nearest_dist2(curves, points, n_dense).max()))


def fit_bezier_curve(
    points: np.ndarray,
    n_ctrl: int,
    constrain_start: bool = False,
    constrain_end: bool = False,
    geometric: bool = True,
) -> tuple[BezierFit, float]:
    """Fit one bezier, trying uniform and chord-length parameters; keep the better path.

    Uniform parameters reproduce input that is already parameter-uniform (exactly, for
    well-conditioned data — which includes every path we build from control points);
    chord-length parameters are stable for arbitrary resampling.

    With ``geometric`` the winner is chosen by point-to-curve distance; inside poly-bezier
    span fits that is set to ``False`` and the (free) parameter residual is used instead,
    which keeps deep splits affordable.
    """
    points = _as_points(points)
    length = points.shape[1]
    uniform = np.linspace(0.0, 1.0, length)

    best: tuple[BezierFit, float] | None = None
    for params in (uniform, _chord_params(points)):
        curve, residual = fit_bezier_segment(
            points,
            n_ctrl,
            constrain_start=constrain_start,
            constrain_end=constrain_end,
            params=params,
        )
        err = geometric_sse(curve, points) if geometric else residual
        if best is None or err < best[1]:
            best = (curve, err)
    assert best is not None
    return best


def fit_poly_bezier(
    points: np.ndarray,
    n_ctrl: int,
    max_segments: int,
) -> Iterator[tuple[list[BezierFit], float]]:
    """Yield poly-bezier fits with 2..max_segments segments of ``n_ctrl`` control points each.

    Segments grow greedily: repeatedly split the worst-fitting span at its point of largest
    error. ``n_ctrl=2`` produces a poly-line. Yields ``(segments, geometric_sse)``.
    """
    points = _as_points(points)
    length = points.shape[1]

    def fit_span(lo: int, hi: int) -> tuple[BezierFit, float, int]:
        seg = points[:, lo:hi + 1]
        n = min(n_ctrl, seg.shape[1])
        c_start, c_end = lo != 0, hi != length - 1
        if n == 2:
            curve, sse = fit_bezier_segment(
                seg, n, constrain_start=c_start, constrain_end=c_end
            )
        else:
            # same parameterisation choice as the single-bezier candidates, so segment
            # residuals are not inflated by the caller's sampling
            curve, sse = fit_bezier_curve(seg, n, c_start, c_end, geometric=False)
        t = np.linspace(0.0, 1.0, seg.shape[1])
        resid = ((curve.at(t) - seg) ** 2).sum(0)
        return curve, sse, lo + int(resid.argmax())

    spans = [(0, length - 1)]
    fits = [fit_span(0, length - 1)]
    previous_best = math.inf

    for _ in range(2, max_segments + 1):
        candidates = [k for k, (lo, hi) in enumerate(spans) if hi - lo >= 2]
        if not candidates:
            break
        worst = max(candidates, key=lambda k: fits[k][1])
        lo, hi = spans[worst]
        split = fits[worst][2]
        if not lo < split < hi:
            split = (lo + hi) // 2

        spans = spans[:worst] + [(lo, split), (split, hi)] + spans[worst + 1:]
        fits = fits[:worst] + [fit_span(lo, split), fit_span(split, hi)] + fits[worst + 1:]

        curves = [f[0] for f in fits]
        sse = geometric_sse(curves, points)
        # greedy splitting at the worst-fitting span can occasionally make the *global*
        # geometric error slightly worse; only ever offer an improvement, so callers see a
        # monotonically decreasing sequence
        if sse < previous_best:
            previous_best = sse
            yield curves, sse


# ---------------------------------------------------------------------------
# Perfect arc
# ---------------------------------------------------------------------------


def fit_arc(points: np.ndarray) -> tuple[float, float, list[np.ndarray]] | None:
    """Fit a circular arc, returning ``(sse, length, [start, mid, end])`` or None.

    Arithmetic (algebraic) circle fit: solve ``x^2 + y^2 = 2*cx*x + 2*cy*y + c`` by linear
    least squares, then reject anything osu! could not render as a perfect slider.
    """
    points = _as_points(points)
    if points.shape[1] < 3:
        return None

    x, y = points
    a = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    b = x * x + y * y

    try:
        cx, cy, c = np.linalg.lstsq(a, b, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None

    r_squared = cx * cx + cy * cy + c
    if r_squared <= 0:
        return None

    center = np.array([cx, cy])
    radius = math.sqrt(r_squared)

    start, end = points[:, 0], points[:, -1]
    if np.linalg.norm(end - start) < 15:
        return None
    if radius > MAX_ARC_RADIUS:
        return None

    angles = np.unwrap(np.arctan2(y - cy, x - cx))
    sweep = angles[-1] - angles[0]
    if abs(sweep) < 0.05:
        return None

    deltas = np.diff(angles)
    if np.count_nonzero(np.sign(deltas) != np.sign(sweep)) > len(deltas) * 0.25:
        return None

    radial_err = np.linalg.norm(points - center[:, None], axis=0) - radius
    sse = float((radial_err ** 2).sum())

    mid = center + radius * np.array(
        [math.cos(angles[0] + sweep / 2), math.sin(angles[0] + sweep / 2)]
    )
    length = abs(sweep) * radius
    return sse, length, [start, mid, end]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FittedSlider:
    """A slider path reduced to an osu!-representable curve."""

    path_type: str  # "P" (perfect), "L" (line), "B" (bezier / poly-bezier)
    control_points: tuple[tuple[float, float], ...]  # unrounded; osu! wants ints
    length: float  # px, measured on the fitted (unrounded) curve
    sse: float  # geometric: sum of squared point-to-curve distances, px²
    cost: float  # MAP cost: sse / (2*noise²) - log prior

    def rounded_control_points(self) -> tuple[tuple[int, int], ...]:
        return tuple((int(round(x)), int(round(y))) for x, y in self.control_points)


def _to_control_points(curves: list[BezierFit]) -> tuple[tuple[float, float], ...]:
    """Concatenate segments, keeping shared join points.

    The repeated point is meaningful: osu! uses a duplicated control point as the
    segment separator for poly-bezier sliders.
    """
    pts: list[tuple[float, float]] = []
    for curve in curves:
        pts.extend((float(x), float(y)) for x, y in curve.control_points.T)
    return tuple(pts)


def fit_slider_path(
    points: np.ndarray,
    noise_scale: float = NOISE_SCALE,
    equivalence_msqe: float = EQUIVALENCE_MSQE,
) -> FittedSlider:
    """Choose the best slider curve type for a dense path.

    ``points`` may be sampled any way as long as the order follows the path.
    """
    points = _as_points(points)
    n_pts = points.shape[1]
    inv_2var = 1.0 / (2.0 * noise_scale ** 2)

    candidates: list[tuple[float, str, tuple[tuple[float, float], ...], float, float]] = []

    def consider(
        cost: float,
        path_type: str,
        ctrl: tuple[tuple[float, float], ...],
        length: float,
        sse: float,
    ) -> None:
        candidates.append((cost, path_type, ctrl, length, sse))

    def best_cost() -> float | None:
        return min((c[0] for c in candidates), default=None)

    arc = fit_arc(points)
    if arc is not None:
        sse, length, ctrl = arc
        consider(
            sse * inv_2var - log_prior_arc(),
            "P",
            tuple((float(p[0]), float(p[1])) for p in ctrl),
            float(length),
            sse,
        )

    ordered = sorted(
        (-log_prior_single_bezier(n), n) for n in range(2, min(MAX_BEZIER_CTRL, n_pts) + 1)
    )
    for penalty, n_ctrl in ordered:
        current = best_cost()
        if current is not None and penalty >= current:
            break  # sse >= 0, so no remaining (higher-penalty) candidate can win
        if n_ctrl == 2:
            curve, _ = fit_bezier_segment(points, n_ctrl)
            sse = geometric_sse(curve, points)
        else:
            curve, sse = fit_bezier_curve(points, n_ctrl)
        consider(
            sse * inv_2var + penalty,
            "L" if n_ctrl == 2 else "B",
            _to_control_points([curve]),
            curve.length,
            sse,
        )

    for n_ctrl, all_lines in ((2, True), (4, False)):
        current = best_cost()
        if current is not None and -log_prior_poly(2, all_lines) >= current:
            continue
        for curves, sse in fit_poly_bezier(points, n_ctrl, MAX_SEGMENTS):
            m = len(curves)
            consider(
                sse * inv_2var - log_prior_poly(m, all_lines),
                "B",
                _to_control_points(curves),
                float(sum(c.length for c in curves)),
                sse,
            )
            current = best_cost()
            if current is not None and -log_prior_poly(m + 1, all_lines) >= current:
                break  # penalty only grows with segment count

    if not candidates:  # pragma: no cover - unreachable: n_ctrl=2 is always a candidate
        raise RuntimeError("no slider candidate could be fitted")

    # Among visually-identical candidates, prefer the one osu! will treat as simplest.
    mean_sse = [c[4] / n_pts for c in candidates]
    floor = min(mean_sse)
    keep = [
        c for c, m in zip(candidates, mean_sse) if m <= floor + equivalence_msqe
    ]
    cost, path_type, ctrl, length, sse = min(keep, key=lambda c: (len(c[2]), c[0]))
    return FittedSlider(path_type, ctrl, length, sse, cost)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resample_by_arclength(points: np.ndarray, n: int | None = None) -> np.ndarray:
    """Resample a ``(2, L)`` polyline to ``n`` points uniformly spaced along arc length."""
    points = _as_points(points)
    if n is None:
        n = points.shape[1]
    if n < 2:
        raise ValueError("need at least 2 samples")

    seg = np.linalg.norm(np.diff(points, axis=1), axis=0)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(points[:, :1], n, axis=1)

    s = np.linspace(0.0, total, n)
    return np.stack([np.interp(s, cum, points[0]), np.interp(s, cum, points[1])])


def _circumcircle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, float] | None:
    """Circumscribed circle of a triangle, via the same barycentric weights osu! uses.

    The weight for vertex ``A`` is ``a^2 (b^2 + c^2 - a^2)`` where ``a`` is the side
    *opposite* ``A`` (i.e. ``|B - C|``); likewise for B and C. Returns None when the points
    are collinear (osu! then treats the slider as a bezier instead).
    """
    ab, cb, ac = b - a, c - b, c - a
    if np.cross(ab, cb) == 0:
        return None
    a2, b2, c2 = np.linalg.norm(cb) ** 2, np.linalg.norm(ac) ** 2, np.linalg.norm(ab) ** 2
    w1 = a2 * (b2 + c2 - a2)
    w2 = b2 * (a2 + c2 - b2)
    w3 = c2 * (a2 + b2 - c2)
    total = w1 + w2 + w3
    if total == 0:
        return None
    center = (a * w1 + b * w2 + c * w3) / total
    radius = float(np.linalg.norm(a - center))
    if radius <= 0:
        return None
    return center, radius


def sample_path(fitted: FittedSlider, n: int) -> np.ndarray:
    """Resample a fitted slider back to ``n`` points, for round-trip validation.

    Perfect sliders are reconstructed from their circumscribed circle; bezier/poly-bezier
    sliders are sampled per segment and merged in proportion to segment arc length.
    """
    if n < 2:
        raise ValueError("need at least 2 samples")
    if len(fitted.control_points) < 2:
        raise ValueError("fitted slider has no usable control points")
    pts = np.array(fitted.control_points, dtype=float).T

    if fitted.path_type == "P":
        circle = _circumcircle(pts[:, 0], pts[:, 1], pts[:, 2])
        if circle is not None:
            center, radius = circle
            start = math.atan2(pts[1, 0] - center[1], pts[0, 0] - center[0])
            end = math.atan2(pts[1, 2] - center[1], pts[0, 2] - center[0])
            cross = float(np.cross(pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 1]))
            if cross < 0:
                while end > start:
                    end -= 2 * math.pi
            else:
                while start > end:
                    start -= 2 * math.pi
            angles = np.linspace(start, end, n)
            return center[:, None] + radius * np.stack([np.cos(angles), np.sin(angles)])

    # split at repeated control points (osu!'s segment marker)
    segments: list[np.ndarray] = []
    last = 0
    for i in range(pts.shape[1] - 1):
        if np.allclose(pts[:, i], pts[:, i + 1]):
            segments.append(pts[:, last:i + 1])
            last = i + 1
    segments.append(pts[:, last:])
    segments = [s for s in segments if s.shape[1] >= 2]
    if not segments:
        raise ValueError("fitted slider has no usable segments")

    seg_lengths = np.array([bezier_length(s) for s in segments])
    total_length = float(seg_lengths.sum())
    counts = np.maximum(2, np.round(seg_lengths / total_length * n).astype(int))
    combined = np.concatenate(
        [bezier_points(s, np.linspace(0.0, 1.0, c)) for s, c in zip(segments, counts)], axis=1
    )
    return resample_by_arclength(combined, n)


# ---------------------------------------------------------------------------
# Fast path: fitting a path whose curve family is already known
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FamilyFit:
    """Result of fitting a path whose curve family the caller already knows."""

    path_type: str  # osu! family: "linear" | "bezier" | "perfect" | "catmull"
    control_points: tuple[tuple[float, float], ...]  # excluding the head
    length: float
    method: str  # "linear" | "arc" | "exact" | "simplified" | "passthrough"
    max_error: float = 0.0
    simplified: bool = False


def split_segments(points: np.ndarray) -> list[np.ndarray]:
    """Split an osu! control-point chain at duplicated points (the segment marker)."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 2:
        return []
    # one vectorised comparison; a per-point np.allclose loop dominated this path
    gaps = points[:, 1:] - points[:, :-1]
    duplicates = (gaps * gaps).sum(axis=0) <= 1e-18
    segments: list[np.ndarray] = []
    last = 0
    for i in np.flatnonzero(duplicates):
        segments.append(points[:, last:i + 1])
        last = i + 1
    segments.append(points[:, last:])
    return [s for s in segments if s.shape[1] >= 2]


def bezier_chain_length(points: np.ndarray) -> float:
    """Exact arc length of a (possibly multi-segment) osu! bezier chain."""
    points = np.asarray(points, dtype=float)
    return bezier_chain_length_xy(points[0].tolist(), points[1].tolist())


def _split_spans(xs: Sequence[float], ys: Sequence[float]) -> list[tuple[int, int]]:
    """Half-open index spans of a chain split at duplicated anchors (osu's marker)."""
    spans: list[tuple[int, int]] = []
    last = 0
    for i in range(len(xs) - 1):
        if xs[i] == xs[i + 1] and ys[i] == ys[i + 1]:
            spans.append((last, i + 1))
            last = i + 1
    spans.append((last, len(xs)))
    return [(lo, hi) for lo, hi in spans if hi - lo >= 2]


def bezier_chain_length_xy(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Exact chain length from plain coordinate sequences (the production hot path)."""
    if len(xs) < 2:
        return 0.0
    return float(
        sum(
            _bezier_length_xy(xs[lo:hi], ys[lo:hi])
            for lo, hi in _split_spans(xs, ys)
        )
    )


def arc_through(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float | None:
    """Length of the circular arc ``a -> b -> c``, or None if osu! could not render it.

    Closed form, pure floats (this runs once per arc slider, so numpy dispatch costs more
    than the arithmetic): circumcircle by the standard determinant, then the signed sweep
    that actually passes through ``b``. ``length = radius * |sweep|``.
    """
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cx, cy = float(c[0]), float(c[1])

    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None  # collinear: osu! cannot render a perfect slider

    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d

    radius = math.hypot(ax - ux, ay - uy)
    if radius <= 0 or radius > MAX_ARC_RADIUS:
        return None

    start = math.atan2(ay - uy, ax - ux)
    mid = math.atan2(by - uy, bx - ux)
    end = math.atan2(cy - uy, cx - ux)

    # orient the sweep by the side the middle point lies on
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if cross < 0:  # clockwise
        while end > start:
            end -= 2 * math.pi
        while mid > start:
            mid -= 2 * math.pi
    else:  # counter-clockwise
        while start > end:
            start -= 2 * math.pi
        while mid < start:
            mid += 2 * math.pi

    sweep = end - start
    if abs(sweep) < 0.05:
        return None
    # the middle anchor must lie inside the sweep, else the arc would be the long way round
    if not (min(start, end) - 1e-9 <= mid <= max(start, end) + 1e-9):
        return None
    return abs(sweep) * radius


def _sample_chain(segments: Sequence[np.ndarray], per_segment: int) -> np.ndarray:
    """Dense sample of a bezier chain, de-duplicating the shared join points."""
    if not segments:
        return np.empty((2, 0))
    samples = [bezier_points(s, np.linspace(0.0, 1.0, per_segment)) for s in segments]
    chain = [samples[0]]
    for sample in samples[1:]:
        chain.append(sample[:, 1:])
    return np.concatenate(chain, axis=1)


def fit_known_family(
    start: Sequence[float],
    control_points: Sequence[Sequence[float]],
    path_type: str,
    *,
    simplify_tolerance: float = 1.0,
) -> FamilyFit:
    """Resolve geometry for a path whose family is already known.

    This is the production fast path: it avoids the full MAP search in
    :func:`fit_slider_path` by using closed forms for lines and arcs and an exact
    hodograph integral for bezier chains. Behaves as follows:

    * ``linear``  — exact endpoint distance.
    * ``perfect`` — closed-form arc length; degrades to a line when the three anchors
      are collinear or the radius exceeds osu!'s 320 px limit.
    * ``bezier``/``catmull`` — exact chain length; additionally *simplifies* a
      multi-anchor chain to a single cubic when that reproduces it within
      ``simplify_tolerance`` px.

    The returned control points are the *unrounded* anchors (excluding the head), in the
    same family as the input unless a simplification or degradation happened.
    """
    anchors = [(float(p[0]), float(p[1])) for p in control_points]
    if not anchors:
        return FamilyFit("linear", (), 0.0, "linear")

    points = np.array([[float(start[0]), *[p[0] for p in anchors]],
                       [float(start[1]), *[p[1] for p in anchors]]])

    if path_type == "linear":
        return FamilyFit(
            "linear",
            (anchors[-1],),
            float(np.linalg.norm(points[:, -1] - points[:, 0])),
            "linear",
        )

    if path_type == "perfect":
        if points.shape[1] == 3:
            length = arc_through(points[:, 0], points[:, 1], points[:, 2])
            if length is not None:
                return FamilyFit("perfect", (anchors[0], anchors[1]), float(length), "arc")
            # collinear or too flat for osu!'s arc renderer: emit a straight slider
            return FamilyFit(
                "linear",
                (anchors[-1],),
                float(np.linalg.norm(points[:, -1] - points[:, 0])),
                "arc->line",
            )
        # "P" needs exactly 3 anchors; anything else must go out as a bezier
        path_type = "bezier"

    xs = points[0].tolist()
    ys = points[1].tolist()
    spans = _split_spans(xs, ys)
    length = float(
        sum(_bezier_length_xy(xs[lo:hi], ys[lo:hi]) for lo, hi in spans)
    )
    segments = [points[:, lo:hi] for lo, hi in spans] if spans else []
    # Only try to collapse short chains: a 3+ segment wave/zigzag/loop cannot be one
    # cubic, and attempting the fit is the expensive part of this path.
    if simplify_tolerance > 0 and len(anchors) > 3 and 1 <= len(spans) <= 2:
        simplified = _simplify_chain(segments, simplify_tolerance)
        if simplified is not None:
            return simplified

    return FamilyFit(path_type, tuple(anchors), length, "exact")


def _simplify_chain(segments: Sequence[np.ndarray], tolerance: float) -> FamilyFit | None:
    """Collapse a multi-anchor bezier chain into one cubic, if that is faithful."""
    path = _sample_chain(segments, 12)
    if path.shape[1] < 4:
        return None
    path = resample_by_arclength(path, 24)
    # residual-based parameter choice is enough here: both candidates are fits to the
    # same 24 samples, and the geometric error is measured once below
    curve, _ = fit_bezier_curve(path, 4, geometric=False)
    error = max_geometric_error(curve, path)
    if error > tolerance:
        return None
    return FamilyFit(
        "bezier",
        tuple((float(x), float(y)) for x, y in curve.control_points.T),
        curve.length,
        "simplified",
        float(error),
        True,
    )
