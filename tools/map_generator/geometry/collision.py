"""Phase 23 — Anti-overlap collision primitives.

Radius-aware, deterministic collision math used by the rebalancer, the
validation pass, and the evolution gate. Everything here is a pure function
of geometry — no randomness, no global state.

Primitives:
* ``discs_overlap`` — circle vs circle with per-object radii + margin.
* ``point_polyline_distance`` — distance from a point to a sampled path
  (used for circle vs slider-body checks).
* ``polyline_polyline_distance`` — minimum distance between two sampled
  paths (used for slider vs slider checks).
* ``sample_slider_path`` — rebuild a slider's sampled path from raw map
  JSON via the Phase 21 slider geometry engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

# Playfield bounds (osu! standard).
PLAYFIELD_X_MAX = 512.0
PLAYFIELD_Y_MAX = 384.0

# Default nudge distance when two objects collide (px from each center).
COLLISION_NUDGE_PX = 8.0
# Margin added on top of the geometric radii before a pair counts as overlap.
DEFAULT_OVERLAP_MARGIN_PX = 2.0
# A "perfect stack" is when centers are within this many px of each other.
PERFECT_STACK_PX = 2.0
# Objects separated by more than this much time can share a spot (intentional
# stacks are legal in osu!), so they are not flagged as collisions.
STACK_TIME_WINDOW_MS = 1500
# Pairs closer in time than this are "pattern density" (streams / bursts):
# their discs are allowed to overlap by design in osu!, so they use the
# relaxed tight floor instead of the full disc-disc floor.
COLLISION_TIGHT_GAP_MS = 250.0
# Tight-floor fraction of ``2 * radius`` applied to pattern-density pairs.
# Two consecutive tight steps (2 * 0.55 * 2r) already exceed the full
# ``2r + margin`` floor, so real streams never accumulate into flagged pairs.
TIGHT_OVERLAP_RATIO = 0.55


def disc_disc_floor(radius: float, gap_ms: float, margin_px: float = DEFAULT_OVERLAP_MARGIN_PX) -> float:
    """Minimum center distance for a disc-disc pair with a given time gap.

    Pattern-density pairs (streams / bursts, ``gap <= COLLISION_TIGHT_GAP_MS``)
    use the relaxed tight floor; all other pairs must clear the full sum of
    radii plus margin. This keeps generated streams alive while still catching
    near-stacks of distinct notes.
    """
    if gap_ms <= COLLISION_TIGHT_GAP_MS:
        return radius * 2.0 * TIGHT_OVERLAP_RATIO
    return radius * 2.0 + margin_px


def discs_overlap(
    x1: float,
    y1: float,
    r1: float,
    x2: float,
    y2: float,
    r2: float,
    *,
    margin_px: float = DEFAULT_OVERLAP_MARGIN_PX,
) -> bool:
    """True when two discs (hit circles / slider heads/tails) overlap."""
    return _center_distance(x1, y1, x2, y2) < (r1 + r2 + margin_px)


def discs_clearance(
    x1: float,
    y1: float,
    r1: float,
    x2: float,
    y2: float,
    r2: float,
) -> float:
    """Signed clearance between two discs (negative = overlap depth)."""
    return _center_distance(x1, y1, x2, y2) - (r1 + r2)


def point_polyline_distance(
    px: float,
    py: float,
    path: Sequence[tuple[float, float]],
) -> float:
    """Minimum distance from a point to a sampled polyline path."""
    if not path:
        return float("inf")
    if len(path) == 1:
        return _center_distance(px, py, path[0][0], path[0][1])
    best = float("inf")
    for index in range(1, len(path)):
        distance = _point_segment_distance(px, py, path[index - 1], path[index])
        best = min(best, distance)
    return best


def polyline_polyline_distance(
    path_a: Sequence[tuple[float, float]],
    path_b: Sequence[tuple[float, float]],
) -> float:
    """Minimum distance between two sampled polylines (segment pairs)."""
    if not path_a or not path_b:
        return float("inf")
    best = float("inf")
    for index in range(1, len(path_a)):
        segment_a = (path_a[index - 1], path_a[index])
        for other_index in range(1, len(path_b)):
            segment_b = (path_b[other_index - 1], path_b[other_index])
            distance = _segment_segment_distance(segment_a, segment_b)
            best = min(best, distance)
            if best == 0.0:
                return 0.0
    return best


def clamp_to_playfield(x: float, y: float, radius: float) -> tuple[float, float]:
    """Clamp a coordinate so the disc stays fully inside the playfield."""
    margin = max(0.0, radius)
    clamped_x = min(PLAYFIELD_X_MAX - margin, max(margin, x))
    clamped_y = min(PLAYFIELD_Y_MAX - margin, max(margin, y))
    return round(clamped_x, 2), round(clamped_y, 2)


def nearest_point_on_polyline(
    px: float,
    py: float,
    path: Sequence[tuple[float, float]],
) -> tuple[float, float]:
    """Return the closest point on a sampled polyline to ``(px, py)``."""
    if not path:
        return (px, py)
    if len(path) == 1:
        return path[0]
    best_point = path[0]
    best_distance = float("inf")
    for index in range(1, len(path)):
        point, distance = _point_segment_nearest(px, py, path[index - 1], path[index])
        if distance < best_distance:
            best_distance = distance
            best_point = point
    return best_point


def nearest_pair_on_polylines(
    path_a: Sequence[tuple[float, float]],
    path_b: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Closest pair of points between two sampled polylines.

    Returns ``((ax, ay), (bx, by), distance)``. When the polylines cross the
    pair coincides (distance 0) — the caller can then fall back to a path
    normal to separate them.
    """
    if not path_a or not path_b:
        raise ValueError("nearest_pair_on_polylines requires non-empty paths")
    best_pair: tuple[tuple[float, float], tuple[float, float]] | None = None
    best_distance = float("inf")
    for index in range(1, len(path_a)):
        a1 = path_a[index - 1]
        a2 = path_a[index]
        for other_index in range(1, len(path_b)):
            b1 = path_b[other_index - 1]
            b2 = path_b[other_index]
            point_a, point_b, distance = _segment_segment_nearest(a1, a2, b1, b2)
            if distance < best_distance:
                best_distance = distance
                best_pair = (point_a, point_b)
                if distance == 0.0:
                    return point_a, point_b, 0.0
    assert best_pair is not None
    return _as_flat_point(best_pair[0]), _as_flat_point(best_pair[1]), best_distance


