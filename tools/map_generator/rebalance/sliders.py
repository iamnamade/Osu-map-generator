from __future__ import annotations

import copy
from typing import Any

from ..difficulty.common import clamp
from .models import SectionQuality, SliderAdjustment

_MAX_SLIDER_VELOCITY_PPS = 380.0
_MAX_PIXEL_LENGTH_PX = 460.0
_MIN_PIXEL_LENGTH_PX = 60.0


def optimize_sliders(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    issues: list[Any],
    difficulty: str = "normal",
    max_adjustments: int = 6,
) -> tuple[dict[str, Any], list[SliderAdjustment]]:
    """Optimize sliders: repeat count, velocity consistency, and curve shape.

    Musical timing (``time``/``endTime``) is never changed.
    """
    repeat_limit = {"easy": 1, "normal": 2, "hard": 2}.get(difficulty, 2)
    flagged_sections = {
        issue.section_label
        for issue in issues
        if issue.code in ("POOR_SLIDER_USAGE", "STREAM_OVERLOAD", "DIFFICULTY_SPIKE")
    }

    objects = map_dict.get("objects")
    if not isinstance(objects, list):
        return map_dict, []

    adjustments: list[SliderAdjustment] = []
    for item in objects:
        if len(adjustments) >= max_adjustments:
            break
        if not isinstance(item, dict) or item.get("type") != "slider":
            continue
        object_id = int(item["id"])
        time = int(item.get("time", 0))
        end_time = int(item.get("endTime", time + 1))
        repeats = int(item.get("repeats") or 1)
        pixel_length = float(item.get("pixelLength") or 100.0)
        control_points = item.get("controlPoints")
        section_label = _section_label_for_time(sections, time)

        duration_ms = max(1, end_time - time)

        # --- Repeat count simplification ------------------------------------
        if repeats > repeat_limit:
            adjustments.append(
                SliderAdjustment(
                    object_id=object_id,
                    action="simplify_repeats",
                    reason=f"Slider uses {repeats} repeats; the {difficulty} limit is {repeat_limit}.",
                    before={"repeats": repeats},
                    after={"repeats": repeat_limit},
                    section_label=section_label,
                )
            )
            repeats = repeat_limit

        # --- Velocity / length consistency ----------------------------------
        velocity_pps = pixel_length / (duration_ms / 1000.0)
        if velocity_pps > _MAX_SLIDER_VELOCITY_PPS and duration_ms >= 500:
            reduced = clamp(
                int(_MAX_SLIDER_VELOCITY_PPS * (duration_ms / 1000.0) * 0.85),
                _MIN_PIXEL_LENGTH_PX,
                _MAX_PIXEL_LENGTH_PX,
            )
            adjustments.append(
                SliderAdjustment(
                    object_id=object_id,
                    action="velocity_consistency",
                    reason=(
                        f"Slider velocity {velocity_pps:.0f}px/s exceeds the "
                        f"{_MAX_SLIDER_VELOCITY_PPS:.0f}px/s limit."
                    ),
                    before={"pixelLength": int(pixel_length)},
                    after={"pixelLength": int(reduced)},
                    section_label=section_label,
                )
            )
            pixel_length = float(reduced)

        # --- Curve smoothing -------------------------------------------------
        if (
            isinstance(control_points, list)
            and len(control_points) >= 4
            and section_label in flagged_sections
        ):
            smoothed = _smooth_control_points(control_points)
            if smoothed is not None and smoothed != _points_as_tuples(control_points):
                adjustments.append(
                    SliderAdjustment(
                        object_id=object_id,
                        action="curve_smoothing",
                        reason="Erratic control points produce an unreadable curve shape.",
                        before={"controlPoints": len(control_points)},
                        after={"controlPoints": len(smoothed)},
                        section_label=section_label,
                    )
                )
                control_points = [
                    {"x": point[0], "y": point[1]} for point in smoothed
                ]

    if not adjustments:
        return map_dict, []

    adjusted = copy.deepcopy(map_dict)
    by_id = {
        int(obj["id"]): obj
        for obj in adjusted.get("objects", [])
        if isinstance(obj, dict) and isinstance(obj.get("id"), (int, float))
    }
    for adjustment in adjustments:
        target = by_id.get(adjustment.object_id)
        if target is None:
            continue
        for key, value in adjustment.after.items():
            if key == "controlPoints":
                continue
            target[key] = value
        if "controlPoints" in adjustment.after:
            existing = target.get("controlPoints")
            if isinstance(existing, list) and len(existing) >= 4:
                points = _points_as_tuples(existing)
                smoothed = _smooth_control_points(points)
                if smoothed is not None:
                    target["controlPoints"] = [
                        {"x": round(point[0]), "y": round(point[1])}
                        for point in smoothed
                    ]
    return adjusted, adjustments


def _smooth_control_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]] | None:
    if len(points) < 4:
        return None
    middle = points[1:-1]
    centroid = (
        sum(point[0] for point in middle) / len(middle),
        sum(point[1] for point in middle) / len(middle),
    )
    return [points[0], (round(centroid[0]), round(centroid[1])), points[-1]]


def _points_as_tuples(points: Any) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            output.append((float(x), float(y)))
    return output


def _section_label_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> str:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section.label
    return ""
