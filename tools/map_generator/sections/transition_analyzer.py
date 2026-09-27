from __future__ import annotations

import math

from ..config import DifficultyPreset
from ..utils import clamp
from .section_models import HybridTransition, MapObject, SongSection


def analyze_transition(
    *,
    boundary_index: int,
    left_section: SongSection,
    right_section: SongSection,
    from_candidate: int,
    to_candidate: int,
    left_objects: list[MapObject],
    right_objects: list[MapObject],
    preset: DifficultyPreset,
) -> HybridTransition:
    left_last = left_objects[-1] if left_objects else None
    right_first = right_objects[0] if right_objects else None
    metrics: dict[str, float | int | str | bool | None] = {
        "timeGapMs": None,
        "distancePx": None,
        "requiredCursorSpeed": None,
        "directionAngleChangeDeg": None,
        "densityBefore": len(left_objects) * 1000 / max(1, left_section.duration_ms),
        "densityAfter": len(right_objects) * 1000 / max(1, right_section.duration_ms),
        "musicalBoundaryStrength": round((left_section.confidence + right_section.confidence) / 2, 4),
        "sameCandidate": from_candidate == to_candidate,
        "patternContinuity": 0.0,
    }
    issues: list[str] = []
    if left_last is None or right_first is None:
        issues.append("missing-boundary-object")
        return HybridTransition(
            boundary_index=boundary_index,
            from_section_id=left_section.id,
            to_section_id=right_section.id,
            from_candidate=from_candidate,
            to_candidate=to_candidate,
            classification="critical",
            score=12.0,
            metrics=metrics,
            issues=issues,
            corrections=[],
        )

    time_gap_ms = right_first.time - left_last.time
    distance_px = math.hypot(right_first.x - left_last.x, right_first.y - left_last.y)
    required_cursor_speed = distance_px * 1000 / max(1, time_gap_ms)
    direction_angle_change = _direction_delta(left_objects, right_objects)
    pattern_continuity = clamp(
        1.0 - abs((len(right_objects) - len(left_objects))) / max(2.0, len(left_objects) + len(right_objects)),
        0.0,
        1.0,
    )
    metrics.update(
        {
            "timeGapMs": time_gap_ms,
            "distancePx": round(distance_px, 4),
            "requiredCursorSpeed": round(required_cursor_speed, 4),
            "directionAngleChangeDeg": round(direction_angle_change, 4) if direction_angle_change is not None else None,
            "patternContinuity": round(pattern_continuity, 4),
            "stackingRisk": distance_px <= max(10.0, preset.circle_radius * 0.4),
            "approachCircleOverlap": distance_px <= preset.circle_radius * 1.4 and time_gap_ms <= preset.approach_time_ms * 0.35,
        }
    )

    if time_gap_ms <= 0:
        issues.append("duplicate-or-reversed-time")
    if required_cursor_speed > preset.max_cursor_speed * 1.12:
        issues.append("excessive-cursor-speed")
    elif required_cursor_speed > preset.max_cursor_speed:
        issues.append("borderline-cursor-speed")
    if distance_px <= max(10.0, preset.circle_radius * 0.4):
        issues.append("stacking-risk")
    if direction_angle_change is not None and direction_angle_change > 175:
        issues.append("direction-reversal")
    density_before = float(metrics["densityBefore"])
    density_after = float(metrics["densityAfter"])
    if density_after > density_before + 0.85:
        issues.append("density-spike")
    if density_before > density_after + 1.0 and right_section.label not in {"break-like", "quiet", "outro-like"}:
        issues.append("density-collapse")

    score = clamp(
        96.0
        - max(0.0, required_cursor_speed - preset.max_cursor_speed) / max(1.0, preset.max_cursor_speed) * 80.0
        - (18.0 if time_gap_ms <= 0 else 0.0)
        - (12.0 if "stacking-risk" in issues else 0.0)
        - (8.0 if "density-spike" in issues else 0.0)
        - (7.0 if "direction-reversal" in issues else 0.0)
        - (1.0 - pattern_continuity) * 18.0,
        0.0,
        100.0,
    )
    if score >= 92.0:
        classification = "excellent"
    elif score >= 80.0:
        classification = "safe"
    elif score >= 65.0:
        classification = "borderline"
    elif score >= 45.0:
        classification = "unsafe"
    else:
        classification = "critical"
    return HybridTransition(
        boundary_index=boundary_index,
        from_section_id=left_section.id,
        to_section_id=right_section.id,
        from_candidate=from_candidate,
        to_candidate=to_candidate,
        classification=classification,
        score=score,
        metrics=metrics,
        issues=issues,
        corrections=[],
    )


def _direction_delta(
    left_objects: list[MapObject],
    right_objects: list[MapObject],
) -> float | None:
    if len(left_objects) < 2 or len(right_objects) < 2:
        return None
    left_angle = math.degrees(
        math.atan2(
            left_objects[-1].y - left_objects[-2].y,
            left_objects[-1].x - left_objects[-2].x,
        )
    )
    right_angle = math.degrees(
        math.atan2(
            right_objects[1].y - right_objects[0].y,
            right_objects[1].x - right_objects[0].x,
        )
    )
    return abs(((right_angle - left_angle + 180.0) % 360.0) - 180.0)
