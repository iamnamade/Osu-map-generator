from __future__ import annotations

from typing import Any

from ..difficulty.common import clamp, mean
from .models import EvolutionHeatmap

# Dimensions used for the comparison heatmaps. Each value is normalized 0..1
# where 1 is "more intense / better" depending on the dimension.
HEATMAP_DIMENSIONS: tuple[str, ...] = (
    "movement",
    "difficulty",
    "density",
    "reading",
    "spacing",
    "cursor-speed",
    "pattern-quality",
    "section-quality",
    "transition-quality",
)

_DIMENSION_LABELS: dict[str, str] = {
    "movement": "Movement",
    "difficulty": "Difficulty",
    "density": "Density",
    "reading": "Reading",
    "spacing": "Spacing",
    "cursor-speed": "Cursor speed",
    "pattern-quality": "Pattern quality",
    "section-quality": "Section quality",
    "transition-quality": "Transition quality",
}


def build_heatmaps(
    *,
    difficulty_reports: list[Any],
    ranking_indices: list[int],
) -> list[EvolutionHeatmap]:
    """Build per-dimension heatmaps across the ranked candidates.

    ``ranking_indices`` maps a leaderboard position to the original candidate
    index; values are ordered by rank so heatmap columns read Champion first.
    """
    by_index = {
        index: report
        for index, report in zip(ranking_indices, difficulty_reports, strict=False)
    }
    reports_in_rank_order = [
        by_index[index] for index in ranking_indices if index in by_index
    ]

    dimension_values: dict[str, list[float]] = {
        dimension: [] for dimension in HEATMAP_DIMENSIONS
    }
    for report in reports_in_rank_order:
        values = _single_report_values(report)
        for dimension in HEATMAP_DIMENSIONS:
            dimension_values[dimension].append(values[dimension])

    return [
        EvolutionHeatmap(
            dimension=dimension,
            label=_DIMENSION_LABELS.get(dimension, dimension),
            values=dimension_values[dimension],
        )
        for dimension in HEATMAP_DIMENSIONS
    ]


def _single_report_values(report) -> dict[str, float]:
    metrics = report.metrics
    star_rating = report.star_rating
    sections = report.sections
    section_scores = [section.difficulty_score for section in sections]

    section_quality = (
        mean(section_scores) if section_scores else 0.0
    )
    transitions = [
        abs(sections[index + 1].difficulty_score - sections[index].difficulty_score)
        for index in range(len(sections) - 1)
    ]
    transition_quality = (
        clamp(1.0 - (mean(transitions) / 0.5 if transitions else 0.0), 0.0, 1.0)
    )

    return {
        "movement": clamp(float(metrics.average_jump_distance) / 320.0, 0.0, 1.0),
        "difficulty": clamp(float(star_rating.overall) / 10.0, 0.0, 1.0),
        "density": clamp(float(metrics.objects_per_second) / 6.0, 0.0, 1.0),
        "reading": clamp(float(report.reading.score) / 100.0, 0.0, 1.0),
        "spacing": clamp(float(metrics.average_jump_distance) / 300.0, 0.0, 1.0),
        "cursor-speed": clamp(float(metrics.average_cursor_velocity_pps) / 1200.0, 0.0, 1.0),
        "pattern-quality": clamp(float(metrics.pattern_variation), 0.0, 1.0),
        "section-quality": clamp(section_quality, 0.0, 1.0),
        "transition-quality": clamp(transition_quality, 0.0, 1.0),
    }
