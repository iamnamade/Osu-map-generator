from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_json_file
from ..utils import MapGeneratorError, ensure_existing_file, resolve_browser_audio_path, write_json
from .candidate_section_evaluator import (
    CandidateSectionBatchResult,
    evaluate_candidate_reports,
)
from .hybrid_assembler import HybridAssemblyResult, assemble_hybrid_map
from .hybrid_report import compare_hybrid_reports
from .section_analyzer import build_section_analysis
from .section_config import SectionPipelineConfig
from .section_models import CandidateSectionReport, SectionAnalysis, SongSection


@dataclass(frozen=True)
class SectionAnalysisRunResult:
    section_analysis: SectionAnalysis
    reused: bool
    console_report: str


def analyze_sections(
    *,
    audio_path: Path,
    analysis_path: Path,
    output_path: Path,
    project_root: Path,
    config: SectionPipelineConfig,
    force: bool = False,
    audio_browser_path_override: str | None = None,
) -> SectionAnalysisRunResult:
    ensure_existing_file(audio_path, "Audio file")
    ensure_existing_file(analysis_path, "Analysis JSON")
    input_signature = _signature_for_paths([audio_path, analysis_path], config.to_dict(), "sections-v1")
    if not force and _analysis_is_complete(output_path, input_signature):
        raw_data = load_json_file(output_path, "Section analysis JSON")
        if not isinstance(raw_data, dict):
            raise MapGeneratorError(f"Section analysis JSON root must be an object: {output_path}")
        section_analysis = parse_section_analysis(raw_data)
        return SectionAnalysisRunResult(
            section_analysis=section_analysis,
            reused=True,
            console_report="\n".join(
                [
                    "Section analysis complete",
                    "",
                    f"Reused existing artifact: {output_path.as_posix()}",
                    f"Sections: {len(section_analysis.sections)}",
                ]
            ),
        )
    section_analysis = build_section_analysis(
        audio_path=audio_path,
        analysis_path=analysis_path,
        project_root=project_root,
        input_signature=input_signature,
        config=config,
        audio_browser_path_override=audio_browser_path_override,
    )
    write_json(output_path, section_analysis.to_dict())
    return SectionAnalysisRunResult(
        section_analysis=section_analysis,
        reused=False,
        console_report="\n".join(
            [
                "Section analysis complete",
                "",
                f"Sections detected: {len(section_analysis.sections)}",
                f"Boundaries detected: {len(section_analysis.boundaries)}",
                "",
                output_path.as_posix(),
            ]
        ),
    )


def evaluate_candidate_sections(
    *,
    sections_path: Path,
    analysis_path: Path,
    candidates_root: Path,
    difficulty: str,
    output_dir: Path,
    config: SectionPipelineConfig,
    force: bool = False,
) -> CandidateSectionBatchResult:
    section_analysis = load_section_analysis(sections_path)
    input_signature = _signature_for_paths(
        [sections_path, analysis_path, *sorted(candidates_root.glob("candidate-*/improved-map.json")), *sorted(candidates_root.glob("candidate-*/candidate-summary.json"))],
        config.to_dict(),
        f"section-eval-{difficulty}-v1",
    )
    return evaluate_candidate_reports(
        section_analysis=section_analysis,
        analysis_path=analysis_path,
        candidates_root=candidates_root,
        difficulty=difficulty,
        output_dir=output_dir,
        input_signature=input_signature,
        config=config,
        force=force,
    )


def assemble_hybrid(
    *,
    song_slug: str,
    title: str,
    artist: str,
    audio_path: Path,
    analysis_path: Path,
    sections_path: Path,
    section_reports_dir: Path,
    candidates_root: Path,
    difficulty: str,
    output_map: Path,
    output_report: Path,
    assembly_report_path: Path,
    transition_log_path: Path,
    project_root: Path,
    config: SectionPipelineConfig,
    audio_browser_path_override: str | None = None,
) -> HybridAssemblyResult:
    section_analysis = load_section_analysis(sections_path)
    candidate_reports = load_candidate_section_reports(section_reports_dir)
    input_signature = _signature_for_paths(
        [sections_path, analysis_path, *sorted(section_reports_dir.glob("*.json")), *sorted(candidates_root.glob("candidate-*/improved-map.json"))],
        config.to_dict(),
        f"hybrid-{difficulty}-v1",
    )
    return assemble_hybrid_map(
        song_slug=song_slug,
        title=title,
        artist=artist,
        difficulty=difficulty,
        audio_browser_path=resolve_browser_audio_path(
            audio_source_path=audio_path,
            project_root=project_root,
            audio_browser_path_override=audio_browser_path_override,
        ),
        analysis_path=analysis_path,
        candidates_root=candidates_root,
        section_analysis=section_analysis,
        candidate_reports=candidate_reports,
        output_map=output_map,
        output_report=output_report,
        assembly_report_path=assembly_report_path,
        transition_log_path=transition_log_path,
        input_signature=input_signature,
        config=config,
    )


