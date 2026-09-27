from __future__ import annotations

from typing import Any

from ..difficulty.common import clamp
from .flow import analyze_flow
from .models import SectionQuality

_PATTERN_KINDS = (
    "stream",
    "burst",
    "jump",
    "cross-screen jump",
    "stack",
    "linear",
    "zigzag",
    "triangle",
)


def analyze_sections(
    *,
    map_dict: dict[str, Any],
    difficulty_report: Any | None,
    replay_report: Any | None,
    difficulty: str = "normal",
    phrase_density_at: Any | None = None,
) -> list[SectionQuality]:
    """Analyze every logical section independently.

    Merges the difficulty engine's section report, the Phase 15 replay report,
    the difficulty curve, cursor segments, and fatigue samples into one
    deterministic per-section quality snapshot.

    When ``phrase_density_at`` (a Phase 20 phrase-density resolver) is
    provided, the per-section target density follows the phrase trajectory so
    dense phrases are held to their target and recovery phrases are allowed
    to breathe.
    """
    windows = _section_windows(difficulty_report, replay_report, map_dict)
    positioned = _positioned_objects(map_dict)
    if not windows:
        return []

    curve = getattr(difficulty_report, "curve", None) or []
    patterns = getattr(difficulty_report, "patterns", None) or []
    star_rating = float(
        getattr(
            getattr(difficulty_report, "star_rating", None),
            "overall",
            0.0,
        )
        or 0.0
    )
    target_density = _target_density(difficulty_report, difficulty)
    phrase_density_at = phrase_density_at or (lambda time_ms: None)
    flow = analyze_flow(map_dict)
    turn_by_id = {turn.object_id: turn for turn in flow.turns}

    cursor_segments = getattr(getattr(replay_report, "cursor", None), "segments", None) or []
    fatigue_samples = getattr(getattr(replay_report, "fatigue", None), "samples", None) or []
    replay_combo_pct = getattr(
        getattr(replay_report, "combo", None),
        "expected_combo_pct",
        0.0,
    )
    replay_sections = getattr(replay_report, "sections", None) or []
    replay_by_start: dict[int, Any] = {}
    for section in replay_sections:
        start = getattr(section, "start_ms", None)
        if isinstance(start, int):
            replay_by_start[start] = section

    # Global mean difficulty across the curve for local star scaling.
    curve_scores = [float(point.difficulty_score) for point in curve]
    mean_curve = sum(curve_scores) / len(curve_scores) if curve_scores else 0.0

    output: list[SectionQuality] = []
    for window in windows:
        start = int(window["startMs"])
        end = int(window["endMs"])
        section_id = window.get("sectionId")
        label = window.get("label", "Section")

        in_window = [
            item
            for item in positioned
            if start <= int(item["time"]) < end
        ]
        object_count = len(in_window)

        # Difficulty curve averages inside the window.
        curve_points = [
            point
            for point in curve
            if start <= int(point.time_ms) <= end
        ]
        window_curve = (
            sum(float(point.difficulty_score) for point in curve_points)
            / len(curve_points)
            if curve_points
            else 0.0
        )
        rhythm = _mean_curve_attr(curve_points, "rhythm")
        reading_curve = _mean_curve_attr(curve_points, "reading")
        flow_curve = _mean_curve_attr(curve_points, "flow")

        density = object_count / max(1.0, (end - start) / 1000.0)
        # Phase 20: phrase-aware target density overrides the global target
        # for this window when the phrase trajectory knows this time range.
        phrase_target = phrase_density_at((start + end) // 2)
        if isinstance(phrase_target, (int, float)) and phrase_target > 0:
            window_target_density = float(phrase_target)
        else:
            window_target_density = target_density

        # Local star rating: scale the map stars by relative section strain.
        local_star = star_rating
        if mean_curve > 0.0 and window_curve > 0.0:
            local_star = star_rating * clamp(window_curve / mean_curve, 0.3, 3.0)

        # Cursor travel from replay segments whose target lands in the window.
        cursor_travel = 0.0
        for segment in cursor_segments:
            target_time = getattr(segment, "end_ms", None)
            if isinstance(target_time, int) and start <= target_time < end:
                cursor_travel += float(getattr(segment, "distance_px", 0.0))

        # Fatigue average from replay fatigue samples inside the window.
        fatigue_values = [
            float(sample.fatigue)
            for sample in fatigue_samples
            if start <= int(sample.time_ms) <= end
        ]
        fatigue_average = (
            sum(fatigue_values) / len(fatigue_values) if fatigue_values else 0.0
        )

        # Replay section stats (matched by start ms; windows align with the
        # difficulty engine when both reports were produced from it).
        replay_section = replay_by_start.get(start)
        miss_probability = 0.0
        replay_reading_demand = 0.0
        if replay_section is not None:
            miss_probability = float(getattr(replay_section, "miss_rate", 0.0) or 0.0)
            replay_reading_demand = float(
                getattr(replay_section, "reading_demand", 0.0) or 0.0
            )

        combo_stability = clamp(
            1.0 - miss_probability * 0.8 - max(0.0, 1.0 - replay_combo_pct) * 0.2,
            0.0,
            1.0,
        )

        # Flow quality: curve flow blended with sharp-turn penalties.
        sharp_turns = sum(
            1
            for item in in_window
            if int(item["id"]) in turn_by_id and turn_by_id[int(item["id"])].sharp
        )
        flow_quality = clamp(flow_curve * 100.0 - sharp_turns * 4.0, 0.0, 100.0)

        # Pattern variety from difficulty pattern classifications in the window.
        window_patterns = {
            str(pattern.pattern)
            for pattern in patterns
            if start <= int(pattern.start_ms) <= end
            or start <= int(pattern.end_ms) <= end
            or (int(pattern.start_ms) <= start and int(pattern.end_ms) >= end)
        }
        pattern_variety = clamp(len(window_patterns) / 5.0, 0.0, 1.0)

        reading_score = clamp(
            reading_curve * 60.0 + (1.0 - replay_reading_demand) * 40.0,
            0.0,
            100.0,
        )
        rhythm_consistency = clamp(rhythm, 0.0, 1.0)

        quality = _section_quality(
            object_count=object_count,
            density=density,
            target_density=window_target_density,
            rhythm=rhythm_consistency,
            reading=reading_score,
            flow=flow_quality,
            miss=miss_probability,
            combo=combo_stability,
            variety=pattern_variety,
        )

        output.append(
            SectionQuality(
                section_id=section_id,
                label=label,
                start_ms=start,
                end_ms=end,
                object_count=object_count,
                star_rating=round(local_star, 3),
                density=round(density, 4),
                pattern_variety=round(pattern_variety, 4),
                rhythm_consistency=round(rhythm_consistency, 4),
                reading_score=round(reading_score, 2),
                cursor_travel_px=round(cursor_travel, 2),
                fatigue_average=round(fatigue_average, 4),
                miss_probability=round(miss_probability, 4),
                combo_stability=round(combo_stability, 4),
                flow_quality=round(flow_quality, 2),
                quality_score=round(quality, 2),
            )
        )
    return output


def _section_windows(
    difficulty_report: Any | None,
    replay_report: Any | None,
    map_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    sections = getattr(difficulty_report, "sections", None) or []
    if sections:
        return [
            {
                "sectionId": getattr(section, "section_id", None),
                "label": getattr(section, "label", "Section"),
                "startMs": int(section.start_ms),
                "endMs": int(section.end_ms),
            }
            for section in sections
        ]
    replay_sections = getattr(replay_report, "sections", None) or []
    if replay_sections:
        return [
            {
                "sectionId": getattr(section, "section_id", None),
                "label": getattr(section, "label", "Section"),
                "startMs": int(section.start_ms),
                "endMs": int(section.end_ms),
            }
            for section in replay_sections
        ]
    return _fallback_windows(map_dict)


def _fallback_windows(map_dict: dict[str, Any]) -> list[dict[str, Any]]:
    objects = map_dict.get("objects")
    if not isinstance(objects, list) or not objects:
        return []
    times = [int(item["time"]) for item in objects if isinstance(item, dict)]
    if not times:
        return []
    start = min(times)
    end = max(times)
    span = max(4000, end - start)
    count = max(2, round(span / 8000))
    step = span / count
    windows: list[dict[str, Any]] = []
    for index in range(count):
        section_start = start + round(index * step)
        section_end = start + round((index + 1) * step)
        windows.append(
            {
                "sectionId": index + 1,
                "label": f"Section {index + 1}",
                "startMs": section_start,
                "endMs": section_end,
            }
        )
    return windows


def _mean_curve_attr(points: list[Any], attribute: str) -> float:
    values = [
        float(getattr(point, attribute, 0.0))
        for point in points
        if getattr(point, attribute, None) is not None
    ]
    return sum(values) / len(values) if values else 0.0


def _target_density(difficulty_report: Any | None, difficulty: str) -> float:
    target = getattr(difficulty_report, "target", None)
    if target is not None:
        value = getattr(target, "density_target", None)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return {"easy": 0.8, "normal": 1.1, "hard": 1.7}.get(difficulty, 1.1)


def _section_quality(
    *,
    object_count: int,
    density: float,
    target_density: float,
    rhythm: float,
    reading: float,
    flow: float,
    miss: float,
    combo: float,
    variety: float,
) -> float:
    if object_count == 0:
        return 15.0
    density_balance = clamp(1.0 - abs(density - target_density) / max(target_density, 0.5), 0.0, 1.0)
    return clamp(
        0.25 * rhythm * 100.0
        + 0.15 * (1.0 - miss) * 100.0
        + 0.15 * combo * 100.0
        + 0.15 * flow
        + 0.15 * reading
        + 0.10 * variety * 100.0
        + 0.05 * density_balance * 100.0,
        0.0,
        100.0,
    )


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
