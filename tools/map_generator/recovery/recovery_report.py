"""Phase 22 — recovery structure report (persisted for the editor overlay).

Reads a final map JSON plus the phrase report, computes the fatigue profile,
recovery windows, and density harmony, and writes a compact
``recovery-structure.json`` artifact. Fully deterministic: identical inputs
produce identical reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import get_difficulty_preset
from ..utils import write_json
from .recovery_engine import (
    analyze_density_harmony,
    compute_fatigue_profile,
    plan_recovery_windows,
    spinner_guidelines,
)


def analyze_recovery_structure(
    *,
    map_path: Path,
    phrase_report_path: Path | None,
    output_path: Path,
    difficulty: str,
    force: bool = False,
) -> dict[str, Any]:
    """Analyze a final map and persist its recovery structure.

    Args:
        map_path: Final map JSON (generated/improved/champion/hybrid).
        phrase_report_path: Optional phrase-structure.json.
        output_path: Where to write recovery-structure.json.
        difficulty: Difficulty name (easy/normal/hard).
        force: Recompute even when the output already exists.

    Returns:
        The recovery report payload (also written to ``output_path``).
    """
    if output_path.exists() and not force:
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    payload = json.loads(map_path.read_text(encoding="utf-8"))
    objects = payload.get("objects") or []
    preset = get_difficulty_preset(difficulty)

    phrase_info = _load_phrase_info(phrase_report_path)

    # Rebuild light dataclass wrappers so the recovery engine can read
    # positions/times the same way it does during generation.
    wrapped = _wrap_objects(objects)

    fatigue = compute_fatigue_profile(wrapped, preset=preset)
    recovery_windows = plan_recovery_windows(
        wrapped,
        phrase_info=phrase_info,
        fatigue=fatigue,
        preset=preset,
    )
    harmony = analyze_density_harmony(
        wrapped,
        phrase_info=phrase_info,
        difficulty=difficulty,
    )

    guidelines = spinner_guidelines(difficulty)
    spinners = [obj for obj in objects if isinstance(obj, dict) and obj.get("type") == "spinner"]
    spinner_durations = [
        int(item.get("endTime", 0)) - int(item.get("time", 0))
        for item in spinners
        if int(item.get("endTime", 0)) > int(item.get("time", 0))
    ]

    report: dict[str, Any] = {
        "version": 1,
        "difficulty": difficulty,
        "audioDurationMs": int(payload.get("audioDurationMs") or 0),
        "objectCount": len(objects),
        "spinnerCount": len(spinners),
        "avgSpinnerDurationMs": (
            round(sum(spinner_durations) / len(spinner_durations), 2)
            if spinner_durations
            else 0.0
        ),
        "guidelines": guidelines,
        "fatigue": fatigue.to_dict(),
        "recoveryWindows": [window.to_dict() for window in recovery_windows],
        "harmony": harmony,
        "objectTypeCounts": _object_type_counts(objects),
    }
    write_json(output_path, report)
    return report


def _load_phrase_info(phrase_report_path: Path | None) -> list[Any]:
    if phrase_report_path is None or not phrase_report_path.exists():
        return []
    from ..phrase import load_phrase_report, build_phrase_rhythm_info

    try:
        report = load_phrase_report(phrase_report_path)
    except Exception:
        return []
    return build_phrase_rhythm_info(report)


def _wrap_objects(objects: list[dict[str, Any]]) -> list[Any]:
    from ..models import (
        GeneratedCircleHitObject,
        GeneratedSliderHitObject,
        GeneratedSpinnerHitObject,
    )

    wrapped: list[Any] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        object_type = item.get("type")
        if object_type == "spinner":
            # Spinners have no position; they reset cursor speed to zero so
            # they act as natural recovery anchors in the fatigue curve.
            wrapped.append(
                GeneratedSpinnerHitObject(
                    id=int(item.get("id", 0)),
                    type="spinner",
                    time=int(item.get("time", 0)),
                    end_time=int(item.get("endTime", 0)),
                )
            )
        elif object_type == "slider":
            wrapped.append(
                GeneratedSliderHitObject(
                    id=int(item.get("id", 0)),
                    type="slider",
                    x=int(item.get("x", 0)),
                    y=int(item.get("y", 0)),
                    time=int(item.get("time", 0)),
                    end_time=int(item.get("endTime", item.get("time", 0))),
                    path_type="bezier",
                    control_points=[],
                    repeats=1,
                    pixel_length=1,
                )
            )
        else:
            wrapped.append(
                GeneratedCircleHitObject(
                    id=int(item.get("id", 0)),
                    type="circle",
                    x=int(item.get("x", 0)),
                    y=int(item.get("y", 0)),
                    time=int(item.get("time", 0)),
                )
            )
    return wrapped


def _object_type_counts(objects: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"circle": 0, "slider": 0, "spinner": 0}
    for item in objects:
        if isinstance(item, dict):
            object_type = item.get("type")
            if object_type in counts:
                counts[object_type] += 1
    return counts
