from __future__ import annotations

from typing import Any

from ..difficulty.common import clamp
from .flow import SHARP_TURN_THRESHOLD_DEG, analyze_flow
from .models import RebalanceIssue, SectionQuality


def detect_issues(
    *,
    sections: list[SectionQuality],
    map_dict: dict[str, Any],
    difficulty_report: Any | None,
    replay_report: Any | None,
    difficulty: str = "normal",
) -> list[RebalanceIssue]:
    """Detect problematic areas with severity, reason, and a suggestion."""
    if not sections:
        return []
    issues: list[RebalanceIssue] = []

    star_rating = float(
        getattr(getattr(difficulty_report, "star_rating", None), "overall", 0.0) or 0.0
    )
    target = getattr(difficulty_report, "target", None)
    target_high = float(target.star_range[1]) if target is not None else 0.0
    spinner_frequency = float(
        getattr(getattr(difficulty_report, "metrics", None), "spinner_frequency_per_minute", 0.0)
        or 0.0
    )
    replay_combo_pct = float(
        getattr(getattr(replay_report, "combo", None), "expected_combo_pct", 0.0) or 0.0
    )
    target_density = float(getattr(target, "density_target", 0.0) or 0.0)
    if target_density <= 0.0:
        target_density = {"easy": 0.8, "normal": 1.1, "hard": 1.7}.get(difficulty, 1.1)
    flow = analyze_flow(map_dict)
    sharp_by_section: dict[int, int] = {}
    for section in sections:
        sharp_by_section[section.section_id or 0] = 0
    for turn in flow.turns:
        for section in sections:
            if (
                section.section_id is not None
                and section.start_ms <= turn.time_ms < section.end_ms
            ):
                sharp_by_section[section.section_id] = (
                    sharp_by_section.get(section.section_id, 0) + 1
                )
                break

    jump_stats = _jump_stats_per_section(map_dict, sections)
    slider_stats = _slider_stats_per_section(map_dict, sections)
    spinner_stats = _spinner_stats_per_section(map_dict, sections)
    stream_stats = _stream_stats_per_section(map_dict, sections)

    for index, section in enumerate(sections):
        label = section.label
        sharp_turns = sharp_by_section.get(section.section_id or 0, 0)
        jumps = jump_stats.get(section.section_id or 0, (0.0, 0.0, 0))
        max_jump, average_jump, _ = jumps
        slider_repeats = slider_stats.get(section.section_id or 0, 0)
        spinner_count = spinner_stats.get(section.section_id or 0, 0)
        longest_stream = stream_stats.get(section.section_id or 0, 0)

        # Difficulty spikes: local star far above the map target or map average.
        spike_threshold = max(star_rating * 1.5, target_high * 1.35)
        if section.object_count >= 4 and section.star_rating > spike_threshold:
            issues.append(
                RebalanceIssue(
                    code="DIFFICULTY_SPIKE",
                    severity="high",
                    reason=(
                        f"Local star rating {section.star_rating:.2f} exceeds the "
                        f"spike threshold {spike_threshold:.2f} in {label}."
                    ),
                    suggestion="Reduce oversized jumps and smooth angle transitions inside this section.",
                    section_label=label,
                )
            )

        # Empty sections: no objects or far below the target density.
        if section.object_count == 0:
            issues.append(
                RebalanceIssue(
                    code="EMPTY_SECTION",
                    severity="medium",
                    reason=f"{label} contains no objects.",
                    suggestion="Fill the gap with a recovery pattern or subdivision objects.",
                    section_label=label,
                )
            )
        elif (
            section.object_count >= 4
            and section.density < target_density * 0.4
        ):
            issues.append(
                RebalanceIssue(
                    code="EMPTY_SECTION",
                    severity="low",
                    reason=(
                        f"{label} is sparsely populated ({section.density:.2f} objects/s "
                        f"vs {target_density:.2f} target)."
                    ),
                    suggestion="Consider adding subdivision objects for pacing continuity.",
                    section_label=label,
                )
            )

        # Repetitive patterns: little pattern variety across many objects.
        if section.object_count >= 6 and section.pattern_variety < 0.2:
            issues.append(
                RebalanceIssue(
                    code="REPETITIVE_PATTERN",
                    severity="medium",
                    reason=f"{label} repeats the same pattern family across {section.object_count} objects.",
                    suggestion="Vary spacing and angle transitions to increase pattern variety.",
                    section_label=label,
                )
            )

        # Awkward spacing: jump outliers far above the section average.
        if max_jump > 240.0 and max_jump > average_jump * 1.8 + 40.0:
            issues.append(
                RebalanceIssue(
                    code="AWKWARD_SPACING",
                    severity="medium",
                    reason=(
                        f"{label} contains a {max_jump:.0f}px jump against a "
                        f"{average_jump:.0f}px section average."
                    ),
                    suggestion="Shrink outlier jumps toward the section average.",
                    section_label=label,
                )
            )

        # Unreadable jumps: low reading score combined with large jumps.
        if section.reading_score < 45.0 and max_jump > 260.0:
            issues.append(
                RebalanceIssue(
                    code="UNREADABLE_JUMP",
                    severity="high",
                    reason=(
                        f"{label} pairs low readability ({section.reading_score:.0f}/100) "
                        f"with jumps up to {max_jump:.0f}px."
                    ),
                    suggestion="Reduce jump distance and increase time spacing for readability.",
                    section_label=label,
                )
            )

        # Stream overload: long stream runs relative to the difficulty.
        stream_limit = {"easy": 6, "normal": 10, "hard": 14}.get(difficulty, 10)
        if longest_stream > stream_limit:
            issues.append(
                RebalanceIssue(
                    code="STREAM_OVERLOAD",
                    severity="medium",
                    reason=f"{label} has a {longest_stream}-object stream run.",
                    suggestion="Break the stream with a rest or slider to reduce stamina demand.",
                    section_label=label,
                )
            )

        # Rhythm inconsistency.
        if section.object_count >= 4 and section.rhythm_consistency < 0.45:
            issues.append(
                RebalanceIssue(
                    code="RHYTHM_INCONSISTENCY",
                    severity="medium",
                    reason=f"{label} shows weak rhythm consistency ({section.rhythm_consistency:.2f}).",
                    suggestion="Align object timing with the underlying beat subdivisions.",
                    section_label=label,
                )
            )

        # Poor slider usage: high repeat counts.
        if slider_repeats > 2:
            issues.append(
                RebalanceIssue(
                    code="POOR_SLIDER_USAGE",
                    severity="low",
                    reason=f"{label} uses sliders with up to {slider_repeats} repeats.",
                    suggestion="Simplify repeat counts to reduce stamina demand.",
                    section_label=label,
                )
            )

        # Spinner overuse.
        if spinner_count >= 3 or spinner_frequency > 0.5:
            issues.append(
                RebalanceIssue(
                    code="SPINNER_OVERUSE",
                    severity="medium",
                    reason=f"{label} contains {spinner_count} spinners.",
                    suggestion="Shorten, remove, or replace unnecessary spinners.",
                    section_label=label,
                )
            )

        # Sudden pacing changes between adjacent sections.
        if index > 0:
            previous = sections[index - 1]
            if (
                previous.object_count >= 3
                and section.object_count >= 3
                and previous.star_rating > 0.0
            ):
                ratio = section.star_rating / previous.star_rating
                if ratio > 1.8 or ratio < 1.0 / 1.8:
                    issues.append(
                        RebalanceIssue(
                            code="PACING_CHANGE",
                            severity="low",
                            reason=(
                                f"{label} jumps from {previous.star_rating:.2f} to "
                                f"{section.star_rating:.2f} local stars."
                            ),
                            suggestion="Smooth the difficulty ramp between adjacent sections.",
                            section_label=label,
                        )
                    )

        # Flow breaks: many sharp turns.
        if sharp_turns >= 3:
            issues.append(
                RebalanceIssue(
                    code="FLOW_BREAK",
                    severity="medium",
                    reason=f"{label} has {sharp_turns} sharp cursor turns.",
                    suggestion="Smooth angle transitions to avoid doubling back on the cursor path.",
                    section_label=label,
                )
            )

    # Global combo warning from the replay simulation.
    if replay_combo_pct < 0.55:
        issues.append(
            RebalanceIssue(
                code="COMBO_STABILITY",
                severity="low",
                reason=f"Replay expects only {replay_combo_pct:.0%} of objects comboed.",
                suggestion="Reduce difficulty spikes and improve recovery windows.",
                section_label="",
            )
        )

    issues.sort(key=lambda issue: (_severity_rank(issue.severity), issue.code, issue.section_label))
    return issues


