from __future__ import annotations

from .models import CorrectionPlan, PlannedIssue, ProcessingStage

SEVERITY_WEIGHT = {
    "critical": 400.0,
    "error": 300.0,
    "warning": 200.0,
    "info": 100.0,
}
CODE_BONUS = {
    "ROOT_NOT_OBJECT": 60.0,
    "MOVEMENT_SPEED_EXCEEDED": 55.0,
    "READABILITY_EXACT_STACKING": 45.0,
    "READABILITY_APPROACH_OVERLAP": 36.0,
    "TIMING_MISTIMED_OBJECT": 42.0,
    "DIFFICULTY_BEHAVIOR_INCONSISTENT": 20.0,
    "DENSITY_UNEXPLAINED_SPIKE": 18.0,
    "DENSITY_LOW_MAP_HIGH_AUDIO": 22.0,
    "DENSITY_HIGH_MAP_LOW_AUDIO": 22.0,
    "REPETITION_TWO_POINT_LOOP": 20.0,
}


def build_correction_plan(report: any) -> CorrectionPlan:
    issues_by_stage: dict[ProcessingStage, list[PlannedIssue]] = {
        "structural_safety": [],
        "timing_corrections": [],
        "movement_corrections": [],
        "stacking_corrections": [],
        "density_corrections": [],
        "repetition_corrections": [],
        "difficulty_corrections": [],
        "local_optimization": [],
    }

    for issue in report.issues:
        stage = _stage_for_issue(issue.code, issue.category)
        planned_issue = PlannedIssue(
            stage=stage,
            priority=_priority_for_issue(issue),
            confidence=_confidence_for_issue(issue),
            code=issue.code,
            severity=issue.severity,
            category=issue.category,
            object_ids=list(issue.object_ids),
            start_time_ms=issue.start_time_ms,
            end_time_ms=issue.end_time_ms,
            measured_value=issue.measured_value,
            allowed_value=issue.allowed_value,
        )
        issues_by_stage[stage].append(planned_issue)

    for stage, issues in issues_by_stage.items():
        issues_by_stage[stage] = sorted(
            issues,
            key=lambda issue: (
                -issue.priority,
                issue.start_time_ms if issue.start_time_ms is not None else 10**12,
                issue.code,
                tuple(issue.object_ids),
            ),
        )

    return CorrectionPlan(issues_by_stage=issues_by_stage)


def _stage_for_issue(code: str, category: str) -> ProcessingStage:
    if category == "structural":
        return "structural_safety"
    if code.startswith("TIMING_") or category == "timing":
        return "timing_corrections"
    if code.startswith("READABILITY_"):
        return "stacking_corrections"
    if code.startswith("MOVEMENT_") or code.startswith("SPATIAL_") or category in {"movement", "spatialBalance"}:
        return "movement_corrections"
    if category == "densityConsistency" or code.startswith("DENSITY_"):
        return "density_corrections"
    if category == "repetition" or code.startswith("REPETITION_"):
        return "repetition_corrections"
    if category == "difficultyConsistency" or code.startswith("DIFFICULTY_"):
        return "difficulty_corrections"
    return "local_optimization"


def _priority_for_issue(issue: any) -> float:
    magnitude = 0.0
    if issue.measured_value is not None and issue.allowed_value is not None:
        allowed = max(abs(issue.allowed_value), 1.0)
        magnitude = min(80.0, abs(issue.measured_value - issue.allowed_value) / allowed * 35.0)
    return (
        SEVERITY_WEIGHT.get(issue.severity, 0.0)
        + CODE_BONUS.get(issue.code, 0.0)
        + magnitude
        + min(len(issue.object_ids), 3) * 2.5
    )


def _confidence_for_issue(issue: any) -> float:
    base = {
        "critical": 0.95,
        "error": 0.86,
        "warning": 0.74,
        "info": 0.58,
    }.get(issue.severity, 0.55)
    if issue.measured_value is not None and issue.allowed_value is not None:
        allowed = max(abs(issue.allowed_value), 1.0)
        base += min(0.14, abs(issue.measured_value - issue.allowed_value) / allowed * 0.08)
    return round(min(0.99, base), 4)
