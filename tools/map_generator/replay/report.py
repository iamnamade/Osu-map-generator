from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .models import (
    ComboStats,
    CursorSegment,
    CursorSimulation,
    FatigueCurve,
    FatigueSample,
    HitEvent,
    PatternRecognitionResult,
    PatternRecognizability,
    PatternTransition,
    ReadingSimulation,
    ReplayPlayerProfile,
    ReplayReport,
    ReplayScoreBreakdown,
    SectionReplayResult,
)


def write_replay_report(path: Path, report: ReplayReport) -> None:
    write_json(path, report.to_dict())


def load_replay_report(path: Path) -> ReplayReport:
    raw_data = _load_json(path, "Replay report JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Replay report JSON must be an object: {path}")

    map_info = _record(raw_data.get("map"), "map")
    player = _record(raw_data.get("player"), "player")
    cursor = _record(raw_data.get("cursor"), "cursor")
    combo = _record(raw_data.get("combo"), "combo")
    patterns = _record(raw_data.get("patterns"), "patterns")
    fatigue = _record(raw_data.get("fatigue"), "fatigue")
    reading = _record(raw_data.get("reading"), "reading")
    breakdown = _record(raw_data.get("scoreBreakdown"), "scoreBreakdown")

    return ReplayReport(
        version=_int(raw_data.get("version"), "version"),
        map_title=_string(map_info.get("title"), "map.title"),
        map_artist=_string(map_info.get("artist"), "map.artist"),
        difficulty=_string(map_info.get("difficulty"), "map.difficulty"),
        object_count=_int(map_info.get("objectCount"), "map.objectCount"),
        duration_ms=_int(map_info.get("durationMs"), "map.durationMs"),
        bpm=_number(map_info.get("bpm"), "map.bpm"),
        approach_time_ms=_int(map_info.get("approachTimeMs"), "map.approachTimeMs"),
        player=_player(player),
        seed=_int(raw_data.get("seed"), "seed"),
        cursor=_cursor(cursor),
        hit_events=[
            HitEvent(
                object_id=_int(item.get("objectId"), f"hitEvents[{index}].objectId"),
                object_type=_string(item.get("objectType"), f"hitEvents[{index}].objectType"),
                time_ms=_int(item.get("timeMs"), f"hitEvents[{index}].timeMs"),
                offset_ms=_number(item.get("offsetMs"), f"hitEvents[{index}].offsetMs"),
                result=_string(item.get("result"), f"hitEvents[{index}].result"),
                demand=_number(item.get("demand"), f"hitEvents[{index}].demand"),
                fatigue=_number(item.get("fatigue"), f"hitEvents[{index}].fatigue"),
            )
            for index, item in enumerate(_record_array(raw_data.get("hitEvents"), "hitEvents"))
        ],
        expected_accuracy=_number(raw_data.get("expectedAccuracy"), "expectedAccuracy"),
        expected_misses=_number(raw_data.get("expectedMisses"), "expectedMisses"),
        full_combo_chance=_number(raw_data.get("fullComboChance"), "fullComboChance"),
        result_counts=_number_record(raw_data.get("resultCounts"), "resultCounts"),
        timing_consistency=_number(raw_data.get("timingConsistency"), "timingConsistency"),
        peak_stress_ms=_int(raw_data.get("peakStressMs"), "peakStressMs"),
        combo=ComboStats(
            combo_breaks=_int(combo.get("comboBreaks"), "combo.comboBreaks"),
            max_combo=_int(combo.get("maxCombo"), "combo.maxCombo"),
            expected_combo_pct=_number(combo.get("expectedComboPct"), "combo.expectedComboPct"),
            recovery_time_ms=_number(combo.get("recoveryTimeMs"), "combo.recoveryTimeMs"),
            miss_clusters=_int(combo.get("missClusters"), "combo.missClusters"),
            isolated_misses=_int(combo.get("isolatedMisses"), "combo.isolatedMisses"),
            stream_failures=_int(combo.get("streamFailures"), "combo.streamFailures"),
            average_combo_before_break=_number(
                combo.get("averageComboBeforeBreak"),
                "combo.averageComboBeforeBreak",
            ),
        ),
        patterns=PatternRecognitionResult(
            patterns=[
                PatternRecognizability(
                    kind=_string(item.get("kind"), f"patterns.patterns[{index}].kind"),
                    label=_string(item.get("label"), f"patterns.patterns[{index}].label"),
                    count=_int(item.get("count"), f"patterns.patterns[{index}].count"),
                    recognizability=_number(
                        item.get("recognizability"),
                        f"patterns.patterns[{index}].recognizability",
                    ),
                )
                for index, item in enumerate(
                    _record_array(patterns.get("patterns"), "patterns.patterns")
                )
            ],
            transitions=[
                PatternTransition(
                    from_ms=_int(item.get("fromMs"), f"patterns.transitions[{index}].fromMs"),
                    to_ms=_int(item.get("toMs"), f"patterns.transitions[{index}].toMs"),
                    from_kind=_string(item.get("fromKind"), f"patterns.transitions[{index}].fromKind"),
                    to_kind=_string(item.get("toKind"), f"patterns.transitions[{index}].toKind"),
                    angle_deg=_number(item.get("angleDeg"), f"patterns.transitions[{index}].angleDeg"),
                    penalty=_number(item.get("penalty"), f"patterns.transitions[{index}].penalty"),
                )
                for index, item in enumerate(
                    _record_array(patterns.get("transitions"), "patterns.transitions")
                )
            ],
            overall_recognizability=_number(
                patterns.get("overallRecognizability"),
                "patterns.overallRecognizability",
            ),
            transition_penalty=_number(
                patterns.get("transitionPenalty"),
                "patterns.transitionPenalty",
            ),
            hardest_pattern=_string(patterns.get("hardestPattern"), "patterns.hardestPattern"),
        ),
        fatigue=FatigueCurve(
            samples=[
                FatigueSample(
                    time_ms=_int(item.get("timeMs"), f"fatigue.samples[{index}].timeMs"),
                    fatigue=_number(item.get("fatigue"), f"fatigue.samples[{index}].fatigue"),
                    section_label=_string_or_empty(
                        item.get("sectionLabel"),
                        f"fatigue.samples[{index}].sectionLabel",
                    ),
                )
                for index, item in enumerate(
                    _record_array(fatigue.get("samples"), "fatigue.samples")
                )
            ],
            average=_number(fatigue.get("average"), "fatigue.average"),
            peak=_number(fatigue.get("peak"), "fatigue.peak"),
            recovery_episodes=_int(fatigue.get("recoveryEpisodes"), "fatigue.recoveryEpisodes"),
        ),
        reading=ReadingSimulation(
            score=_number(reading.get("score"), "reading.score"),
            spacing=_number(reading.get("spacing"), "reading.spacing"),
            time_spacing=_number(reading.get("timeSpacing"), "reading.timeSpacing"),
            angle_variation=_number(reading.get("angleVariation"), "reading.angleVariation"),
            pattern_repetition=_number(reading.get("patternRepetition"), "reading.patternRepetition"),
            visual_clutter=_number(reading.get("visualClutter"), "reading.visualClutter"),
        ),
        sections=_sections(raw_data.get("sections"), "sections"),
        weakest_sections=_sections(raw_data.get("weakestSections"), "weakestSections"),
        strongest_sections=_sections(raw_data.get("strongestSections"), "strongestSections"),
        score_breakdown=ReplayScoreBreakdown(
            accuracy_prediction=_number(breakdown.get("accuracyPrediction"), "scoreBreakdown.accuracyPrediction"),
            miss_prediction=_number(breakdown.get("missPrediction"), "scoreBreakdown.missPrediction"),
            combo_stability=_number(breakdown.get("comboStability"), "scoreBreakdown.comboStability"),
            reading=_number(breakdown.get("reading"), "scoreBreakdown.reading"),
            cursor_efficiency=_number(breakdown.get("cursorEfficiency"), "scoreBreakdown.cursorEfficiency"),
            fatigue=_number(breakdown.get("fatigue"), "scoreBreakdown.fatigue"),
            rhythm_consistency=_number(breakdown.get("rhythmConsistency"), "scoreBreakdown.rhythmConsistency"),
            overall=_number(breakdown.get("overall"), "scoreBreakdown.overall"),
        ),
    )


