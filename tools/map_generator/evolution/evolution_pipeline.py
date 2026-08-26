from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_logger = logging.getLogger(__name__)

from ..analysis_io import load_analysis_json
from ..candidates.candidate_generator import build_candidate_profile
from ..candidates.candidate_models import (
    CandidateDiversity,
    CandidateFiles,
    CandidateIdentity,
    CandidateMetrics,
    CandidateScores,
    CandidateStatus,
    CandidateSummary,
    StabilitySummary,
    TournamentScoreBreakdown,
)
from ..candidates.candidate_pipeline import (
    _candidate_is_complete,
    _candidate_metrics,
    _candidate_paths,
    _generate_candidate_artifacts,
    _load_map,
    _public_path,
    _relative_path,
)
from ..candidates.candidate_report import write_candidate_summary
from ..candidates.selection_policy import evaluate_candidate_status
from ..config import DifficultyPreset, get_difficulty_preset
from ..difficulty import analyze_difficulty
from ..difficulty.common import clamp
from ..difficulty.models import DifficultyTarget
from ..variation import PositionVariation
from ..event_selector import select_events
from ..geometry.collision import clear_slider_cache
from ..postprocess import improve_beatmap
from ..rebalance import (
    MapEvaluation,
    rebalance_generator_metadata,
    run_rebalance,
    write_rebalance_report,
)
from ..replay import (
    replay_generator_metadata,
    simulate_replay,
    write_replay_report,
)
from ..utils import MapGeneratorError, copy_file, ensure_existing_file, write_json
from ..validation import validate_beatmap
from .archive import archive_status_line, validate_archive_policy
from .comparison import build_comparison
from .final_ranking import (
    EvolutionFinalWeights,
    compute_final_breakdown,
    diversity_penalty,
    mandatory_gates_passed,
    quality_gate_penalty,
    run_quality_gates,
    target_deviation,
)
from .heatmaps import build_heatmaps
from .improvement import ImprovementResult, run_improvement_passes
from .models import (
    EvolutionChampion,
    EvolutionComparisonEntry,
    EvolutionConfiguration,
    EvolutionDiagnostics,
    EvolutionDimensionScores,
    EvolutionHeatmap,
    EvolutionRankingEntry,
    EvolutionRebalanceSummary,
    EvolutionReplaySummary,
    EvolutionReport,
    EvolutionReproductionInfo,
    EvolutionSongInfo,
    EvolutionSummary,
    ImprovementPassEntry,
    RejectedEvolutionCandidate,
)
from .report_writer import write_evolution_report
from .scoring import EvolutionScoreWeights, score_candidate

MAX_EVOLUTION_PASSES = 5
DEFAULT_ARCHIVE_POLICY = "all"


@dataclass(frozen=True)
class CandidateEvolutionResult:
    evolution_report: EvolutionReport
    console_report: str
    candidate_summaries: list[CandidateSummary]
    output_root: Path
    reused_count: int
    regenerated_count: int


