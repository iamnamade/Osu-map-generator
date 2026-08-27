from __future__ import annotations

import copy
from typing import Any

from ..difficulty.common import clamp
from .flow import pair_distance
from .models import SectionQuality, SpinnerAdjustment

_MAX_SPINNER_DURATION_MS = 2600
_MIN_SPINNER_DURATION_MS = 800
_MIN_SPINNER_REPLACE_MS = 400
_SPINNERS_PER_SECTION_LIMIT = 2

_PLAYFIELD_X_MIN = 30.0
_PLAYFIELD_X_MAX = 482.0
_PLAYFIELD_Y_MIN = 30.0
_PLAYFIELD_Y_MAX = 354.0


def optimize_spinners(
    *,
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
    issues: list[Any],
    difficulty: str = "normal",
    max_adjustments: int = 4,
) -> tuple[dict[str, Any], list[SpinnerAdjustment]]:
    """Evaluate every spinner and keep/shorten/extend/replace/remove it.

    Deterministic: every decision is a pure function of the spinner's own
    geometry, the section it lives in, and the flagged issues. Musical timing
    (start time) is preserved; only ``endTime`` and object type change.
    """
    objects = map_dict.get("objects")
    if not isinstance(objects, list):
        return map_dict, []

    overuse_sections = {
        issue.section_label
        for issue in issues
        if issue.code == "SPINNER_OVERUSE"
    }
    anchored = _positioned_objects(map_dict)

    spinners = [
        item
        for item in objects
        if isinstance(item, dict) and item.get("type") == "spinner"
    ]
    spinners.sort(key=lambda item: int(item.get("time", 0)))

    section_counts: dict[str, int] = {}
    for item in spinners:
        section_label = _section_label_for_time(sections, int(item.get("time", 0)))
        section_counts[section_label] = section_counts.get(section_label, 0) + 1

    adjustments: list[SpinnerAdjustment] = []
    for item in spinners:
        if len(adjustments) >= max_adjustments:
            break
        object_id = int(item["id"])
        start = int(item.get("time", 0))
        end = int(item.get("endTime", start))
        duration = max(0, end - start)
        section_label = _section_label_for_time(sections, start)
        section = _section_for_time(sections, start)
        section_is_sparse = (
            section is not None and section.density < 0.7
        ) if section is not None else True
        overused = (
            section_label in overuse_sections
            or section_counts.get(section_label, 0) > _SPINNERS_PER_SECTION_LIMIT
        )

        # 1. Remove: sub-100ms spinners are meaningless and always pointless.
        if duration < 100:
            adjustments.append(
                SpinnerAdjustment(
                    object_id=object_id,
                    action="remove",
                    reason=f"Spinner lasting {duration}ms provides no challenge.",
                    before={"endTime": end},
                    after={"endTime": start},
                    section_label=section_label,
                )
            )
            continue

        # 2. Replace: very short spinners in overused sections become a circle
        #    anchored to the previous positioned object (deterministic offset).
        if (
            duration < _MIN_SPINNER_REPLACE_MS
            and overused
            and anchored
            and _anchor_position(anchored, item) is not None
        ):
            position = _anchor_position(anchored, item)
            adjustments.append(
                SpinnerAdjustment(
                    object_id=object_id,
                    action="replace_with_circle",
                    reason=(
                        f"Spinner lasting {duration}ms barely registers; replacing "
                        "it with a circle keeps rhythm without spinner overuse."
                    ),
                    before={"endTime": end},
                    after={"endTime": end},
                    section_label=section_label,
                )
            )
            continue

        # 3. Shorten: long spinners are penalized when the section is overused.
        if overused and duration > _MAX_SPINNER_DURATION_MS:
            new_end = start + _MAX_SPINNER_DURATION_MS
            adjustments.append(
                SpinnerAdjustment(
                    object_id=object_id,
                    action="shorten",
                    reason=(
                        f"Spinner of {duration}ms exceeds the {_MAX_SPINNER_DURATION_MS}ms "
                        "limit; shortening reduces spinner overuse."
                    ),
                    before={"endTime": end},
                    after={"endTime": new_end},
                    section_label=section_label,
                )
            )
            continue

        # 4. Extend: spinners shorter than a beat in sparse sections underuse
        #    the rest opportunity.
        if (
            duration < _MIN_SPINNER_DURATION_MS
            and section_is_sparse
            and not overused
        ):
            new_end = start + _MIN_SPINNER_DURATION_MS
            adjustments.append(
                SpinnerAdjustment(
                    object_id=object_id,
                    action="extend",
                    reason=(
                        f"Spinner of {duration}ms is shorter than the {_MIN_SPINNER_DURATION_MS}ms "
                        "minimum; extending improves the rest window in a sparse section."
                    ),
                    before={"endTime": end},
                    after={"endTime": new_end},
                    section_label=section_label,
                )
            )

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
        if adjustment.action == "replace_with_circle":
            position = _anchor_position(anchored, target)
            if position is None:
                continue
            target["type"] = "circle"
            target["x"] = int(position[0])
            target["y"] = int(position[1])
            target.pop("endTime", None)
            continue
        if adjustment.action == "remove":
            # Removal keeps the object slot but collapses the duration to the
            # start instant so the spinner no longer occupies play time.
            target["endTime"] = int(round(adjustment.after["endTime"]))
            continue
        target["endTime"] = int(round(adjustment.after["endTime"]))
        # Enforce strict endTime > time for valid spinners.
        start_val = int(round(target.get("time", 0)))
        if target["endTime"] <= start_val:
            target["endTime"] = start_val + _MIN_SPINNER_DURATION_MS
    return adjusted, adjustments


def _anchor_position(
    positioned: list[dict[str, Any]],
    item: dict[str, Any],
) -> tuple[float, float] | None:
    """Deterministic circle placement for spinner replacement.

    Uses the previous positioned object plus a fixed offset that depends only
    on the spinner's id parity — never randomness.
    """
    time = int(item.get("time", 0))
    previous = None
    for candidate in positioned:
        if int(candidate["time"]) < time:
            previous = candidate
        else:
            break
    if previous is None:
        return None
    x = float(previous["x"]) + (80.0 if int(item["id"]) % 2 == 0 else -80.0)
    y = float(previous["y"]) + (50.0 if int(item["id"]) % 3 == 0 else -50.0)
    x = clamp(x, _PLAYFIELD_X_MIN, _PLAYFIELD_X_MAX)
    y = clamp(y, _PLAYFIELD_Y_MIN, _PLAYFIELD_Y_MAX)
    if pair_distance(previous, {"x": x, "y": y}) < 30.0:
        return None
    return (round(x), round(y))


def _section_label_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> str:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section.label
    return ""


def _section_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> SectionQuality | None:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section
    return None


def _positioned_objects(map_dict: dict[str, Any]) -> list[dict[str, Any]]:
    objects = map_dict.get("objects")
    if not isinstance(objects, list):
        return []
    positioned = [
        item
        for item in objects
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("x"), (int, float))
        and isinstance(item.get("y"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item.get("time", 0)), int(item.get("id", 0))))
    return positioned
