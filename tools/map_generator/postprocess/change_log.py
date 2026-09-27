from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError, write_json
from .models import CorrectionAction, CorrectionReport


def write_correction_report(path: Path, report: CorrectionReport) -> None:
    write_json(path, report.to_dict())


def format_improvement_console_report(
    *,
    title: str,
    difficulty: str,
    seed: int,
    correction_report: CorrectionReport,
    output_map_path: Path,
    output_report_path: Path,
    changes_output_path: Path,
    verbose: bool = False,
) -> str:
    lines = [
        "Beatmap improvement complete",
        "",
        f"Map: {title}",
        f"Difficulty: {difficulty}",
        f"Seed: {seed}",
        "",
        f"Before score: {correction_report.before.overall_score:.1f}",
        f"After score: {correction_report.after.overall_score:.1f}",
        f"Change: {correction_report.score_changes.overall:+.1f}",
        "",
        f"Accepted corrections: {correction_report.summary.accepted_actions}",
        f"Reverted corrections: {correction_report.summary.reverted_actions}",
        "",
        f"Moved objects: {correction_report.summary.moved_objects}",
        f"Timing adjustments: {correction_report.summary.timing_adjustments}",
        f"Removed objects: {correction_report.summary.removed_objects}",
        f"Inserted objects: {correction_report.summary.inserted_objects}",
    ]

    if correction_report.accepted:
        lines.extend(
            [
                "",
                "Improved map:",
                output_map_path.as_posix(),
                "",
                "Improved report:",
                output_report_path.as_posix(),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Improved map:",
                "Original map kept",
            ]
        )
        if correction_report.rejection_reason:
            lines.append(f"Reason: {correction_report.rejection_reason}")

    lines.extend(["", "Correction log:", changes_output_path.as_posix()])

    visible_actions = correction_report.actions if verbose else _top_actions(correction_report.actions)
    if visible_actions:
        lines.extend(["", "Most important corrections"])
        for action in visible_actions:
            status = "accepted" if action.accepted else "reverted"
            lines.append(
                f"- [{status}] {action.action_id}: {action.reason_code} "
                f"({action.action_type}, objects={','.join(str(item) for item in action.object_ids) or 'n/a'}, "
                f"delta={action.actual_score_impact:+.2f})"
            )

    return "\n".join(lines)


def format_improvement_comparison(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise MapGeneratorError("No improvement report pairs were found to compare.")

    lines = ["Improvement comparison", ""]
    for index, row in enumerate(rows, start=1):
        status = str(row.get("status", "unknown"))
        lines.append(
            f"{index}. {row['label']} - {row['before']:.1f} -> {row['after']:.1f} "
            f"({row['delta']:+.1f}, {status})"
        )

    return "\n".join(lines)


def _top_actions(actions: list[CorrectionAction]) -> list[CorrectionAction]:
    ranked = sorted(
        actions,
        key=lambda action: (
            0 if action.accepted else 1,
            -action.confidence,
            -abs(action.actual_score_impact),
            action.action_id,
        ),
    )
    return ranked[:5]
