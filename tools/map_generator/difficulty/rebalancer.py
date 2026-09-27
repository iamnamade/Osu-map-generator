from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .common import clamp
from .loader import LoadedDifficultyMap
from .models import DifficultyTarget, ObjectDifficulty
from .targets import TargetDeviation


@dataclass(frozen=True)
class RebalanceAction:
    action: str
    object_id: int
    reason: str
    before: dict[str, float | int | str | None]
    after: dict[str, float | int | str | None]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "objectId": self.object_id,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
            "confidence": round(self.confidence, 3),
        }


@dataclass(frozen=True)
class RebalancePlan:
    deviation: TargetDeviation
    actions: list[RebalanceAction] = field(default_factory=list)
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "deviation": {
                "direction": self.deviation.direction,
                "starRating": round(self.deviation.star_rating, 3),
                "targetRange": [
                    self.deviation.target.star_range[0],
                    self.deviation.target.star_range[1],
                ],
                "magnitude": round(self.deviation.magnitude, 3),
            },
            "actions": [action.to_dict() for action in self.actions],
            "applied": self.applied,
        }


def plan_rebalancing(
    beatmap: LoadedDifficultyMap,
    *,
    star_rating: float,
    target: DifficultyTarget,
    metrics,
    object_scores: list[ObjectDifficulty],
    seed: int,
    max_actions: int = 12,
) -> RebalancePlan:
    """Build a deterministic set of corrective actions that would move the map
    toward the requested difficulty target. The plan is advisory: actions are
    reported but the generated final maps are never mutated by this engine."""
    if target.star_range[0] <= star_rating <= target.star_range[1]:
        deviation = TargetDeviation(
            star_rating=star_rating,
            target=target,
            direction="within",
            magnitude=0.0,
        )
        return RebalancePlan(deviation=deviation, applied=False)

    if star_rating < target.star_range[0]:
        direction = "below"
        magnitude = (target.star_range[0] - star_rating) / max(1.0, target.star_range[0])
    else:
        direction = "above"
        magnitude = (star_rating - target.star_range[1]) / max(1.0, target.star_range[1])

    deviation = TargetDeviation(
        star_rating=star_rating,
        target=target,
        direction=direction,
        magnitude=magnitude,
    )

    rng = random.Random(seed)
    actions: list[RebalanceAction] = []
    positioned = [item for item in beatmap.objects if item.is_positioned]

    if direction == "above":
        # Reduce jumps: shrink the largest jump distances toward the average.
        oversized = _find_oversized_jumps(beatmap, target)
        for object_id, distance, reduced_distance in oversized:
            if len(actions) >= max_actions:
                break
            if rng.random() > 0.5:
                continue
            obj = next((item for item in positioned if item.id == object_id), None)
            if obj is None or obj.x is None or obj.y is None:
                continue
            previous = _previous_positioned(positioned, object_id)
            if previous is None:
                continue
            before = {"x": obj.x, "y": obj.y}
            after = _shrink_toward(previous, obj, distance, reduced_distance)
            actions.append(
                RebalanceAction(
                    action="reduce_jump",
                    object_id=object_id,
                    reason=f"Jump of {distance:.0f}px exceeds the {target.jump_target:.0f}px target.",
                    before=before,
                    after=after,
                    confidence=0.7,
                )
            )

        # Replace difficult sliders: flag high-complexity sliders.
        for item in beatmap.objects:
            if len(actions) >= max_actions:
                break
            if item.object_type != "slider":
                continue
            if item.repeats is not None and item.repeats > 2:
                actions.append(
                    RebalanceAction(
                        action="simplify_slider",
                        object_id=item.id,
                        reason=f"Slider has {item.repeats} repeats which raises stamina demand.",
                        before={"repeats": item.repeats},
                        after={"repeats": 1},
                        confidence=0.6,
                    )
                )

        # Insert recovery gaps: rest opportunities after the hardest sections.
        recovery_gaps = _find_recovery_gaps(beatmap)
        for gap_start, gap_end in recovery_gaps:
            if len(actions) >= max_actions:
                break
            actions.append(
                RebalanceAction(
                    action="insert_recovery_gap",
                    object_id=gap_end,
                    reason="Insert a rest window after a high-intensity passage.",
                    before={"timeMs": gap_end},
                    after={"timeMs": gap_start + (gap_end - gap_start) // 2},
                    confidence=0.5,
                )
            )
    else:
        # Increase density: add subdivision objects in the largest gaps.
        largest_gaps = _find_largest_gaps(beatmap, target)
        for object_id, gap_ms, insert_time in largest_gaps:
            if len(actions) >= max_actions:
                break
            actions.append(
                RebalanceAction(
                    action="increase_density",
                    object_id=object_id,
                    reason=f"Gap of {gap_ms}ms is under the target density; insert a subdivision object.",
                    before={"timeMs": object_id},
                    after={"timeMs": insert_time},
                    confidence=0.6,
                )
            )

        # Increase movement: push small jumps outward.
        for pair in _find_small_jumps(beatmap, target):
            object_id, distance, enlarged = pair
            if len(actions) >= max_actions:
                break
            obj = next((item for item in positioned if item.id == object_id), None)
            previous = _previous_positioned(positioned, object_id)
            if obj is None or previous is None:
                continue
            before = {"x": obj.x, "y": obj.y}
            after = _enlarge_away(previous, obj, distance, enlarged)
            actions.append(
                RebalanceAction(
                    action="increase_movement",
                    object_id=object_id,
                    reason=f"Jump of {distance:.0f}px is below the {target.jump_target:.0f}px target.",
                    before=before,
                    after=after,
                    confidence=0.6,
                )
            )

    # Deterministic ordering keeps output stable across runs.
    actions.sort(key=lambda action: (action.action, action.object_id))
    return RebalancePlan(deviation=deviation, actions=actions[:max_actions], applied=False)


def _find_oversized_jumps(
    beatmap: LoadedDifficultyMap,
    target: DifficultyTarget,
) -> list[tuple[int, float, float]]:
    positioned = [item for item in beatmap.objects if item.is_positioned]
    results: list[tuple[int, float, float]] = []
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        if left.x is None or left.y is None or right.x is None or right.y is None:
            continue
        distance = math.hypot(right.x - left.x, right.y - left.y)
        if distance > target.jump_target * 1.35:
            reduced = clamp(distance * 0.8, 0.0, target.jump_target * 1.15)
            results.append((right.id, round(distance, 2), round(reduced, 2)))
    return results


def _find_small_jumps(
    beatmap: LoadedDifficultyMap,
    target: DifficultyTarget,
) -> list[tuple[int, float, float]]:
    positioned = [item for item in beatmap.objects if item.is_positioned]
    results: list[tuple[int, float, float]] = []
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        if left.x is None or left.y is None or right.x is None or right.y is None:
            continue
        distance = math.hypot(right.x - left.x, right.y - left.y)
        if 0 < distance < target.jump_target * 0.55:
            enlarged = clamp(distance * 1.25, 0.0, target.jump_target * 0.9)
            results.append((right.id, round(distance, 2), round(enlarged, 2)))
    return results


def _find_recovery_gaps(beatmap: LoadedDifficultyMap) -> list[tuple[int, int]]:
    positioned = [item for item in beatmap.objects if item.is_positioned]
    results: list[tuple[int, int]] = []
    for index in range(1, len(positioned)):
        gap = positioned[index].time - positioned[index - 1].time
        if gap >= 1600:
            results.append((positioned[index - 1].time, positioned[index].time))
    return results


def _find_largest_gaps(
    beatmap: LoadedDifficultyMap,
    target: DifficultyTarget,
) -> list[tuple[int, int, int]]:
    positioned = [item for item in beatmap.objects if item.is_positioned]
    results: list[tuple[int, int, int]] = []
    for index in range(1, len(positioned)):
        gap = positioned[index].time - positioned[index - 1].time
        if gap >= target.density_target * 0.0 + 1500:
            insert_time = positioned[index - 1].time + gap // 2
            results.append((positioned[index].id, gap, insert_time))
    return results


def _previous_positioned(positioned, object_id: int):
    for index, item in enumerate(positioned):
        if item.id == object_id and index > 0:
            return positioned[index - 1]
    return None


def _shrink_toward(previous, obj, distance: float, reduced: float) -> dict[str, float]:
    if distance <= 0 or previous.x is None or previous.y is None or obj.x is None or obj.y is None:
        return {"x": obj.x, "y": obj.y}
    ratio = reduced / distance
    return {
        "x": round(previous.x + (obj.x - previous.x) * ratio, 2),
        "y": round(previous.y + (obj.y - previous.y) * ratio, 2),
    }


def _enlarge_away(previous, obj, distance: float, enlarged: float) -> dict[str, float]:
    if distance <= 0 or previous.x is None or previous.y is None or obj.x is None or obj.y is None:
        return {"x": obj.x, "y": obj.y}
    ratio = enlarged / distance
    return {
        "x": round(previous.x + (obj.x - previous.x) * ratio, 2),
        "y": round(previous.y + (obj.y - previous.y) * ratio, 2),
    }