def run_candidate_evolution(
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
    evolution_report_path: Path,
    project_root: Path,
    count: int | None = None,
    timing_variation: bool = False,
    force: bool = False,
    verbose: bool = False,
    max_passes: int = MAX_EVOLUTION_PASSES,
    archive_policy: str = DEFAULT_ARCHIVE_POLICY,
    sections_path: Path | None = None,
    browser_audio_path_override: str | None = None,
    champion_map_browser_path_override: str | None = None,
    champion_report_browser_path_override: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    replay_report_path: Path | None = None,
    player_profile: str = "advanced",
    player_overrides: dict[str, Any] | None = None,
    rebalance_passes: int = 2,
    rebalance_report_path: Path | None = None,
    final_weight_overrides: dict[str, float] | None = None,
    diversity_protection: bool = True,
    preset: DifficultyPreset | None = None,
    target: DifficultyTarget | None = None,
    base_variation: PositionVariation | None = None,
    generation_config: dict[str, Any] | None = None,
    phrase_report_path: Path | None = None,
    phrase_info: list[Any] | None = None,
) -> CandidateEvolutionResult:
    """Generate, evaluate, compare, improve, and promote the best candidate.

    Every candidate receives a deterministic Phase 15 replay simulation that
    contributes to the leaderboard scoring. Deterministic: identical audio,
    analysis, seed, settings, difficulty, player profile, and evolution
    options always produce the same leaderboard and champion.

    When ``phrase_report_path`` (or a prebuilt ``phrase_info``) is provided,
    Phase 20 phrase intelligence shapes event density per phrase and adds a
    phrase-coherence component to candidate evaluation.
    """
    ensure_existing_file(audio_path, "Audio file")
    ensure_existing_file(analysis_path, "Analysis JSON")
    preset = preset or get_difficulty_preset(difficulty)
    from ..candidates.candidate_config import default_candidate_count, validate_candidate_count

    candidate_count = validate_candidate_count(count or default_candidate_count(difficulty))
    passes = max(0, min(MAX_EVOLUTION_PASSES, int(max_passes)))
    policy = validate_archive_policy(archive_policy)
    analysis = load_analysis_json(analysis_path)
    shared_events = None if timing_variation else select_events(analysis, preset)
    browser_audio_path = browser_audio_path_override or _public_path(
        audio_path,
        project_root,
    )
    resolved_phrase_info = phrase_info
    phrase_report = None
    phrase_density_at = None
    if resolved_phrase_info is None and phrase_report_path is not None:
        from ..phrase import load_phrase_report
        if phrase_report_path.exists():
            phrase_report = load_phrase_report(phrase_report_path)
            from ..phrase.phrase_pipeline import build_phrase_rhythm_info
            resolved_phrase_info = build_phrase_rhythm_info(phrase_report)
    if phrase_report is not None:
        from ..phrase.trajectory_planner import build_phrase_density_resolver
        phrase_density_at = build_phrase_density_resolver(phrase_report.phrases)
    resolved_replay_report_path = replay_report_path or evolution_report_path.with_name(
        evolution_report_path.stem + "-replay.json"
    )
    replay_report_path_label = _relative_path(resolved_replay_report_path, project_root)
    resolved_rebalance_report_path = rebalance_report_path or evolution_report_path.with_name(
        evolution_report_path.stem + "-rebalance.json"
    )
    rebalance_report_path_label = _relative_path(
        resolved_rebalance_report_path,
        project_root,
    )
    rebalance_passes = max(0, int(rebalance_passes))
    final_weights = EvolutionFinalWeights().with_overrides(final_weight_overrides)

    candidate_summaries: list[CandidateSummary] = []
    difficulty_results_by_index: dict[int, Any] = {}
    difficulty_reports_by_index: dict[int, Any] = {}
    scores_by_index: dict[int, EvolutionDimensionScores] = {}
    improved_reports_by_index: dict[int, Any] = {}
    improved_maps_by_index: dict[int, dict[str, Any]] = {}
    replay_reports_by_index: dict[int, Any] = {}
    rebalance_reports_by_index: dict[int, Any] = {}
    reused_count = 0
    regenerated_count = 0

    for candidate_index in range(1, candidate_count + 1):
        if progress_callback is not None:
            progress_callback(
                candidate_index,
                candidate_count,
                f"Generating candidate {candidate_index:03d} for {difficulty}.",
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
                base_variation=base_variation,
                phrase_info=resolved_phrase_info,
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

        difficulty_result = analyze_difficulty(
            map_path=paths["improved_map"],
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=None,
            map_label=_relative_path(paths["improved_map"], project_root),
            sections_path=sections_path if sections_path and sections_path.exists() else None,
            target=target,
        )
        difficulty_results_by_index[candidate_index] = difficulty_result
        difficulty_reports_by_index[candidate_index] = difficulty_result.report
        improved_reports_by_index[candidate_index] = improved_report
        improved_maps_by_index[candidate_index] = improved_map

        # Phase 15: every candidate receives a deterministic replay simulation
        # as a primary evaluation stage alongside static difficulty analysis.
        replay_report = simulate_replay(
            map_path=paths["improved_map"],
            analysis=analysis,
            difficulty_report=difficulty_result.report,
            difficulty=difficulty,
            seed=profile.candidate_seed,
            player_profile=player_profile,
            player_overrides=player_overrides,
        )
        replay_reports_by_index[candidate_index] = replay_report
        candidate_replay_path_label = _relative_path(
            candidate_dir / "replay-report.json",
            project_root,
        )
        write_replay_report(candidate_dir / "replay-report.json", replay_report)
        _embed_replay_metadata(
            paths["improved_map"],
            replay_report,
            candidate_replay_path_label,
        )

        # Phase 16: adaptive rebalancing refines the candidate before ranking.
        # Runs after generation, difficulty evaluation, and replay simulation;
        # only meaningful improvements are kept.
        rebalance_outcome = _rebalance_candidate(
            candidate_index=candidate_index,
            map_dict=improved_map,
            difficulty_report=difficulty_result.report,
            replay_report=replay_report,
            improved_report=improved_report,
            difficulty=difficulty,
            seed=profile.candidate_seed,
            analysis=analysis,
            analysis_path=analysis_path,
            project_root=project_root,
            candidate_dir=candidate_dir,
            paths=paths,
            passes=rebalance_passes,
            player_profile=player_profile,
            player_overrides=player_overrides,
            map_title=title,
            map_artist=artist,
            preset=preset,
            target=target,
            phrase_density_at=phrase_density_at,
        )
        if rebalance_outcome is not None:
            rebalance_reports_by_index[candidate_index] = rebalance_outcome.rebalance_report
        if rebalance_outcome is not None and rebalance_outcome.improved:
            improved_map = rebalance_outcome.map_dict
            difficulty_result = rebalance_outcome.difficulty_result
            improved_report = rebalance_outcome.validation_report
            replay_report = rebalance_outcome.replay_report
            replay_reports_by_index[candidate_index] = replay_report
            difficulty_results_by_index[candidate_index] = difficulty_result
            difficulty_reports_by_index[candidate_index] = difficulty_result.report
            improved_reports_by_index[candidate_index] = improved_report
            improved_maps_by_index[candidate_index] = improved_map

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
            rules=_eligibility_rules(),
        )
        stability = _evolution_stability(difficulty_result.report)
        scores = score_candidate(
            improved_report=improved_report,
            difficulty_report=difficulty_result.report,
            replay_report=replay_report,
        )
        scores_by_index[candidate_index] = scores

        summary = CandidateSummary(
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
                tournament_score=scores.overall,
                quality_score=scores.quality,
                stability_score=stability.score,
            ),
            status=status,
            metrics=candidate_metrics,
            diversity=CandidateDiversity(),
            stability=stability,
            score_breakdown=TournamentScoreBreakdown(
                improved_overall_component=scores.quality,
                safety_component=scores.playability,
                stability_component=stability.score,
                difficulty_component=scores.difficulty,
                efficiency_component=scores.flow,
                diversity_component=scores.pattern,
            ),
        )
        candidate_summaries.append(summary)
        write_candidate_summary(candidate_dir / "candidate-summary.json", summary)

        # Flush slider path cache between candidates to prevent gradual
        # memory accumulation from validation / difficulty / replay passes
        # that each sample slider geometry independently.
        clear_slider_cache()

    eligible_count = sum(1 for summary in candidate_summaries if summary.status.eligible)
    if eligible_count == 0:
        # Relax strict gate: when all candidates are technically rejected,
        # fall back to the best-scoring candidate rather than aborting the
        # entire generation pipeline.
        _logger.warning(
            "All %d candidates were rejected for %s — falling back to best-scoring candidate.",
            candidate_count,
            difficulty,
        )

    # Flush slider cache before champion improvement to reclaim memory
    # accumulated across all candidate evaluations.
    clear_slider_cache()

    # Phase 17: final ranking combines every evaluation signal, applies
    # quality gates and diversity protection, then selects the champion.
    # Phase 20: when phrase intelligence is active, a phrase-coherence
    # component is folded into each candidate's final breakdown.
    ranking_entries, rejected_entries, champion_record = _build_final_ranking(
        candidates=candidate_summaries,
        scores_by_index=scores_by_index,
        difficulty_reports_by_index=difficulty_reports_by_index,
        replay_reports_by_index=replay_reports_by_index,
        improved_reports_by_index=improved_reports_by_index,
        improved_maps_by_index=improved_maps_by_index,
        rebalance_reports_by_index=rebalance_reports_by_index,
        final_weights=final_weights,
        diversity_protection=diversity_protection,
        difficulty=difficulty,
        output_root=output_root,
        phrase_report=phrase_report,
    )
    champion_index = champion_record.candidate_index
    champion_summary = next(
        summary
        for summary in candidate_summaries
        if summary.candidate.index == champion_index
    )
    runner_index = champion_record.runner_index

    # Multi-pass improvement refines the champion toward its difficulty target.
    improvement = _improve_champion(
        champion_summary=champion_summary,
        difficulty_result=difficulty_results_by_index[champion_index],
        improved_report=improved_reports_by_index[champion_index],
        improved_map=improved_maps_by_index[champion_index],
        difficulty=difficulty,
        analysis_path=analysis_path,
        analysis=analysis,
        project_root=project_root,
        candidate_dir=output_root / f"candidate-{champion_index:03d}",
        passes=passes,
        player_profile=player_profile,
        player_overrides=player_overrides,
        replay_report_path_label=replay_report_path_label,
        current_replay_report=replay_reports_by_index[champion_index],
        preset=preset,
        target=target,
    )
    champion_scores = (
        improvement.final_scores
        if improvement.final_scores is not None
        else scores_by_index[champion_index]
    )
    champion_replay_report = (
        improvement.final_replay_report
        if improvement.final_replay_report is not None
        else replay_reports_by_index[champion_index]
    )
    runner_scores = scores_by_index[runner_index]

    comparison_entries, comparison_reasons = build_comparison(
        champion=champion_scores,
        runner=runner_scores,
        improvement_gain=improvement.improvement_gain,
    )
    # Reports must be in the same (rank) order as ranking_indices so the
    # heatmap columns line up with the leaderboard.
    heatmaps = build_heatmaps(
        difficulty_reports=[
            difficulty_reports_by_index[entry.candidate_index]
            for entry in ranking_entries
        ],
        ranking_indices=[entry.candidate_index for entry in ranking_entries],
    )
    replay_summary = _build_replay_summary(champion_replay_report)

    retained = _apply_archive(
        output_root=output_root,
        ranked_indices=[entry.candidate_index for entry in ranking_entries],
        policy=policy,
    )
    # When evolution passes produced a stronger champion, promote the final
    # pass artifacts so the delivered map/report match the reported scores.
    champion_source_map, champion_source_report = _champion_source_artifacts(
        improvement=improvement,
        candidate_dir=output_root / f"candidate-{champion_index:03d}",
        fallback_map=champion_summary.files.improved_map,
        fallback_report=champion_summary.files.improved_report,
        project_root=project_root,
    )
    champion_browser_map = champion_map_browser_path_override or _public_path(
        champion_map_path,
        project_root,
    )
    champion_browser_report = champion_report_browser_path_override or _public_path(
        champion_report_path,
        project_root,
    )
    champion = EvolutionChampion(
        candidate_index=champion_summary.candidate.index,
        candidate_seed=champion_summary.candidate.candidate_seed,
        overall_score=champion_scores.overall,
        quality_score=champion_scores.quality,
        stars=float(difficulty_reports_by_index[champion_index].star_rating.overall),
        map_path=champion_browser_map,
        report_path=champion_browser_report,
        source_map_path=champion_source_map,
        source_report_path=champion_source_report,
        summary_path=champion_summary.files.summary,
        promotion_reason=_promotion_reason(
            candidate_index=champion_summary.candidate.index,
            champion=champion_scores,
            runner=runner_scores,
            improvement_gain=improvement.improvement_gain,
        ),
        final_breakdown=champion_record.final_breakdown,
        weakest_sections=champion_record.weakest_sections,
        strongest_sections=champion_record.strongest_sections,
        biggest_improvements=champion_record.biggest_improvements,
        lost_reasons=champion_record.lost_reasons,
    )
    copy_file(project_root / champion.source_map_path, champion_map_path)
    copy_file(project_root / champion.source_report_path, champion_report_path)
    # Persist the champion replay report both as a separate JSON file and
    # embedded into the champion map's generator metadata.
    write_replay_report(resolved_replay_report_path, champion_replay_report)
    _embed_replay_metadata(
        champion_map_path,
        champion_replay_report,
        replay_report_path_label,
    )
    # Flush slider cache after improvement passes to reclaim memory before
    # the final champion rebalance.
    clear_slider_cache()

    # Phase 16: adaptive rebalancing on the champion's delivered map so the
    # champion report always reflects the final map (including any accepted
    # improvement-pass output). Runs whenever rebalance passes are enabled.
    champion_rebalance_report = _rebalance_champion(
        champion_map_path=champion_map_path,
        difficulty=difficulty,
        seed=champion_summary.candidate.candidate_seed,
        analysis=analysis,
        analysis_path=analysis_path,
        project_root=project_root,
        working_dir=output_root
        / f"candidate-{champion_index:03d}"
        / "champion-rebalance",
        passes=rebalance_passes,
        player_profile=player_profile,
        player_overrides=player_overrides,
        resolved_replay_report_path=resolved_replay_report_path,
        replay_report_path_label=replay_report_path_label,
        resolved_rebalance_report_path=resolved_rebalance_report_path,
        rebalance_report_path_label=rebalance_report_path_label,
        map_title=title,
        map_artist=artist,
        preset=preset,
        target=target,
        phrase_density_at=phrase_density_at,
    )

    # Flush slider cache after champion rebalance to prevent stale cached
    # paths from persisting into the final report assembly.
    clear_slider_cache()

    # Phase 17: persist the reproduction configuration with the report so the
    # champion can be reproduced from identical inputs.
    reproduction = EvolutionReproductionInfo(
        generator_version=_generator_version(champion_map_path),
        evolution_version="20",
        seed=root_seed,
        candidate_count=candidate_count,
        final_weights=final_weights.to_dict(),
        replay_profile=player_profile,
        rebalance_passes=rebalance_passes,
        target_difficulty=difficulty,
        generation_config=generation_config,
        phrase_report_path=(
            _relative_path(phrase_report_path, project_root)
            if phrase_report_path is not None
            else None
        ),
    )

    evolution_report = EvolutionReport(
        version=1,
        song=EvolutionSongInfo(
            title=title,
            artist=artist,
            difficulty=difficulty,
            audio=browser_audio_path,
        ),
        configuration=EvolutionConfiguration(
            root_seed=root_seed,
            candidate_count=candidate_count,
            max_passes=passes,
            archive_policy=policy,
            timing_variation=timing_variation,
        ),
        summary=EvolutionSummary(
            generated=candidate_count,
            eligible=eligible_count,
            rejected=candidate_count - eligible_count,
            passes_used=improvement.passes_used,
            early_stopped=improvement.early_stopped,
        ),
        champion=champion,
        ranking=ranking_entries,
        rejected_candidates=rejected_entries,
        comparison=comparison_entries,
        comparison_reasons=comparison_reasons,
        heatmaps=heatmaps,
        replay=replay_summary,
        improvement_history=improvement.history,
        diagnostics=_build_diagnostics(
            ranking_entries=ranking_entries,
            improvement=improvement,
            champion_scores=champion_scores,
            runner_scores=runner_scores,
        ),
        score_weights=EvolutionScoreWeights().to_dict(),
        replay_report_path=replay_report_path_label,
        rebalance=(
            _build_rebalance_summary(champion_rebalance_report)
            if champion_rebalance_report is not None
            else EvolutionRebalanceSummary.empty()
        ),
        rebalance_report_path=rebalance_report_path_label,
        reproduction=reproduction,
        final_weights=final_weights.to_dict(),
    )
    write_evolution_report(evolution_report_path, evolution_report)

    return CandidateEvolutionResult(
        evolution_report=evolution_report,
        console_report=_format_console_report(
            report=evolution_report,
            evolution_report_path=evolution_report_path,
            retained_count=len(retained),
            archive_status=archive_status_line(policy, len(retained), candidate_count),
            reused_count=reused_count,
            regenerated_count=regenerated_count,
            verbose=verbose,
        ),
        candidate_summaries=candidate_summaries,
        output_root=output_root,
        reused_count=reused_count,
        regenerated_count=regenerated_count,
    )


