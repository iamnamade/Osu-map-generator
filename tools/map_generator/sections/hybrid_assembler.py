from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json, load_json_file
from ..config import get_difficulty_preset
from ..utils import MapGeneratorError, average, normalize_map_objects, write_json
from ..validation import validate_beatmap
from .hybrid_selector import select_section_sources
from .section_config import SectionPipelineConfig
from .section_models import (
    CandidateSectionReport,
    HybridAssemblyReport,
    HybridPromotionStatus,
    HybridScores,
    HybridSectionSelection,
    MapObject,
    SectionAnalysis,
    SongSection,
)
from .transition_analyzer import analyze_transition
from .transition_optimizer import optimize_transition


@dataclass(frozen=True)
class HybridAssemblyResult:
    assembly_report: HybridAssemblyReport
    console_report: str
    validation_report_path: Path


def assemble_hybrid_map(
    *,
    song_slug: str,
    title: str,
    artist: str,
    difficulty: str,
    audio_browser_path: str,
    analysis_path: Path,
    candidates_root: Path,
    section_analysis: SectionAnalysis,
    candidate_reports: list[CandidateSectionReport],
    output_map: Path,
    output_report: Path,
    assembly_report_path: Path,
    transition_log_path: Path,
    input_signature: str,
    config: SectionPipelineConfig,
) -> HybridAssemblyResult:
    preset = get_difficulty_preset(difficulty)
    analysis = load_analysis_json(analysis_path)
    candidate_maps = _load_candidate_maps(candidates_root)
    selections = select_section_sources(
        sections=section_analysis.sections,
        candidate_reports=candidate_reports,
        config=config.selection,
    )
    section_lookup = {section.id: section for section in section_analysis.sections}
    assembled_sections: list[list[MapObject]] = []
    for selection in selections:
        section = section_lookup[selection.section_id]
        source_objects = candidate_maps.get(selection.source_candidate)
        if source_objects is None:
            raise MapGeneratorError(f"Selected candidate {selection.source_candidate} has no loaded map.")
        assembled_sections.append(_slice_section_objects(source_objects, section))

    transitions = []
    accepted_corrections = 0
    reverted_corrections = 0
    for index in range(len(selections) - 1):
        optimization = optimize_transition(
            boundary_index=index + 1,
            left_section=section_lookup[selections[index].section_id],
            right_section=section_lookup[selections[index + 1].section_id],
            left_selection=selections[index],
            right_selection=selections[index + 1],
            left_objects=assembled_sections[index],
            right_objects=assembled_sections[index + 1],
            candidate_reports=candidate_reports,
            candidate_maps=candidate_maps,
            analysis=analysis,
            preset=preset,
            config=config,
        )
        assembled_sections[index] = optimization.left_objects
        assembled_sections[index + 1] = optimization.right_objects
        if optimization.updated_right_selection is not None:
            selections[index + 1] = optimization.updated_right_selection
        accepted_corrections += len(optimization.accepted_corrections)
        reverted_corrections += len(optimization.reverted_corrections)
        transitions.append(optimization.transition)

    merged_objects = _merge_sections(assembled_sections)
    if not merged_objects:
        raise MapGeneratorError("Hybrid assembly produced an empty beatmap.")
    hybrid_map = {
        "title": title,
        "artist": artist,
        "audio": audio_browser_path,
        "approachTime": preset.approach_time_ms,
        "circleRadius": preset.circle_radius,
        "objects": [item.to_dict() for item in merged_objects],
        "hybrid": {
            "version": 1,
            "difficulty": difficulty,
            "sectionCount": len(selections),
            "sourceCandidates": [selection.source_candidate for selection in selections],
            "transitionCorrections": accepted_corrections,
        },
    }
    write_json(output_map, hybrid_map)
    validation_result = validate_beatmap(
        map_path=output_map,
        analysis_path=analysis_path,
        difficulty=difficulty,
        output_path=output_report,
        map_label=output_map.as_posix(),
    )
    final_transitions = [
        analyze_transition(
            boundary_index=index + 1,
            left_section=section_lookup[selections[index].section_id],
            right_section=section_lookup[selections[index + 1].section_id],
            from_candidate=selections[index].source_candidate,
            to_candidate=selections[index + 1].source_candidate,
            left_objects=assembled_sections[index],
            right_objects=assembled_sections[index + 1],
            preset=preset,
        )
        if index >= len(transitions)
        else transitions[index]
        for index in range(len(selections) - 1)
    ]
    for index, selection in enumerate(selections):
        before_status = final_transitions[index - 1].classification if index > 0 else None
        after_status = final_transitions[index].classification if index < len(final_transitions) else None
        selections[index] = HybridSectionSelection(
            section_id=selection.section_id,
            start_ms=selection.start_ms,
            end_ms=selection.end_ms,
            label=selection.label,
            source_candidate=selection.source_candidate,
            section_score=selection.section_score,
            selection_reason=selection.selection_reason,
            lock_state=selection.lock_state,
            transition_status_before=before_status,
            transition_status_after=after_status,
            issues=list(selection.issues),
        )

    section_quality = average(selection.section_score for selection in selections)
    transition_quality = average(transition.score for transition in final_transitions) if final_transitions else 100.0
    style_consistency = _style_consistency(candidate_reports, selections)
    final_python_quality = validation_result.report.scores.overall
    overall_hybrid_score = _hybrid_score(
        section_quality=section_quality,
        transition_quality=transition_quality,
        style_consistency=style_consistency,
        final_python_quality=final_python_quality,
        config=config,
    )
    champion_quality = _load_champion_quality(
        candidates_root=candidates_root,
        song_slug=song_slug,
        difficulty=difficulty,
    )
    promotion = _promotion_status(
        champion_quality=champion_quality,
        validation_report=validation_result.report,
        hybrid_score=overall_hybrid_score,
        config=config,
    )
    assembly_report = HybridAssemblyReport(
        version=1,
        difficulty=difficulty,
        input_signature=input_signature,
        sections=selections,
        transitions=final_transitions,
        scores=HybridScores(
            section_quality=section_quality,
            transition_quality=transition_quality,
            style_consistency=style_consistency,
            final_python_quality=final_python_quality,
            overall_hybrid_score=overall_hybrid_score,
        ),
        source_usage=_source_usage(selections),
        corrections={
            "accepted": accepted_corrections,
            "reverted": reverted_corrections,
            "unsafeTransitionsRemaining": sum(
                1
                for transition in final_transitions
                if transition.classification in {"unsafe", "critical"}
            ),
        },
        valid=validation_result.report.valid,
        playable=validation_result.report.playable,
        promotion=promotion,
        summary={
            "sectionCount": len(selections),
            "sourceCandidatesUsed": len({selection.source_candidate for selection in selections}),
            "candidateSwitches": _candidate_switch_count(selections),
        },
    )
    write_json(assembly_report_path, assembly_report.to_dict())
    write_json(
        transition_log_path,
        {
            "version": 1,
            "difficulty": difficulty,
            "inputSignature": input_signature,
            "transitions": [transition.to_dict() for transition in final_transitions],
            "corrections": assembly_report.corrections,
        },
    )
    return HybridAssemblyResult(
        assembly_report=assembly_report,
        console_report=_format_console_report(
            title=title,
            difficulty=difficulty,
            selections=selections,
            assembly_report=assembly_report,
            champion_quality=champion_quality,
            output_map=output_map,
            assembly_report_path=assembly_report_path,
        ),
        validation_report_path=output_report,
    )


