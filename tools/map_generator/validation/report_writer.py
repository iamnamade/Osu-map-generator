from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .models import ReportSummary, SEVERITY_ORDER, ValidationIssue, ValidationReport


def write_validation_report(path: Path, report: ValidationReport) -> None:
    write_json(path, report.to_dict())


def sort_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            -SEVERITY_ORDER[issue.severity],
            issue.start_time_ms if issue.start_time_ms is not None else 10**12,
            issue.end_time_ms if issue.end_time_ms is not None else 10**12,
            issue.category,
            issue.code,
            tuple(issue.object_ids),
        ),
    )


def build_summary(issues: list[ValidationIssue]) -> ReportSummary:
    return ReportSummary(
        critical=sum(1 for issue in issues if issue.severity == "critical"),
        errors=sum(1 for issue in issues if issue.severity == "error"),
        warnings=sum(1 for issue in issues if issue.severity == "warning"),
        info=sum(1 for issue in issues if issue.severity == "info"),
    )


def format_validation_console_report(
    report: ValidationReport,
    *,
    report_path: Path | None,
    verbose: bool = False,
) -> str:
    lines = [
        "Beatmap validation complete",
        "",
        f"Map: {report.map_info.title}",
        f"Difficulty: {report.map_info.difficulty}",
        f"Objects: {report.map_info.object_count}",
        f"Playable: {'yes' if report.playable else 'no'}",
        "",
        f"Overall score: {report.scores.overall:.1f} / 100",
        f"Interpretation: {report.interpretation}",
        "",
        f"Structural: {report.scores.structural:.1f}",
        f"Timing: {report.scores.timing:.1f}",
        f"Rhythm: {report.scores.rhythm:.1f}",
        f"Movement: {report.scores.movement:.1f}",
        f"Readability: {report.scores.readability:.1f}",
        f"Spatial balance: {report.scores.spatial_balance:.1f}",
        f"Repetition: {report.scores.repetition:.1f}",
        f"Density consistency: {report.scores.density_consistency:.1f}",
        f"Difficulty consistency: {report.scores.difficulty_consistency:.1f}",
        "",
        f"Critical: {report.summary.critical}",
        f"Errors: {report.summary.errors}",
        f"Warnings: {report.summary.warnings}",
        f"Info: {report.summary.info}",
    ]

    if report_path is not None:
        lines.extend(["", "Report:", report_path.as_posix()])

    visible_issues = report.issues if verbose else report.issues[:5]
    if visible_issues:
        heading = "Issues" if verbose else "Top issues"
        lines.extend(["", heading])
        for issue in visible_issues:
            context = []
            if issue.start_time_ms is not None:
                context.append(f"t={issue.start_time_ms}ms")
            if issue.object_ids:
                context.append("objects=" + ",".join(str(item) for item in issue.object_ids[:5]))
            lines.append(
                f"- [{issue.severity}] {issue.code}: {issue.message}"
                + (f" ({'; '.join(context)})" if context else "")
            )

    return "\n".join(lines)


def format_report_comparison(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise MapGeneratorError("No validation reports were found to compare.")

    leader = rows[0]
    lines = ["Validation report comparison", ""]
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. {row['label']} - {row['overall']:.1f}")

    lines.extend(["", "Differences from best"])
    for row in rows[1:]:
        deltas = []
        for key in (
            "structural",
            "timing",
            "rhythm",
            "movement",
            "readability",
            "spatialBalance",
            "repetition",
            "densityConsistency",
            "difficultyConsistency",
        ):
            delta = row["scores"][key] - leader["scores"][key]
            deltas.append(f"{key} {delta:+.1f}")
        lines.append(f"{row['label']}: overall {row['overall'] - leader['overall']:+.1f}; " + ", ".join(deltas))

    return "\n".join(lines)
