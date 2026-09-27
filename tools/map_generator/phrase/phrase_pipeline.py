"""Phase 20 phrase pipeline: report construction, persistence, and metadata.

``analyze_phrase_structure`` is the canonical entry point. It loads the audio
analysis + section analysis, runs phrase segmentation, relationship
classification, motif assignment, strategy planning, and trajectory planning,
then persists ``phrase-structure-report.json`` with an input signature so
identical inputs reuse the artifact.

Also exposes compact generator metadata (embedded into map files) and a
console report for pipeline stages.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis_io import load_analysis_json
from ..sections.section_pipeline import load_section_analysis
from ..utils import MapGeneratorError, ensure_existing_file, write_json
from .motif_engine import (
    DEFAULT_MOTIF_CONFIG,
    MotifEngineConfig,
    build_motifs,
    strategy_generation_multipliers,
)
from .phrase_analyzer import (
    DEFAULT_PHRASE_CONFIG,
    PhraseDetectionConfig,
    build_phrase_report_data,
)
from .phrase_models import PhraseReport
from .trajectory_planner import (
    DEFAULT_TRAJECTORY_CONFIG,
    TrajectoryConfig,
    build_trajectory_points,
    full_trajectory_plan,
)

PHRASE_REPORT_VERSION = 1


@dataclass(frozen=True)
class PhrasePipelineConfig:
    detection: PhraseDetectionConfig = DEFAULT_PHRASE_CONFIG
    motifs: MotifEngineConfig = DEFAULT_MOTIF_CONFIG
    trajectory: TrajectoryConfig = DEFAULT_TRAJECTORY_CONFIG

    def to_dict(self) -> dict[str, Any]:
        return {
            "detection": self.detection.to_dict(),
            "motifs": self.motifs.to_dict(),
            "trajectory": self.trajectory.to_dict(),
        }


DEFAULT_PHRASE_PIPELINE_CONFIG = PhrasePipelineConfig()


@dataclass(frozen=True)
class PhraseAnalysisRunResult:
    phrase_report: PhraseReport
    reused: bool
    console_report: str


def analyze_phrase_structure(
    *,
    analysis_path: Path,
    sections_path: Path,
    output_path: Path,
    config: PhrasePipelineConfig = DEFAULT_PHRASE_PIPELINE_CONFIG,
    force: bool = False,
) -> PhraseAnalysisRunResult:
    """Build and persist a phrase-structure report.

    Requires an existing section analysis (phrases subdivide sections).
    Deterministic: identical analysis + sections + config always produce the
    identical report; the artifact is reused when the input signature matches.
    """
    ensure_existing_file(analysis_path, "Analysis JSON")
    ensure_existing_file(sections_path, "Section analysis JSON")
    input_signature = _signature_for_paths(
        [analysis_path, sections_path],
        config.to_dict(),
        "phrase-v1",
    )
    if not force and _report_is_complete(output_path, input_signature):
        phrase_report = load_phrase_report(output_path)
        return PhraseAnalysisRunResult(
            phrase_report=phrase_report,
            reused=True,
            console_report="\n".join(
                [
                    "Phrase analysis complete",
                    "",
                    f"Reused existing artifact: {output_path.as_posix()}",
                    f"Phrases: {len(phrase_report.phrases)}",
                ]
            ),
        )

    analysis = load_analysis_json(analysis_path)
    section_analysis = load_section_analysis(sections_path)
    phrases, relationships = build_phrase_report_data(
        analysis,
        section_analysis.sections,
        config.detection,
    )
    motifs = build_motifs(phrases, config.motifs)
    phrases = full_trajectory_plan(phrases, config.trajectory, config.motifs)
    trajectory = build_trajectory_points(phrases)

    phrase_report = PhraseReport(
        version=PHRASE_REPORT_VERSION,
        audio_path=section_analysis.audio_path,
        duration_ms=section_analysis.duration_ms,
        configuration=config.to_dict(),
        input_signature=input_signature,
        phrases=phrases,
        relationships=relationships,
        motifs=motifs,
        trajectory=trajectory,
        summary=_build_summary(phrases, relationships, motifs),
    )
    write_json(output_path, phrase_report.to_dict())
    return PhraseAnalysisRunResult(
        phrase_report=phrase_report,
        reused=False,
        console_report="\n".join(
            [
                "Phrase analysis complete",
                "",
                f"Phrases detected: {len(phrase_report.phrases)}",
                f"Relationships: {len(phrase_report.relationships)}",
                f"Motifs: {len(phrase_report.motifs)}",
                "",
                output_path.as_posix(),
            ]
        ),
    )


def load_phrase_report(path: Path) -> PhraseReport:
    from ..analysis_io import load_json_file

    raw_data = load_json_file(path, "Phrase report JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Phrase report JSON root must be an object: {path}")
    return PhraseReport.from_dict(raw_data)


def phrase_generator_metadata(
    report: PhraseReport,
    report_path_label: str,
) -> dict[str, Any]:
    """Compact phrase summary embedded into map generator metadata."""
    strategy_counts: dict[str, int] = {}
    for phrase in report.phrases:
        strategy_counts[phrase.strategy] = strategy_counts.get(phrase.strategy, 0) + 1
    return {
        "phraseCount": len(report.phrases),
        "motifCount": len(report.motifs),
        "relationshipCount": len(report.relationships),
        "strategies": {
            key: strategy_counts[key] for key in sorted(strategy_counts)
        },
        "reportPath": report_path_label,
        "version": report.version,
    }


def _build_summary(
    phrases: list[Any],
    relationships: list[Any],
    motifs: list[Any],
) -> dict[str, Any]:
    strategy_counts: dict[str, int] = {}
    for phrase in phrases:
        strategy_counts[phrase.strategy] = strategy_counts.get(phrase.strategy, 0) + 1
    return {
        "phraseCount": len(phrases),
        "relationshipCount": len(relationships),
        "motifCount": len(motifs),
        "averagePhraseDurationMs": round(
            sum(phrase.duration_ms for phrase in phrases) / len(phrases), 3
        )
        if phrases
        else 0.0,
        "strategyDistribution": {
            key: strategy_counts[key] for key in sorted(strategy_counts)
        },
        "relationshipTypes": _relationship_type_counts(relationships),
    }


def _relationship_type_counts(relationships: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relationship in relationships:
        counts[relationship.relationship_type] = (
            counts.get(relationship.relationship_type, 0) + 1
        )
    return {key: counts[key] for key in sorted(counts)}


def _report_is_complete(path: Path, signature: str) -> bool:
    if not path.exists():
        return False
    try:
        raw_data = __import__("json").loads(
            path.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        return False
    return (
        isinstance(raw_data, dict)
        and raw_data.get("inputSignature") == signature
        and isinstance(raw_data.get("phrases"), list)
        and bool(raw_data.get("phrases"))
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


def build_phrase_rhythm_info(
    report: PhraseReport,
) -> list[Any]:
    """Map the phrase report to rhythm-pipeline ``PhraseInfo`` objects.

    This is the bridge between Phase 20 phrase intelligence and the existing
    rhythm/density pipeline: each phrase contributes expected density and gap
    targets that adjust density targets during event selection.
    """
    from ..rhythm.rhythm_models import PhraseInfo, PhraseLabel

    output: list[PhraseInfo] = []
    for phrase in sorted(report.phrases, key=lambda item: item.start_ms):
        label = _to_phrase_label(phrase.label)
        output.append(
            PhraseInfo(
                start_ms=phrase.start_ms,
                end_ms=phrase.end_ms,
                label=label,
                confidence=phrase.confidence,
                expected_density=phrase.target_density,
                density_flexibility=0.6,
                min_gap_ms=phrase.min_gap_ms,
                target_gap_ms=phrase.target_gap_ms,
                strategy=phrase.strategy,
            )
        )
    return output


def _to_phrase_label(label: str) -> str:
    mapping: dict[str, str] = {
        "chorus-like": "chorus-like",
        "verse-like": "verse-like",
        "build-up": "build-up",
        "drop-like": "drop-like",
        "break-like": "break-like",
        "bridge-like": "bridge-like",
        "intro-like": "intro-like",
        "outro-like": "outro-like",
        "instrumental": "instrumental",
        "quiet": "quiet",
    }
    base = label.split("-")[0]
    if base in mapping:
        return mapping[base]
    return "unknown"