def path_normal_at(
    path: Sequence[tuple[float, float]],
    point: tuple[float, float],
    object_id: int,
) -> tuple[float, float]:
    """Unit normal of the path segment nearest to ``point``.

    The side is chosen deterministically from ``object_id`` parity so two
    passes never flip direction. Falls back to a fixed axis on degenerate
    paths.
    """
    # Defensive: ensure point is a flat (float, float) tuple.
    flat_point = _as_flat_point(point)
    best_segment: tuple[tuple[float, float], tuple[float, float]] | None = None
    best_distance = float("inf")
    for index in range(1, len(path)):
        segment = (_as_flat_point(path[index - 1]), _as_flat_point(path[index]))
        _, distance = _point_segment_nearest(flat_point[0], flat_point[1], segment[0], segment[1])
        if distance < best_distance:
            best_distance = distance
            best_segment = segment
    if best_segment is None:
        angle = math.radians(45.0 if object_id % 2 == 0 else -45.0)
        return math.cos(angle), math.sin(angle)
    dx = best_segment[1][0] - best_segment[0][0]
    dy = best_segment[1][1] - best_segment[0][1]
    magnitude = math.hypot(dx, dy)
    sign = 1.0 if object_id % 2 == 0 else -1.0
    if magnitude <= 1e-6:
        angle = math.radians(45.0 if object_id % 2 == 0 else -45.0)
        return math.cos(angle), math.sin(angle)
    return (-dy / magnitude) * sign, (dx / magnitude) * sign


