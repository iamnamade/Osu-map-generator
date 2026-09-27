from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .models import (
    ObjectAdjustment,
    RebalanceIssue,
    RebalancePass,
    RebalanceReport,
    RebalanceSummary,
    SectionQuality,
    SliderAdjustment,
    SpinnerAdjustment,
)

_REBALANCE_REPORT_VERSION = 1


def write_rebalance_report(path: Path, report: RebalanceReport) -> None:
    write_json(path, report.to_dict())


def load_rebalance_report(path: Path) -> RebalanceReport:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as error:
        raise MapGeneratorError(
            f"Rebalance report is malformed at {path}: {error.msg}"
        ) from error
    except OSError as error:
        raise MapGeneratorError(
            f"Rebalance report could not be read from {path}: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise MapGeneratorError(f"Rebalance report must be an object: {path}")

    summary = _record(raw.get("summary"), "summary")
    map_info = _record(raw.get("map"), "map")
    return RebalanceReport(
        version=_int(raw.get("version", _REBALANCE_REPORT_VERSION), "version"),
        map_title=_string_or_empty(map_info.get("title"), "map.title"),
        map_artist=_string_or_empty(map_info.get("artist"), "map.artist"),
        difficulty=_string_or_empty(map_info.get("difficulty"), "map.difficulty"),
        seed=_int(raw.get("seed", 1), "seed"),
        sections=[
            _section(item, f"sections[{index}]")
            for index, item in enumerate(_record_array(raw.get("sections"), "sections"))
        ],
        issues=[
            RebalanceIssue(
                code=_string(item.get("code"), f"issues[{index}].code"),
                severity=_string(item.get("severity"), f"issues[{index}].severity"),
                reason=_string(item.get("reason"), f"issues[{index}].reason"),
                suggestion=_string(
                    item.get("suggestion"),
                    f"issues[{index}].suggestion",
                ),
                section_label=_string_or_empty(
                    item.get("sectionLabel"),
                    f"issues[{index}].sectionLabel",
                ),
            )
            for index, item in enumerate(_record_array(raw.get("issues"), "issues"))
        ],
        object_adjustments=[
            ObjectAdjustment(
                object_id=_int(item.get("objectId"), f"objectAdjustments[{index}].objectId"),
                object_type=_string(
                    item.get("objectType"),
                    f"objectAdjustments[{index}].objectType",
                ),
                action=_string(item.get("action"), f"objectAdjustments[{index}].action"),
                reason=_string(item.get("reason"), f"objectAdjustments[{index}].reason"),
                before=_number_record(item.get("before"), f"objectAdjustments[{index}].before"),
                after=_number_record(item.get("after"), f"objectAdjustments[{index}].after"),
                section_label=_string_or_empty(
                    item.get("sectionLabel"),
                    f"objectAdjustments[{index}].sectionLabel",
                ),
            )
            for index, item in enumerate(
                _record_array(raw.get("objectAdjustments"), "objectAdjustments")
            )
        ],
        slider_adjustments=[
            SliderAdjustment(
                object_id=_int(item.get("objectId"), f"sliderAdjustments[{index}].objectId"),
                action=_string(item.get("action"), f"sliderAdjustments[{index}].action"),
                reason=_string(item.get("reason"), f"sliderAdjustments[{index}].reason"),
                before=_number_record(item.get("before"), f"sliderAdjustments[{index}].before"),
                after=_number_record(item.get("after"), f"sliderAdjustments[{index}].after"),
                section_label=_string_or_empty(
                    item.get("sectionLabel"),
                    f"sliderAdjustments[{index}].sectionLabel",
                ),
            )
            for index, item in enumerate(
                _record_array(raw.get("sliderAdjustments"), "sliderAdjustments")
            )
        ],
        spinner_adjustments=[
            SpinnerAdjustment(
                object_id=_int(item.get("objectId"), f"spinnerAdjustments[{index}].objectId"),
                action=_string(item.get("action"), f"spinnerAdjustments[{index}].action"),
                reason=_string(item.get("reason"), f"spinnerAdjustments[{index}].reason"),
                before=_number_record(item.get("before"), f"spinnerAdjustments[{index}].before"),
                after=_number_record(item.get("after"), f"spinnerAdjustments[{index}].after"),
                section_label=_string_or_empty(
                    item.get("sectionLabel"),
                    f"spinnerAdjustments[{index}].sectionLabel",
                ),
            )
            for index, item in enumerate(
                _record_array(raw.get("spinnerAdjustments"), "spinnerAdjustments")
            )
        ],
        passes=[
            RebalancePass(
                pass_number=_int(item.get("passNumber"), f"passes[{index}].passNumber"),
                score_before=_number(item.get("scoreBefore"), f"passes[{index}].scoreBefore"),
                score_after=_number(item.get("scoreAfter"), f"passes[{index}].scoreAfter"),
                issues_found=_int(item.get("issuesFound"), f"passes[{index}].issuesFound"),
                sections_modified=_int(
                    item.get("sectionsModified"),
                    f"passes[{index}].sectionsModified",
                ),
                adjustments_count=_int(
                    item.get("adjustmentsCount"),
                    f"passes[{index}].adjustmentsCount",
                ),
                accepted=_bool(item.get("accepted"), f"passes[{index}].accepted"),
            )
            for index, item in enumerate(_record_array(raw.get("passes"), "passes"))
        ],
        summary=RebalanceSummary(
            passes_run=_int(summary.get("passesRun"), "summary.passesRun"),
            early_stopped=_bool(summary.get("earlyStopped"), "summary.earlyStopped"),
            sections_modified=_int(
                summary.get("sectionsModified"),
                "summary.sectionsModified",
            ),
            objects_adjusted=_int(summary.get("objectsAdjusted"), "summary.objectsAdjusted"),
            sliders_optimized=_int(
                summary.get("slidersOptimized"),
                "summary.slidersOptimized",
            ),
            spinners_adjusted=_int(
                summary.get("spinnersAdjusted"),
                "summary.spinnersAdjusted",
            ),
            issues_found=_int(summary.get("issuesFound"), "summary.issuesFound"),
            quality_before=_number(summary.get("qualityBefore"), "summary.qualityBefore"),
            quality_after=_number(summary.get("qualityAfter"), "summary.qualityAfter"),
            quality_gain=_number(summary.get("qualityGain"), "summary.qualityGain"),
            replay_before=_number(summary.get("replayBefore"), "summary.replayBefore"),
            replay_after=_number(summary.get("replayAfter"), "summary.replayAfter"),
            replay_gain=_number(summary.get("replayGain"), "summary.replayGain"),
            cursor_efficiency_before=_number(
                summary.get("cursorEfficiencyBefore"),
                "summary.cursorEfficiencyBefore",
            ),
            cursor_efficiency_after=_number(
                summary.get("cursorEfficiencyAfter"),
                "summary.cursorEfficiencyAfter",
            ),
            cursor_efficiency_gain=_number(
                summary.get("cursorEfficiencyGain"),
                "summary.cursorEfficiencyGain",
            ),
            star_rating_before=_number(
                summary.get("starRatingBefore"),
                "summary.starRatingBefore",
            ),
            star_rating_after=_number(
                summary.get("starRatingAfter"),
                "summary.starRatingAfter",
            ),
            weakest_section=_string_or_empty(
                summary.get("weakestSection"),
                "summary.weakestSection",
            ),
            strongest_section=_string_or_empty(
                summary.get("strongestSection"),
                "summary.strongestSection",
            ),
        ),
    )


def rebalance_generator_metadata(
    report: RebalanceReport,
    report_path_label: str,
) -> dict[str, Any]:
    """Compact rebalance summary embedded into the map's generator metadata."""
    summary = report.summary
    return {
        "passesRun": summary.passes_run,
        "earlyStopped": summary.early_stopped,
        "sectionsModified": summary.sections_modified,
        "objectsAdjusted": summary.objects_adjusted,
        "slidersOptimized": summary.sliders_optimized,
        "spinnersAdjusted": summary.spinners_adjusted,
        "issuesFound": summary.issues_found,
        "qualityGain": round(summary.quality_gain, 2),
        "replayGain": round(summary.replay_gain, 2),
        "cursorEfficiencyGain": round(summary.cursor_efficiency_gain, 4),
        "weakestSection": summary.weakest_section,
        "strongestSection": summary.strongest_section,
        "reportPath": report_path_label,
    }


def format_rebalance_summary(report: RebalanceReport) -> str:
    summary = report.summary
    lines = [
        "Adaptive rebalancing complete",
        "",
        f"Map: {report.map_title} - {report.map_artist} ({report.difficulty})",
        f"Seed: {report.seed}",
        f"Passes run: {summary.passes_run}",
        f"Early stopped: {'yes' if summary.early_stopped else 'no'}",
        f"Sections modified: {summary.sections_modified}",
        f"Objects adjusted: {summary.objects_adjusted}",
        f"Sliders optimized: {summary.sliders_optimized}",
        f"Spinners adjusted: {summary.spinners_adjusted}",
        f"Issues found: {summary.issues_found}",
        f"Quality: {summary.quality_before:.1f} -> {summary.quality_after:.1f} "
        f"(gain {summary.quality_gain:+.1f})",
        f"Replay: {summary.replay_before:.1f} -> {summary.replay_after:.1f} "
        f"(gain {summary.replay_gain:+.1f})",
        f"Cursor efficiency: {summary.cursor_efficiency_before:.2f} -> "
        f"{summary.cursor_efficiency_after:.2f} (gain {summary.cursor_efficiency_gain:+.2f})",
        f"Stars: {summary.star_rating_before:.2f} -> {summary.star_rating_after:.2f}",
        f"Weakest section: {summary.weakest_section or 'n/a'}",
        f"Strongest section: {summary.strongest_section or 'n/a'}",
    ]
    if report.issues:
        lines.extend(["", f"Detected issues ({len(report.issues)}):"])
        for issue in report.issues[:10]:
            lines.append(
                f"- [{issue.severity.upper()}] {issue.code} ({issue.section_label}): "
                f"{issue.reason}"
            )
    if report.passes:
        lines.extend(["", "Passes:"])
        for entry in report.passes:
            marker = "accepted" if entry.accepted else "rejected"
            lines.append(
                f"- Pass {entry.pass_number}: {entry.score_before:.2f} -> "
                f"{entry.score_after:.2f} ({marker}, {entry.adjustments_count} adjustments)"
            )
    return "\n".join(lines)


def _section(raw: dict[str, Any], label: str) -> SectionQuality:
    return SectionQuality(
        section_id=_int_or_none(raw.get("sectionId"), f"{label}.sectionId"),
        label=_string_or_empty(raw.get("label"), f"{label}.label"),
        start_ms=_int(raw.get("startMs"), f"{label}.startMs"),
        end_ms=_int(raw.get("endMs"), f"{label}.endMs"),
        object_count=_int(raw.get("objectCount", 0), f"{label}.objectCount"),
        star_rating=_number(raw.get("starRating", 0.0), f"{label}.starRating"),
        density=_number(raw.get("density", 0.0), f"{label}.density"),
        pattern_variety=_number(raw.get("patternVariety", 0.0), f"{label}.patternVariety"),
        rhythm_consistency=_number(
            raw.get("rhythmConsistency", 0.0),
            f"{label}.rhythmConsistency",
        ),
        reading_score=_number(raw.get("readingScore", 0.0), f"{label}.readingScore"),
        cursor_travel_px=_number(
            raw.get("cursorTravelPx", 0.0),
            f"{label}.cursorTravelPx",
        ),
        fatigue_average=_number(raw.get("fatigueAverage", 0.0), f"{label}.fatigueAverage"),
        miss_probability=_number(raw.get("missProbability", 0.0), f"{label}.missProbability"),
        combo_stability=_number(raw.get("comboStability", 0.0), f"{label}.comboStability"),
        flow_quality=_number(raw.get("flowQuality", 0.0), f"{label}.flowQuality"),
        quality_score=_number(raw.get("qualityScore", 0.0), f"{label}.qualityScore"),
    )


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return value


def _record_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise MapGeneratorError(f"{label} must be an array.")
    output: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MapGeneratorError(f"{label}[{index}] must be an object.")
        output.append(item)
    return output


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MapGeneratorError(f"{label} must be a non-empty string.")
    return value


def _string_or_empty(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MapGeneratorError(f"{label} must be a string.")
    return value


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise MapGeneratorError(f"{label} must be a finite number.")
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise MapGeneratorError(f"{label} must be a finite number.")
    return numeric


def _number_record(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    output: dict[str, float] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            raise MapGeneratorError(f"{label}.{key} must be a finite number.")
        output[str(key)] = _number(item, f"{label}.{key}")
    return output


def _int(value: Any, label: str) -> int:
    numeric = _number(value, label)
    if int(numeric) != numeric:
        raise MapGeneratorError(f"{label} must be an integer.")
    return int(numeric)


def _int_or_none(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _int(value, label)


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MapGeneratorError(f"{label} must be a boolean.")
    return value
