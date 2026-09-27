from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json
from ..utils import MapGeneratorError, ensure_existing_file, write_json
from .aim import analyze_aim
from .curves import build_difficulty_curve
from .diagnostics import build_diagnostics, compute_object_scores
from .gameplay import analyze_gameplay
from .loader import load_difficulty_map, load_song_sections
from .metrics import compute_raw_metrics
from .models import (
    DifficultyMapInfo,
    DifficultyReport,
    SectionDifficulty,
    VerificationIssue,
)
from .patterns import score_patterns
from .reading import analyze_reading
from .rebalancer import plan_rebalancing
from .rhythm import analyze_rhythm
from .stamina import analyze_stamina
from .stars import compute_star_rating, compute_technical_score
from .models import DifficultyTarget
from .targets import (
    TargetDeviation,
    get_difficulty_target,
    is_target_match,
    resolve_target_for_preset,
)


@dataclass(frozen=True)
class DifficultyAnalysisResult:
    report: DifficultyReport
    rebalance_plan: Any
    console_report: str


def analyze_difficulty(
    *,
    map_path: Path,
    analysis_path: Path | None,
    difficulty: str,
    output_path: Path | None = None,
    map_label: str | None = None,
    sections_path: Path | None = None,
    seed: int = 1,
    target_name: str | None = None,
    target: DifficultyTarget | None = None,
) -> DifficultyAnalysisResult:
    """Run the full difficulty intelligence pipeline for one beatmap.

    Deterministic: identical map, analysis, sections, difficulty, and seed
    always produce an identical report.
    """
    beatmap_file = ensure_existing_file(map_path, "Beatmap file")
    beatmap = load_difficulty_map(beatmap_file, map_label=map_label)

    if target is not None:
        resolved_target = target
    else:
        resolved_target = (
            get_difficulty_target(target_name)
            if target_name
            else resolve_target_for_preset(difficulty)
        )

    analysis = None
    if analysis_path is not None:
        analysis_file = ensure_existing_file(analysis_path, "Analysis file")
        analysis = load_analysis_json(analysis_file)

    sections = load_song_sections(sections_path)
    metrics = compute_raw_metrics(beatmap)

    reading = analyze_reading(
        beatmap,
        metrics=metrics,
        approach_time_ms=beatmap.approach_time_ms,
    )
    rhythm = analyze_rhythm(
        beatmap,
        metrics=metrics,
        bpm=analysis.bpm if analysis is not None else None,
    )
    aim = analyze_aim(beatmap, metrics=metrics)
    stamina = analyze_stamina(beatmap, metrics=metrics)

    patterns = score_patterns(beatmap, metrics=metrics)
    technical_score = compute_technical_score(metrics, patterns)
    star_rating = compute_star_rating(
        metrics,
        aim,
        reading,
        rhythm,
        stamina,
        technical_score,
    )

    section_difficulties = _build_section_difficulties(
        beatmap,
        metrics=metrics,
        reading_score=reading.score,
        rhythm_score=rhythm.score,
        aim_score=aim.score,
        sections=sections,
    )
    section_scores = [section.difficulty_score for section in section_difficulties]

    curve = build_difficulty_curve(
        beatmap,
        metrics=metrics,
        reading_score=reading.score,
        rhythm_score=rhythm.score,
    )

    object_scores = compute_object_scores(
        beatmap,
        metrics=metrics,
        aim_score=aim.score,
        reading_score=reading.score,
        rhythm_score=rhythm.score,
    )
    object_difficulties = build_diagnostics(
        beatmap,
        object_scores=object_scores,
        patterns=patterns,
        sections=section_difficulties,
        section_scores=section_scores,
        star_calculation_summary=_build_star_summary(star_rating),
    ).object_contribution

    gameplay = analyze_gameplay(
        beatmap,
        metrics=metrics,
        aim_score=aim.score,
        reading_score=reading.score,
        rhythm_score=rhythm.score,
        stamina_score=stamina.score,
    )

    verification = _verify(
        star_rating.overall,
        resolved_target,
        section_scores,
        curve,
    )

    peak_difficulty = max(curve, key=lambda item: item.difficulty_score).difficulty_score if curve else 0.0
    average_difficulty = (
        sum(item.difficulty_score for item in curve) / len(curve) if curve else 0.0
    )
    consistency_score = _consistency_score(section_scores)
    confidence_score = _confidence_score(section_scores)

    diagnostics = build_diagnostics(
        beatmap,
        object_scores=object_scores,
        patterns=patterns,
        sections=section_difficulties,
        section_scores=section_scores,
        star_calculation_summary=_build_star_summary(star_rating),
    )

    heatmap = [
        {
            "startMs": section.start_ms,
            "endMs": section.end_ms,
            "difficultyScore": section.difficulty_score,
        }
        for section in section_difficulties
    ]

    signature = _build_signature(
        beatmap,
        difficulty,
        seed,
        resolved_target.name,
        star_rating.overall,
    )

    report = DifficultyReport(
        version=1,
        map=DifficultyMapInfo(
            path=map_label or beatmap_file.as_posix(),
            title=beatmap.title,
            artist=beatmap.artist,
            difficulty=difficulty,
            object_count=beatmap.object_count,
            duration_ms=metrics.active_duration_ms,
            approach_time_ms=beatmap.approach_time_ms,
            circle_radius=beatmap.circle_radius,
        ),
        target=resolved_target,
        metrics=metrics,
        reading=reading,
        rhythm=rhythm,
        aim=aim,
        stamina=stamina,
        patterns=patterns,
        sections=section_difficulties,
        heatmap=heatmap,
        curve=curve,
        object_difficulty=object_difficulties,
        star_rating=star_rating,
        gameplay=gameplay,
        verification=verification,
        diagnostics=diagnostics,
        recommended_player_level=_recommended_level(star_rating.overall),
        consistency_score=consistency_score,
        peak_difficulty=peak_difficulty,
        average_difficulty=average_difficulty,
        confidence_score=confidence_score,
        signature=signature,
    )

    rebalance_plan = plan_rebalancing(
        beatmap,
        star_rating=star_rating.overall,
        target=resolved_target,
        metrics=metrics,
        object_scores=object_difficulties,
        seed=seed,
    )

    if output_path is not None:
        write_json(output_path, report.to_dict())

    return DifficultyAnalysisResult(
        report=report,
        rebalance_plan=rebalance_plan,
        console_report=_format_console_report(report, rebalance_plan, output_path),
    )


