from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..analysis_io import load_analysis_json, load_json_file
from ..beatmap_generator import generate_beatmap_from_analysis
from ..config import DifficultyPreset, get_difficulty_preset
from ..event_selector import select_events
from ..postprocess import improve_beatmap
from ..utils import (
    MapGeneratorError,
    copy_file,
    ensure_existing_file,
    resolve_browser_audio_path,
    write_json,
)
from ..validation import validate_beatmap

_logger = logging.getLogger(__name__)
from ..variation import PositionVariation
from .candidate_config import TournamentSettings, default_candidate_count, validate_candidate_count
from .candidate_generator import CandidateGenerationProfile, build_candidate_profile
from .candidate_models import (
    CandidateDiversity,
    CandidateFiles,
    CandidateIdentity,
    CandidateMetrics,
    CandidateScores,
    CandidateStatus,
    CandidateSummary,
    TournamentChampion,
    TournamentConfiguration,
    TournamentReport,
    TournamentScoreBreakdown,
    TournamentSongInfo,
    TournamentSummary,
)
from .candidate_report import (
    format_candidate_inspection,
    format_tournament_comparison,
    load_candidate_summary,
    load_tournament_report,
    write_candidate_summary,
    write_tournament_report,
)
from .diversity_analyzer import analyze_diversity
from .selection_policy import evaluate_candidate_status
from .stability_analyzer import analyze_stability
from .tournament_ranker import build_ranking, score_candidates


@dataclass(frozen=True)
class CandidateTournamentResult:
    tournament_report: TournamentReport
    console_report: str
    candidate_summaries: list[CandidateSummary]
    output_root: Path
    reused_count: int
    regenerated_count: int