def run_candidate_evolution_all(
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
    max_passes: int = MAX_EVOLUTION_PASSES,
    archive_policy: str = DEFAULT_ARCHIVE_POLICY,
    sections_path: Path | None = None,
    player_profile: str = "advanced",
    player_overrides: dict[str, Any] | None = None,
    rebalance_passes: int = 2,
    final_weight_overrides: dict[str, float] | None = None,
    diversity_protection: bool = True,
    preset: DifficultyPreset | None = None,
    target: DifficultyTarget | None = None,
    base_variation: PositionVariation | None = None,
    generation_config: dict[str, Any] | None = None,
    phrase_report_path: Path | None = None,
) -> list[CandidateEvolutionResult]:
    slug = _slugify(audio_path.stem)
    results: list[CandidateEvolutionResult] = []
    for difficulty in ("easy", "normal", "hard"):
        results.append(
            run_candidate_evolution(
                audio_path=audio_path,
                analysis_path=analysis_path,
                title=title,
                artist=artist,
                difficulty=difficulty,
                root_seed=root_seed,
                output_root=project_root / "public" / "candidates" / slug / difficulty,
                champion_map_path=project_root / "public" / "maps" / "champions" / f"{slug}-{difficulty}.json",
                champion_report_path=project_root / "public" / "reports" / "champions" / f"{slug}-{difficulty}-report.json",
                evolution_report_path=project_root / "public" / "evolution" / f"{slug}-{difficulty}-evolution.json",
                project_root=project_root,
                count=count,
                timing_variation=timing_variation,
                force=force,
                verbose=verbose,
                max_passes=max_passes,
                archive_policy=archive_policy,
                sections_path=sections_path,
                player_profile=player_profile,
                player_overrides=player_overrides,
                rebalance_passes=rebalance_passes,
                final_weight_overrides=final_weight_overrides,
                diversity_protection=diversity_protection,
                preset=preset,
                target=target,
                base_variation=base_variation,
                generation_config=generation_config,
                phrase_report_path=phrase_report_path,
            )
        )
        # Flush slider path cache between difficulty levels to prevent
        # stale slider geometry data from leaking across difficulty runs.
        clear_slider_cache()

    return results