def _as_flat_point(value: Any) -> tuple[float, float]:
    """Coerce a point to a flat (float, float) tuple.

    Handles nested tuples from malformed slider paths.
    """
    if isinstance(value, (list, tuple)):
        a = value[0]
        b = value[1]
        # Unwrap one level of nesting if needed.
        if isinstance(a, (list, tuple)):
            a = a[0]
        if isinstance(b, (list, tuple)):
            b = b[0]
        return (float(a), float(b))
    return (0.0, 0.0)


# Slider path cache: bounded LRU-style cache keyed by a deterministic
# string built from the slider's geometry fields.  The cache is capped at
# ``_SLIDER_CACHE_MAX_SIZE`` entries; when the cap is exceeded the oldest
# half of the entries are evicted to keep memory bounded across long
# evolution runs (many candidates × validation passes).
_SLIDER_CACHE_MAX_SIZE = 500
_slider_path_cache: dict[str, list[tuple[float, float]]] = {}
_slider_cache_order: list[str] = []  # insertion-ordered keys for eviction


def _slider_cache_key(obj: dict[str, Any]) -> str:
    """Deterministic cache key for slider path sampling."""
    parts = [
        str(obj.get("id", "")),
        str(obj.get("x", "")),
        str(obj.get("y", "")),
        str(obj.get("pathType", "")),
        str(obj.get("pixelLength", "")),
    ]
    cps = obj.get("controlPoints")
    if isinstance(cps, list):
        for cp in cps:
            if isinstance(cp, dict):
                parts.append(f"{cp.get('x', '')}:{cp.get('y', '')}")
    return "|".join(parts)


def _get_slider_path(obj: dict[str, Any]) -> list[tuple[float, float]]:
    """Get slider path with bounded caching."""
    key = _slider_cache_key(obj)
    cached = _slider_path_cache.get(key)
    if cached is not None:
        return cached
    path = sample_slider_path(obj)
    # Evict oldest entries when the cache exceeds the cap.
    if len(_slider_path_cache) >= _SLIDER_CACHE_MAX_SIZE:
        evict_count = _SLIDER_CACHE_MAX_SIZE // 2
        for old_key in _slider_cache_order[:evict_count]:
            _slider_path_cache.pop(old_key, None)
        del _slider_cache_order[:evict_count]
    _slider_path_cache[key] = path
    _slider_cache_order.append(key)
    return path


def clear_slider_cache() -> None:
    """Clear the slider path cache and its eviction order."""
    _slider_path_cache.clear()
    _slider_cache_order.clear()


def detect_map_overlaps(
    objects: Sequence[dict[str, Any]],
    circle_radius: float,
    *,
    margin_px: float = DEFAULT_OVERLAP_MARGIN_PX,
    max_time_gap_ms: float = 2000.0,
) -> list[dict[str, Any]]:
    """Scan raw map objects for physical overlaps.

    Canonical detector used by the collision validator, the evolution hard
    gate, and the rebalancer. Deterministic: pairs are visited in time order
    and every metric is a pure function of geometry.

    Only near-in-time objects are compared (within ``max_time_gap_ms``) so
    intentional time-separated stacks and distant objects are never flagged.
    Each returned record carries ``left_id``, ``right_id``, ``kind``
    (disc-disc | disc-slider | slider-slider), ``clearance_px`` (negative =
    overlap depth), ``required_px``, ``start_time_ms``, and a suggestion.
    """
    positioned = [
        item
        for item in objects
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("time"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item["time"]), int(item.get("id", 0))))
    radius = float(circle_radius or 1.0)

    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(positioned):
        left_path = (
            _get_slider_path(left)
            if left.get("type") == "slider"
            else [(float(left.get("x") or 0.0), float(left.get("y") or 0.0))]
        )
        left_time = int(left["time"])
        for right in positioned[index + 1 :]:
            gap = int(right["time"]) - left_time
            if gap <= 0:
                continue
            if gap > max_time_gap_ms:
                break  # List is time-sorted; all remaining objects are further away.
            right_path = (
                _get_slider_path(right)
                if right.get("type") == "slider"
                else [(float(right.get("x") or 0.0), float(right.get("y") or 0.0))]
            )
            pair = _check_raw_pair(
                left=left,
                right=right,
                left_path=left_path,
                right_path=right_path,
                radius=radius,
                gap=gap,
                margin_px=margin_px,
            )
            if pair is None:
                continue
            # Intentional time-separated stacks are legal osu! notation.
            if (
                gap > STACK_TIME_WINDOW_MS
                and pair["kind"] == "disc-disc"
                and abs(pair["clearance_px"]) <= PERFECT_STACK_PX + radius * 2.0
                and _same_center(left_path, right_path)
            ):
                continue
            overlaps.append(pair)
    return overlaps