def run_candidate_tournament(
    *,
    audio_path: Path,
    analysis_path: Path,
    title: str,
    artist: str,
    difficulty: str,
    root_seed: int,
    output_root: Path,
    champion_map_path: Path,
    champion_report_path: Path,
    tournament_report_path: Path,
    project_root: Path,
    count: int | None = None,
    timing_variation: bool = False,
    force: bool = False,
    verbose: bool = False,
    browser_audio_path_override: str | None = None,
    champion_map_browser_path_override: str | None = None,
    champion_report_browser_path_override: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    preset: DifficultyPreset | None = None,
    phrase_info: list[Any] | None = None,
) -> CandidateTournamentResult:
    ensure_existing_file(audio_path, "Audio file")
    ensure_existing_file(analysis_path, "Analysis JSON")
    preset = preset or get_difficulty_preset(difficulty)
    settings = TournamentSettings(
        candidate_count=validate_candidate_count(count or default_candidate_count(difficulty)),
        timing_variation=timing_variation,
        force=force,
    )
    analysis = load_analysis_json(analysis_path)

    # Load raw audio samples for slider intelligence (sustained analysis).
    raw_samples = None
    raw_sample_rate = None
    if preset.slider_enabled:
        try:
            from ..audio_analyzer import _load_audio
            raw_samples, raw_sample_rate = _load_audio(audio_path)
        except Exception:
            raw_samples = None

    shared_events = None if timing_variation else select_events(analysis, preset)
    browser_audio_path = resolve_browser_audio_path(
        audio_source_path=audio_path,
        project_root=project_root,
        audio_browser_path_override=browser_audio_path_override,
    )

    candidate_summaries: list[CandidateSummary] = []
    improved_maps_by_index: dict[int, dict[str, Any]] = {}
    improved_reports_by_index: dict[int, Any] = {}
    difficulty_consistency_by_index: dict[int, float] = {}
    reused_count = 0
    regenerated_count = 0

    for candidate_index in range(1, settings.candidate_count + 1):
        if progress_callback is not None:
            progress_callback(
                candidate_index,
                settings.candidate_count,
                f"Preparing candidate {candidate_index:03d} for {difficulty}.",
            )
        profile = build_candidate_profile(
            preset=preset,
            root_seed=root_seed,
            candidate_index=candidate_index,
            timing_variation=timing_variation,
        )
        candidate_dir = output_root / f"candidate-{candidate_index:03d}"
        paths = _candidate_paths(candidate_dir)
        files_complete = _candidate_is_complete(paths)

        if force or not files_complete:
            regenerated_count += 1
            _generate_candidate_artifacts(
                profile=profile,
                audio_path=audio_path,
                analysis_path=analysis_path,
                analysis=analysis,
                title=title,
                artist=artist,
                difficulty=difficulty,
                project_root=project_root,
                paths=paths,
                shared_events=shared_events,
                browser_audio_path_override=browser_audio_path_override,
                preset=preset,
                phrase_info=phrase_info,
                raw_samples=raw_samples,
                raw_sample_rate=raw_sample_rate,
            )
        else:
            reused_count += 1

        original_map = _load_map(paths["original_map"])
        improved_map = _load_map(paths["improved_map"])
        correction_data = _load_map(paths["corrections"])
        original_report = validate_beatmap(
            map_path=paths["original_map"],
            analysis_path=analysis_path,
            difficulty=difficulty,
            map_label=_relative_path(paths["original_map"], project_root),
        ).report
        improved_report = validate_beatmap(
            map_path=paths["improved_map"],
            analysis_path=analysis_path,
            difficulty=difficulty,
            map_label=_relative_path(paths["improved_map"], project_root),
        ).report

        candidate_metrics = _candidate_metrics(
            original_map=original_map,
            improved_report=improved_report,
            correction_data=correction_data,
        )
        status = evaluate_candidate_status(
            original_map=original_map,
            improved_map=improved_map,
            improved_report=improved_report,
            candidate_seed=profile.candidate_seed,
            expected_candidate_metadata=profile.metadata_dict(),
            files_complete=_candidate_artifacts_complete(paths),
            preset=preset,
            rules=settings.eligibility_rules,
        )
        stability = analyze_stability(
            original_report=original_report,
            improved_report=improved_report,
            candidate_metrics=candidate_metrics,
            preset=preset,
            settings=settings.stability,
        )
        candidate_summaries.append(
            CandidateSummary(
                version=1,
                candidate=CandidateIdentity(
                    index=profile.index,
                    difficulty=profile.difficulty,
                    root_seed=profile.root_seed,
                    candidate_seed=profile.candidate_seed,
                    timing_variation_enabled=profile.timing_variation_enabled,
                    variation_signature=profile.variation_signature,
                    variation_profile=profile.variation_profile(),
                ),
                files=CandidateFiles(
                    original_map=_relative_path(paths["original_map"], project_root),
                    original_report=_relative_path(paths["original_report"], project_root),
                    improved_map=_relative_path(paths["improved_map"], project_root),
                    improved_report=_relative_path(paths["improved_report"], project_root),
                    corrections=_relative_path(paths["corrections"], project_root),
                    summary=_relative_path(paths["summary"], project_root),
                ),
                scores=CandidateScores(
                    original_overall=original_report.scores.overall,
                    improved_overall=improved_report.scores.overall,
                    improvement=improved_report.scores.overall - original_report.scores.overall,
                ),
                status=status,
                metrics=candidate_metrics,
                diversity=CandidateDiversity(),
                stability=stability,
                score_breakdown=TournamentScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            )
        )
        improved_maps_by_index[candidate_index] = improved_map
        improved_reports_by_index[candidate_index] = improved_report
        difficulty_consistency_by_index[candidate_index] = improved_report.scores.difficulty_consistency

    eligible_count = sum(1 for summary in candidate_summaries if summary.status.eligible)
    diversity_result = analyze_diversity(
        candidates=candidate_summaries,
        improved_maps_by_index=improved_maps_by_index,
        eligible_count=eligible_count,
        timing_variation_enabled=timing_variation,
        settings=settings.diversity,
    )
    for summary in candidate_summaries:
        summary.diversity = diversity_result.candidate_diversity[summary.candidate.index]

    score_candidates(
        candidates=candidate_summaries,
        improved_reports_by_index=improved_reports_by_index,
        difficulty_consistency_by_index=difficulty_consistency_by_index,
        weights=settings.weights,
    )

    for summary in candidate_summaries:
        write_candidate_summary(output_root / f"candidate-{summary.candidate.index:03d}" / "candidate-summary.json", summary)

    if eligible_count == 0:
        raise MapGeneratorError(
            f"All {settings.candidate_count} candidates were rejected for {difficulty}. Candidate files were preserved under {output_root.as_posix()}."
        )

    ranking_entries, rejected_entries, champion_seed = build_ranking(
        candidates=candidate_summaries,
        improved_reports_by_index=improved_reports_by_index,
    )
    champion_browser_map = champion_map_browser_path_override or _public_path(
        champion_map_path,
        project_root,
    )
    champion_browser_report = champion_report_browser_path_override or _public_path(
        champion_report_path,
        project_root,
    )
    champion = TournamentChampion(
        candidate_index=champion_seed.candidate_index,
        candidate_seed=champion_seed.candidate_seed,
        tournament_score=champion_seed.tournament_score,
        quality_score=champion_seed.quality_score,
        stability_score=champion_seed.stability_score,
        map_path=champion_browser_map,
        report_path=champion_browser_report,
        source_map_path=champion_seed.source_map_path,
        source_report_path=champion_seed.source_report_path,
        summary_path=champion_seed.summary_path,
    )
    copy_file(project_root / champion.source_map_path, champion_map_path)
    copy_file(project_root / champion.source_report_path, champion_report_path)

    tournament_report = TournamentReport(
        version=1,
        song=TournamentSongInfo(
            title=title,
            artist=artist,
            difficulty=difficulty,
            audio=browser_audio_path,
        ),
        configuration=TournamentConfiguration(
            root_seed=root_seed,
            candidate_count=settings.candidate_count,
            timing_variation=timing_variation,
        ),
        summary=TournamentSummary(
            generated=settings.candidate_count,
            eligible=eligible_count,
            rejected=settings.candidate_count - eligible_count,
            unique=diversity_result.summary.unique_candidate_count,
            near_duplicate_groups=len(diversity_result.summary.near_duplicate_groups),
        ),
        champion=champion,
        ranking=ranking_entries,
        rejected_candidates=rejected_entries,
        diversity=diversity_result.summary,
        score_weights=settings.weights.to_dict(),
    )
    write_tournament_report(tournament_report_path, tournament_report)

    return CandidateTournamentResult(
        tournament_report=tournament_report,
        console_report=_format_console_report(
            report=tournament_report,
            tournament_report_path=tournament_report_path,
            reused_count=reused_count,
            regenerated_count=regenerated_count,
            verbose=verbose,
        ),
        candidate_summaries=candidate_summaries,
        output_root=output_root,
        reused_count=reused_count,
        regenerated_count=regenerated_count,
    )