@dataclass(frozen=True)
class _FinalChampionRecord:
    candidate_index: int
    runner_index: int
    final_breakdown: Any
    weakest_sections: list[str]
    strongest_sections: list[str]
    biggest_improvements: list[str]
    lost_reasons: list[str]


def _build_final_ranking(
    *,
    candidates: list[CandidateSummary],
    scores_by_index: dict[int, EvolutionDimensionScores],
    difficulty_reports_by_index: dict[int, Any],
    replay_reports_by_index: dict[int, Any],
    improved_reports_by_index: dict[int, Any],
    improved_maps_by_index: dict[int, dict[str, Any]],
    rebalance_reports_by_index: dict[int, Any],
    final_weights: EvolutionFinalWeights,
    diversity_protection: bool,
    difficulty: str,
    output_root: Path,
    phrase_report: Any | None = None,
) -> tuple[list[EvolutionRankingEntry], list[RejectedEvolutionCandidate], _FinalChampionRecord]:
    """Phase 17 final ranking: unified score + quality gates + diversity.

    Every candidate receives a separately-visible final breakdown. Mandatory
    gate failures disqualify a candidate from champion selection; quality-gate
    and diversity penalties affect the ranking order. Returns ranked entries,
    rejected candidates, and the selected champion record.
    """
    eligible = [summary for summary in candidates if summary.status.eligible]
    rejected = [
        RejectedEvolutionCandidate(
            candidate_index=summary.candidate.index,
            candidate_seed=summary.candidate.candidate_seed,
            overall_score=summary.scores.tournament_score,
            rejection_reasons=summary.status.rejection_reasons,
            summary_path=summary.files.summary,
        )
        for summary in candidates
        if not summary.status.eligible
    ]

    records: list[dict[str, Any]] = []
    for summary in eligible:
        index = summary.candidate.index
        difficulty_report = difficulty_reports_by_index[index]
        replay_report = replay_reports_by_index.get(index)
        validation_report = improved_reports_by_index.get(index)
        map_dict = improved_maps_by_index.get(index) or {}
        rebalance_report = rebalance_reports_by_index.get(index)
        final = compute_final_breakdown(
            scores=scores_by_index[index],
            difficulty_report=difficulty_report,
            replay_report=replay_report,
            validation_report=validation_report,
            rebalance_report=rebalance_report,
            weights=final_weights,
            phrase_report=phrase_report,
            map_dict=map_dict,
        )
        gates = run_quality_gates(
            difficulty_report=difficulty_report,
            replay_report=replay_report,
            validation_report=validation_report,
            map_dict=map_dict,
        )
        gate_penalty = quality_gate_penalty(gates)
        valid = mandatory_gates_passed(gates)
        records.append(
            {
                "summary": summary,
                "index": index,
                "map_dict": map_dict,
                "final": final,
                "gates": gates,
                "gate_penalty": gate_penalty,
                "adjusted": clamp(final.weighted_score - gate_penalty, 0.0, 100.0),
                "diversity_penalty": 0.0,
                "validation_status": "passed" if valid else "failed",
            }
        )

    records.sort(
        key=lambda record: (
            -record["adjusted"],
            -record["final"].weighted_score,
            -scores_by_index[record["index"]].quality,
            record["index"],
        )
    )

    # Diversity protection: near-identical candidates are penalized relative
    # to every candidate ranked above them. Two deterministic sweeps let the
    # penalties settle into a stable order.
    if diversity_protection and len(records) > 1:
        for _ in range(2):
            higher_ranked_maps: list[dict[str, Any]] = []
            for record in records:
                record["diversity_penalty"] = diversity_penalty(
                    record["map_dict"],
                    higher_ranked_maps,
                )
                record["adjusted"] = clamp(
                    record["final"].weighted_score
                    - record["gate_penalty"]
                    - record["diversity_penalty"],
                    0.0,
                    100.0,
                )
                higher_ranked_maps.append(record["map_dict"])
            records.sort(
                key=lambda record: (
                    -record["adjusted"],
                    -record["final"].weighted_score,
                    record["index"],
                )
            )

    entries: list[EvolutionRankingEntry] = []
    for position, record in enumerate(records, start=1):
        summary = record["summary"]
        index = summary.candidate.index
        entries.append(
            EvolutionRankingEntry(
                rank=position,
                candidate_index=index,
                candidate_seed=summary.candidate.candidate_seed,
                stars=float(difficulty_reports_by_index[index].star_rating.overall),
                scores=scores_by_index[index],
                map_path=summary.files.improved_map,
                report_path=summary.files.improved_report,
                summary_path=summary.files.summary,
                final=record["final"],
                quality_gates=record["gates"],
                validation_status=record["validation_status"],
                improvements_made=_improvements_made(
                    summary,
                    rebalance_reports_by_index.get(index),
                ),
                target_deviation=target_deviation(difficulty_reports_by_index[index]),
                diversity_penalty=record["diversity_penalty"],
            )
        )

    # Champion selection: the highest-ranked candidate that passes every
    # mandatory gate. When no candidate passes all gates, fall back to the
    # best overall scored candidate instead of aborting the pipeline.
    champion_record = None
    for record in records:
        if record["validation_status"] == "passed":
            champion_record = record
            break
    if champion_record is None and records:
        _logger.warning(
            "No candidate passed mandatory validation gates for %s — "
            "promoting best-scored candidate as fallback.",
            difficulty,
        )
        champion_record = records[0]
    if champion_record is None:
        raise MapGeneratorError(
            f"No candidate passed mandatory validation gates for {difficulty}. "
            f"Candidate files were preserved under {output_root.as_posix()}."
        )

    champion_index = champion_record["index"]
    runner_index = champion_index
    for record in records:
        if (
            record["index"] != champion_index
            and record["validation_status"] == "passed"
        ):
            runner_index = record["index"]
            break

    lost_reasons: list[str] = []
    for record in records:
        if record["index"] == champion_index:
            continue
        if record["validation_status"] != "passed":
            failed = [
                gate.code
                for gate in record["gates"]
                if gate.mandatory and not gate.passed
            ]
            lost_reasons.append(
                f"Candidate {record['index']:03d} scored "
                f"{record['adjusted']:.1f} but failed mandatory gate(s): "
                f"{', '.join(failed)}."
            )
        else:
            lost_reasons.append(
                f"Candidate {record['index']:03d} finished behind the champion "
                f"with a weighted score of {record['adjusted']:.1f}."
            )

    champion_replay = replay_reports_by_index.get(champion_index)
    weakest_sections = (
        [section.label for section in champion_replay.weakest_sections]
        if champion_replay is not None
        else []
    )
    strongest_sections = (
        [section.label for section in champion_replay.strongest_sections]
        if champion_replay is not None
        else []
    )
    champion_summary = next(
        summary
        for summary in candidates
        if summary.candidate.index == champion_index
    )
    record = _FinalChampionRecord(
        candidate_index=champion_index,
        runner_index=runner_index,
        final_breakdown=champion_record["final"],
        weakest_sections=weakest_sections,
        strongest_sections=strongest_sections,
        biggest_improvements=_improvements_made(
            champion_summary,
            rebalance_reports_by_index.get(champion_index),
        ),
        lost_reasons=lost_reasons,
    )
    return entries, rejected, record


