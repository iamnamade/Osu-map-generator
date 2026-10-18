from __future__ import annotations

import math
from typing import Any

from ..position_generator import PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from ..utils import clamp
from .slider_models import ControlPoint, SliderPathType


def generate_linear_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
) -> list[ControlPoint]:
    """Generate a linear slider path.

    Linear paths consist of the start point and exactly one control point
    (which defines the end). osu! format: start is implicit, only end CP.
    """
    return [ControlPoint(x=end_x, y=end_y)]


def generate_bezier_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    curvature: float = 0.3,
    segments: int = 3,
) -> list[ControlPoint]:
    """Generate a bezier slider path with intermediate control points.

    Args:
        start_x, start_y: Starting position
        end_x, end_y: Ending position
        curvature: How much the curve bends (0=straight, >0=more curve)
        segments: Number of bezier curve segments (1=simple, >1=complex)

    Returns control points (excluding the implicit start point).
    osu! bezier format: consecutive control points form curves,
    with red anchor points (duplicated) at segment boundaries.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    angle = math.atan2(dy, dx)
    perp_angle = angle + math.pi / 2

    points: list[ControlPoint] = []
    for i in range(segments):
        t = (i + 1) / segments
        mid_x = start_x + dx * (t - 0.5 / segments)
        mid_y = start_y + dy * (t - 0.5 / segments)

        # Add curvature perpendicular to the main direction
        curve_strength = curvature * distance * 0.3 * math.sin(t * math.pi)
        cp_x = int(round(mid_x + math.cos(perp_angle) * curve_strength))
        cp_y = int(round(mid_y + math.sin(perp_angle) * curve_strength))

        cp_x = clamp(cp_x, 0, PLAYFIELD_WIDTH)
        cp_y = clamp(cp_y, 0, PLAYFIELD_HEIGHT)
        points.append(ControlPoint(x=cp_x, y=cp_y))

    # Add end point as final control point
    points.append(ControlPoint(x=end_x, y=end_y))
    return points


def generate_perfect_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    arc_height_ratio: float = 0.2,
) -> list[ControlPoint]:
    """Generate a perfect (circular arc) slider path.

    Uses exactly two control points: the arc midpoint and the end point.
    For osu! perfect curves, exactly 3 points (start + 2 CPs) define
    a circular arc. Falls back to bezier if points are collinear.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    angle = math.atan2(dy, dx)
    perp_angle = angle + math.pi / 2

    # Compute arc midpoint with controlled height
    arc_height = distance * arc_height_ratio
    mid_x = int(round((start_x + end_x) / 2 + math.cos(perp_angle) * arc_height))
    mid_y = int(round((start_y + end_y) / 2 + math.sin(perp_angle) * arc_height))
    mid_x = clamp(mid_x, 0, PLAYFIELD_WIDTH)
    mid_y = clamp(mid_y, 0, PLAYFIELD_HEIGHT)

    return [
        ControlPoint(x=mid_x, y=mid_y),
        ControlPoint(x=end_x, y=end_y),
    ]