def _build_section_difficulties(
    beatmap,
    *,
    metrics,
    reading_score: float,
    rhythm_score: float,
    aim_score: float,
    sections: list[dict[str, Any]],
) -> list[SectionDifficulty]:
    if not sections:
        sections = _fallback_sections(beatmap)
    positioned = [item for item in beatmap.objects if item.is_positioned]
    output: list[SectionDifficulty] = []
    for index, section in enumerate(sections):
        start_ms = int(section["startMs"])
        end_ms = int(section["endMs"])
        label = str(section["label"])
        section_id = section.get("sectionId")
        in_window = [
            item for item in positioned if start_ms <= item.time < end_ms
        ]
        window_seconds = max(1.0, (end_ms - start_ms) / 1000.0)
        density = len(in_window) / window_seconds
        speeds = [
            (
                ((right.x - left.x) ** 2 + (right.y - left.y) ** 2) ** 0.5  # type: ignore[operator]
                / max(1, (right.time - left.time) / 1000.0)
            )
            for left, right in zip(in_window, in_window[1:], strict=False)
            if right.time > left.time
        ]
        speed = sum(speeds) / len(speeds) if speeds else 0.0

        difficulty_score = _section_score(
            density,
            speed,
            reading_score,
            rhythm_score,
            aim_score,
        )
        output.append(
            SectionDifficulty(
                section_id=section_id,
                label=label,
                start_ms=start_ms,
                end_ms=end_ms,
                difficulty_score=difficulty_score,
                density=round(density, 4),
                speed=round(speed, 4),
                reading=round(reading_score, 4),
                rhythm=round(rhythm_score, 4),
            )
        )
    return output


