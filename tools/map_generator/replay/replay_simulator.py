from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

from ..difficulty.common import clamp, mean
from ..difficulty.loader import load_difficulty_map
from ..difficulty.models import DifficultyReport
from ..utils import ensure_existing_file
from .combo import simulate_combo
from .cursor import simulate_cursor
from .fatigue import simulate_fatigue
from .hits import simulate_hits
from .models import ReplayReport, SectionReplayResult
from .patterns import recognize_patterns
from .player import resolve_player_profile
from .reading import simulate_reading
from .scoring import ReplayScoreWeights, compute_replay_score

_HIT_VALUES: dict[str, float] = {
    "perfect": 1.0,
    "great": 0.95,
    "good": 0.8,
    "meh": 0.5,
    "miss": 0.0,
}


def simulate_replay(
    *,
    map_path: Path,
    analysis: Any | None = None,
    difficulty_report: DifficultyReport | None = None,
    difficulty: str = "normal",
    seed: int = 1,
    player_profile: str = "advanced",
    player_overrides: dict[str, Any] | None = None,
) -> ReplayReport:
    """Run the full deterministic replay simulation for one beatmap.

    Combines the virtual player model, cursor simulation, hit window
    simulation, combo simulation, pattern recognition, fatigue model, and
    reading simulation into one replay report with a composite replay score.

    Deterministic: identical map, analysis, difficulty, seed, and player
    profile always produce identical reports.
    """
    map_file = ensure_existing_file(map_path, "Beatmap file")
    beatmap = load_difficulty_map(map_file)
    player = resolve_player_profile(player_profile, player_overrides)

    bpm = _resolve_bpm(analysis, beatmap)
    sections = _resolve_sections(difficulty_report, beatmap)

    rng_seed = _stable_seed(
        difficulty,
        seed,
        player.name,
        _map_signature(beatmap),
    )
    rng = random.Random(rng_seed)

    cursor = simulate_cursor(beatmap, player)
    fatigue = simulate_fatigue(beatmap, player, bpm=bpm, sections=sections)
    hits = simulate_hits(
        beatmap,
        player,
        rng,
        fatigue,
        bpm=bpm,
    )
    combo = simulate_combo(hits.events)
    patterns = recognize_patterns(beatmap, player)
    reading = simulate_reading(beatmap)

    section_results = _build_section_results(beatmap, sections, hits.events, fatigue.samples)
    weakest = sorted(
        section_results,
        key=lambda section: (section.miss_rate, section.fatigue_peak),
        reverse=True,
    )[:3]
    strongest = sorted(
        section_results,
        key=lambda section: (section.miss_rate, section.fatigue_peak),
    )[:3]

    object_count = max(1, beatmap.object_count)
    breakdown = compute_replay_score(
        accuracy=hits.expected_accuracy,
        miss_rate=hits.expected_misses / object_count,
        combo_pct=combo.expected_combo_pct,
        full_combo_chance=hits.full_combo_chance,
        reading_score=reading.score,
        cursor_efficiency=cursor.efficiency,
        fatigue_average=fatigue.average,
        rhythm_consistency=hits.timing_consistency,
        weights=ReplayScoreWeights(),
    )

    return ReplayReport(
        version=1,
        map_title=beatmap.title,
        map_artist=beatmap.artist,
        difficulty=difficulty,
        object_count=beatmap.object_count,
        duration_ms=_duration_ms(beatmap),
        bpm=round(bpm, 2),
        approach_time_ms=beatmap.approach_time_ms,
        player=player,
        seed=rng_seed,
        cursor=cursor,
        hit_events=hits.events,
        expected_accuracy=hits.expected_accuracy,
        expected_misses=hits.expected_misses,
        full_combo_chance=hits.full_combo_chance,
        result_counts=hits.result_counts,
        timing_consistency=hits.timing_consistency,
        peak_stress_ms=hits.peak_stress_ms,
        combo=combo,
        patterns=patterns,
        fatigue=fatigue,
        reading=reading,
        sections=section_results,
        weakest_sections=weakest,
        strongest_sections=strongest,
        score_breakdown=breakdown,
    )