def generate_catmull_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    smoothness: float = 0.5,
) -> list[ControlPoint]:
    """Generate a catmull-rom slider path.

    Catmull paths create smooth curves through all control points.
    More intermediate points = more complex path.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    angle = math.atan2(dy, dx)
    perp_angle = angle + math.pi / 2

    points: list[ControlPoint] = []

    # 2-3 intermediate control points for smooth catmull curves
    num_intermediate = 2 if smoothness < 0.5 else 3
    for i in range(1, num_intermediate + 1):
        t = i / (num_intermediate + 1)
        wave = smoothness * 0.5 * math.sin(t * math.pi * 2)
        cp_x = int(round(start_x + dx * t + math.cos(perp_angle) * distance * wave))
        cp_y = int(round(start_y + dy * t + math.sin(perp_angle) * distance * wave))
        cp_x = clamp(cp_x, 0, PLAYFIELD_WIDTH)
        cp_y = clamp(cp_y, 0, PLAYFIELD_HEIGHT)
        points.append(ControlPoint(x=cp_x, y=cp_y))

    points.append(ControlPoint(x=end_x, y=end_y))
    return points


def generate_shape_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    shape: str,
    *,
    flow_in_deg: float | None = None,
    flow_out_deg: float | None = None,
    curvature: float = 0.3,
) -> tuple[SliderPathType, list[ControlPoint]]:
    """Generate control points for an expressive slider shape family.

    Phase 21 shape engine. All shapes are deterministic functions of their
    inputs (position, flow angles, curvature) so identical audio + seed +
    config always reproduce identical slider geometry.

    Returns ``(path_type, control_points)`` where multi-segment shapes emit
    red-anchor (duplicated) control points in osu! bezier format.
    """
    if shape == "linear":
        return "linear", generate_linear_path(start_x, start_y, end_x, end_y)
    if shape == "arc":
        arc_height = 0.12 + curvature * 0.25
        return "perfect", generate_perfect_path(
            start_x, start_y, end_x, end_y, arc_height_ratio=arc_height
        )
    if shape == "wave":
        return "bezier", generate_wave_path(
            start_x, start_y, end_x, end_y, curvature=curvature
        )
    if shape == "hook":
        return "bezier", generate_hook_path(
            start_x, start_y, end_x, end_y,
            flow_in_deg=flow_in_deg,
            flow_out_deg=flow_out_deg,
            curvature=curvature,
        )
    if shape == "zigzag":
        return "bezier", generate_zigzag_path(
            start_x, start_y, end_x, end_y, curvature=curvature
        )
    if shape == "loop":
        return "bezier", generate_loop_path(
            start_x, start_y, end_x, end_y,
            flow_in_deg=flow_in_deg,
            curvature=curvature,
        )
    # Unknown shape falls back to a simple curve (deterministic).
    return "bezier", generate_bezier_path(
        start_x, start_y, end_x, end_y, curvature=curvature
    )


def generate_wave_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    curvature: float = 0.3,
) -> list[ControlPoint]:
    """Generate an S-curve (two bezier segments joined by a red anchor)."""
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    angle = math.atan2(dy, dx)
    perp = angle + math.pi / 2
    amp = distance * (0.18 + curvature * 0.22)

    def offset(t: float, side: float) -> tuple[float, float]:
        px = start_x + dx * t + math.cos(perp) * amp * side
        py = start_y + dy * t + math.sin(perp) * amp * side
        return (
            clamp(int(round(px)), 0, PLAYFIELD_WIDTH),
            clamp(int(round(py)), 0, PLAYFIELD_HEIGHT),
        )

    c1 = offset(0.3, 1.0)
    mid = offset(0.5, 0.0)
    c2 = offset(0.7, -1.0)

    # Red anchor at the midpoint: [C1, M, M, C2, E]
    return [
        ControlPoint(x=c1[0], y=c1[1]),
        ControlPoint(x=mid[0], y=mid[1]),
        ControlPoint(x=mid[0], y=mid[1]),
        ControlPoint(x=c2[0], y=c2[1]),
        ControlPoint(x=end_x, y=end_y),
    ]


def generate_hook_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    *,
    flow_in_deg: float | None,
    flow_out_deg: float | None,
    curvature: float = 0.3,
) -> list[ControlPoint]:
    """Generate a flow-aligned hook (cubic bezier).

    The curve starts heading along the incoming cursor flow and finishes
    heading along the outgoing flow, so the slider continues the player's
    motion instead of fighting it.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    straight = math.atan2(dy, dx)
    flow_in = math.radians(flow_in_deg) if flow_in_deg is not None else straight
    flow_out = math.radians(flow_out_deg) if flow_out_deg is not None else straight

    stretch = 0.8 + curvature * 0.6
    c1_len = distance * 0.35 * stretch
    c2_len = distance * 0.35 * stretch
    c1 = (
        clamp(int(round(start_x + math.cos(flow_in) * c1_len)), 0, PLAYFIELD_WIDTH),
        clamp(int(round(start_y + math.sin(flow_in) * c1_len)), 0, PLAYFIELD_HEIGHT),
    )
    c2 = (
        clamp(int(round(end_x - math.cos(flow_out) * c2_len)), 0, PLAYFIELD_WIDTH),
        clamp(int(round(end_y - math.sin(flow_out) * c2_len)), 0, PLAYFIELD_HEIGHT),
    )
    return [
        ControlPoint(x=c1[0], y=c1[1]),
        ControlPoint(x=c2[0], y=c2[1]),
        ControlPoint(x=end_x, y=end_y),
    ]


