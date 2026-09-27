from __future__ import annotations

from .common import clamp, mean, standard_deviation
from .loader import LoadedDifficultyMap
from .models import (
    DifficultyDiagnostics,
    ObjectDifficulty,
    PatternDifficulty,
    SectionDifficulty,
)


def build_diagnostics(
    beatmap: LoadedDifficultyMap,
    *,
    object_scores: list[tuple[int, str, int, float]],
    patterns: list[PatternDifficulty],
    sections: list[SectionDifficulty],
    section_scores: list[float],
    star_calculation_summary: dict,
) -> DifficultyDiagnostics:
    """Build debugging-only diagnostics from per-object scores and sections."""
    histogram: dict[str, int] = {}
    for bucket in range(10):
        histogram[f"{bucket * 10}-{(bucket + 1) * 10}"] = 0
    for _, _, _, score in object_scores:
        normalized = clamp(score, 0.0, 1.0) * 10.0
        bucket = min(9, int(normalized))
        key = f"{bucket * 10}-{(bucket + 1) * 10}"
        histogram[key] = histogram.get(key, 0) + 1

    total_score = sum(score for _, _, _, score in object_scores)
    contributions: list[ObjectDifficulty] = []
    for object_id, object_type, time_ms, score in object_scores:
        contribution = score / max(1e-6, total_score)
        contributions.append(
            ObjectDifficulty(
                object_id=object_id,
                object_type=object_type,
                time_ms=time_ms,
                score=round(score, 4),
                contribution=round(contribution, 4),
            )
        )
    contributions.sort(key=lambda item: (-item.score, item.time_ms))

    hardest_patterns = sorted(patterns, key=lambda item: -item.score)[:5]

    hardest_section = None
    if sections:
        hardest_section = max(sections, key=lambda item: item.difficulty_score)

    difficulty_variance = (
        standard_deviation(section_scores) if section_scores else 0.0
    )

    return DifficultyDiagnostics(
        difficulty_histogram=histogram,
        object_contribution=contributions[:50],
        hardest_patterns=hardest_patterns,
        hardest_section=hardest_section,
        difficulty_variance=difficulty_variance,
        star_calculation_summary=star_calculation_summary,
    )


def compute_object_scores(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    aim_score: float,
    reading_score: float,
    rhythm_score: float,
) -> list[tuple[int, str, int, float]]:
    """Per-object difficulty scores used for contribution diagnostics."""
    positioned = [item for item in beatmap.objects if item.is_positioned]
    scores: list[tuple[int, str, int, float]] = []
    for index, item in enumerate(positioned):
        previous_time = positioned[index - 1].time if index > 0 else item.time
        next_time = positioned[index + 1].time if index + 1 < len(positioned) else item.time
        reaction = max(0, item.time - previous_time)
        gap_to_next = max(0, next_time - item.time)
        local_density = 1000.0 / max(1, reaction + gap_to_next)
        score = clamp(
            (1.0 - clamp(reaction / 600.0, 0.0, 1.0)) * 0.35
            + local_density / 8.0 * 0.3
            + aim_score * 0.2
            + reading_score * 0.1
            + rhythm_score * 0.05,
            0.0,
            1.0,
        )
        scores.append((item.id, item.object_type, item.time, round(score, 4)))
    return scores