def _player(raw: dict[str, Any]) -> ReplayPlayerProfile:
    return ReplayPlayerProfile(
        name=_string(raw.get("name"), "player.name"),
        label=_string(raw.get("label"), "player.label"),
        reaction_time_ms=_number(raw.get("reactionTimeMs"), "player.reactionTimeMs"),
        cursor_speed_pps=_number(raw.get("cursorSpeedPps"), "player.cursorSpeedPps"),
        aim_precision=_number(raw.get("aimPrecision"), "player.aimPrecision"),
        rhythm_precision=_number(raw.get("rhythmPrecision"), "player.rhythmPrecision"),
        fatigue_growth=_number(raw.get("fatigueGrowth"), "player.fatigueGrowth"),
        recovery_speed=_number(raw.get("recoverySpeed"), "player.recoverySpeed"),
        consistency=_number(raw.get("consistency"), "player.consistency"),
        pattern_memory=_number(raw.get("patternMemory"), "player.patternMemory"),
    )


def _cursor(raw: dict[str, Any]) -> CursorSimulation:
    return CursorSimulation(
        total_travel_px=_number(raw.get("totalTravelPx"), "cursor.totalTravelPx"),
        average_velocity_pps=_number(raw.get("averageVelocityPps"), "cursor.averageVelocityPps"),
        peak_velocity_pps=_number(raw.get("peakVelocityPps"), "cursor.peakVelocityPps"),
        average_acceleration_pps2=_number(
            raw.get("averageAccelerationPps2"),
            "cursor.averageAccelerationPps2",
        ),
        sharp_turn_count=_int(raw.get("sharpTurnCount"), "cursor.sharpTurnCount"),
        efficiency=_number(raw.get("efficiency"), "cursor.efficiency"),
        segments=[
            CursorSegment(
                from_object_id=_int(item.get("fromObjectId"), f"cursor.segments[{index}].fromObjectId"),
                to_object_id=_int(item.get("toObjectId"), f"cursor.segments[{index}].toObjectId"),
                start_ms=_int(item.get("startMs"), f"cursor.segments[{index}].startMs"),
                end_ms=_int(item.get("endMs"), f"cursor.segments[{index}].endMs"),
                distance_px=_number(item.get("distancePx"), f"cursor.segments[{index}].distancePx"),
                velocity_pps=_number(item.get("velocityPps"), f"cursor.segments[{index}].velocityPps"),
                acceleration_pps2=_number(
                    item.get("accelerationPps2"),
                    f"cursor.segments[{index}].accelerationPps2",
                ),
                angle_deg=_number(item.get("angleDeg"), f"cursor.segments[{index}].angleDeg"),
                required_velocity_pps=_number(
                    item.get("requiredVelocityPps"),
                    f"cursor.segments[{index}].requiredVelocityPps",
                ),
                penalty=_number(item.get("penalty"), f"cursor.segments[{index}].penalty"),
            )
            for index, item in enumerate(_record_array(raw.get("segments"), "cursor.segments"))
        ],
    )