def generate_zigzag_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    curvature: float = 0.3,
) -> list[ControlPoint]:
    """Generate a W-shaped zigzag (three bezier segments, red anchors)."""
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [ControlPoint(x=end_x, y=end_y)]

    angle = math.atan2(dy, dx)
    perp = angle + math.pi / 2
    amp = distance * (0.08 + curvature * 0.14)

    def offset(t: float, side: float) -> tuple[float, float]:
        px = start_x + dx * t + math.cos(perp) * amp * side
        py = start_y + dy * t + math.sin(perp) * amp * side
        return (
            clamp(int(round(px)), 0, PLAYFIELD_WIDTH),
            clamp(int(round(py)), 0, PLAYFIELD_HEIGHT),
        )

    c1 = offset(0.25, 1.0)
    a1 = offset(0.33, 0.0)
    c2 = offset(0.50, -1.0)
    a2 = offset(0.66, 0.0)
    c3 = offset(0.75, 1.0)

    return [
        ControlPoint(x=c1[0], y=c1[1]),
        ControlPoint(x=a1[0], y=a1[1]),
        ControlPoint(x=a1[0], y=a1[1]),
        ControlPoint(x=c2[0], y=c2[1]),
        ControlPoint(x=a2[0], y=a2[1]),
        ControlPoint(x=a2[0], y=a2[1]),
        ControlPoint(x=c3[0], y=c3[1]),
        ControlPoint(x=end_x, y=end_y),
    ]


def generate_loop_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    *,
    flow_in_deg: float | None,
    curvature: float = 0.3,
) -> list[ControlPoint]:
    """Generate a loop-de-loop (three cubic arc segments + short exit).

    The loop sweeps 1.5 turns around a small circle sitting on the incoming
    flow side, then exits to the end point. Kept small and playfield-safe so
    it stays playable on hard difficulty.
    """
    dx = end_x - start_x
    dy = end_y - start_y
    distance = math.hypot(dx, dy)
    if distance < 30:
        # Too short to loop meaningfully; fall back to a flow hook.
        return generate_hook_path(
            start_x, start_y, end_x, end_y,
            flow_in_deg=flow_in_deg,
            flow_out_deg=flow_in_deg,
            curvature=curvature,
        )

    straight = math.atan2(dy, dx)
    flow_in = math.radians(flow_in_deg) if flow_in_deg is not None else straight
    radius = clamp(distance * 0.3, 18.0, 70.0)

    center_x = start_x + math.cos(flow_in) * radius
    center_y = start_y + math.sin(flow_in) * radius
    center_x = clamp(center_x, radius + 4, PLAYFIELD_WIDTH - radius - 4)
    center_y = clamp(center_y, radius + 4, PLAYFIELD_HEIGHT - radius - 4)

    # Compute the start angle from the (possibly clamped) center so the first
    # arc starts exactly at the slider start position.
    theta0 = math.atan2(start_y - center_y, start_x - center_x)
    # Three 180-degree arcs = 1.5 turns (540 degrees).
    arc_deg = 180.0
    arc = math.radians(arc_deg)
    k = 4.0 / 3.0 * math.tan(arc / 4.0)  # 1.333... for 180-degree arcs

    def point_at(theta: float) -> tuple[int, int]:
        return (
            clamp(int(round(center_x + radius * math.cos(theta))), 0, PLAYFIELD_WIDTH),
            clamp(int(round(center_y + radius * math.sin(theta))), 0, PLAYFIELD_HEIGHT),
        )

    control_points: list[ControlPoint] = []
    prev_theta = theta0
    prev_point = (start_x, start_y)
    for index in range(3):
        next_theta = prev_theta + arc
        next_point = point_at(next_theta)
        # Tangents (counter-clockwise sweep): (-sin, cos)
        tangent_in = (-math.sin(prev_theta), math.cos(prev_theta))
        tangent_out = (-math.sin(next_theta), math.cos(next_theta))
        cp1 = (
            clamp(int(round(prev_point[0] + tangent_in[0] * k * radius)), 0, PLAYFIELD_WIDTH),
            clamp(int(round(prev_point[1] + tangent_in[1] * k * radius)), 0, PLAYFIELD_HEIGHT),
        )
        cp2 = (
            clamp(int(round(next_point[0] - tangent_out[0] * k * radius)), 0, PLAYFIELD_WIDTH),
            clamp(int(round(next_point[1] - tangent_out[1] * k * radius)), 0, PLAYFIELD_HEIGHT),
        )
        control_points.append(ControlPoint(x=cp1[0], y=cp1[1]))
        control_points.append(ControlPoint(x=cp2[0], y=cp2[1]))
        control_points.append(ControlPoint(x=next_point[0], y=next_point[1]))
        control_points.append(ControlPoint(x=next_point[0], y=next_point[1]))
        prev_theta = next_theta
        prev_point = next_point

    # Exit segment from the loop end to the target end point.
    exit_dx = end_x - prev_point[0]
    exit_dy = end_y - prev_point[1]
    exit_len = math.hypot(exit_dx, exit_dy)
    if exit_len > 1:
        exit_cp = (
            clamp(int(round(prev_point[0] + exit_dx * 0.4)), 0, PLAYFIELD_WIDTH),
            clamp(int(round(prev_point[1] + exit_dy * 0.4)), 0, PLAYFIELD_HEIGHT),
        )
        control_points.append(ControlPoint(x=exit_cp[0], y=exit_cp[1]))
    control_points.append(ControlPoint(x=end_x, y=end_y))
    return control_points