def _jump_stats_per_section(
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
) -> dict[int, tuple[float, float, int]]:
    positioned = [
        item
        for item in (map_dict.get("objects") or [])
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("x"), (int, float))
        and isinstance(item.get("y"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item.get("time", 0)), int(item.get("id", 0))))
    totals: dict[int, tuple[float, float, int]] = {}
    previous = None
    for item in positioned:
        time = int(item["time"])
        section_id = _section_id_for_time(sections, time)
        key = section_id if section_id is not None else 0
        if previous is not None:
            distance = _distance(previous, item)
            total, max_jump, count = totals.get(key, (0.0, 0.0, 0))
            totals[key] = (total + distance, max(max_jump, distance), count + 1)
        previous = item
    return {
        key: (max_jump, total / count if count else 0.0, count)
        for key, (total, max_jump, count) in totals.items()
    }


def _slider_stats_per_section(
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
) -> dict[int, int]:
    stats: dict[int, int] = {}
    for item in map_dict.get("objects") or []:
        if not isinstance(item, dict) or item.get("type") != "slider":
            continue
        repeats = item.get("repeats") or 0
        section_id = _section_id_for_time(sections, int(item.get("time", 0)))
        key = section_id if section_id is not None else 0
        stats[key] = max(stats.get(key, 0), int(repeats))
    return stats


