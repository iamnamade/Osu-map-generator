"""Phase 23 — Anti-overlap collision validation.

Detects physical overlaps that the structural validator (timestamps only)
cannot see: two discs whose radii intersect, a slider body passing through a
circle, or two slider bodies crossing. All geometry is radius-aware and
deterministic.

Emits ``COLLISION_OVERLAP`` issues with the measured clearance, the allowed
value (sum of radii), and a concrete nudge suggestion. Detection itself lives
in :mod:`..geometry.collision` (``detect_map_overlaps``) so the evolution hard
gate and the rebalancer share the exact same geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..geometry.collision import detect_map_overlaps
from .models import ParsedBeatmap, ValidationIssue

# Margin on top of geometric radii before a pair counts as a collision.
_OVERLAP_MARGIN_PX = 2.0


@dataclass(frozen=True)
class CollisionPair:
    left_id: int
    right_id: int
    kind: str  # disc-disc | disc-slider | slider-slider
    clearance_px: float
    required_px: float
    start_time_ms: int
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "leftId": self.left_id,
            "rightId": self.right_id,
            "kind": self.kind,
            "clearancePx": round(self.clearance_px, 2),
            "requiredPx": round(self.required_px, 2),
            "startTimeMs": self.start_time_ms,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True)
class CollisionValidationResult:
    issues: list[ValidationIssue]
    collisions: list[CollisionPair]
    overlap_count: int
    max_overlap_px: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.to_dict() for issue in self.issues],
            "collisions": [collision.to_dict() for collision in self.collisions],
            "overlapCount": self.overlap_count,
            "maxOverlapPx": round(self.max_overlap_px, 2),
        }


def validate_collisions(
    parsed: ParsedBeatmap,
    *,
    margin_px: float = _OVERLAP_MARGIN_PX,
) -> CollisionValidationResult:
    """Scan the parsed beatmap for physical overlaps.

    Delegates to ``detect_map_overlaps`` (the canonical detector) after
    projecting the parsed objects into raw map JSON shape.
    """
    raw_objects = [object_value.to_dict() for object_value in parsed.objects]
    records = detect_map_overlaps(
        raw_objects,
        float(parsed.circle_radius or 1.0),
        margin_px=margin_px,
    )

    collisions: list[CollisionPair] = []
    issues: list[ValidationIssue] = []
    max_overlap = 0.0
    for record in records:
        pair = CollisionPair(
            left_id=int(record["left_id"]),
            right_id=int(record["right_id"]),
            kind=str(record["kind"]),
            clearance_px=float(record["clearance_px"]),
            required_px=float(record["required_px"]),
            start_time_ms=int(record["start_time_ms"]),
            suggestion=str(record["suggestion"]),
        )
        collisions.append(pair)
        max_overlap = max(max_overlap, abs(pair.clearance_px))
        issues.append(
            ValidationIssue(
                code="COLLISION_OVERLAP",
                severity="error",
                message=pair.suggestion,
                category="movement",
                object_ids=[pair.left_id, pair.right_id],
                start_time_ms=pair.start_time_ms,
                measured_value=round(pair.clearance_px, 2),
                allowed_value=round(pair.required_px, 2),
                suggestion=pair.suggestion,
            )
        )

    return CollisionValidationResult(
        issues=issues,
        collisions=collisions,
        overlap_count=len(collisions),
        max_overlap_px=max_overlap,
    )