def _improvements_made(summary: CandidateSummary, rebalance_report: Any | None) -> list[str]:
    parts: list[str] = []
    metrics = summary.metrics
    if metrics.accepted_corrections > 0:
        parts.append(f"{metrics.accepted_corrections} structural corrections")
    if metrics.reverted_corrections > 0:
        parts.append(f"{metrics.reverted_corrections} corrections reverted")
    if rebalance_report is not None:
        rebalance_summary = rebalance_report.summary
        adjusted = (
            rebalance_summary.objects_adjusted
            + rebalance_summary.sliders_optimized
            + rebalance_summary.spinners_adjusted
        )
        if adjusted > 0:
            parts.append(
                f"{adjusted} rebalancing adjustments across "
                f"{rebalance_summary.sections_modified} sections"
            )
    parts.append("replay-simulated")
    return parts


def _generator_version(map_path: Path) -> str:
    """Read the generator version from the delivered map's metadata."""
    try:
        raw_map = _load_map(map_path)
        generator = raw_map.get("generator")
        if isinstance(generator, dict) and isinstance(generator.get("version"), str):
            return generator["version"]
    except Exception as exc:
        _logger.debug("Could not read generator version from %s: %s", map_path, exc)
    return "1.0"


def _improve_champion(
    *,
    champion_summary: CandidateSummary,
    difficulty_result: Any,
    improved_report: Any,
    improved_map: dict[str, Any],
    difficulty: str,
    analysis_path: Path,
    analysis: Any,
    project_root: Path,
    candidate_dir: Path,
    passes: int,
    player_profile: str,
    player_overrides: dict[str, Any] | None,
    replay_report_path_label: str,
    current_replay_report: Any,
    preset: DifficultyPreset | None = None,
    target: DifficultyTarget | None = None,
) -> ImprovementResult:
    if passes <= 0:
        return ImprovementResult(
            passes_used=0,
            early_stopped=True,
            history=[],
            final_map=None,
            final_scores=None,
            improvement_gain=0.0,
        )

    def pass_processor(adjusted_map: dict[str, Any]):
        candidate_dir.mkdir(parents=True, exist_ok=True)
        pass_source_path = candidate_dir / "improved-pass-source.json"
        pass_report_path = candidate_dir / "improved-pass-report.json"
        pass_output_path = candidate_dir / "improved-pass-map.json"
        pass_changes_path = candidate_dir / "improved-pass-changes.json"
        write_json(pass_source_path, adjusted_map)
        try:
            validate_beatmap(
                map_path=pass_source_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                output_path=pass_report_path,
                map_label=pass_source_path.relative_to(project_root).as_posix(),
                preset=preset,
            )
            improved = improve_beatmap(
                map_path=pass_source_path,
                analysis_path=analysis_path,
                report_path=pass_report_path,
                difficulty=difficulty,
                seed=champion_summary.candidate.candidate_seed,
                output_path=pass_output_path,
                report_output_path=candidate_dir / "improved-pass-final-report.json",
                changes_output_path=pass_changes_path,
                source_map_label=pass_source_path.relative_to(project_root).as_posix(),
                output_map_label=pass_output_path.relative_to(project_root).as_posix(),
                preset=preset,
            )
        except Exception as exc:
            _logger.warning(
                "Champion improvement pass failed for candidate %03d: %s",
                champion_summary.candidate.index,
                exc,
            )
            return None
        if improved is None or not improved.output_map_path.exists():
            return None
        validation = validate_beatmap(
            map_path=improved.output_map_path,
            analysis_path=analysis_path,
            difficulty=difficulty,
            map_label=improved.output_map_path.relative_to(project_root).as_posix(),
            preset=preset,
        ).report
        difficulty_result_next = analyze_difficulty(
            map_path=improved.output_map_path,
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=None,
            map_label=improved.output_map_path.relative_to(project_root).as_posix(),
            sections_path=None,
            target=target,
        )
        replay_report_next = simulate_replay(
            map_path=improved.output_map_path,
            analysis=analysis,
            difficulty_report=difficulty_result_next.report,
            difficulty=difficulty,
            seed=champion_summary.candidate.candidate_seed,
            player_profile=player_profile,
            player_overrides=player_overrides,
        )
        write_replay_report(candidate_dir / "replay-report.json", replay_report_next)
        _embed_replay_metadata(
            improved.output_map_path,
            replay_report_next,
            _relative_path(
                candidate_dir / "replay-report.json",
                project_root,
            ),
        )
        return validation, difficulty_result_next, replay_report_next

    current_scores = score_candidate(
        improved_report=improved_report,
        difficulty_report=difficulty_result.report,
        replay_report=current_replay_report,
    )
    return run_improvement_passes(
        current_map=improved_map,
        current_plan=difficulty_result.rebalance_plan,
        current_scores=current_scores,
        pass_processor=pass_processor,
        seed=champion_summary.candidate.candidate_seed,
        candidate_index=champion_summary.candidate.index,
        max_passes=passes,
    )