def _spinner_stats_per_section(
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
) -> dict[int, int]:
    stats: dict[int, int] = {}
    for item in map_dict.get("objects") or []:
        if not isinstance(item, dict) or item.get("type") != "spinner":
            continue
        section_id = _section_id_for_time(sections, int(item.get("time", 0)))
        key = section_id if section_id is not None else 0
        stats[key] = stats.get(key, 0) + 1
    return stats


def _stream_stats_per_section(
    map_dict: dict[str, Any],
    sections: list[SectionQuality],
) -> dict[int, int]:
    stats: dict[int, int] = {}
    positioned = [
        item
        for item in (map_dict.get("objects") or [])
        if isinstance(item, dict)
        and item.get("type") in ("circle", "slider")
        and isinstance(item.get("x"), (int, float))
        and isinstance(item.get("y"), (int, float))
    ]
    positioned.sort(key=lambda item: (int(item.get("time", 0)), int(item.get("id", 0))))
    run = 1
    run_section = None
    for index in range(1, len(positioned)):
        gap = int(positioned[index]["time"]) - int(positioned[index - 1]["time"])
        section_id = _section_id_for_time(sections, int(positioned[index]["time"]))
        if gap <= 190:
            run += 1
            run_section = section_id if section_id is not None else run_section
        else:
            if run >= 3 and run_section is not None:
                key = run_section if run_section is not None else 0
                stats[key] = max(stats.get(key, 0), run)
            run = 1
            run_section = None
    if run >= 3 and run_section is not None:
        key = run_section if run_section is not None else 0
        stats[key] = max(stats.get(key, 0), run)
    return stats


def _section_id_for_time(
    sections: list[SectionQuality],
    time_ms: int,
) -> int | None:
    for section in sections:
        if section.start_ms <= time_ms < section.end_ms:
            return section.section_id
    return None


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    import math

    return math.hypot(
        float(right["x"]) - float(left["x"]),
        float(right["y"]) - float(left["y"]),
    )


def _severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)