def sample_slider_path(
    raw_object: dict[str, Any],
    *,
    num_samples: int = 40,
) -> list[tuple[float, float]]:
    """Rebuild a slider's sampled path from raw map JSON.

    Reads the Phase 21 slider fields (``x``/``y``, ``pathType``,
    ``controlPoints``) and samples the path deterministically. Falls back to
    the slider head when geometry is missing so old maps never crash.
    """
    start_x = _number(raw_object.get("x"), 0.0)
    start_y = _number(raw_object.get("y"), 0.0)
    path_type = raw_object.get("pathType") or "bezier"
    if path_type not in ("linear", "bezier", "perfect", "catmull"):
        path_type = "bezier"

    from ..sliders.slider_geometry import sample_path_points
    from ..sliders.slider_models import ControlPoint

    control_points = _control_points(raw_object.get("controlPoints"))
    try:
        sampled = sample_path_points(
            start_x=int(round(start_x)),
            start_y=int(round(start_y)),
            control_points=control_points,
            path_type=path_type,
            num_samples=num_samples,
        )
    except Exception:
        return [(start_x, start_y)]
    return [(float(point[0]), float(point[1])) for point in sampled]


def slider_endpoint(
    raw_object: dict[str, Any],
    *,
    num_samples: int = 40,
) -> tuple[float, float]:
    """Approximate the slider's final (head+tail) point after repeats."""
    path = sample_slider_path(raw_object, num_samples=num_samples)
    if not path:
        return (_number(raw_object.get("x"), 0.0), _number(raw_object.get("y"), 0.0))
    return path[-1]