def path_start_direction(
    start_x: int,
    start_y: int,
    control_points: list[ControlPoint],
    path_type: SliderPathType,
) -> float | None:
    """Return the path's initial tangent direction (degrees, atan2)."""
    sampled = sample_path_points(start_x, start_y, control_points, path_type, 24)
    if len(sampled) < 2:
        return None
    p0 = sampled[0]
    p1 = sampled[1]
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 0.5:
        return None
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def path_end_direction(
    start_x: int,
    start_y: int,
    control_points: list[ControlPoint],
    path_type: SliderPathType,
) -> float | None:
    """Return the path's final tangent direction (degrees, atan2)."""
    sampled = sample_path_points(start_x, start_y, control_points, path_type, 24)
    if len(sampled) < 2:
        return None
    p0 = sampled[-2]
    p1 = sampled[-1]
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 0.5:
        return None
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def compute_slider_length(
    control_points: list[ControlPoint],
    start_x: int,
    start_y: int,
    path_type: SliderPathType,
    num_samples: int = 100,
) -> float:
    """Compute the pixel length of a slider path by sampling.

    Approximates the path length by sampling points along the curve
    and summing the distances between consecutive samples.
    """
    if not control_points:
        return 0.0

    # Sample the path and compute cumulative length
    path_points = sample_path_points(
        start_x, start_y, control_points, path_type, num_samples
    )
    total_length = 0.0
    for i in range(1, len(path_points)):
        dx = path_points[i][0] - path_points[i - 1][0]
        dy = path_points[i][1] - path_points[i - 1][1]
        total_length += math.hypot(dx, dy)

    return total_length


def sample_path_points(
    start_x: int,
    start_y: int,
    control_points: list[ControlPoint],
    path_type: SliderPathType,
    num_samples: int = 50,
) -> list[tuple[float, float]]:
    """Sample points along a slider path for rendering/length calculation."""
    if path_type == "linear":
        return _sample_linear(start_x, start_y, control_points, num_samples)
    elif path_type == "bezier":
        return _sample_bezier(start_x, start_y, control_points, num_samples)
    elif path_type == "perfect":
        return _sample_perfect(start_x, start_y, control_points, num_samples)
    elif path_type == "catmull":
        return _sample_catmull(start_x, start_y, control_points, num_samples)
    return [(float(start_x), float(start_y))]


def _sample_linear(
    start_x: int, start_y: int,
    control_points: list[ControlPoint],
    num_samples: int,
) -> list[tuple[float, float]]:
    if not control_points:
        return [(float(start_x), float(start_y))]
    end = control_points[-1]
    points: list[tuple[float, float]] = []
    for i in range(num_samples):
        t = i / max(1, num_samples - 1)
        x = start_x + (end.x - start_x) * t
        y = start_y + (end.y - start_y) * t
        points.append((x, y))
    return points