def _build_replay_summary(replay_report: Any) -> EvolutionReplaySummary:
    """Project the Phase 15 replay report onto the evolution report summary."""
    weakest = (
        replay_report.weakest_sections[0] if replay_report.weakest_sections else None
    )
    strongest = (
        replay_report.strongest_sections[0] if replay_report.strongest_sections else None
    )
    worst_transition = (
        max(
            replay_report.patterns.transitions,
            key=lambda transition: transition.penalty,
        )
        if replay_report.patterns.transitions
        else None
    )
    return EvolutionReplaySummary(
        full_combo_chance=replay_report.full_combo_chance,
        expected_accuracy=replay_report.expected_accuracy,
        expected_misses=replay_report.expected_misses,
        highest_stress_section_ms=replay_report.peak_stress_ms,
        hardest_pattern=replay_report.patterns.hardest_pattern,
        most_difficult_transition_ms=(
            worst_transition.to_ms if worst_transition is not None else 0
        ),
        replay_score=replay_report.score_breakdown.overall,
        player_profile=replay_report.player.name,
        expected_combo_pct=replay_report.combo.expected_combo_pct,
        cursor_efficiency=replay_report.cursor.efficiency,
        reading_score=replay_report.reading.score,
        fatigue_average=replay_report.fatigue.average,
        fatigue_peak=replay_report.fatigue.peak,
        combo_breaks=replay_report.combo.combo_breaks,
        miss_clusters=replay_report.combo.miss_clusters,
        weakest_section=weakest.label if weakest is not None else "",
        strongest_section=strongest.label if strongest is not None else "",
    )


def _embed_replay_metadata(
    map_path: Path,
    replay_report: Any,
    replay_report_path_label: str,
) -> None:
    """Embed a compact replay summary into the map's generator metadata."""
    raw_map = _load_map(map_path)
    generator = raw_map.get("generator")
    if not isinstance(generator, dict):
        generator = {}
    generator["replay"] = replay_generator_metadata(
        replay_report,
        replay_report_path_label,
    )
    raw_map["generator"] = generator
    write_json(map_path, raw_map)


def _embed_rebalance_metadata(
    map_path: Path,
    rebalance_report: Any,
    rebalance_report_path_label: str,
) -> None:
    """Embed a compact rebalance summary into the map's generator metadata."""
    raw_map = _load_map(map_path)
    generator = raw_map.get("generator")
    if not isinstance(generator, dict):
        generator = {}
    generator["rebalance"] = rebalance_generator_metadata(
        rebalance_report,
        rebalance_report_path_label,
    )
    raw_map["generator"] = generator
    write_json(map_path, raw_map)


def _rebalance_candidate(
    *,
    candidate_index: int,
    map_dict: dict[str, Any],
    difficulty_report: Any,
    replay_report: Any,
    improved_report: Any,
    difficulty: str,
    seed: int,
    analysis: Any,
    analysis_path: Path,
    project_root: Path,
    candidate_dir: Path,
    paths: dict[str, Path],
    passes: int,
    player_profile: str,
    player_overrides: dict[str, Any] | None,
    map_title: str,
    map_artist: str,
    preset: DifficultyPreset | None = None,
    target: DifficultyTarget | None = None,
    phrase_density_at: Any | None = None,
) -> Any | None:
    """Run Phase 16 adaptive rebalancing for one candidate.

    Returns an outcome object carrying the improved map dict, the refreshed
    difficulty/validation/replay results, or None when no meaningful
    improvement was accepted (or rebalancing is disabled).
    """
    if passes <= 0:
        return None
    holder: dict[str, Any] = {}
    working_dir = candidate_dir / "rebalance-eval"

    def evaluator(candidate_map: dict[str, Any]) -> MapEvaluation | None:
        working_dir.mkdir(parents=True, exist_ok=True)
        eval_path = working_dir / "eval-map.json"
        write_json(eval_path, candidate_map)
        try:
            validation_report = validate_beatmap(
                map_path=eval_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                map_label=_relative_path(eval_path, project_root),
                preset=preset,
            ).report
            difficulty_result = analyze_difficulty(
                map_path=eval_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                output_path=None,
                map_label=_relative_path(eval_path, project_root),
                sections_path=None,
                target=target,
            )
            replay_report_next = simulate_replay(
                map_path=eval_path,
                analysis=analysis,
                difficulty_report=difficulty_result.report,
                difficulty=difficulty,
                seed=seed,
                player_profile=player_profile,
                player_overrides=player_overrides,
            )
        except Exception as exc:
            _logger.warning(
                "Rebalance evaluation failed for candidate %03d: %s",
                candidate_index,
                exc,
            )
            return None
        holder["difficulty_result"] = difficulty_result
        holder["validation_report"] = validation_report
        holder["replay_report"] = replay_report_next
        return MapEvaluation(
            difficulty_report=difficulty_result.report,
            replay_report=replay_report_next,
            validation_report=validation_report,
        )

    outcome = run_rebalance(
        map_dict=map_dict,
        difficulty_report=difficulty_report,
        replay_report=replay_report,
        validation_report=improved_report,
        difficulty=difficulty,
        seed=seed,
        max_passes=passes,
        evaluator=evaluator,
        map_title=map_title,
        map_artist=map_artist,
        phrase_density_at=phrase_density_at,
    )
    # Always persist the candidate rebalance report so the final ranking can
    # use the rebalancing-gain component for every candidate.
    rebalance_report_label = _relative_path(
        candidate_dir / "rebalance-report.json",
        project_root,
    )
    write_rebalance_report(candidate_dir / "rebalance-report.json", outcome.report)
    if not outcome.improved:
        return _RebalanceOutcome(
            map_dict=map_dict,
            difficulty_result=None,
            validation_report=None,
            replay_report=None,
            rebalance_report=outcome.report,
            improved=False,
        )

    # Persist the rebalanced map as the candidate's improved artifact, refresh
    # the replay metadata on it, and embed the rebalance summary.
    write_json(paths["improved_map"], outcome.map_dict)
    replay_report_label = _relative_path(
        candidate_dir / "replay-report.json",
        project_root,
    )
    write_replay_report(candidate_dir / "replay-report.json", holder["replay_report"])
    _embed_replay_metadata(
        paths["improved_map"],
        holder["replay_report"],
        replay_report_label,
    )
    _embed_rebalance_metadata(
        paths["improved_map"],
        outcome.report,
        rebalance_report_label,
    )

    return _RebalanceOutcome(
        map_dict=outcome.map_dict,
        difficulty_result=holder["difficulty_result"],
        validation_report=holder["validation_report"],
        replay_report=holder["replay_report"],
        rebalance_report=outcome.report,
        improved=True,
    )


