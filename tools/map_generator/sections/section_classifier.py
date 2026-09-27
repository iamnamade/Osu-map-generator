from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionClassification:
    label: str
    confidence: float
    energy_class: str


def classify_section(
    *,
    index: int,
    total: int,
    average_energy: float,
    energy_trend: str,
    beat_density: float,
    onset_density: float,
    rhythm_complexity: float,
    quiet_ratio: float,
    high_energy_ratio: float,
    emphasis_ratio: float,
    previous_energy: float | None,
    next_energy: float | None,
) -> SectionClassification:
    if average_energy < 0.28 or quiet_ratio >= 0.45:
        energy_class = "low"
    elif average_energy > 0.62 or high_energy_ratio >= 0.45:
        energy_class = "high"
    else:
        energy_class = "medium"

    label = "unknown"
    confidence = 0.52

    if index == 0 and energy_class != "high":
        label = "intro-like"
        confidence = 0.76 if energy_class == "low" else 0.68
    elif index == total - 1 and (energy_trend == "falling" or energy_class != "high"):
        label = "outro-like"
        confidence = 0.74
    elif energy_class == "low" and onset_density < 0.95:
        label = "quiet" if index == 0 else "break-like"
        confidence = 0.72
    elif (
        energy_trend == "rising"
        and next_energy is not None
        and next_energy > average_energy + 0.08
    ):
        label = "build-up"
        confidence = 0.71
    elif energy_class == "high" and onset_density >= 1.25:
        label = "drop-like" if emphasis_ratio >= 0.58 else "chorus-like"
        confidence = 0.8 if label == "drop-like" else 0.75
    elif rhythm_complexity < 0.26 and onset_density < 0.9 and beat_density >= 0.7:
        label = "instrumental"
        confidence = 0.63
    elif energy_class == "medium" and beat_density >= 0.75:
        label = "verse-like"
        confidence = 0.67
    elif (
        previous_energy is not None
        and average_energy + 0.1 < previous_energy
        and energy_class != "high"
    ):
        label = "bridge-like"
        confidence = 0.61

    return SectionClassification(
        label=label,
        confidence=confidence,
        energy_class=energy_class,
    )