def _sample_bezier(
    start_x: int, start_y: int,
    control_points: list[ControlPoint],
    num_samples: int,
) -> list[tuple[float, float]]:
    """Sample a bezier path, honoring red anchors.

    A red anchor (two consecutive identical control points) splits the
    path into independent bezier segments — this is how multi-segment
    Phase 21 sliders (wave, zigzag, loop) are represented in osu! format.
    Paths without duplicate points sample as a single curve (legacy
    behavior is unchanged).
    """
    if not control_points:
        return [(float(start_x), float(start_y))]

    all_pts = [(float(start_x), float(start_y))] + [
        (float(cp.x), float(cp.y)) for cp in control_points
    ]

    # Split at red anchors.
    segments: list[list[tuple[float, float]]] = []
    current = [all_pts[0]]
    for index in range(1, len(all_pts)):
        if all_pts[index] == all_pts[index - 1]:
            current.append(all_pts[index])
            segments.append(current)
            current = [all_pts[index]]
        else:
            current.append(all_pts[index])
    if current:
        segments.append(current)

    points: list[tuple[float, float]] = []
    samples_per_segment = max(4, num_samples // max(1, len(segments)))
    for segment in segments:
        # Split the segment into flat coordinate lists once: _de_casteljau rebuilds a list
        # of tuples per sample, which dominated slider build time (78 calls per slider).
        xs = [point[0] for point in segment]
        ys = [point[1] for point in segment]
        for i in range(samples_per_segment):
            t = i / max(1, samples_per_segment - 1)
            points.append(_de_casteljau_coords(xs, ys, t))
    return points


def _de_casteljau_coords(
    xs: list[float],
    ys: list[float],
    t: float,
) -> tuple[float, float]:
    """De Casteljau evaluation on flat coordinate lists.

    Bit-for-bit the same arithmetic as :func:`_de_casteljau` (same operation order), but
    it works on two float lists instead of rebuilding a list of tuples for every step.
    """
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (xs[0], ys[0])
    px = list(xs)
    py = list(ys)
    while n > 1:
        for i in range(n - 1):
            px[i] = px[i] + (px[i + 1] - px[i]) * t
            py[i] = py[i] + (py[i + 1] - py[i]) * t
        n -= 1
    return (px[0], py[0])


def _sample_perfect(
    start_x: int, start_y: int,
    control_points: list[ControlPoint],
    num_samples: int,
) -> list[tuple[float, float]]:
    if len(control_points) < 2:
        return _sample_linear(start_x, start_y, control_points, num_samples)

    # Perfect curves use 3 points (start + 2 CPs) for circular arc
    p1 = (float(start_x), float(start_y))
    p2 = (float(control_points[0].x), float(control_points[0].y))
    p3 = (float(control_points[1].x), float(control_points[1].y))

    # Compute circle from 3 points
    try:
        ax, ay = p1
        bx, by = p2
        cx, cy = p3
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 0.001:
            return _sample_bezier(start_x, start_y, control_points, num_samples)

        ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d
        uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d
        center = (ux, uy)
        radius = math.hypot(ax - ux, ay - uy)

        # Compute start and end angles
        start_angle = math.atan2(ay - uy, ax - ux)
        end_angle = math.atan2(cy - uy, cx - ux)

        # Determine direction (clockwise vs counter-clockwise) from the side the
        # midpoint lies on, then walk a single consistent signed sweep. The previous
        # branch could pick the wrong sweep sign and sample the *long* way round,
        # inflating arc length by up to ~2.8x.
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        sweep = end_angle - start_angle
        if cross < 0:  # clockwise
            if sweep > 0:
                sweep -= 2 * math.pi
        elif sweep < 0:  # counter-clockwise
            sweep += 2 * math.pi

        points: list[tuple[float, float]] = []
        for i in range(num_samples):
            t = i / max(1, num_samples - 1)
            angle = start_angle + sweep * t
            points.append((
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
            ))
        return points
    except (ZeroDivisionError, ValueError):
        return _sample_bezier(start_x, start_y, control_points, num_samples)


def _sample_catmull(
    start_x: int, start_y: int,
    control_points: list[ControlPoint],
    num_samples: int,
) -> list[tuple[float, float]]:
    all_pts = [(float(start_x), float(start_y))] + [
        (float(cp.x), float(cp.y)) for cp in control_points
    ]
    if len(all_pts) < 3:
        return _sample_linear(start_x, start_y, control_points, num_samples)

    points: list[tuple[float, float]] = []
    segments_count = len(all_pts) - 1
    samples_per_segment = max(2, num_samples // segments_count)

    for seg in range(segments_count):
        p0 = all_pts[max(0, seg - 1)]
        p1 = all_pts[seg]
        p2 = all_pts[min(seg + 1, len(all_pts) - 1)]
        p3 = all_pts[min(seg + 2, len(all_pts) - 1)]

        for j in range(samples_per_segment):
            t = j / max(1, samples_per_segment - 1)
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                2 * p1[0] + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1] + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            points.append((x, y))

    return points


def _de_casteljau(
    points: list[tuple[float, float]],
    t: float,
) -> tuple[float, float]:
    """Evaluate a bezier curve at parameter t using De Casteljau's algorithm."""
    pts = list(points)
    while len(pts) > 1:
        new_pts = []
        for i in range(len(pts) - 1):
            x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
            y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
            new_pts.append((x, y))
        pts = new_pts
    return pts[0] if pts else (0.0, 0.0)


def evaluate_path_smoothness(
    control_points: list[ControlPoint],
    start_x: int,
    start_y: int,
    path_type: SliderPathType,
) -> float:
    """Evaluate how smooth a slider path is (0-100, higher = smoother).

    Considers:
    - Angle changes between consecutive segments
    - Self-intersections
    - Extreme curvature changes
    """
    sampled = sample_path_points(start_x, start_y, control_points, path_type, 30)
    if len(sampled) < 4:
        return 100.0

    score = 100.0

    # Check angle changes
    for i in range(2, len(sampled) - 1):
        v1 = (sampled[i][0] - sampled[i - 1][0], sampled[i][1] - sampled[i - 1][1])
        v2 = (sampled[i + 1][0] - sampled[i][0], sampled[i + 1][1] - sampled[i][1])
        v1_len = math.hypot(*v1)
        v2_len = math.hypot(*v2)
        if v1_len > 0 and v2_len > 0:
            dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (v1_len * v2_len)
            angle = math.acos(clamp(dot, -1.0, 1.0))
            if math.degrees(angle) > 120:
                score -= 15  # Sharp turn penalty

    # Check self-intersection (crude: check if path crosses itself)
    #
    # This is the O(n^2) innermost loop of the whole slider build, so the oriented-area
    # test is inlined and each candidate pair is rejected by bounding box first. Both
    # changes are exactly equivalent to calling _segments_intersect: two segments whose
    # boxes do not overlap cannot cross, and the orientation signs are unchanged.
    for i in range(2, len(sampled) - 3):
        p1x, p1y = sampled[i]
        p2x, p2y = sampled[i + 1]
        pdx = p2x - p1x
        pdy = p2y - p1y
        p_lo_x = p1x if p1x < p2x else p2x
        p_hi_x = p2x if p1x < p2x else p1x
        p_lo_y = p1y if p1y < p2y else p2y
        p_hi_y = p2y if p1y < p2y else p1y
        for j in range(i + 2, len(sampled) - 1):
            q1x, q1y = sampled[j]
            q2x, q2y = sampled[j + 1]
            if (q1x if q1x > q2x else q2x) < p_lo_x or (q1x if q1x < q2x else q2x) > p_hi_x:
                continue
            if (q1y if q1y > q2y else q2y) < p_lo_y or (q1y if q1y < q2y else q2y) > p_hi_y:
                continue
            o1 = pdx * (q1y - p1y) - pdy * (q1x - p1x)
            o2 = pdx * (q2y - p1y) - pdy * (q2x - p1x)
            if (o1 > 0) == (o2 > 0):
                continue
            qdx = q2x - q1x
            qdy = q2y - q1y
            o3 = qdx * (p1y - q1y) - qdy * (p1x - q1x)
            o4 = qdx * (p2y - q1y) - qdy * (p2x - q1x)
            if (o3 > 0) != (o4 > 0):
                score -= 30
                return max(0.0, score)

    return max(0.0, score)


def _orient2d(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    """Twice the signed area of the triangle (a, b, c); sign gives the turn direction."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """Check if two line segments intersect (excluding shared endpoints)."""
    o1 = _orient2d(p1, p2, q1)
    o2 = _orient2d(p1, p2, q2)
    o3 = _orient2d(q1, q2, p1)
    o4 = _orient2d(q1, q2, p2)

    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)