def _rebalance_champion(
    *,
    champion_map_path: Path,
    difficulty: str,
    seed: int,
    analysis: Any,
    analysis_path: Path,
    project_root: Path,
    working_dir: Path,
    passes: int,
    player_profile: str,
    player_overrides: dict[str, Any] | None,
    resolved_replay_report_path: Path,
    replay_report_path_label: str,
    resolved_rebalance_report_path: Path,
    rebalance_report_path_label: str,
    map_title: str,
    map_artist: str,
    preset: DifficultyPreset | None = None,
    target: DifficultyTarget | None = None,
    phrase_density_at: Any | None = None,
) -> Any | None:
    """Run adaptive rebalancing on the champion's delivered map.

    Always writes the champion rebalance report (even when nothing improved) so
    the evolution report carries a consistent ``rebalance`` summary. When an
    improvement is accepted the champion map and its replay metadata are
    refreshed to match the delivered artifact.
    """
    if passes <= 0:
        return None
    champion_map = _load_map(champion_map_path)
    holder: dict[str, Any] = {}

    def evaluator(candidate_map: dict[str, Any]) -> MapEvaluation | None:
        working_dir.mkdir(parents=True, exist_ok=True)
        eval_path = working_dir / "eval-map.json"
        write_json(eval_path, candidate_map)
        try:
            validation_report = validate_beatmap(
                map_path=eval_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                map_label=_relative_path(eval_path, project_root),
                preset=preset,
            ).report
            difficulty_result = analyze_difficulty(
                map_path=eval_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                output_path=None,
                map_label=_relative_path(eval_path, project_root),
                sections_path=None,
                target=target,
            )
            replay_report_next = simulate_replay(
                map_path=eval_path,
                analysis=analysis,
                difficulty_report=difficulty_result.report,
                difficulty=difficulty,
                seed=seed,
                player_profile=player_profile,
                player_overrides=player_overrides,
            )
        except Exception as exc:
            _logger.warning(
                "Champion rebalance evaluation failed: %s",
                exc,
            )
            return None
        holder["difficulty_result"] = difficulty_result
        holder["validation_report"] = validation_report
        holder["replay_report"] = replay_report_next
        return MapEvaluation(
            difficulty_report=difficulty_result.report,
            replay_report=replay_report_next,
            validation_report=validation_report,
        )

    baseline = evaluator(champion_map)
    if baseline is None:
        return None
    outcome = run_rebalance(
        map_dict=champion_map,
        difficulty_report=baseline.difficulty_report,
        replay_report=baseline.replay_report,
        validation_report=baseline.validation_report,
        difficulty=difficulty,
        seed=seed,
        max_passes=passes,
        evaluator=evaluator,
        map_title=map_title,
        map_artist=map_artist,
        phrase_density_at=phrase_density_at,
    )
    if outcome.improved:
        write_json(champion_map_path, outcome.map_dict)
        write_replay_report(
            resolved_replay_report_path,
            holder["replay_report"],
        )
        _embed_replay_metadata(
            champion_map_path,
            holder["replay_report"],
            replay_report_path_label,
        )
    write_rebalance_report(resolved_rebalance_report_path, outcome.report)
    _embed_rebalance_metadata(
        champion_map_path,
        outcome.report,
        rebalance_report_path_label,
    )
    return outcome.report


def _build_rebalance_summary(rebalance_report: Any) -> EvolutionRebalanceSummary:
    """Project the Phase 16 rebalance report onto the evolution report summary."""
    summary = rebalance_report.summary
    return EvolutionRebalanceSummary(
        passes_run=summary.passes_run,
        early_stopped=summary.early_stopped,
        sections_modified=summary.sections_modified,
        objects_adjusted=summary.objects_adjusted,
        sliders_optimized=summary.sliders_optimized,
        spinners_adjusted=summary.spinners_adjusted,
        issues_found=summary.issues_found,
        quality_before=summary.quality_before,
        quality_after=summary.quality_after,
        quality_gain=summary.quality_gain,
        replay_before=summary.replay_before,
        replay_after=summary.replay_after,
        replay_gain=summary.replay_gain,
        cursor_efficiency_before=summary.cursor_efficiency_before,
        cursor_efficiency_after=summary.cursor_efficiency_after,
        cursor_efficiency_gain=summary.cursor_efficiency_gain,
        star_rating_before=summary.star_rating_before,
        star_rating_after=summary.star_rating_after,
        weakest_section=summary.weakest_section,
        strongest_section=summary.strongest_section,
    )


@dataclass(frozen=True)
class _RebalanceOutcome:
    map_dict: dict[str, Any]
    difficulty_result: Any
    validation_report: Any
    replay_report: Any
    rebalance_report: Any
    improved: bool = True


def _evolution_stability(difficulty_report: Any) -> StabilitySummary:
    return StabilitySummary(
        score=clamp(difficulty_report.consistency_score * 100.0, 0.0, 100.0),
        label="evolution",
        speed_margin_ratio=1.0,
        gap_margin_ratio=1.0,
        near_threshold_warnings=0,
        reverted_corrections=0,
        accepted_correction_magnitude=0.0,
        quality_swing=0.0,
        severe_section_count=0,
    )


def _promotion_reason(
    *,
    candidate_index: int,
    champion: Any,
    runner: Any,
    improvement_gain: float,
) -> str:
    margin = champion.overall - runner.overall
    if margin >= 5.0:
        reason = f"won by a clear {margin:.1f}-point overall margin"
    elif margin >= 1.0:
        reason = f"won by {margin:.1f} points overall"
    else:
        reason = "won a very close leaderboard"
    if improvement_gain > 0.05:
        reason += f" after gaining {improvement_gain:.1f} points through evolution passes"
    return f"Candidate {candidate_index:03d} {reason}."