def _sections(raw: Any, label: str) -> list[SectionReplayResult]:
    return [
        SectionReplayResult(
            section_id=_optional_int(item.get("sectionId"), f"{label}[{index}].sectionId"),
            label=_string(item.get("label") or f"Section {index + 1}", f"{label}[{index}].label"),
            start_ms=_int(item.get("startMs"), f"{label}[{index}].startMs"),
            end_ms=_int(item.get("endMs"), f"{label}[{index}].endMs"),
            object_count=_int(item.get("objectCount"), f"{label}[{index}].objectCount"),
            miss_rate=_number(item.get("missRate"), f"{label}[{index}].missRate"),
            accuracy=_number(item.get("accuracy"), f"{label}[{index}].accuracy"),
            fatigue_peak=_number(item.get("fatiguePeak"), f"{label}[{index}].fatiguePeak"),
            reading_demand=_number(item.get("readingDemand"), f"{label}[{index}].readingDemand"),
        )
        for index, item in enumerate(_record_array(raw, label))
    ]


def _load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise MapGeneratorError(
            f"{label} is malformed at {path}: {error.msg} (line {error.lineno}, column {error.colno})"
        ) from error
    except OSError as error:
        raise MapGeneratorError(f"{label} could not be read from {path}: {error}") from error


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
    """Parse a string that may be absent or empty (defaults to empty)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MapGeneratorError(f"{label} must be a string.")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MapGeneratorError(f"{label} must be a finite number.")
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise MapGeneratorError(f"{label} must be a finite number.")
    return numeric


def _number_record(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise MapGeneratorError(f"{label} must be an object.")
    return {str(key): _number(item, f"{label}.{key}") for key, item in value.items()}


def _int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise MapGeneratorError(f"{label} must be an integer.")
    if isinstance(value, int):
        return value
    numeric = _number(value, label)
    if int(numeric) != numeric:
        raise MapGeneratorError(f"{label} must be an integer.")
    return int(numeric)


def _optional_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _int(value, label)
