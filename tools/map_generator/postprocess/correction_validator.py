from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json, load_json_file
from ..utils import MapGeneratorError, write_json
from ..validation.beatmap_validator import validate_beatmap
from .models import ScoreChanges, ScoreSnapshot



def load_existing_validation_report(path: Path) -> dict[str, Any]:
    raw_report = load_json_file(path, "Validation report JSON")
    if not isinstance(raw_report, dict):
        raise MapGeneratorError(f"Validation report must be a JSON object: {path}")

    map_section = raw_report.get("map")
    scores = raw_report.get("scores")
    summary = raw_report.get("summary")
    issues = raw_report.get("issues")
    if not isinstance(map_section, dict) or not isinstance(scores, dict) or not isinstance(summary, dict) or not isinstance(issues, list):
        raise MapGeneratorError(f"Validation report is missing required sections: {path}")
    return raw_report


def load_source_map(path: Path) -> dict[str, Any]:
    raw_map = load_json_file(path, "Beatmap JSON")
    if not isinstance(raw_map, dict):
        raise MapGeneratorError(f"Beatmap JSON must be an object: {path}")
    return raw_map


def load_analysis(path: Path):
    return load_analysis_json(path)


def validate_map_data(
    *,
    map_data: dict[str, Any],
    analysis_path: Path,
    difficulty: str,
    map_label: str,
    analysis: Any | None = None,
) -> Any:
    # Pass map_data directly as raw_map to skip the temp-file write/read
    # round-trip.  The map_path argument is only used by ensure_existing_file
    # when raw_map is None, so we pass analysis_path (which is guaranteed to
    # exist) as a safe placeholder.
    # Pass pre-parsed analysis when available to avoid redundant disk I/O
    # and JSON parsing on each validation call.
    return validate_beatmap(
        map_path=analysis_path,
        analysis_path=analysis_path,
        difficulty=difficulty,
        map_label=map_label,
        raw_map=map_data,
        analysis=analysis,
    )


def deep_copy_map(map_data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(map_data)


def score_snapshot_from_report(report: Any) -> ScoreSnapshot:
    return ScoreSnapshot(
        overall_score=report.scores.overall,
        playable=report.playable,
        critical=report.summary.critical,
        errors=report.summary.errors,
        warnings=report.summary.warnings,
    )


def score_changes_from_reports(before: Any, after: Any) -> ScoreChanges:
    return ScoreChanges(
        overall=after.scores.overall - before.scores.overall,
        structural=after.scores.structural - before.scores.structural,
        timing=after.scores.timing - before.scores.timing,
        rhythm=after.scores.rhythm - before.scores.rhythm,
        movement=after.scores.movement - before.scores.movement,
        readability=after.scores.readability - before.scores.readability,
        spatial_balance=after.scores.spatial_balance - before.scores.spatial_balance,
        repetition=after.scores.repetition - before.scores.repetition,
        density_consistency=after.scores.density_consistency - before.scores.density_consistency,
        difficulty_consistency=after.scores.difficulty_consistency - before.scores.difficulty_consistency,
    )


def write_map_output(path: Path, map_data: dict[str, Any]) -> None:
    write_json(path, map_data)


def load_json_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            parsed = json.load(handle)
    except json.JSONDecodeError as error:
        raise MapGeneratorError(
            f"JSON is malformed at {path}: {error.msg} (line {error.lineno}, column {error.colno})"
        ) from error
    except OSError as error:
        raise MapGeneratorError(f"JSON could not be read from {path}: {error}") from error

    return json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
