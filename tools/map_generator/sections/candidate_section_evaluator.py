from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json, load_json_file
from ..config import get_difficulty_preset
from ..utils import MapGeneratorError, average, ensure_parent_directory, normalize_map_objects, write_json
from .section_config import SectionPipelineConfig
from .section_models import (
    CandidateSectionEvaluation,
    CandidateSectionReport,
    MapObject,
    SectionAnalysis,
    SectionIssue,
    SectionMetrics,
    SectionScores,
    SectionState,
)
from .section_scorer import evaluate_section_window


@dataclass(frozen=True)
class CandidateSectionBatchResult:
    reports: list[CandidateSectionReport]
    reused_count: int
    regenerated_count: int
    console_report: str


def evaluate_candidate_reports(
    *,
    section_analysis: SectionAnalysis,
    analysis_path: Path,
    candidates_root: Path,
    difficulty: str,
    output_dir: Path,
    input_signature: str,
    config: SectionPipelineConfig,
    force: bool = False,
) -> CandidateSectionBatchResult:
    analysis = load_analysis_json(analysis_path)
    preset = get_difficulty_preset(difficulty)
    candidate_dirs = sorted(path for path in candidates_root.glob("candidate-*") if path.is_dir())
    if not candidate_dirs:
        raise MapGeneratorError(f"No candidate directories were found in {candidates_root}")

    reports: list[CandidateSectionReport] = []
    reused_count = 0
    regenerated_count = 0
    ensure_parent_directory(output_dir / ".keep")

    for candidate_dir in candidate_dirs:
        candidate_index = _candidate_index(candidate_dir.name)
        report_path = output_dir / f"candidate-{candidate_index:03d}-sections.json"
        if (
            not force
            and report_path.exists()
            and _is_complete_report(report_path, input_signature, len(section_analysis.sections))
        ):
            reports.append(_load_candidate_section_report(report_path))
            reused_count += 1
            continue

        generated_report = _evaluate_single_candidate(
            section_analysis=section_analysis,
            analysis=analysis,
            candidate_dir=candidate_dir,
            difficulty=difficulty,
            preset=preset,
            input_signature=input_signature,
            config=config,
        )
        write_json(report_path, generated_report.to_dict())
        reports.append(generated_report)
        regenerated_count += 1

    console_report = _format_console_report(
        difficulty=difficulty,
        report_count=len(reports),
        section_count=len(section_analysis.sections),
        reused_count=reused_count,
        regenerated_count=regenerated_count,
        output_dir=output_dir,
    )
    return CandidateSectionBatchResult(
        reports=reports,
        reused_count=reused_count,
        regenerated_count=regenerated_count,
        console_report=console_report,
    )


def _evaluate_single_candidate(
    *,
    section_analysis: SectionAnalysis,
    analysis: Any,
    candidate_dir: Path,
    difficulty: str,
    preset: Any,
    input_signature: str,
    config: SectionPipelineConfig,
) -> CandidateSectionReport:
    summary = _load_json_object(candidate_dir / "candidate-summary.json", "Candidate summary")
    improved_map = _load_json_object(candidate_dir / "improved-map.json", "Improved candidate map")
    objects = _load_map_objects(improved_map)
    evaluations: list[CandidateSectionEvaluation] = []
    for section in section_analysis.sections:
        local_result = evaluate_section_window(
            analysis=analysis,
            preset=preset,
            section=section,
            all_objects=objects,
            evaluation_config=config.evaluation,
        )
        quality_bias = float(summary.get("scores", {}).get("qualityScore", summary.get("scores", {}).get("improvedOverall", 0.0)))
        stability_bias = float(summary.get("stability", {}).get("score", summary.get("scores", {}).get("stabilityScore", 0.0)))
        adjusted_overall = min(
            100.0,
            max(
                0.0,
                local_result.scores.overall * 0.82
                + quality_bias * 0.11
                + stability_bias * 0.07,
            ),
        )
        evaluations.append(
            CandidateSectionEvaluation(
                section_id=section.id,
                start_ms=section.start_ms,
                end_ms=section.end_ms,
                label=section.label,
                source_candidate=_candidate_index(candidate_dir.name),
                scores=type(local_result.scores)(
                    structural=local_result.scores.structural,
                    timing=local_result.scores.timing,
                    rhythm=local_result.scores.rhythm,
                    movement=local_result.scores.movement,
                    readability=local_result.scores.readability,
                    spatial_balance=local_result.scores.spatial_balance,
                    repetition=local_result.scores.repetition,
                    density_consistency=local_result.scores.density_consistency,
                    difficulty_consistency=local_result.scores.difficulty_consistency,
                    transition_readiness=local_result.scores.transition_readiness,
                    overall=adjusted_overall,
                ),
                metrics=local_result.metrics,
                issues=local_result.issues,
                entry_state=local_result.entry_state,
                exit_state=local_result.exit_state,
            )
        )
    section_scores = [evaluation.scores.overall for evaluation in evaluations]
    summary_payload = {
        "averageSectionScore": round(average(section_scores), 4),
        "minimumSectionScore": round(min(section_scores), 4),
        "maximumSectionScore": round(max(section_scores), 4),
        "sectionCount": len(evaluations),
        "candidateQuality": float(summary.get("scores", {}).get("qualityScore", 0.0)),
        "candidateStability": float(summary.get("stability", {}).get("score", 0.0)),
    }
    return CandidateSectionReport(
        version=1,
        candidate_index=_candidate_index(candidate_dir.name),
        difficulty=difficulty,
        input_signature=input_signature,
        status=summary.get("status", {}),
        summary=summary_payload,
        sections=evaluations,
    )