def run_candidate_tournament_all(
    *,
    audio_path: Path,
    analysis_path: Path,
    title: str,
    artist: str,
    root_seed: int,
    project_root: Path,
    count: int | None = None,
    timing_variation: bool = False,
    force: bool = False,
    verbose: bool = False,
    browser_audio_path_override: str | None = None,
    champion_map_browser_path_override: str | None = None,
    champion_report_browser_path_override: str | None = None,
) -> list[CandidateTournamentResult]:
    slug = _slugify(audio_path.stem)
    results: list[CandidateTournamentResult] = []
    for difficulty in ("easy", "normal", "hard"):
        results.append(
            run_candidate_tournament(
                audio_path=audio_path,
                analysis_path=analysis_path,
                title=title,
                artist=artist,
                difficulty=difficulty,
                root_seed=root_seed,
                output_root=project_root / "public" / "candidates" / slug / difficulty,
                champion_map_path=project_root / "public" / "maps" / "champions" / f"{slug}-{difficulty}.json",
                champion_report_path=project_root / "public" / "reports" / "champions" / f"{slug}-{difficulty}-report.json",
                tournament_report_path=project_root / "public" / "tournaments" / f"{slug}-{difficulty}-tournament.json",
                project_root=project_root,
                count=count,
                timing_variation=timing_variation,
                force=force,
                verbose=verbose,
                browser_audio_path_override=browser_audio_path_override,
                champion_map_browser_path_override=champion_map_browser_path_override,
                champion_report_browser_path_override=champion_report_browser_path_override,
            )
        )
    return results


def compare_tournament_reports(*, tournaments_dir: Path) -> str:
    if not tournaments_dir.exists() or not tournaments_dir.is_dir():
        raise MapGeneratorError(f"Tournaments directory does not exist: {tournaments_dir}")
    reports = [
        load_tournament_report(path)
        for path in sorted(tournaments_dir.glob("*-tournament.json"))
    ]
    return format_tournament_comparison(reports)


def inspect_candidate_summary(*, summary_path: Path, verbose: bool = False) -> str:
    return format_candidate_inspection(load_candidate_summary(summary_path), verbose=verbose)


