from __future__ import annotations

from .models import (
    EvolutionComparisonEntry,
    EvolutionDimensionScores,
)

_DIMENSION_LABELS: dict[str, str] = {
    "quality": "Quality",
    "difficulty": "Difficulty match",
    "flow": "Flow",
    "rhythm": "Rhythm",
    "movement": "Movement",
    "pattern": "Pattern",
    "slider": "Slider",
    "spinner": "Spinner",
    "reading": "Reading",
    "playability": "Playability",
    "consistency": "Consistency",
    "confidence": "Confidence",
    "replay": "Replay",
}


def build_comparison(
    *,
    champion: EvolutionDimensionScores,
    runner: EvolutionDimensionScores,
    improvement_gain: float,
) -> tuple[list[EvolutionComparisonEntry], list[str]]:
    """Compare the champion against the runner-up dimension by dimension.

    Returns the comparison table and a list of human-readable reasons that
    explain where the champion gained and lost points.
    """
    champion_values = dict(champion.as_ordered_values())
    runner_values = dict(runner.as_ordered_values())
    entries: list[EvolutionComparisonEntry] = []
    for dimension, champion_value in champion_values.items():
        runner_value = runner_values[dimension]
        delta = champion_value - runner_value
        label = _DIMENSION_LABELS.get(dimension, dimension)
        if abs(delta) < 0.05:
            note = f"Even on {label}."
        elif delta > 0:
            note = f"Champion leads by {delta:.1f} points on {label}."
        else:
            note = f"Runner-up leads by {abs(delta):.1f} points on {label}."
        entries.append(
            EvolutionComparisonEntry(
                dimension=dimension,
                champion_value=champion_value,
                runner_value=runner_value,
                delta=delta,
                note=note,
            )
        )

    gained = [
        entry
        for entry in entries
        if entry.delta > 0.05
    ]
    lost = [
        entry
        for entry in entries
        if entry.delta < -0.05
    ]
    gained.sort(key=lambda entry: entry.delta, reverse=True)
    lost.sort(key=lambda entry: entry.delta)

    reasons: list[str] = []
    for entry in gained[:4]:
        reasons.append(
            f"Champion gained {entry.delta:.1f} points on {_DIMENSION_LABELS.get(entry.dimension, entry.dimension)} "
            f"({entry.champion_value:.1f} vs {entry.runner_value:.1f})."
        )
    for entry in lost[:4]:
        reasons.append(
            f"Champion lost {abs(entry.delta):.1f} points on {_DIMENSION_LABELS.get(entry.dimension, entry.dimension)} "
            f"({entry.champion_value:.1f} vs {entry.runner_value:.1f})."
        )
    if improvement_gain > 0.05:
        reasons.append(
            f"Champion carried {improvement_gain:.1f} points of improvement from the evolution passes."
        )
    if not reasons:
        reasons.append("The champion edged out the runner-up by a narrow overall margin.")
    return entries, reasons


def format_comparison_table(entries: list[EvolutionComparisonEntry]) -> str:
    lines = ["Dimension comparison (champion vs runner-up)", ""]
    lines.append(f"{'Dimension':<18} {'Champion':>9} {'Runner':>9} {'Delta':>8}")
    for entry in entries:
        lines.append(
            f"{_DIMENSION_LABELS.get(entry.dimension, entry.dimension):<18} "
            f"{entry.champion_value:>9.1f} {entry.runner_value:>9.1f} "
            f"{entry.delta:>+8.1f}"
        )
    return "\n".join(lines)