def run_hybrid_all(
    *,
    audio_path: Path,
    analysis_path: Path,
    seed: int,
    project_root: Path,
    force: bool = False,
    config: SectionPipelineConfig,
    audio_browser_path_override: str | None = None,
) -> list[HybridAssemblyResult]:
    song_slug = _slugify(audio_path.stem)
    section_output = project_root / "public" / "sections" / f"{song_slug}-sections.json"
    analyze_sections(
        audio_path=audio_path,
        analysis_path=analysis_path,
        output_path=section_output,
        project_root=project_root,
        config=config,
        force=force,
        audio_browser_path_override=audio_browser_path_override,
    )
    results: list[HybridAssemblyResult] = []
    for difficulty in ("easy", "normal", "hard"):
        section_reports_dir = project_root / "public" / "section-reports" / song_slug / difficulty
        evaluate_candidate_sections(
            sections_path=section_output,
            analysis_path=analysis_path,
            candidates_root=project_root / "public" / "candidates" / song_slug / difficulty,
            difficulty=difficulty,
            output_dir=section_reports_dir,
            config=config,
            force=force,
        )
        results.append(
            assemble_hybrid(
                song_slug=song_slug,
                title="Test Song",
                artist="Unknown Artist",
                audio_path=audio_path,
                analysis_path=analysis_path,
                sections_path=section_output,
                section_reports_dir=section_reports_dir,
                candidates_root=project_root / "public" / "candidates" / song_slug / difficulty,
                difficulty=difficulty,
                output_map=project_root / "public" / "maps" / "hybrid" / f"{song_slug}-{difficulty}.json",
                output_report=project_root / "public" / "reports" / "hybrid" / f"{song_slug}-{difficulty}-report.json",
                assembly_report_path=project_root / "public" / "hybrids" / f"{song_slug}-{difficulty}-assembly.json",
                transition_log_path=project_root / "public" / "hybrids" / f"{song_slug}-{difficulty}-transitions.json",
                project_root=project_root,
                config=config,
                audio_browser_path_override=audio_browser_path_override,
            )
        )
    return results


def load_section_analysis(path: Path) -> SectionAnalysis:
    raw_data = load_json_file(path, "Section analysis JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Section analysis JSON root must be an object: {path}")
    return parse_section_analysis(raw_data)


def load_candidate_section_reports(directory: Path) -> list[CandidateSectionReport]:
    reports: list[CandidateSectionReport] = []
    for report_path in sorted(directory.glob("candidate-*-sections.json")):
        raw_data = load_json_file(report_path, "Candidate section report")
        if not isinstance(raw_data, dict):
            raise MapGeneratorError(f"Candidate section report root must be an object: {report_path}")
        reports.append(parse_candidate_section_report(raw_data))
    if not reports:
        raise MapGeneratorError(f"No candidate section reports were found in {directory}")
    return reports