def _generate_candidate_artifacts(
    *,
    profile: CandidateGenerationProfile,
    audio_path: Path,
    analysis_path: Path,
    analysis: Any,
    title: str,
    artist: str,
    difficulty: str,
    project_root: Path,
    paths: dict[str, Path],
    shared_events: list[Any] | None,
    browser_audio_path_override: str | None,
    preset: DifficultyPreset | None = None,
    base_variation: PositionVariation | None = None,
    phrase_info: list[Any] | None = None,
    raw_samples: Any = None,
    raw_sample_rate: int | None = None,
) -> None:
    selected_events = shared_events
    if selected_events is None:
        selected_events = select_events(
            analysis,
            preset or get_difficulty_preset(difficulty),
            variation=profile.event_variation,
        )

    generate_beatmap_from_analysis(
        analysis=analysis,
        audio_path=audio_path,
        title=title,
        artist=artist,
        difficulty=difficulty,
        seed=profile.candidate_seed,
        output_path=paths["original_map"],
        analysis_output_path=None,
        project_root=project_root,
        selected_events_override=selected_events,
        event_variation=profile.event_variation,
        position_variation=profile.position_variation,
        preset=preset,
        base_variation=base_variation,
        generator_metadata={"candidate": profile.metadata_dict()},
        browser_audio_path_override=browser_audio_path_override,
        phrase_info=phrase_info,
        raw_samples=raw_samples,
        raw_sample_rate=raw_sample_rate,
    )
    validate_beatmap(
        map_path=paths["original_map"],
        analysis_path=analysis_path,
        difficulty=difficulty,
        output_path=paths["original_report"],
        map_label=_relative_path(paths["original_map"], project_root),
    )
    try:
        improve_beatmap(
            map_path=paths["original_map"],
            analysis_path=analysis_path,
            report_path=paths["original_report"],
            difficulty=difficulty,
            seed=profile.candidate_seed,
            output_path=paths["improved_map"],
            report_output_path=paths["improved_report"],
            changes_output_path=paths["corrections"],
            source_map_label=_relative_path(paths["original_map"], project_root),
            output_map_label=_relative_path(paths["improved_map"], project_root),
        )
    except (MapGeneratorError, ValueError, RuntimeError) as exc:
        _logger.warning(
            "Post-processing failed for candidate %03d (%s) — "
            "falling back to unimproved map. Error: %s",
            profile.index,
            difficulty,
            exc,
        )
        # Fall back: copy the original map as the "improved" output so
        # downstream ranking still has a valid file to work with.
        original_map_data = _load_map(paths["original_map"])
        write_json(paths["improved_map"], original_map_data)
        copy_file(paths["original_report"], paths["improved_report"])
        write_json(
            paths["corrections"],
            {
                "version": 1,
                "sourceMap": _relative_path(paths["original_map"], project_root),
                "outputMap": _relative_path(paths["improved_map"], project_root),
                "difficulty": difficulty,
                "seed": profile.candidate_seed,
                "accepted": False,
                "summary": {
                    "plannedActions": 0,
                    "acceptedActions": 0,
                    "revertedActions": 0,
                    "movedObjects": 0,
                    "timingAdjustments": 0,
                    "removedObjects": 0,
                    "insertedObjects": 0,
                },
                "actions": [],
                "rejectionReason": f"Post-processing failed: {exc}",
            },
        )


def _candidate_paths(candidate_dir: Path) -> dict[str, Path]:
    return {
        "original_map": candidate_dir / "original-map.json",
        "original_report": candidate_dir / "original-report.json",
        "improved_map": candidate_dir / "improved-map.json",
        "improved_report": candidate_dir / "improved-report.json",
        "corrections": candidate_dir / "corrections.json",
        "summary": candidate_dir / "candidate-summary.json",
    }


def _candidate_is_complete(paths: dict[str, Path]) -> bool:
    return _candidate_artifacts_complete(paths) and paths["summary"].exists() and paths["summary"].is_file()


def _candidate_artifacts_complete(paths: dict[str, Path]) -> bool:
    required_keys = (
        "original_map",
        "original_report",
        "improved_map",
        "improved_report",
        "corrections",
    )
    return all(paths[key].exists() and paths[key].is_file() for key in required_keys)


def _load_map(path: Path) -> dict[str, Any]:
    raw_data = load_json_file(path, "JSON")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"JSON root must be an object: {path}")
    return raw_data


