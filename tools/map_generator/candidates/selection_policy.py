from __future__ import annotations

import math
from typing import Any

from ..config import DifficultyPreset
from .candidate_config import EligibilityRules
from .candidate_models import CandidateStatus


def evaluate_candidate_status(
    *,
    original_map: dict[str, Any],
    improved_map: dict[str, Any],
    improved_report: Any,
    candidate_seed: int,
    expected_candidate_metadata: dict[str, object],
    files_complete: bool,
    preset: DifficultyPreset,
    rules: EligibilityRules,
) -> CandidateStatus:
    rejection_reasons: list[str] = []

    if not files_complete:
        rejection_reasons.append("Candidate output files are incomplete.")

    if not improved_report.valid:
        rejection_reasons.append("Improved report is not structurally valid.")

    if not improved_report.playable:
        rejection_reasons.append("Improved report is not safely playable.")

    # Allow a small proportion of critical issues for generated maps.
    # Timing-anchor criticals (< 5% of objects) are expected in generated
    # candidates and should not disqualify them outright.
    object_count = improved_report.map_info.object_count or 0
    max_critical = max(3, object_count // 20)  # up to 5 % of objects
    if improved_report.summary.critical > max_critical:
        rejection_reasons.append(
            f"Too many critical issues ({improved_report.summary.critical} > {max_critical})."
        )

    structural_errors = sum(
        1
        for issue in improved_report.issues
        if issue.category == "structural" and issue.severity in {"error", "critical"}
    )
    if structural_errors > 0:
        rejection_reasons.append("Unresolved structural errors remain in the improved candidate.")

    if improved_report.metrics.movement.highest_cursor_speed > preset.max_cursor_speed * rules.hard_speed_safety_multiplier + 1e-6:
        rejection_reasons.append("Maximum cursor speed exceeds the configured hard safety limit.")

    if improved_report.map_info.object_count <= 0:
        rejection_reasons.append("Candidate object count is zero.")

    if not _generator_metadata_matches(
        original_map=original_map,
        improved_map=improved_map,
        candidate_seed=candidate_seed,
        expected_candidate_metadata=expected_candidate_metadata,
    ):
        rejection_reasons.append("Deterministic integrity checks failed for candidate metadata.")

    for score in (
        improved_report.scores.structural,
        improved_report.scores.timing,
        improved_report.scores.rhythm,
        improved_report.scores.movement,
        improved_report.scores.readability,
        improved_report.scores.spatial_balance,
        improved_report.scores.repetition,
        improved_report.scores.density_consistency,
        improved_report.scores.difficulty_consistency,
        improved_report.scores.overall,
    ):
        if not math.isfinite(score):
            rejection_reasons.append("Improved report contains a non-finite score.")
            break

    return CandidateStatus(
        valid=bool(improved_report.valid),
        playable=bool(improved_report.playable),
        eligible=len(rejection_reasons) == 0,
        rejection_reasons=rejection_reasons,
    )


def _generator_metadata_matches(
    *,
    original_map: dict[str, Any],
    improved_map: dict[str, Any],
    candidate_seed: int,
    expected_candidate_metadata: dict[str, object],
) -> bool:
    original_generator = original_map.get("generator")
    improved_generator = improved_map.get("generator")
    if not isinstance(original_generator, dict) or not isinstance(improved_generator, dict):
        return False

    if original_generator.get("seed") != candidate_seed or improved_generator.get("seed") != candidate_seed:
        return False

    original_candidate = original_generator.get("candidate")
    improved_candidate = improved_generator.get("candidate")
    if not isinstance(original_candidate, dict) or not isinstance(improved_candidate, dict):
        return False

    for key, expected_value in expected_candidate_metadata.items():
        if original_candidate.get(key) != expected_value:
            return False
        if improved_candidate.get(key) != expected_value:
            return False

    return True