def _load_candidate_maps(candidates_root: Path) -> dict[int, list[MapObject]]:
    maps: dict[int, list[MapObject]] = {}
    for candidate_dir in sorted(path for path in candidates_root.glob("candidate-*") if path.is_dir()):
        candidate_index = int(candidate_dir.name.split("-")[-1])
        map_data = load_json_file(candidate_dir / "improved-map.json", "Improved candidate map")
        if not isinstance(map_data, dict):
            raise MapGeneratorError(f"Improved candidate map must be an object: {candidate_dir}")
        raw_objects = map_data.get("objects")
        if not isinstance(raw_objects, list):
            raise MapGeneratorError(f"Improved candidate map is missing objects: {candidate_dir}")
        normalized = normalize_map_objects(raw_objects)
        objects: list[MapObject] = []
        for item in normalized:
            try:
                x_val = item.get("x")
                y_val = item.get("y")
                t_val = item.get("time")
                if x_val is None or y_val is None or t_val is None:
                    continue
                objects.append(
                    MapObject(
                        id=int(item.get("id", 0)),
                        x=int(x_val),
                        y=int(y_val),
                        time=int(t_val),
                    )
                )
            except (TypeError, ValueError):
                continue
        if not objects:
            raise MapGeneratorError(
                f"Improved candidate map produced zero valid objects: {candidate_dir}"
            )
        maps[candidate_index] = objects
    return maps


def _slice_section_objects(objects: list[MapObject], section: SongSection) -> list[MapObject]:
    return [
        copy.deepcopy(item)
        for item in objects
        if section.start_ms <= item.time < section.end_ms
    ]


def _merge_sections(section_slices: list[list[MapObject]]) -> list[MapObject]:
    merged: list[MapObject] = []
    next_id = 1
    previous_time = -1
    for slice_objects in section_slices:
        for object_ in slice_objects:
            if object_.time <= previous_time:
                continue
            merged.append(
                MapObject(
                    id=next_id,
                    x=object_.x,
                    y=object_.y,
                    time=object_.time,
                )
            )
            next_id += 1
            previous_time = object_.time
    return merged


