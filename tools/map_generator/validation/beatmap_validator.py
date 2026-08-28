from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json, load_json_file
from ..config import DIFFICULTY_PRESETS, DifficultyPreset, get_difficulty_preset
from ..models import AudioAnalysis, EnergyFrame, EnergyRegion, TimedStrength
from ..utils import MapGeneratorError, ensure_existing_file
from .collision_validator import validate_collisions
from .density_validator import validate_density
from .difficulty_validator import validate_difficulty
from .models import (
    DensityMetrics,
    DifficultyMetrics,
    MovementMetrics,
    ParsedBeatmap,
    ReportMapInfo,
    RepetitionMetrics,
    SpatialMetrics,
    StructuralMetrics,
    TimingMetrics,
    ValidationMetrics,
    ValidationReport,
)
from .movement_validator import validate_movement
from .quality_scorer import calculate_quality_scores
from .repetition_validator import validate_repetition
from .report_writer import build_summary, format_report_comparison, sort_issues, write_validation_report
from .rhythm_validator import validate_rhythm
from .spinner_validator import validate_spinners
from .structural_validator import validate_structural
from .timing_validator import validate_timing


@dataclass(frozen=True)
class ValidationRunResult:
    map_path: Path
    report_path: Path | None
    report: ValidationReport


def validate_beatmap(
    *,
    map_path: Path,
    analysis_path: Path,
    difficulty: str,
    output_path: Path | None = None,
    map_label: str | None = None,
    preset: DifficultyPreset | None = None,
    raw_map: dict[str, Any] | None = None,
    analysis: AudioAnalysis | None = None,
) -> ValidationRunResult:
    if raw_map is None:
        beatmap_file = ensure_existing_file(map_path, "Beatmap file")
        raw_map = _load_json(beatmap_file, "Beatmap JSON")
    else:
        beatmap_file = map_path
    if analysis is None:
        analysis_file = ensure_existing_file(analysis_path, "Analysis file")
        analysis = _load_analysis(analysis_file)

    try:
        resolved_preset = preset or get_difficulty_preset(difficulty)
    except ValueError as error:
        raise MapGeneratorError(str(error)) from error
    preset = resolved_preset

    structural = validate_structural(
        raw_map,
        map_path=Path(map_label or beatmap_file.as_posix()),
        analysis=analysis,
        preset=preset,
    )
    parsed_beatmap = structural.parsed_beatmap

    if parsed_beatmap is None or not parsed_beatmap.objects:
        metrics = _empty_metrics(structural.metrics, analysis.duration_ms)
        issues = sort_issues(structural.issues)
    else:
        timing = validate_timing(parsed_beatmap, analysis, preset)
        rhythm = validate_rhythm(parsed_beatmap, analysis, preset)
        movement = validate_movement(parsed_beatmap, analysis, preset)
        repetition = validate_repetition(parsed_beatmap, movement.pair_diagnostics, rhythm.gaps_ms)
        density = validate_density(parsed_beatmap, analysis, preset, timing.diagnostics, movement.pair_diagnostics)
        difficulty_result = validate_difficulty(
            parsed_beatmap,
            preset,
            timing.metrics,
            rhythm.metrics,
            movement.movement_metrics,
            movement.spatial_metrics,
        )
        spinner_result = validate_spinners(parsed_beatmap, analysis, preset)
        collision_result = validate_collisions(parsed_beatmap)

        combined_issues = [
            *structural.issues,
            *timing.issues,
            *rhythm.issues,
            *movement.issues,
            *repetition.issues,
            *density.issues,
            *difficulty_result.issues,
            *spinner_result.issues,
            *collision_result.issues,
        ]
        issues = sort_issues(combined_issues)
        density_metrics = _with_density_issue_counts(density.metrics, issues)
        metrics = ValidationMetrics(
            structural=structural.metrics,
            timing=timing.metrics,
            rhythm=rhythm.metrics,
            movement=movement.movement_metrics,
            spatial=movement.spatial_metrics,
            density=density_metrics,
            repetition=repetition.metrics,
            difficulty=difficulty_result.metrics,
        )

    summary = build_summary(issues)
    score_result = calculate_quality_scores(metrics=metrics, issues=issues, preset=preset)
    # Allow a small proportion of critical issues for generated maps.
    # Timing-anchor criticals are expected in generated candidates and
    # should not render an entire map invalid when the count is low.
    object_count = structural.metrics.object_count or 0
    max_critical = max(3, object_count // 20)  # up to 5 % of objects
    playable = summary.critical <= max_critical
    valid = (
        structural.parsed_beatmap is not None
        and structural.metrics.valid_object_count > 0
        and summary.critical <= max_critical
    )
    effective_beatmap = parsed_beatmap or _fallback_beatmap(structural, map_label or beatmap_file.as_posix())
    map_info = ReportMapInfo(
        path=map_label or beatmap_file.as_posix(),
        title=effective_beatmap.title,
        artist=effective_beatmap.artist,
        difficulty=preset.name,
        object_count=effective_beatmap.object_count if effective_beatmap.objects else structural.metrics.object_count,
        duration_ms=analysis.duration_ms,
    )
    report = ValidationReport(
        version=1,
        map_info=map_info,
        valid=valid,
        playable=playable,
        scores=score_result.scores,
        interpretation=score_result.interpretation,
        summary=summary,
        metrics=metrics,
        issues=issues,
    )

    if output_path is not None:
        write_validation_report(output_path, report)

    return ValidationRunResult(map_path=beatmap_file, report_path=output_path, report=report)


def validate_all_maps(
    *,
    maps_dir: Path,
    analysis_path: Path,
    reports_dir: Path,
) -> list[ValidationRunResult]:
    directory = maps_dir
    if not directory.exists():
        raise MapGeneratorError(f"Maps directory does not exist: {maps_dir}")
    if not directory.is_dir():
        raise MapGeneratorError(f"Maps directory is not a directory: {maps_dir}")

    map_files = sorted(directory.glob("*.json"))
    if not map_files:
        raise MapGeneratorError(f"No beatmap JSON files were found in {maps_dir}")

    results: list[ValidationRunResult] = []
    failures: list[str] = []

    for map_file in map_files:
        try:
            raw_map = _load_json(map_file, "Beatmap JSON")
            difficulty = _infer_difficulty(map_file, raw_map)
            output_path = reports_dir / f"{map_file.stem}-report.json"
            try:
                map_label = map_file.relative_to(Path.cwd()).as_posix()
            except ValueError:
                map_label = map_file.as_posix()
            results.append(
                validate_beatmap(
                    map_path=map_file,
                    analysis_path=analysis_path,
                    difficulty=difficulty,
                    output_path=output_path,
                    map_label=map_label,
                )
            )
        except MapGeneratorError as error:
            failures.append(f"{map_file.as_posix()}: {error}")

    if failures:
        raise MapGeneratorError("One or more maps could not be validated:\n" + "\n".join(failures))

    return results


def compare_validation_reports(*, reports_dir: Path) -> str:
    if not reports_dir.exists():
        raise MapGeneratorError(f"Reports directory does not exist: {reports_dir}")
    if not reports_dir.is_dir():
        raise MapGeneratorError(f"Reports directory is not a directory: {reports_dir}")

    rows: list[dict[str, Any]] = []
    for report_file in sorted(reports_dir.glob("*.json")):
        raw_report = _load_json(report_file, "Validation report JSON")
        if not isinstance(raw_report, dict):
            raise MapGeneratorError(f"Validation report must be a JSON object: {report_file}")
        map_section = raw_report.get("map")
        scores = raw_report.get("scores")
        if not isinstance(map_section, dict) or not isinstance(scores, dict):
            raise MapGeneratorError(f"Validation report is missing map or scores data: {report_file}")

        label = _safe_string(map_section.get("path")) or report_file.stem
        rows.append(
            {
                "label": Path(label).name,
                "overall": _safe_number(scores.get("overall"), "scores.overall", report_file),
                "scores": {
                    "structural": _safe_number(scores.get("structural"), "scores.structural", report_file),
                    "timing": _safe_number(scores.get("timing"), "scores.timing", report_file),
                    "rhythm": _safe_number(scores.get("rhythm"), "scores.rhythm", report_file),
                    "movement": _safe_number(scores.get("movement"), "scores.movement", report_file),
                    "readability": _safe_number(scores.get("readability"), "scores.readability", report_file),
                    "spatialBalance": _safe_number(scores.get("spatialBalance"), "scores.spatialBalance", report_file),
                    "repetition": _safe_number(scores.get("repetition"), "scores.repetition", report_file),
                    "densityConsistency": _safe_number(scores.get("densityConsistency"), "scores.densityConsistency", report_file),
                    "difficultyConsistency": _safe_number(scores.get("difficultyConsistency"), "scores.difficultyConsistency", report_file),
                },
            }
        )

    rows.sort(key=lambda row: (-row["overall"], row["label"]))
    return format_report_comparison(rows)


def _load_json(path: Path, label: str) -> Any:
    return load_json_file(path, label)


def _load_analysis(path: Path) -> AudioAnalysis:
    return load_analysis_json(path)


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_int(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not numeric.is_integer():
        return None
    return int(numeric)


def _safe_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def _safe_number(value: Any, label: str, path: Path) -> float:
    parsed = _safe_float(value)
    if parsed is None:
        raise MapGeneratorError(f"Validation report field {label} is missing or invalid in {path}")
    return parsed


def _infer_difficulty(map_file: Path, raw_map: Any) -> str:
    if isinstance(raw_map, dict):
        generator = raw_map.get("generator")
        if isinstance(generator, dict):
            difficulty = generator.get("difficulty")
            if difficulty in DIFFICULTY_PRESETS:
                return str(difficulty)

    lowered_name = map_file.stem.lower()
    for difficulty_name in DIFFICULTY_PRESETS:
        if lowered_name.endswith(f"-{difficulty_name}") or lowered_name.endswith(f"_{difficulty_name}") or difficulty_name in lowered_name:
            return difficulty_name

    allowed = ", ".join(sorted(DIFFICULTY_PRESETS))
    raise MapGeneratorError(
        f"Could not infer difficulty for {map_file}. Add generator.difficulty metadata or use a filename containing one of: {allowed}."
    )


def _with_density_issue_counts(metrics: DensityMetrics, issues: list[Any]) -> DensityMetrics:
    windows = []
    for window in metrics.windows:
        issue_count = sum(
            1
            for issue in issues
            if (
                issue.start_time_ms is not None
                and window.start_ms <= issue.start_time_ms < window.end_ms
            )
            or (
                issue.start_time_ms is None
                and issue.end_time_ms is not None
                and window.start_ms <= issue.end_time_ms < window.end_ms
            )
        )
        windows.append(window.with_issue_count(issue_count))

    return DensityMetrics(
        windows=windows,
        high_density_low_energy_windows=metrics.high_density_low_energy_windows,
        low_density_high_energy_windows=metrics.low_density_high_energy_windows,
        abrupt_density_spikes=metrics.abrupt_density_spikes,
        flat_density_despite_energy_change=metrics.flat_density_despite_energy_change,
        ending_gap_ms=metrics.ending_gap_ms,
    )


def _empty_metrics(structural_metrics: StructuralMetrics, duration_ms: int) -> ValidationMetrics:
    return ValidationMetrics(
        structural=structural_metrics,
        timing=TimingMetrics(
            average_anchor_delta_ms=0.0,
            average_beat_delta_ms=0.0,
            average_onset_delta_ms=0.0,
            excellent_alignment_count=0,
            good_alignment_count=0,
            acceptable_alignment_count=0,
            weak_alignment_count=0,
            mistimed_count=0,
            early_bias_count=0,
            late_bias_count=0,
            anchor_usage={"beat": 0, "onset": 0, "none": 0},
        ),
        rhythm=RhythmMetrics(
            min_gap_ms=duration_ms,
            max_gap_ms=duration_ms,
            average_gap_ms=float(duration_ms),
            median_gap_ms=float(duration_ms),
            gap_standard_deviation_ms=0.0,
            gap_percentiles_ms={"p10": float(duration_ms), "p25": float(duration_ms), "p75": float(duration_ms), "p90": float(duration_ms)},
            rapid_sequence_count=0,
            long_empty_space_count=0,
            repeated_equal_gap_runs=0,
            common_rhythm_intervals_ms=[],
        ),
        movement=MovementMetrics(
            min_jump_distance=0.0,
            max_jump_distance=0.0,
            average_jump_distance=0.0,
            highest_cursor_speed=0.0,
            average_cursor_speed=0.0,
            speed_violation_count=0,
            near_limit_run_count=0,
            exact_stacking_count=0,
            near_stacking_count=0,
            overlap_count=0,
            large_isolated_jump_count=0,
        ),
        spatial=SpatialMetrics(
            grid_columns=4,
            grid_rows=3,
            region_counts={f"r{row + 1}c{column + 1}": 0 for row in range(3) for column in range(4)},
            playfield_coverage_percent=0.0,
            center_usage_percent=0.0,
            edge_usage_percent=0.0,
            corner_usage_percent=0.0,
            left_right_balance=0.0,
            top_bottom_balance=0.0,
            most_used_region="r1c1",
            least_used_region="r1c1",
        ),
        density=DensityMetrics(
            windows=[],
            high_density_low_energy_windows=0,
            low_density_high_energy_windows=0,
            abrupt_density_spikes=0,
            flat_density_despite_energy_change=0,
            ending_gap_ms=duration_ms,
        ),
        repetition=RepetitionMetrics(
            repeated_coordinate_pairs=0,
            repeated_two_point_loops=0,
            repeated_three_object_shapes=0,
            repeated_distance_patterns=0,
            repeated_angle_patterns=0,
            repeated_gap_sequences=0,
            longest_repetition_run=0,
        ),
        difficulty=DifficultyMetrics(
            estimated_behavior="inconsistent",
            density_ratio=0.0,
            jump_ratio=0.0,
            speed_ratio=0.0,
            timing_complexity_ratio=0.0,
            spatial_variation_ratio=0.0,
        ),
    )


def _fallback_beatmap(structural: Any, map_label: str) -> ParsedBeatmap:
    parsed = structural.parsed_beatmap
    if parsed is not None:
        return parsed

    return ParsedBeatmap(
        path=map_label,
        title="Unknown Title",
        artist="Unknown Artist",
        audio="",
        approach_time=0.0,
        circle_radius=0.0,
        objects=[],
        generator=None,
    )