def _candidate_index(name: str) -> int:
    try:
        return int(name.split("-")[-1])
    except ValueError as error:
        raise MapGeneratorError(f"Candidate directory name is invalid: {name}") from error


def _load_map_objects(map_data: dict[str, Any]) -> list[MapObject]:
    raw_objects = map_data.get("objects")
    if not isinstance(raw_objects, list):
        raise MapGeneratorError("Candidate map is missing its objects list.")
    normalized = normalize_map_objects(raw_objects)
    objects: list[MapObject] = []
    for item in normalized:
        try:
            objects.append(
                MapObject(
                    id=int(item["id"]),
                    x=int(item["x"]),
                    y=int(item["y"]),
                    time=int(item["time"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            # Should not happen after normalisation, but guard anyway.
            continue
    if not objects:
        raise MapGeneratorError("Candidate map produced zero valid objects after normalisation.")
    return sorted(objects, key=lambda item: (item.time, item.id))


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    data = load_json_file(path, label)
    if not isinstance(data, dict):
        raise MapGeneratorError(f"{label} JSON root must be an object: {path}")
    return data


def _is_complete_report(path: Path, signature: str, section_count: int) -> bool:
    try:
        raw_data = _load_json_object(path, "Candidate section report")
    except MapGeneratorError:
        return False
    if raw_data.get("inputSignature") != signature:
        return False
    sections = raw_data.get("sections")
    return isinstance(sections, list) and len(sections) == section_count


def _load_candidate_section_report(path: Path) -> CandidateSectionReport:
    raw_data = _load_json_object(path, "Candidate section report")
    sections_raw = raw_data.get("sections")
    if not isinstance(sections_raw, list):
        raise MapGeneratorError(f"Candidate section report is malformed: {path}")
    sections: list[CandidateSectionEvaluation] = []
    for item in sections_raw:
        if not isinstance(item, dict):
            raise MapGeneratorError(f"Candidate section entry is malformed: {path}")
        scores = item.get("scores", {})
        metrics = item.get("metrics", {})
        entry_state = item.get("entryState", {})
        exit_state = item.get("exitState", {})
        issues = item.get("issues", [])
        if not isinstance(scores, dict) or not isinstance(metrics, dict):
            raise MapGeneratorError(f"Candidate section entry is malformed: {path}")
        sections.append(
            CandidateSectionEvaluation(
                section_id=int(item.get("sectionId", 0)),
                start_ms=int(item.get("startMs", 0)),
                end_ms=int(item.get("endMs", 0)),
                label=str(item.get("label", "unknown")),
                source_candidate=int(item.get("sourceCandidate", raw_data.get("candidateIndex", 0))),
                scores=SectionScores(
                    structural=float(scores.get("structural", 0.0)),
                    timing=float(scores.get("timing", 0.0)),
                    rhythm=float(scores.get("rhythm", 0.0)),
                    movement=float(scores.get("movement", 0.0)),
                    readability=float(scores.get("readability", 0.0)),
                    spatial_balance=float(scores.get("spatialBalance", 0.0)),
                    repetition=float(scores.get("repetition", 0.0)),
                    density_consistency=float(scores.get("densityConsistency", 0.0)),
                    difficulty_consistency=float(scores.get("difficultyConsistency", 0.0)),
                    transition_readiness=float(scores.get("transitionReadiness", 0.0)),
                    overall=float(scores.get("overall", 0.0)),
                ),
                metrics=SectionMetrics(
                    object_count=int(metrics.get("objectCount", 0)),
                    objects_per_second=float(metrics.get("objectsPerSecond", 0.0)),
                    average_object_gap_ms=float(metrics.get("averageObjectGapMs", 0.0)),
                    minimum_object_gap_ms=int(metrics.get("minimumObjectGapMs", 0)),
                    maximum_object_gap_ms=int(metrics.get("maximumObjectGapMs", 0)),
                    average_jump_distance=float(metrics.get("averageJumpDistance", 0.0)),
                    maximum_jump_distance=float(metrics.get("maximumJumpDistance", 0.0)),
                    average_cursor_speed=float(metrics.get("averageCursorSpeed", 0.0)),
                    maximum_cursor_speed=float(metrics.get("maximumCursorSpeed", 0.0)),
                    timing_confidence=float(metrics.get("timingConfidence", 0.0)),
                    beat_alignment=float(metrics.get("beatAlignment", 0.0)),
                    onset_alignment=float(metrics.get("onsetAlignment", 0.0)),
                    spatial_coverage=float(metrics.get("spatialCoverage", 0.0)),
                    center_usage=float(metrics.get("centerUsage", 0.0)),
                    edge_usage=float(metrics.get("edgeUsage", 0.0)),
                    repetition_count=int(metrics.get("repetitionCount", 0)),
                    stacking_count=int(metrics.get("stackingCount", 0)),
                    warning_count=int(metrics.get("warningCount", 0)),
                    error_count=int(metrics.get("errorCount", 0)),
                    local_difficulty_behavior=str(metrics.get("localDifficultyBehavior", "balanced")),
                    energy_to_density_ratio=float(metrics.get("energyToDensityRatio", 0.0)),
                    entry_direction_deg=(
                        float(metrics["entryDirectionDeg"])
                        if isinstance(metrics.get("entryDirectionDeg"), (int, float))
                        else None
                    ),
                    exit_direction_deg=(
                        float(metrics["exitDirectionDeg"])
                        if isinstance(metrics.get("exitDirectionDeg"), (int, float))
                        else None
                    ),
                ),
                issues=[
                    SectionIssue(
                        code=str(issue.get("code", "")),
                        severity=str(issue.get("severity", "info")),
                        message=str(issue.get("message", "")),
                        measured_value=(
                            float(issue["measuredValue"])
                            if isinstance(issue.get("measuredValue"), (int, float))
                            else None
                        ),
                        allowed_value=(
                            float(issue["allowedValue"])
                            if isinstance(issue.get("allowedValue"), (int, float))
                            else None
                        ),
                    )
                    for issue in issues
                    if isinstance(issue, dict)
                ],
                entry_state=SectionState(
                    object_id=(int(entry_state["objectId"]) if isinstance(entry_state.get("objectId"), (int, float)) else None),
                    time_ms=(int(entry_state["timeMs"]) if isinstance(entry_state.get("timeMs"), (int, float)) else None),
                    x=(float(entry_state["x"]) if isinstance(entry_state.get("x"), (int, float)) else None),
                    y=(float(entry_state["y"]) if isinstance(entry_state.get("y"), (int, float)) else None),
                    direction_deg=(float(entry_state["directionDeg"]) if isinstance(entry_state.get("directionDeg"), (int, float)) else None),
                    cursor_speed_pps=(float(entry_state["cursorSpeedPps"]) if isinstance(entry_state.get("cursorSpeedPps"), (int, float)) else None),
                    gap_ms=(int(entry_state["gapMs"]) if isinstance(entry_state.get("gapMs"), (int, float)) else None),
                    density=(float(entry_state["density"]) if isinstance(entry_state.get("density"), (int, float)) else None),
                    region=(str(entry_state["region"]) if isinstance(entry_state.get("region"), str) else None),
                ),
                exit_state=SectionState(
                    object_id=(int(exit_state["objectId"]) if isinstance(exit_state.get("objectId"), (int, float)) else None),
                    time_ms=(int(exit_state["timeMs"]) if isinstance(exit_state.get("timeMs"), (int, float)) else None),
                    x=(float(exit_state["x"]) if isinstance(exit_state.get("x"), (int, float)) else None),
                    y=(float(exit_state["y"]) if isinstance(exit_state.get("y"), (int, float)) else None),
                    direction_deg=(float(exit_state["directionDeg"]) if isinstance(exit_state.get("directionDeg"), (int, float)) else None),
                    cursor_speed_pps=(float(exit_state["cursorSpeedPps"]) if isinstance(exit_state.get("cursorSpeedPps"), (int, float)) else None),
                    gap_ms=(int(exit_state["gapMs"]) if isinstance(exit_state.get("gapMs"), (int, float)) else None),
                    density=(float(exit_state["density"]) if isinstance(exit_state.get("density"), (int, float)) else None),
                    region=(str(exit_state["region"]) if isinstance(exit_state.get("region"), str) else None),
                ),
            )
        )
    return CandidateSectionReport(
        version=int(raw_data.get("version", 1)),
        candidate_index=int(raw_data.get("candidateIndex", 0)),
        difficulty=str(raw_data.get("difficulty", "")),
        input_signature=str(raw_data.get("inputSignature", "")),
        status=raw_data.get("status", {}) if isinstance(raw_data.get("status"), dict) else {},
        summary=raw_data.get("summary", {}) if isinstance(raw_data.get("summary"), dict) else {},
        sections=sections,
    )


def _format_console_report(
    *,
    difficulty: str,
    report_count: int,
    section_count: int,
    reused_count: int,
    regenerated_count: int,
    output_dir: Path,
) -> str:
    return "\n".join(
        [
            "Section candidate evaluation complete",
            "",
            f"Difficulty: {difficulty}",
            f"Candidates evaluated: {report_count}",
            f"Sections per candidate: {section_count}",
            f"Reused reports: {reused_count}",
            f"Regenerated reports: {regenerated_count}",
            "",
            "Output directory:",
            output_dir.as_posix(),
        ]
    )