def _fallback_sections(beatmap) -> list[dict[str, Any]]:
    objects = beatmap.objects
    if not objects:
        return []
    start = objects[0].time
    end = objects[-1].end_time or objects[-1].time
    span = max(4000, end - start)
    count = max(2, round(span / 8000))
    step = span / count
    sections: list[dict[str, Any]] = []
    for index in range(count):
        section_start = start + round(index * step)
        section_end = start + round((index + 1) * step)
        sections.append(
            {
                "sectionId": index + 1,
                "label": f"Section {index + 1}",
                "startMs": section_start,
                "endMs": section_end,
            }
        )
    return sections


def _section_score(
    density: float,
    speed: float,
    reading_score: float,
    rhythm_score: float,
    aim_score: float,
) -> float:
    from .common import clamp, normalize

    return round(
        clamp(
            normalize(density, 3.5) * 0.35
            + normalize(speed, 900.0) * 0.3
            + reading_score * 0.15
            + rhythm_score * 0.1
            + aim_score * 0.1,
            0.0,
            1.0,
        ),
        4,
    )


def _verify(
    star_rating: float,
    target,
    section_scores: list[float],
    curve,
) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    if not is_target_match(star_rating, target):
        deviation = (
            target.star_range[0] - star_rating
            if star_rating < target.star_range[0]
            else star_rating - target.star_range[1]
        )
        direction = "below" if star_rating < target.star_range[0] else "above"
        issues.append(
            VerificationIssue(
                code="DIFFICULTY_TARGET_TOLERANCE",
                severity="warning" if abs(deviation) <= target.tolerance else "error",
                message=(
                    f"Star rating {star_rating:.2f} is {direction} the "
                    f"{target.name} target range {target.star_range[0]:.1f}-{target.star_range[1]:.1f}."
                ),
                measured_value=star_rating,
                allowed_value=target.star_center,
            )
        )

    if section_scores:
        peak = max(section_scores)
        average = sum(section_scores) / len(section_scores)
        if average > 0 and peak / average > 1.9:
            issues.append(
                VerificationIssue(
                    code="DIFFICULTY_SECTION_SPIKE",
                    severity="warning",
                    message="One section peaks well above the average difficulty.",
                    measured_value=peak / max(1e-6, average),
                    allowed_value=1.9,
                )
            )
        spread = max(section_scores) - min(section_scores)
        if spread > 0.55:
            issues.append(
                VerificationIssue(
                    code="DIFFICULTY_SECTION_IMBALANCE",
                    severity="warning",
                    message="Section difficulty varies widely across the song.",
                    measured_value=spread,
                    allowed_value=0.55,
                )
            )
        for index in range(1, len(section_scores)):
            transition = abs(section_scores[index] - section_scores[index - 1])
            if transition > 0.45:
                issues.append(
                    VerificationIssue(
                        code="DIFFICULTY_TRANSITION",
                        severity="info",
                        message="A section transition jumps more than expected.",
                        measured_value=transition,
                        allowed_value=0.45,
                    )
                )

    if curve:
        curve_values = [point.difficulty_score for point in curve]
        peak = max(curve_values)
        average = sum(curve_values) / len(curve_values)
        if average > 0 and peak / max(1e-6, average) > 2.2:
            issues.append(
                VerificationIssue(
                    code="DIFFICULTY_IMPOSSIBLE_SPIKE",
                    severity="error",
                    message="A short passage spikes far above the map's average difficulty.",
                    measured_value=peak / max(1e-6, average),
                    allowed_value=2.2,
                )
            )

    return issues