def replay_generator_metadata(report: ReplayReport, replay_report_path: str) -> dict[str, Any]:
    """Compact replay summary embedded into the beatmap generator metadata."""
    weakest = report.weakest_sections[0] if report.weakest_sections else None
    strongest = report.strongest_sections[0] if report.strongest_sections else None
    return {
        "playerProfile": report.player.name,
        "replayScore": round(report.score_breakdown.overall, 2),
        "expectedAccuracy": report.expected_accuracy,
        "expectedMisses": report.expected_misses,
        "expectedComboPct": report.combo.expected_combo_pct,
        "fullComboChance": report.full_combo_chance,
        "readingScore": report.reading.score,
        "cursorEfficiency": report.cursor.efficiency,
        "fatigueAverage": report.fatigue.average,
        "fatiguePeak": report.fatigue.peak,
        "comboBreaks": report.combo.combo_breaks,
        "missClusters": report.combo.miss_clusters,
        "hardestPattern": report.patterns.hardest_pattern,
        "weakestSection": weakest.label if weakest else "",
        "strongestSection": strongest.label if strongest else "",
        "replayReportPath": replay_report_path,
    }


def format_replay_summary(report: ReplayReport) -> str:
    lines = [
        "Replay simulation complete",
        "",
        f"Map: {report.map_title} - {report.map_artist}",
        f"Difficulty: {report.difficulty}",
        f"Objects: {report.object_count}",
        f"BPM: {report.bpm:.1f}",
        f"Player profile: {report.player.label}",
        "",
        f"Replay score: {report.score_breakdown.overall:.1f}",
        f"Expected accuracy: {report.expected_accuracy:.1%}",
        f"Expected misses: {report.expected_misses:.2f}",
        f"Full combo chance: {report.full_combo_chance:.1%}",
        f"Expected combo: {report.combo.expected_combo_pct:.0%} of objects",
        f"Combo breaks: {report.combo.combo_breaks}",
        "",
        f"Reading score: {report.reading.score:.1f}",
        f"Cursor efficiency: {report.cursor.efficiency:.0%}",
        f"Cursor travel: {report.cursor.total_travel_px:.0f}px",
        f"Fatigue (avg/peak): {report.fatigue.average:.0%} / {report.fatigue.peak:.0%}",
        f"Hardest pattern: {report.patterns.hardest_pattern}",
        f"Peak stress at: {report.peak_stress_ms}ms",
        "",
        "Score breakdown",
        f"Accuracy prediction: {report.score_breakdown.accuracy_prediction:.1f}",
        f"Miss prediction: {report.score_breakdown.miss_prediction:.1f}",
        f"Combo stability: {report.score_breakdown.combo_stability:.1f}",
        f"Reading: {report.score_breakdown.reading:.1f}",
        f"Cursor efficiency: {report.score_breakdown.cursor_efficiency:.1f}",
        f"Fatigue: {report.score_breakdown.fatigue:.1f}",
        f"Rhythm consistency: {report.score_breakdown.rhythm_consistency:.1f}",
    ]
    if report.weakest_sections:
        lines.extend(["", "Weakest sections"])
        for section in report.weakest_sections:
            lines.append(
                f"- {section.label}: {section.miss_rate:.0%} misses, "
                f"accuracy {section.accuracy:.1%}, fatigue peak {section.fatigue_peak:.0%}"
            )
    if report.strongest_sections:
        lines.extend(["", "Strongest sections"])
        for section in report.strongest_sections:
            lines.append(
                f"- {section.label}: {section.miss_rate:.0%} misses, "
                f"accuracy {section.accuracy:.1%}"
            )
    return "\n".join(lines)


