from __future__ import annotations

from pathlib import Path

from ..utils import write_json
from .models import OsuExportReport, OsuImportReport, OsuValidationResult, OszPackageResult


def write_export_report(path: Path, report: OsuExportReport) -> None:
    write_json(path, report.to_dict())


def write_import_report(path: Path, report: OsuImportReport) -> None:
    write_json(path, report.to_dict())


def format_export_console_report(
    report: OsuExportReport,
    *,
    report_path: Path,
) -> str:
    lines = [
        "osu export complete",
        "",
        f"Title: {report.title}",
        f"Artist: {report.artist}",
        f"Version: {report.version}",
        f"Objects: {report.object_count}",
        f"BPM: {report.bpm:.3f}",
        f"Offset: {report.offset_ms} ms",
        f"Audio filename: {report.audio_filename}",
        f"Validation: {'ok' if report.validation.valid else 'warnings'}",
        "",
        f"osu file: {report.output_osu_path}",
        f"Report: {report_path.as_posix()}",
    ]
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def format_import_console_report(
    report: OsuImportReport,
    *,
    report_path: Path,
) -> str:
    lines = [
        "osu import complete",
        "",
        f"Title: {report.metadata.get('title', 'Imported Beatmap')}",
        f"Artist: {report.metadata.get('artist', 'Unknown Artist')}",
        f"Version: {report.metadata.get('version', 'Imported')}",
        f"Circle count: {report.circle_count}",
        f"Spinner count: {report.spinner_count}",
        f"Unsupported objects: {report.unsupported_count}",
        f"Skipped objects: {report.skipped_count}",
        f"Timing points: {report.timing_point_count}",
        f"Validation: {'ok' if report.validation.valid else 'warnings'}",
        "",
        f"Project JSON: {report.output_json_path}",
        f"Report: {report_path.as_posix()}",
    ]
    if report.conversion_warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in report.conversion_warnings)
    return "\n".join(lines)


def format_osu_validation_console_report(result: OsuValidationResult, *, input_path: Path) -> str:
    lines = [
        "osu validation complete",
        "",
        f"Input: {input_path.as_posix()}",
        f"Validation: {'ok' if result.valid else 'warnings'}",
        f"Unsupported sliders: {result.unsupported_counts['slider']}",
        f"Unsupported spinners: {result.unsupported_counts['spinner']}",
        f"Unsupported holds: {result.unsupported_counts['hold']}",
        f"Unsupported unknown: {result.unsupported_counts['unknown']}",
    ]
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines)


def format_package_console_report(result: OszPackageResult) -> str:
    lines = [
        "osz packaging complete",
        "",
        f"Archive: {result.output_path}",
        "Contents:",
    ]
    lines.extend(f"- {item}" for item in result.archived_files)
    return "\n".join(lines)