def _build_diagnostics(
    *,
    ranking_entries: list[EvolutionRankingEntry],
    improvement: ImprovementResult,
    champion_scores: Any,
    runner_scores: Any,
) -> EvolutionDiagnostics:
    buckets = {"60-69": 0, "70-79": 0, "80-89": 0, "90-100": 0}
    for entry in ranking_entries:
        score = entry.scores.overall
        if score < 70:
            buckets["60-69"] += 1
        elif score < 80:
            buckets["70-79"] += 1
        elif score < 90:
            buckets["80-89"] += 1
        else:
            buckets["90-100"] += 1
    margin = champion_scores.overall - runner_scores.overall
    confidence = clamp(50.0 + margin * 8.0, 0.0, 100.0)
    return EvolutionDiagnostics(
        score_distribution=buckets,
        average_improvement=improvement.improvement_gain
        / max(1, improvement.passes_used),
        promotion_reason=_promotion_reason(
            candidate_index=ranking_entries[0].candidate_index,
            champion=champion_scores,
            runner=runner_scores,
            improvement_gain=improvement.improvement_gain,
        ),
        confidence=round(confidence, 1),
    )


def _apply_archive(
    *,
    output_root: Path,
    ranked_indices: list[int],
    policy: str,
) -> list[int]:
    from .archive import apply_archive_policy

    return apply_archive_policy(
        candidates_root=output_root,
        ranked_candidate_indices=ranked_indices,
        policy=policy,
        dry_run=policy == "all",
    )


def _eligibility_rules():
    from ..candidates.candidate_config import EligibilityRules

    return EligibilityRules()


def _champion_source_artifacts(
    *,
    improvement: ImprovementResult,
    candidate_dir: Path,
    fallback_map: str,
    fallback_report: str,
    project_root: Path,
) -> tuple[str, str]:
    """Resolve the champion's source map/report paths.

    When the final improvement pass was accepted, the champion is the final
    pass output (validated improved map + report) so the delivered artifacts
    match the reported champion scores. Otherwise it is the candidate's
    improved artifacts.
    """
    last_accepted = bool(improvement.history) and improvement.history[-1].accepted
    if improvement.final_map is not None and last_accepted:
        pass_map = candidate_dir / "improved-pass-map.json"
        pass_report = candidate_dir / "improved-pass-final-report.json"
        if pass_map.exists() and pass_report.exists():
            return _relative_path(pass_map, project_root), _relative_path(
                pass_report, project_root
            )
    return fallback_map, fallback_report


def _candidate_artifacts_complete(paths: dict[str, Path]) -> bool:
    required_keys = (
        "original_map",
        "original_report",
        "improved_map",
        "improved_report",
        "corrections",
    )
    return all(paths[key].exists() and paths[key].is_file() for key in required_keys)


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
    report: EvolutionReport,
    evolution_report_path: Path,
    retained_count: int,
    archive_status: str,
    reused_count: int,
    regenerated_count: int,
    verbose: bool,
) -> str:
    lines = [
        "Candidate evolution complete",
        "",
        f"Song: {report.song.title}",
        f"Difficulty: {report.song.difficulty}",
        f"Root seed: {report.configuration.root_seed}",
        f"Generated candidates: {report.summary.generated}",
        f"Eligible candidates: {report.summary.eligible}",
        f"Rejected candidates: {report.summary.rejected}",
        f"Improvement passes: {report.summary.passes_used}",
        f"Early stopped: {'yes' if report.summary.early_stopped else 'no'}",
        f"Reused candidate directories: {reused_count}",
        f"Regenerated candidate directories: {regenerated_count}",
        archive_status,
        "",
        f"Champion: Candidate {report.champion.candidate_index:03d}",
        f"Overall score: {report.champion.overall_score:.1f}",
        f"Quality score: {report.champion.quality_score:.1f}",
        f"Stars: {report.champion.stars:.2f}",
        f"Replay ({report.replay.player_profile}): score {report.replay.replay_score:.1f}, ",
        f"  accuracy {report.replay.expected_accuracy:.1%}, expected misses {report.replay.expected_misses:.2f}",
        f"Rebalancing: passes {report.rebalance.passes_run}, quality gain "
        f"{report.rebalance.quality_gain:+.1f}, replay gain {report.rebalance.replay_gain:+.1f}",
        "",
        "Top candidates:",
    ]
    for entry in report.ranking[:3]:
        detail = ""
        if entry.final is not None and entry.diversity_penalty > 0:
            detail = f" (diversity -{entry.diversity_penalty:.1f})"
        lines.append(
            f"{entry.rank}. Candidate {entry.candidate_index:03d} - "
            f"weighted {entry.final.weighted_score:.1f}" + detail
            if entry.final is not None
            else f"{entry.rank}. Candidate {entry.candidate_index:03d} - {entry.scores.overall:.1f}"
        )
    if report.champion.final_breakdown is not None:
        final = report.champion.final_breakdown
        lines.extend(
            [
                "",
                "Final score breakdown (champion):",
                f"  Weighted: {final.weighted_score:.1f}",
                f"  Rhythm {final.rhythm:.0f} | Playability {final.playability:.0f} | "
                f"Pattern {final.pattern:.0f} | Target {final.target:.0f}",
                f"  Reading {final.reading:.0f} | Replay {final.replay:.0f} | "
                f"Consistency {final.consistency:.0f} | Validity {final.validity:.0f}",
                f"  Flow {final.flow:.0f} | Section {final.section:.0f} | "
                f"Fatigue {final.fatigue:.0f} | Rebalance {final.rebalance:.0f}",
            ]
        )
    lines.extend(
        [
            "",
            "Champion map:",
            report.champion.map_path,
            "",
            "Evolution report:",
            evolution_report_path.as_posix(),
        ]
    )
    if verbose:
        if report.champion.lost_reasons:
            lines.extend(["", "Why other candidates lost"])
            lines.extend(f"- {reason}" for reason in report.champion.lost_reasons)
        if report.rejected_candidates:
            lines.extend(["", "Rejected candidates"])
            for candidate in report.rejected_candidates:
                lines.append(
                    f"- Candidate {candidate.candidate_index:03d}: {'; '.join(candidate.rejection_reasons)}"
                )
        if report.reproduction is not None:
            reproduction = report.reproduction
            lines.extend(
                [
                    "",
                    "Reproduction configuration:",
                    f"  Generator {reproduction.generator_version} | Evolution "
                    f"{reproduction.evolution_version}",
                    f"  Seed {reproduction.seed} | Candidates "
                    f"{reproduction.candidate_count} | Target {reproduction.target_difficulty}",
                    f"  Replay profile {reproduction.replay_profile} | Rebalance passes "
                    f"{reproduction.rebalance_passes}",
                ]
            )
    return "\n".join(lines)
