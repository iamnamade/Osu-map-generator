from __future__ import annotations

from pathlib import Path

from ..analysis_io import load_analysis_json
from ..utils import resolve_browser_audio_path
from .boundary_detector import detect_section_boundaries
from .feature_extractor import extract_section_statistics
from .section_classifier import classify_section
from .section_config import SectionPipelineConfig
from .section_models import SectionAnalysis, SongSection


def build_section_analysis(
    *,
    audio_path: Path,
    analysis_path: Path,
    project_root: Path,
    input_signature: str,
    config: SectionPipelineConfig,
    audio_browser_path_override: str | None = None,
) -> SectionAnalysis:
    analysis = load_analysis_json(analysis_path)
    boundaries = detect_section_boundaries(analysis, config.detection)
    boundary_times = [0, *[boundary.final_time_ms for boundary in boundaries], analysis.duration_ms]
    section_stats = [
        extract_section_statistics(
            analysis,
            start_ms=boundary_times[index],
            end_ms=boundary_times[index + 1],
        )
        for index in range(len(boundary_times) - 1)
    ]

    sections: list[SongSection] = []
    for index, stats in enumerate(section_stats):
        classification = classify_section(
            index=index,
            total=len(section_stats),
            average_energy=float(stats["averageEnergy"]),
            energy_trend=str(stats["energyTrend"]),
            beat_density=float(stats["beatDensity"]),
            onset_density=float(stats["onsetDensity"]),
            rhythm_complexity=float(stats["rhythmComplexity"]),
            quiet_ratio=float(stats["quietRatio"]),
            high_energy_ratio=float(stats["highEnergyRatio"]),
            emphasis_ratio=float(stats["emphasisRatio"]),
            previous_energy=(
                float(section_stats[index - 1]["averageEnergy"]) if index > 0 else None
            ),
            next_energy=(
                float(section_stats[index + 1]["averageEnergy"])
                if index + 1 < len(section_stats)
                else None
            ),
        )
        sections.append(
            SongSection(
                id=index + 1,
                start_ms=boundary_times[index],
                end_ms=boundary_times[index + 1],
                duration_ms=boundary_times[index + 1] - boundary_times[index],
                label=classification.label,
                confidence=classification.confidence,
                average_energy=float(stats["averageEnergy"]),
                energy_trend=str(stats["energyTrend"]),
                beat_density=float(stats["beatDensity"]),
                onset_density=float(stats["onsetDensity"]),
                rhythm_complexity=float(stats["rhythmComplexity"]),
                repetition_group=None,
                energy_class=classification.energy_class,
            )
        )

    sections = _assign_repetition_groups(sections)
    summary = {
        "sectionCount": len(sections),
        "boundaryCount": len(boundaries),
        "averageSectionDurationMs": round(
            sum(section.duration_ms for section in sections) / len(sections), 3
        )
        if sections
        else 0.0,
        "labels": {label: sum(1 for section in sections if section.label == label) for label in sorted({section.label for section in sections})},
        "minimumSectionDurationMs": min((section.duration_ms for section in sections), default=0),
        "maximumSectionDurationMs": max((section.duration_ms for section in sections), default=0),
    }

    return SectionAnalysis(
        version=1,
        audio_path=resolve_browser_audio_path(
            audio_source_path=audio_path,
            project_root=project_root,
            audio_browser_path_override=audio_browser_path_override,
        ),
        duration_ms=analysis.duration_ms,
        configuration=config.to_dict(),
        sections=sections,
        boundaries=boundaries,
        summary=summary,
        input_signature=input_signature,
    )


def _assign_repetition_groups(sections: list[SongSection]) -> list[SongSection]:
    group_lookup: dict[tuple[int, int, str], int] = {}
    next_group = 1
    output: list[SongSection] = []
    for section in sections:
        key = (
            int(round(section.average_energy * 4)),
            int(round(section.onset_density * 2)),
            section.label,
        )
        repetition_group = group_lookup.get(key)
        if repetition_group is None:
            group_lookup[key] = next_group
            repetition_group = next_group
            next_group += 1
        output.append(
            SongSection(
                id=section.id,
                start_ms=section.start_ms,
                end_ms=section.end_ms,
                duration_ms=section.duration_ms,
                label=section.label,
                confidence=section.confidence,
                average_energy=section.average_energy,
                energy_trend=section.energy_trend,
                beat_density=section.beat_density,
                onset_density=section.onset_density,
                rhythm_complexity=section.rhythm_complexity,
                repetition_group=repetition_group,
                energy_class=section.energy_class,
            )
        )
    return output
