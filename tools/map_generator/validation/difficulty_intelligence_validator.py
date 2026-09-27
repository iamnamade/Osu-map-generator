from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..difficulty import analyze_difficulty
from ..utils import MapGeneratorError, ensure_existing_file
from .models import ValidationIssue

# Map engine verification severities onto the standard validator severity set.
SEVERITY_MAP = {
    "info": "info",
    "warning": "warning",
    "error": "error",
    "critical": "critical",
}


@dataclass(frozen=True)
class DifficultyIntelligenceValidationResult:
    issues: list[ValidationIssue]
    star_rating: float
    recommended_player_level: str
    peak_difficulty: float
    average_difficulty: float
    consistency_score: float


def validate_difficulty_intelligence(
    *,
    map_path: Path,
    difficulty: str,
    analysis_path: Path | None = None,
    sections_path: Path | None = None,
    seed: int = 1,
    target_name: str | None = None,
) -> DifficultyIntelligenceValidationResult:
    """Run the Phase 13 difficulty intelligence engine and surface its
    verification issues as standard validator issues.

    Verifies difficulty consistency, target tolerance, section balance,
    impossible spikes, and reasonable transitions.
    """
    beatmap_file = ensure_existing_file(map_path, "Beatmap file")
    try:
        result = analyze_difficulty(
            map_path=beatmap_file,
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=None,
            map_label=beatmap_file.as_posix(),
            sections_path=sections_path,
            seed=seed,
            target_name=target_name,
        )
    except (MapGeneratorError, ValueError) as error:
        raise MapGeneratorError(
            f"Difficulty intelligence failed for {beatmap_file}: {error}"
        ) from error

    report = result.report
    issues: list[ValidationIssue] = []
    for issue in report.verification:
        issues.append(
            ValidationIssue(
                code=issue.code,
                severity=SEVERITY_MAP.get(issue.severity, "warning"),
                message=issue.message,
                category="difficultyConsistency",
                measured_value=issue.measured_value,
                allowed_value=issue.allowed_value,
                suggestion=(
                    "Rebalance density, movement, or section transitions to match the target profile."
                    if issue.code in ("DIFFICULTY_TARGET_TOLERANCE", "DIFFICULTY_SECTION_IMBALANCE", "DIFFICULTY_IMPOSSIBLE_SPIKE")
                    else None
                ),
            )
        )

    return DifficultyIntelligenceValidationResult(
        issues=issues,
        star_rating=report.star_rating.overall,
        recommended_player_level=report.recommended_player_level,
        peak_difficulty=report.peak_difficulty,
        average_difficulty=report.average_difficulty,
        consistency_score=report.consistency_score,
    )