def _resolve_bpm(analysis: Any | None, beatmap) -> float:
    if analysis is not None:
        bpm = getattr(analysis, "bpm", None)
        if isinstance(bpm, (int, float)) and bpm > 0:
            return clamp(float(bpm), 40.0, 400.0)
    gaps = [
        right.time - left.time
        for left, right in zip(beatmap.objects, beatmap.objects[1:], strict=False)
        if right.time > left.time
    ]
    if gaps:
        median_gap = sorted(gaps)[len(gaps) // 2]
        return clamp(60000.0 / max(1, median_gap), 40.0, 400.0)
    return 120.0


def _resolve_sections(
    difficulty_report: DifficultyReport | None,
    beatmap,
) -> list[SectionReplayResult]:
    if difficulty_report is not None and difficulty_report.sections:
        return [
            SectionReplayResult(
                section_id=section.section_id,
                label=section.label,
                start_ms=section.start_ms,
                end_ms=section.end_ms,
                object_count=0,
                miss_rate=0.0,
                accuracy=0.0,
                fatigue_peak=0.0,
                reading_demand=0.0,
            )
            for section in difficulty_report.sections
        ]
    return _fallback_sections(beatmap)


def _fallback_sections(beatmap) -> list[SectionReplayResult]:
    objects = beatmap.objects
    if not objects:
        return []
    start = objects[0].time
    end = objects[-1].end_time or objects[-1].time
    span = max(4000, end - start)
    count = max(2, round(span / 8000))
    step = span / count
    sections: list[SectionReplayResult] = []
    for index in range(count):
        section_start = start + round(index * step)
        section_end = start + round((index + 1) * step)
        sections.append(
            SectionReplayResult(
                section_id=index + 1,
                label=f"Section {index + 1}",
                start_ms=section_start,
                end_ms=section_end,
                object_count=0,
                miss_rate=0.0,
                accuracy=0.0,
                fatigue_peak=0.0,
                reading_demand=0.0,
            )
        )
    return sections


def _build_section_results(
    beatmap,
    sections: list[SectionReplayResult],
    events,
    fatigue_samples,
) -> list[SectionReplayResult]:
    event_by_id = {event.object_id: event for event in events}
    fatigue_by_time = {sample.time_ms: sample.fatigue for sample in fatigue_samples}
    output: list[SectionReplayResult] = []
    for section in sections:
        positioned = [
            item
            for item in beatmap.objects
            if item.is_positioned and section.start_ms <= item.time < section.end_ms
        ]
        if not positioned:
            output.append(
                SectionReplayResult(
                    section_id=section.section_id,
                    label=section.label,
                    start_ms=section.start_ms,
                    end_ms=section.end_ms,
                    object_count=0,
                    miss_rate=0.0,
                    accuracy=0.0,
                    fatigue_peak=0.0,
                    reading_demand=0.0,
                )
            )
            continue
        demands: list[float] = []
        misses = 0
        accuracy_sum = 0.0
        fatigue_peak = 0.0
        for item in positioned:
            event = event_by_id.get(item.id)
            if event is None:
                continue
            demands.append(event.demand)
            accuracy_sum += _HIT_VALUES.get(event.result, 0.0)
            if event.result == "miss":
                misses += 1
            fatigue_peak = max(fatigue_peak, fatigue_by_time.get(item.time, 0.0))
        object_count = len(demands) or 1
        output.append(
            SectionReplayResult(
                section_id=section.section_id,
                label=section.label,
                start_ms=section.start_ms,
                end_ms=section.end_ms,
                object_count=len(positioned),
                miss_rate=round(misses / object_count, 4),
                accuracy=round(accuracy_sum / object_count, 4),
                fatigue_peak=round(fatigue_peak, 4),
                reading_demand=round(mean(demands) if demands else 0.0, 4),
            )
        )
    return output


def _duration_ms(beatmap) -> int:
    if not beatmap.objects:
        return 0
    end = beatmap.objects[-1].end_time or beatmap.objects[-1].time
    start = beatmap.objects[0].time
    return max(0, end - start)


def _stable_seed(*parts: Any) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _map_signature(beatmap) -> str:
    digest = hashlib.sha256()
    for item in beatmap.objects:
        digest.update(
            f"{item.id}:{item.object_type}:{item.time}:{item.x}:{item.y}\n".encode("utf-8")
        )
    return digest.hexdigest()[:16]