def parse_section_analysis(raw_data: dict[str, Any]) -> SectionAnalysis:
    audio = raw_data.get("audio", {})
    sections_raw = raw_data.get("sections", [])
    boundaries_raw = raw_data.get("boundaries", [])
    from .section_models import SectionAnalysis as SectionAnalysisModel, SectionBoundary, SongSection
    if not isinstance(audio, dict) or not isinstance(sections_raw, list) or not isinstance(boundaries_raw, list):
        raise MapGeneratorError("Section analysis JSON is malformed.")
    sections = [
        SongSection(
            id=int(item.get("id", 0)),
            start_ms=int(item.get("startMs", 0)),
            end_ms=int(item.get("endMs", 0)),
            duration_ms=int(item.get("durationMs", 0)),
            label=str(item.get("label", "unknown")),
            confidence=float(item.get("confidence", 0.0)),
            average_energy=float(item.get("averageEnergy", 0.0)),
            energy_trend=str(item.get("energyTrend", "steady")),
            beat_density=float(item.get("beatDensity", 0.0)),
            onset_density=float(item.get("onsetDensity", 0.0)),
            rhythm_complexity=float(item.get("rhythmComplexity", 0.0)),
            repetition_group=(int(item["repetitionGroup"]) if isinstance(item.get("repetitionGroup"), int) else None),
            energy_class=str(item.get("energyClass", "medium")),
        )
        for item in sections_raw
        if isinstance(item, dict)
    ]
    boundaries = [
        SectionBoundary(
            raw_time_ms=int(item.get("rawTimeMs", 0)),
            final_time_ms=int(item.get("finalTimeMs", 0)),
            confidence=float(item.get("confidence", 0.0)),
            reason=str(item.get("reason", "")),
            supporting_feature_changes={
                str(key): float(value)
                for key, value in (item.get("supportingFeatureChanges", {}) or {}).items()
                if isinstance(value, (int, float))
            },
            snapped=bool(item.get("snapped", False)),
            snapped_to=(str(item["snappedTo"]) if isinstance(item.get("snappedTo"), str) else None),
            snap_distance_ms=(int(item["snapDistanceMs"]) if isinstance(item.get("snapDistanceMs"), (int, float)) else None),
        )
        for item in boundaries_raw
        if isinstance(item, dict)
    ]
    return SectionAnalysisModel(
        version=int(raw_data.get("version", 1)),
        audio_path=str(audio.get("path", "")),
        duration_ms=int(audio.get("durationMs", 0)),
        configuration=raw_data.get("configuration", {}) if isinstance(raw_data.get("configuration"), dict) else {},
        sections=sections,
        boundaries=boundaries,
        summary=raw_data.get("summary", {}) if isinstance(raw_data.get("summary"), dict) else {},
        input_signature=str(raw_data.get("inputSignature", "")),
    )


def parse_candidate_section_report(raw_data: dict[str, Any]) -> CandidateSectionReport:
    from .section_models import (
        CandidateSectionEvaluation,
        CandidateSectionReport as CandidateSectionReportModel,
        SectionIssue,
        SectionMetrics,
        SectionScores,
        SectionState,
    )

    sections_raw = raw_data.get("sections")
    if not isinstance(sections_raw, list):
        raise MapGeneratorError("Candidate section report is malformed.")
    sections = []
    for item in sections_raw:
        if not isinstance(item, dict):
            raise MapGeneratorError("Candidate section entry must be an object.")
        scores = item.get("scores", {})
        metrics = item.get("metrics", {})
        entry_state = item.get("entryState", {})
        exit_state = item.get("exitState", {})
        issues = item.get("issues", [])
        if not isinstance(scores, dict) or not isinstance(metrics, dict):
            raise MapGeneratorError("Candidate section entry is malformed.")
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
    return CandidateSectionReportModel(
        version=int(raw_data.get("version", 1)),
        candidate_index=int(raw_data.get("candidateIndex", 0)),
        difficulty=str(raw_data.get("difficulty", "")),
        input_signature=str(raw_data.get("inputSignature", "")),
        status=raw_data.get("status", {}) if isinstance(raw_data.get("status"), dict) else {},
        summary=raw_data.get("summary", {}) if isinstance(raw_data.get("summary"), dict) else {},
        sections=sections,
    )


def _analysis_is_complete(path: Path, signature: str) -> bool:
    if not path.exists():
        return False
    raw_data = load_json_file(path, "Section analysis JSON")
    return (
        isinstance(raw_data, dict)
        and raw_data.get("inputSignature") == signature
        and isinstance(raw_data.get("sections"), list)
        and bool(raw_data.get("sections"))
    )


def _signature_for_paths(
    paths: list[Path],
    config_payload: dict[str, Any],
    label: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(label.encode("utf-8"))
    digest.update(repr(sorted(config_payload.items())).encode("utf-8"))
    for path in paths:
        ensure_existing_file(path, "Pipeline input")
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _slugify(value: str) -> str:
    characters: list[str] = []
    previous_dash = False
    for character in value.lower():
        if character.isalnum():
            characters.append(character)
            previous_dash = False
        elif not previous_dash:
            characters.append("-")
            previous_dash = True
    return "".join(characters).strip("-") or "song"