def _control_points(value: Any) -> list[Any]:
    from ..sliders.slider_models import ControlPoint

    points: list[Any] = []
    if not isinstance(value, list):
        return points
    for item in value:
        if not isinstance(item, dict):
            continue
        x = item.get("x")
        y = item.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append(ControlPoint(x=int(round(x)), y=int(round(y))))
    return points


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _center_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def _point_segment_distance(
    px: float,
    py: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 0.0:
        return _center_distance(px, py, sx, sy)
    projection = ((px - sx) * dx + (py - sy) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest_x = sx + projection * dx
    nearest_y = sy + projection * dy
    return _center_distance(px, py, nearest_x, nearest_y)


def _point_segment_nearest(
    px: float,
    py: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    # Defensive: unwrap nested tuples that may come from malformed slider paths.
    if isinstance(px, (list, tuple)):
        px = float(px[0])
    if isinstance(py, (list, tuple)):
        py = float(py[0])
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    dx = ex - sx
    dy = ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 0.0:
        return (sx, sy), _center_distance(px, py, sx, sy)
    projection = ((px - sx) * dx + (py - sy) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest_x = sx + projection * dx
    nearest_y = sy + projection * dy
    return (nearest_x, nearest_y), _center_distance(px, py, nearest_x, nearest_y)


def _segment_segment_nearest(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Closest points between two segments (Ericson closest-point algorithm)."""
    da = (a2[0] - a1[0], a2[1] - a1[1])
    db = (b2[0] - b1[0], b2[1] - b1[1])
    r = (a1[0] - b1[0], a1[1] - b1[1])
    a = da[0] * da[0] + da[1] * da[1]
    e = db[0] * db[0] + db[1] * db[1]
    f = db[0] * r[0] + db[1] * r[1]
    c = da[0] * r[0] + da[1] * r[1]
    if a <= 1e-12 and e <= 1e-12:
        return (a1, a1), (b1, b1), _center_distance(a1[0], a1[1], b1[0], b1[1])
    if a <= 1e-12:
        return (a1, a1), (b1[0] + db[0] * f / e, b1[1] + db[1] * f / e), _center_distance(
            a1[0], a1[1], b1[0] + db[0] * f / e, b1[1] + db[1] * f / e
        )
    s = (a * f - c * e) / (a * e - (da[0] * db[0] + da[1] * db[1]) ** 2) if a * e != (da[0] * db[0] + da[1] * db[1]) ** 2 else 0.0
    s = max(0.0, min(1.0, s))
    t = (f + s * (da[0] * db[0] + da[1] * db[1])) / e if e > 1e-12 else 0.0
    t = max(0.0, min(1.0, t))
    point_a = (a1[0] + da[0] * s, a1[1] + da[1] * s)
    point_b = (b1[0] + db[0] * t, b1[1] + db[1] * t)
    return point_a, point_b, _center_distance(point_a[0], point_a[1], point_b[0], point_b[1])


def _check_raw_pair(
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    left_path: list[tuple[float, float]],
    right_path: list[tuple[float, float]],
    radius: float,
    gap: float,
    margin_px: float,
) -> dict[str, Any] | None:
    kind = "disc-disc"
    if left.get("type") == "slider" and right.get("type") == "slider":
        kind = "slider-slider"
    elif left.get("type") == "slider" or right.get("type") == "slider":
        kind = "disc-slider"

    if kind == "disc-disc":
        lx = float(left.get("x") or 0.0)
        ly = float(left.get("y") or 0.0)
        rx = float(right.get("x") or 0.0)
        ry = float(right.get("y") or 0.0)
        clearance = discs_clearance(lx, ly, radius, rx, ry, radius)
        # Pattern-density pairs (streams / bursts) relax the floor so the
        # classic tight osu! stream look survives; distinct notes must clear.
        floor = disc_disc_floor(radius, gap, margin_px)
        if _center_distance(lx, ly, rx, ry) >= floor:
            return None
    elif kind == "slider-slider":
        clearance = polyline_polyline_distance(left_path, right_path) - radius * 2.0
        if clearance >= -margin_px:
            return None
    else:
        circle = left if left.get("type") == "circle" else right
        slider_path = right_path if left.get("type") == "circle" else left_path
        clearance = point_polyline_distance(
            float(circle.get("x") or 0.0),
            float(circle.get("y") or 0.0),
            slider_path,
        ) - radius * 2.0
        if clearance >= -margin_px:
            return None

    left_type = str(left.get("type", "circle"))
    right_type = str(right.get("type", "circle"))
    return {
        "left_id": int(left.get("id", 0)),
        "right_id": int(right.get("id", 0)),
        "kind": kind,
        "clearance_px": clearance,
        "required_px": -(radius * 2.0),
        "start_time_ms": int(right["time"]),
        "suggestion": (
            f"Objects {left.get('id')} ({left_type}) and {right.get('id')} ({right_type}) "
            f"overlap by {-clearance:.1f}px (required {radius * 2.0:.0f}px gap). "
            "Nudge the later object away from the collision."
        ),
    }


def _same_center(
    left_path: list[tuple[float, float]],
    right_path: list[tuple[float, float]],
) -> bool:
    if not left_path or not right_path:
        return False
    return abs(left_path[0][0] - right_path[0][0]) <= PERFECT_STACK_PX and abs(
        left_path[0][1] - right_path[0][1]
    ) <= PERFECT_STACK_PX


def _segment_segment_distance(
    segment_a: tuple[tuple[float, float], tuple[float, float]],
    segment_b: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Minimum distance between two line segments."""
    a1, a2 = segment_a
    b1, b2 = segment_b
    candidates = [
        _point_segment_distance(b1[0], b1[1], a1, a2),
        _point_segment_distance(b2[0], b2[1], a1, a2),
        _point_segment_distance(a1[0], a1[1], b1, b2),
        _point_segment_distance(a2[0], a2[1], b1, b2),
    ]
    if _segments_intersect(a1, a2, b1, b2):
        return 0.0
    return min(candidates)


def _segments_intersect(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    def orientation(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

    o1 = orientation(a1, a2, b1)
    o2 = orientation(a1, a2, b2)
    o3 = orientation(b1, b2, a1)
    o4 = orientation(b1, b2, a2)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    if o1 == 0 and _on_segment(a1, b1, a2):
        return True
    if o2 == 0 and _on_segment(a1, b2, a2):
        return True
    if o3 == 0 and _on_segment(b1, a1, b2):
        return True
    if o4 == 0 and _on_segment(b1, a2, b2):
        return True
    return False


def _on_segment(
    p: tuple[float, float],
    q: tuple[float, float],
    r: tuple[float, float],
) -> bool:
    return (
        min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
        and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9
    )


# Phase 23 — Explicit API Signatures

@dataclass
class CollisionResult:
    has_collision: bool
    overlap_distance: float
    object_a_index: int
    object_b_index: int
    suggested_nudge: Tuple[float, float]
    time_delta_ms: float


def check_disc_collision(
    p1: Tuple[float, float],
    r1: float,
    p2: Tuple[float, float],
    r2: float,
    margin: float = 2.0
) -> Tuple[bool, float]:
    """Determines spatial overlap between two hit discs."""
    dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if dist < (r1 + r2 + margin):
        return True, (r1 + r2 + margin) - dist
    return False, 0.0


def check_point_to_slider_path(
    point: Tuple[float, float],
    slider_points: List[Tuple[float, float]],
    radius: float,
    margin: float = 2.0
) -> Tuple[bool, float]:
    """Evaluates minimum spatial distance from a circle center to a sampled Bezier slider path."""
    if not slider_points:
        return False, 0.0
    dist = point_polyline_distance(point[0], point[1], slider_points)
    if dist < (radius + margin):
        return True, (radius + margin) - dist
    return False, 0.0


def check_slider_to_slider_collision(
    path_a: List[Tuple[float, float]],
    radius_a: float,
    path_b: List[Tuple[float, float]],
    radius_b: float,
    margin: float = 2.0
) -> Tuple[bool, float]:
    """Evaluates segment-to-segment clearance along two sampled slider paths."""
    if not path_a or not path_b:
        return False, 0.0
    dist = polyline_polyline_distance(path_a, path_b)
    clearance = dist - (radius_a + radius_b + margin)
    if clearance < 0:
        return True, -clearance
    return False, 0.0


def calculate_flow_perpendicular_nudge(
    prev_pos: Tuple[float, float],
    curr_pos: Tuple[float, float],
    nudge_distance: float,
    playfield_bounds: Tuple[float, float] = (512.0, 384.0)
) -> Tuple[float, float]:
    """Calculates a flow-perpendicular nudge vector (-dy, dx) clamped strictly within playfield bounds."""
    dx = curr_pos[0] - prev_pos[0]
    dy = curr_pos[1] - prev_pos[1]
    
    # Perpendicular vector (-dy, dx)
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return (0.0, 0.0)
    
    nx = -dy / length
    ny = dx / length
    
    nudge_x = curr_pos[0] + nx * nudge_distance
    nudge_y = curr_pos[1] + ny * nudge_distance
    
    # Clamp to playfield bounds
    nudge_x = max(0.0, min(playfield_bounds[0], nudge_x))
    nudge_y = max(0.0, min(playfield_bounds[1], nudge_y))
    
    return (nudge_x, nudge_y)


def calculate_time_weighted_clearance(
    spatial_overlap: float,
    delta_time_ms: float,
    time_window_ms: float = 1500.0
) -> float:
    """
    Applies time-weighted clearance dampening:
    If delta_time_ms >= 1500ms, spatial overlap is allowed (intentional re-use of playfield space).
    If delta_time_ms < 1500ms, clearance severity scales inversely with delta_time_ms.
    """
    if delta_time_ms >= time_window_ms:
        return 0.0
    time_factor = 1.0 - (delta_time_ms / time_window_ms)
    return spatial_overlap * time_factor