def _source_usage(selections: list[HybridSectionSelection]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for selection in selections:
        key = f"candidate-{selection.source_candidate:03d}"
        usage[key] = usage.get(key, 0) + 1
    return usage


def _candidate_switch_count(selections: list[HybridSectionSelection]) -> int:
    return sum(
        1
        for left, right in zip(selections, selections[1:])
        if left.source_candidate != right.source_candidate
    )


def _style_consistency(
    reports: list[CandidateSectionReport],
    selections: list[HybridSectionSelection],
) -> float:
    selected_sections = []
    for selection in selections:
        for report in reports:
            if report.candidate_index != selection.source_candidate:
                continue
            selected_sections.extend(
                section
                for section in report.sections
                if section.section_id == selection.section_id
            )
    if len(selected_sections) < 2:
        return 100.0
    jump_values = [section.metrics.average_jump_distance for section in selected_sections]
    speed_values = [section.metrics.average_cursor_speed for section in selected_sections]
    density_values = [section.metrics.objects_per_second for section in selected_sections]
    jump_spread = max(jump_values) - min(jump_values)
    speed_spread = max(speed_values) - min(speed_values)
    density_spread = max(density_values) - min(density_values)
    return max(
        0.0,
        min(100.0, 94.0 - jump_spread * 0.05 - speed_spread * 0.04 - density_spread * 12.0),
    )


def _hybrid_score(
    *,
    section_quality: float,
    transition_quality: float,
    style_consistency: float,
    final_python_quality: float,
    config: SectionPipelineConfig,
) -> float:
    return max(
        0.0,
        min(
            100.0,
            section_quality * config.scoring.section_quality_weight
            + transition_quality * config.scoring.transition_quality_weight
            + style_consistency * config.scoring.style_consistency_weight
            + final_python_quality * config.scoring.final_python_quality_weight,
        ),
    )


def _load_champion_quality(
    *,
    candidates_root: Path,
    song_slug: str,
    difficulty: str,
) -> float | None:
    project_root = candidates_root.parents[3]
    champion_report_path = project_root / "public" / "reports" / "champions" / f"{song_slug}-{difficulty}-report.json"
    if not champion_report_path.exists():
        return None
    raw_report = load_json_file(champion_report_path, "Champion report")
    if not isinstance(raw_report, dict):
        return None
    scores = raw_report.get("scores")
    if not isinstance(scores, dict):
        return None
    value = scores.get("overall")
    return float(value) if isinstance(value, (int, float)) else None


def _promotion_status(
    *,
    champion_quality: float | None,
    validation_report: Any,
    hybrid_score: float,
    config: SectionPipelineConfig,
) -> HybridPromotionStatus:
    structural_failures = [
        issue
        for issue in validation_report.issues
        if issue.category == "structural" and issue.severity in {"error", "critical"}
    ]
    if not validation_report.valid or not validation_report.playable:
        return HybridPromotionStatus(
            promoted=False,
            reason="Hybrid is not valid or not playable.",
            champion_quality=champion_quality,
            hybrid_python_quality=validation_report.scores.overall,
            hybrid_score=hybrid_score,
        )
    if structural_failures:
        return HybridPromotionStatus(
            promoted=False,
            reason="Hybrid still has structural errors.",
            champion_quality=champion_quality,
            hybrid_python_quality=validation_report.scores.overall,
            hybrid_score=hybrid_score,
        )
    if hybrid_score < config.promotion.minimum_hybrid_score:
        return HybridPromotionStatus(
            promoted=False,
            reason="Hybrid score did not meet the promotion threshold.",
            champion_quality=champion_quality,
            hybrid_python_quality=validation_report.scores.overall,
            hybrid_score=hybrid_score,
        )
    if (
        champion_quality is not None
        and validation_report.scores.overall
        < champion_quality - config.promotion.maximum_quality_loss_vs_champion
    ):
        return HybridPromotionStatus(
            promoted=False,
            reason="Hybrid Python quality is meaningfully below the champion.",
            champion_quality=champion_quality,
            hybrid_python_quality=validation_report.scores.overall,
            hybrid_score=hybrid_score,
        )
    return HybridPromotionStatus(
        promoted=True,
        reason="Hybrid satisfied the internal promotion rules.",
        champion_quality=champion_quality,
        hybrid_python_quality=validation_report.scores.overall,
        hybrid_score=hybrid_score,
    )


def _format_console_report(
    *,
    title: str,
    difficulty: str,
    selections: list[HybridSectionSelection],
    assembly_report: HybridAssemblyReport,
    champion_quality: float | None,
    output_map: Path,
    assembly_report_path: Path,
) -> str:
    return "\n".join(
        [
            "Hybrid assembly complete",
            "",
            f"Song: {title}",
            f"Difficulty: {difficulty}",
            f"Sections: {len(selections)}",
            f"Source candidates used: {len({selection.source_candidate for selection in selections})}",
            f"Candidate switches: {_candidate_switch_count(selections)}",
            f"Transition corrections accepted: {assembly_report.corrections['accepted']}",
            f"Transition corrections reverted: {assembly_report.corrections['reverted']}",
            "",
            f"Champion quality: {(champion_quality or 0.0):.1f}",
            f"Hybrid Python quality: {assembly_report.scores.final_python_quality:.1f}",
            f"Hybrid score: {assembly_report.scores.overall_hybrid_score:.1f}",
            f"Promoted: {'yes' if assembly_report.promotion.promoted else 'no'}",
            "",
            "Hybrid map:",
            output_map.as_posix(),
            "",
            "Assembly report:",
            assembly_report_path.as_posix(),
        ]
    )