def _consistency_score(section_scores: list[float]) -> float:
    if not section_scores:
        return 0.0
    from .common import standard_deviation, mean

    average = mean(section_scores)
    if average <= 0:
        return 0.0
    cv = standard_deviation(section_scores) / average
    from .common import clamp

    return clamp(1.0 - cv * 1.5, 0.0, 1.0)


def _confidence_score(section_scores: list[float]) -> float:
    if not section_scores:
        return 0.5
    from .common import mean

    average = mean(section_scores)
    from .common import clamp

    return clamp(0.5 + average * 0.4, 0.0, 1.0)


def _recommended_level(star_rating: float) -> str:
    if star_rating < 1.6:
        return "Beginner"
    if star_rating < 2.6:
        return "Novice"
    if star_rating < 3.6:
        return "Intermediate"
    if star_rating < 4.8:
        return "Advanced"
    if star_rating < 6.0:
        return "Expert"
    return "Master"


def _build_star_summary(star_rating) -> dict[str, Any]:
    return {
        "weights": dict(star_rating.breakdown.get("weights", {})),
        "components": {
            key: value
            for key, value in star_rating.breakdown.items()
            if key not in ("weights",)
        },
    }


def _build_signature(
    beatmap,
    difficulty: str,
    seed: int,
    target_name: str,
    star_rating: float,
) -> str:
    digest = hashlib.sha256()
    for item in beatmap.objects:
        digest.update(f"{item.id}:{item.object_type}:{item.time}:{item.x}:{item.y}\n".encode("utf-8"))
    digest.update(f"difficulty={difficulty};seed={seed};target={target_name};stars={star_rating:.4f}".encode("utf-8"))
    return digest.hexdigest()[:16]


def _format_console_report(report: DifficultyReport, rebalance_plan, output_path: Path | None) -> str:
    lines = [
        "Difficulty intelligence complete",
        "",
        f"Map: {report.map.title} - {report.map.artist}",
        f"Difficulty: {report.map.difficulty}",
        f"Objects: {report.map.object_count}",
        f"Target: {report.target.name} ({report.target.star_range[0]:.1f}-{report.target.star_range[1]:.1f} stars)",
        "",
        f"Overall stars: {report.star_rating.overall:.2f}",
        f"Aim: {report.star_rating.aim:.2f}  Speed: {report.star_rating.speed:.2f}  Reading: {report.star_rating.reading:.2f}",
        f"Rhythm: {report.star_rating.rhythm:.2f}  Stamina: {report.star_rating.stamina:.2f}  Technical: {report.star_rating.technical:.2f}",
        f"Recommended level: {report.recommended_player_level}",
        "",
        f"Objects/sec: {report.metrics.objects_per_second:.2f}",
        f"Avg jump: {report.metrics.average_jump_distance:.1f}px",
        f"Avg cursor speed: {report.metrics.average_cursor_velocity_pps:.0f}px/s",
        f"Longest stream: {report.metrics.longest_stream_length}",
        f"Recovery windows: {report.metrics.recovery_window_count}",
        f"Estimated miss probability: {report.gameplay.estimated_miss_probability:.1%}",
        f"Combo stability: {report.gameplay.estimated_combo_stability:.0%}",
        "",
        f"Peak difficulty: {report.peak_difficulty:.3f}",
        f"Average difficulty: {report.average_difficulty:.3f}",
        f"Consistency: {report.consistency_score:.0%}",
        f"Confidence: {report.confidence_score:.0%}",
    ]
    if report.verification:
        lines.extend(["", "Verification"])
        for issue in report.verification:
            lines.append(f"- [{issue.severity}] {issue.code}: {issue.message}")
    if rebalance_plan.actions:
        lines.extend(["", "Rebalancing proposal"])
        lines.append(f"Direction: {rebalance_plan.deviation.direction} by {rebalance_plan.deviation.magnitude:.2f}")
        for action in rebalance_plan.actions[:8]:
            lines.append(f"- {action.action} on object {action.object_id}: {action.reason}")
    if output_path is not None:
        lines.extend(["", f"Report: {output_path.as_posix()}"])
    return "\n".join(lines)