def _candidate_metrics(
    *,
    original_map: dict[str, Any],
    improved_report: Any,
    correction_data: dict[str, Any],
) -> CandidateMetrics:
    summary = correction_data.get("summary")
    actions = correction_data.get("actions")
    if not isinstance(summary, dict) or not isinstance(actions, list):
        raise MapGeneratorError("Correction report is missing summary or actions data.")

    accepted_actions = [item for item in actions if isinstance(item, dict) and item.get("accepted") is True]
    destructive_corrections = int(summary.get("removedObjects", 0)) + int(summary.get("insertedObjects", 0))
    max_timing_adjustment_ms = 0.0
    max_coordinate_shift_px = 0.0

    for action in accepted_actions:
        before = action.get("before")
        after = action.get("after")
        if isinstance(before, dict) and isinstance(after, dict):
            if isinstance(before.get("time"), (int, float)) and isinstance(after.get("time"), (int, float)):
                max_timing_adjustment_ms = max(
                    max_timing_adjustment_ms,
                    abs(float(after["time"]) - float(before["time"])),
                )
            if all(isinstance(before.get(key), (int, float)) and isinstance(after.get(key), (int, float)) for key in ("x", "y")):
                max_coordinate_shift_px = max(
                    max_coordinate_shift_px,
                    math.hypot(
                        float(after["x"]) - float(before["x"]),
                        float(after["y"]) - float(before["y"]),
                    ),
                )

    return CandidateMetrics(
        accepted_corrections=int(summary.get("acceptedActions", 0)),
        reverted_corrections=int(summary.get("revertedActions", 0)),
        destructive_corrections=destructive_corrections,
        critical_issues=improved_report.summary.critical,
        errors=improved_report.summary.errors,
        warnings=improved_report.summary.warnings,
        max_cursor_speed=improved_report.metrics.movement.highest_cursor_speed,
        object_count=improved_report.map_info.object_count,
        max_timing_adjustment_ms=max_timing_adjustment_ms,
        max_coordinate_shift_px=max_coordinate_shift_px,
        timing_signature=_timing_signature(original_map),
    )


def _timing_signature(map_data: dict[str, Any]) -> str:
    objects = map_data.get("objects", [])
    if not isinstance(objects, list):
        return "invalid"
    payload = ",".join(str(int(item.get("time", 0))) for item in objects if isinstance(item, dict))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _public_path(path: Path, project_root: Path) -> str:
    public_root = (project_root / "public").resolve()
    resolved = path.resolve()
    try:
        return "/" + resolved.relative_to(public_root).as_posix()
    except ValueError as error:
        raise MapGeneratorError(f"Path must stay within public/: {path}") from error


def _slugify(value: str) -> str:
    characters: list[str] = []
    previous_dash = False
    for character in value.lower():
        if character.isalnum():
            characters.append(character)
            previous_dash = False
            continue
        if not previous_dash:
            characters.append("-")
            previous_dash = True
    slug = "".join(characters).strip("-")
    return slug or "song"


def _format_console_report(
    *,
    report: TournamentReport,
    tournament_report_path: Path,
    reused_count: int,
    regenerated_count: int,
    verbose: bool,
) -> str:
    lines = [
        "Candidate tournament complete",
        "",
        f"Song: {report.song.title}",
        f"Difficulty: {report.song.difficulty}",
        f"Root seed: {report.configuration.root_seed}",
        f"Generated candidates: {report.summary.generated}",
        f"Eligible candidates: {report.summary.eligible}",
        f"Rejected candidates: {report.summary.rejected}",
        f"Unique candidates: {report.summary.unique}",
        f"Reused candidate directories: {reused_count}",
        f"Regenerated candidate directories: {regenerated_count}",
        "",
        f"Champion: Candidate {report.champion.candidate_index:03d}",
        f"Tournament score: {report.champion.tournament_score:.1f}",
        f"Quality score: {report.champion.quality_score:.1f}",
        f"Stability score: {report.champion.stability_score:.1f}",
        "",
        "Top candidates:",
    ]
    for entry in report.ranking[:3]:
        lines.append(f"{entry.rank}. Candidate {entry.candidate_index:03d} - {entry.tournament_score:.1f}")
    lines.extend(
        [
            "",
            "Champion map:",
            report.champion.map_path,
            "",
            "Tournament report:",
            tournament_report_path.as_posix(),
        ]
    )
    if verbose and report.rejected_candidates:
        lines.extend(["", "Rejected candidates"])
        for candidate in report.rejected_candidates:
            lines.append(
                f"- Candidate {candidate.candidate_index:03d}: {'; '.join(candidate.rejection_reasons)}"
            )
    return "\n".join(lines)
