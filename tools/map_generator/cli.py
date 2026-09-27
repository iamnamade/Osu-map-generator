from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio_analyzer import analyze_audio
from .analysis_io import load_analysis_json, load_json_file
from .beatmap_generator import format_generation_report, generate_beatmap
from .candidates import (
    compare_tournament_reports,
    inspect_candidate_summary,
    run_candidate_tournament,
    run_candidate_tournament_all,
)
from .config import DIFFICULTY_PRESETS
from .difficulty import analyze_difficulty
from .evolution import (
    format_evolution_comparison,
    load_evolution_report,
    run_candidate_evolution,
    run_candidate_evolution_all,
)
from .postprocess import compare_improvements, improve_all_maps, improve_beatmap
from .rebalance import (
    MapEvaluation,
    format_rebalance_summary,
    run_rebalance,
    write_rebalance_report,
)
from .replay import format_replay_summary, simulate_replay, write_replay_report
from .osu_format import (
    export_osu_file,
    export_osu_mapset,
    import_osu_file,
    package_osz_archive,
    validate_osu_file,
)
from .osu_format.report_writer import (
    format_export_console_report,
    format_import_console_report,
    format_osu_validation_console_report,
    format_package_console_report,
)
from .sections import (
    analyze_sections,
    assemble_hybrid,
    compare_hybrid_reports,
    evaluate_candidate_sections,
    run_hybrid_all,
)
from .sections.section_config import SectionPipelineConfig
from .utils import MapGeneratorError, write_json
from .validation import compare_validation_reports, validate_all_maps, validate_beatmap
from .validation.report_writer import format_validation_console_report


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    phase7_config = SectionPipelineConfig()

    try:
        if args.command == "analyze":
            analysis = analyze_audio(project_root / args.audio)
            write_json(project_root / args.output, analysis.to_dict())
            print(f"Analysis written to {(project_root / args.output).as_posix()}")
            return 0

        if args.command == "difficulty":
            result = analyze_difficulty(
                map_path=project_root / args.map,
                analysis_path=(project_root / args.analysis) if args.analysis else None,
                difficulty=args.difficulty,
                output_path=(project_root / args.output) if args.output else None,
                map_label=args.map.as_posix(),
                sections_path=(project_root / args.sections) if args.sections else None,
                seed=args.seed,
                target_name=args.target,
            )
            print(result.console_report)
            return 0

        if args.command == "generate":
            result = generate_beatmap(
                audio_path=project_root / args.audio,
                title=args.title,
                artist=args.artist,
                difficulty=args.difficulty,
                seed=args.seed,
                output_path=project_root / args.output,
                analysis_output_path=(project_root / args.analysis_output) if args.analysis_output else None,
                project_root=project_root,
            )
            report = format_generation_report(
                result=result,
                audio_path=project_root / args.audio,
                difficulty=args.difficulty,
                seed=args.seed,
                output_path=project_root / args.output,
                analysis_output_path=(project_root / args.analysis_output) if args.analysis_output else None,
            )
            print(report)
            return 0

        if args.command == "validate":
            result = validate_beatmap(
                map_path=project_root / args.map,
                analysis_path=project_root / args.analysis,
                difficulty=args.difficulty,
                output_path=(project_root / args.output) if args.output else None,
                map_label=args.map.as_posix(),
            )
            print(
                format_validation_console_report(
                    result.report,
                    report_path=(project_root / args.output) if args.output else None,
                    verbose=args.verbose,
                )
            )
            return 0

        if args.command == "validate-all":
            results = validate_all_maps(
                maps_dir=project_root / args.maps_dir,
                analysis_path=project_root / args.analysis,
                reports_dir=project_root / args.reports_dir,
            )
            print(
                "\n\n".join(
                    format_validation_console_report(
                        result.report,
                        report_path=result.report_path,
                        verbose=args.verbose,
                    )
                    for result in results
                )
            )
            return 0

        if args.command == "compare-reports":
            comparison = compare_validation_reports(
                reports_dir=project_root / args.reports_dir,
            )
            print(comparison)
            return 0

        if args.command == "improve":
            result = improve_beatmap(
                map_path=project_root / args.map,
                analysis_path=project_root / args.analysis,
                report_path=project_root / args.report,
                difficulty=args.difficulty,
                seed=args.seed,
                output_path=project_root / args.output,
                report_output_path=project_root / args.report_output,
                changes_output_path=project_root / args.changes_output,
                verbose=args.verbose,
                source_map_label=args.map.as_posix(),
                output_map_label=args.output.as_posix(),
            )
            print(result.console_report)
            return 0

        if args.command == "improve-all":
            results = improve_all_maps(
                maps_dir=project_root / args.maps_dir,
                analysis_path=project_root / args.analysis,
                reports_dir=project_root / args.reports_dir,
                output_dir=project_root / args.output_dir,
                improved_reports_dir=project_root / args.improved_reports_dir,
                corrections_dir=project_root / args.corrections_dir,
                seed=args.seed,
                verbose=args.verbose,
            )
            print("\n\n".join(result.console_report for result in results))
            return 0

        if args.command == "compare-improvements":
            comparison = compare_improvements(
                original_reports_dir=project_root / args.original_reports_dir,
                improved_reports_dir=project_root / args.improved_reports_dir,
            )
            print(comparison)
            return 0

        if args.command == "evolution":
            result = run_candidate_evolution(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                title=args.title,
                artist=args.artist,
                difficulty=args.difficulty,
                root_seed=args.seed,
                output_root=project_root / args.output_root,
                champion_map_path=project_root / args.champion_map,
                champion_report_path=project_root / args.champion_report,
                evolution_report_path=project_root / args.evolution_report,
                project_root=project_root,
                count=args.count,
                timing_variation=args.timing_variation,
                force=args.force,
                verbose=args.verbose,
                max_passes=args.max_passes,
                archive_policy=args.archive,
                sections_path=project_root / args.sections if args.sections else None,
                replay_report_path=(
                    project_root / args.replay_report if args.replay_report else None
                ),
                player_profile=args.player_profile,
                rebalance_passes=args.rebalance_passes,
                final_weight_overrides=_parse_weight_overrides(args.final_weight),
                diversity_protection=not args.no_diversity,
            )
            print(result.console_report)
            return 0

        if args.command == "evolution-all":
            results = run_candidate_evolution_all(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                title=args.title,
                artist=args.artist,
                root_seed=args.seed,
                project_root=project_root,
                count=args.count,
                timing_variation=args.timing_variation,
                force=args.force,
                verbose=args.verbose,
                max_passes=args.max_passes,
                archive_policy=args.archive,
                sections_path=project_root / args.sections if args.sections else None,
                player_profile=args.player_profile,
                rebalance_passes=args.rebalance_passes,
                final_weight_overrides=_parse_weight_overrides(args.final_weight),
                diversity_protection=not args.no_diversity,
            )
            print("\n\n".join(result.console_report for result in results))
            return 0

        if args.command == "rebalance":
            import tempfile

            working_dir = Path(tempfile.mkdtemp(prefix="rebalance-eval-"))
            analysis_path = project_root / args.analysis
            analysis = load_analysis_json(analysis_path) if args.analysis else None
            map_dict = load_json_file(project_root / args.map, "Beatmap")

            def evaluate(candidate_map: dict) -> MapEvaluation | None:
                eval_path = working_dir / "eval-map.json"
                write_json(eval_path, candidate_map)
                try:
                    validation_report = validate_beatmap(
                        map_path=eval_path,
                        analysis_path=analysis_path if args.analysis else None,
                        difficulty=args.difficulty,
                        output_path=None,
                        map_label=args.map.as_posix(),
                    ).report
                    difficulty_result = analyze_difficulty(
                        map_path=eval_path,
                        analysis_path=analysis_path if args.analysis else None,
                        difficulty=args.difficulty,
                        output_path=None,
                        map_label=args.map.as_posix(),
                    )
                    replay_report = simulate_replay(
                        map_path=eval_path,
                        analysis=analysis,
                        difficulty_report=difficulty_result.report,
                        difficulty=args.difficulty,
                        seed=args.seed,
                        player_profile=args.profile,
                    )
                except Exception:
                    return None
                return MapEvaluation(
                    difficulty_report=difficulty_result.report,
                    replay_report=replay_report,
                    validation_report=validation_report,
                )

            baseline = evaluate(map_dict)
            if baseline is None:
                raise MapGeneratorError(
                    "Baseline evaluation failed; the map could not be validated "
                    "for adaptive rebalancing."
                )
            outcome = run_rebalance(
                map_dict=map_dict,
                difficulty_report=baseline.difficulty_report,
                replay_report=baseline.replay_report,
                validation_report=baseline.validation_report,
                difficulty=args.difficulty,
                seed=args.seed,
                max_passes=args.passes,
                evaluator=evaluate,
                map_title=str(map_dict.get("title", "")),
                map_artist=str(map_dict.get("artist", "")),
            )
            write_rebalance_report(project_root / args.output, outcome.report)
            print(format_rebalance_summary(outcome.report))
            print(f"\nRebalance report: {(project_root / args.output).as_posix()}")
            return 0

        if args.command == "replay":
            analysis = (
                load_analysis_json(project_root / args.analysis)
                if args.analysis
                else None
            )
            replay_report = simulate_replay(
                map_path=project_root / args.map,
                analysis=analysis,
                difficulty=args.difficulty,
                seed=args.seed,
                player_profile=args.profile,
            )
            write_replay_report(project_root / args.output, replay_report)
            print(format_replay_summary(replay_report))
            print(f"\nReplay report: {(project_root / args.output).as_posix()}")
            return 0

        if args.command == "compare-evolutions":
            comparison = format_evolution_comparison(
                [
                    load_evolution_report(path)
                    for path in sorted((project_root / args.evolutions_dir).glob("*-evolution.json"))
                ]
            )
            print(comparison)
            return 0

        if args.command == "inspect-evolution":
            report = load_evolution_report(project_root / args.report)
            print(
                "\n".join(
                    [
                        "Evolution report inspection",
                        "",
                        f"Song: {report.song.title}",
                        f"Difficulty: {report.song.difficulty}",
                        f"Champion: Candidate {report.champion.candidate_index:03d}",
                        f"Overall score: {report.champion.overall_score:.1f}",
                        f"Stars: {report.champion.stars:.2f}",
                        f"Passes used: {report.summary.passes_used}",
                        f"Early stopped: {'yes' if report.summary.early_stopped else 'no'}",
                        "",
                        "Replay simulation:",
                        f"Player profile: {report.replay.player_profile}",
                        f"Replay score: {report.replay.replay_score:.1f}",
                        f"Expected accuracy: {report.replay.expected_accuracy:.1%}",
                        f"Expected misses: {report.replay.expected_misses:.2f}",
                        f"Reading: {report.replay.reading_score:.1f}",
                        f"Cursor efficiency: {report.replay.cursor_efficiency:.1%}",
                        f"Weakest section: {report.replay.weakest_section or '-'}",
                        "",
                        "Adaptive rebalancing:",
                        f"Passes run: {report.rebalance.passes_run}",
                        f"Quality: {report.rebalance.quality_before:.1f} -> {report.rebalance.quality_after:.1f} (gain {report.rebalance.quality_gain:+.1f})",
                        f"Replay: {report.rebalance.replay_before:.1f} -> {report.rebalance.replay_after:.1f} (gain {report.rebalance.replay_gain:+.1f})",
                        f"Objects adjusted: {report.rebalance.objects_adjusted}",
                        f"Sliders optimized: {report.rebalance.sliders_optimized}",
                        f"Spinners adjusted: {report.rebalance.spinners_adjusted}",
                        f"Weakest section: {report.rebalance.weakest_section or '-'}",
                        "",
                        "Comparison reasons:",
                        *[f"- {reason}" for reason in report.comparison_reasons],
                    ]
                )
            )
            return 0

        if args.command == "tournament":
            result = run_candidate_tournament(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                title=args.title,
                artist=args.artist,
                difficulty=args.difficulty,
                root_seed=args.seed,
                output_root=project_root / args.output_root,
                champion_map_path=project_root / args.champion_map,
                champion_report_path=project_root / args.champion_report,
                tournament_report_path=project_root / args.tournament_report,
                project_root=project_root,
                count=args.count,
                timing_variation=args.timing_variation,
                force=args.force,
                verbose=args.verbose,
            )
            print(result.console_report)
            return 0

        if args.command == "tournament-all":
            results = run_candidate_tournament_all(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                title=args.title,
                artist=args.artist,
                root_seed=args.seed,
                project_root=project_root,
                count=args.count,
                timing_variation=args.timing_variation,
                force=args.force,
                verbose=args.verbose,
            )
            print("\n\n".join(result.console_report for result in results))
            return 0

        if args.command == "compare-tournaments":
            comparison = compare_tournament_reports(
                tournaments_dir=project_root / args.tournaments_dir,
            )
            print(comparison)
            return 0

        if args.command == "inspect-candidate":
            print(
                inspect_candidate_summary(
                    summary_path=project_root / args.summary,
                    verbose=args.verbose,
                )
            )
            return 0

        if args.command == "analyze-sections":
            result = analyze_sections(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                output_path=project_root / args.output,
                project_root=project_root,
                config=phase7_config,
                force=args.force,
            )
            print(result.console_report)
            return 0

        if args.command == "evaluate-sections":
            analysis_path = (
                project_root / args.analysis
                if args.analysis
                else _derive_analysis_path(project_root, project_root / args.sections)
            )
            result = evaluate_candidate_sections(
                sections_path=project_root / args.sections,
                analysis_path=analysis_path,
                candidates_root=project_root / args.candidates_root,
                difficulty=args.difficulty,
                output_dir=project_root / args.output_dir,
                config=phase7_config,
                force=args.force,
            )
            print(result.console_report)
            return 0

        if args.command == "assemble-hybrid":
            sections_path = project_root / args.sections
            candidates_root = project_root / args.candidates_root
            analysis_path = (
                project_root / args.analysis
                if args.analysis
                else _derive_analysis_path(project_root, sections_path)
            )
            metadata = _derive_map_metadata(candidates_root)
            result = assemble_hybrid(
                song_slug=_song_slug_from_sections_path(sections_path),
                title=metadata["title"],
                artist=metadata["artist"],
                audio_path=project_root / "public" / metadata["audioPublicPath"].lstrip("/"),
                analysis_path=analysis_path,
                sections_path=sections_path,
                section_reports_dir=project_root / args.section_reports_dir
                if args.section_reports_dir
                else _derive_section_report_dir(project_root, candidates_root),
                candidates_root=candidates_root,
                difficulty=args.difficulty,
                output_map=project_root / args.output_map,
                output_report=project_root / args.output_report,
                assembly_report_path=project_root / args.assembly_report,
                transition_log_path=project_root / args.transition_log,
                project_root=project_root,
                config=phase7_config,
            )
            print(result.console_report)
            return 0

        if args.command == "hybrid-all":
            results = run_hybrid_all(
                audio_path=project_root / args.audio,
                analysis_path=project_root / args.analysis,
                seed=args.seed,
                project_root=project_root,
                force=args.force,
                config=phase7_config,
            )
            print("\n\n".join(result.console_report for result in results))
            return 0

        if args.command == "compare-hybrids":
            print(compare_hybrid_reports(hybrids_dir=project_root / args.hybrids_dir))
            return 0

        if args.command == "export-osu":
            result = export_osu_file(
                map_path=project_root / args.map,
                analysis_path=project_root / args.analysis,
                output_path=project_root / args.output,
                creator=args.creator,
                version_name=args.version_name,
                beatmap_id=args.beatmap_id,
                beatmap_set_id=args.beatmap_set_id,
                background_filename=args.background,
            )
            print(
                format_export_console_report(
                    result.report,
                    report_path=_derive_osu_export_report_path(project_root / args.output),
                )
            )
            return 0

        if args.command == "import-osu":
            result = import_osu_file(
                input_path=project_root / args.input,
                output_path=project_root / args.output,
                unsupported_mode=args.unsupported,
            )
            print(
                format_import_console_report(
                    result.report,
                    report_path=_derive_osu_import_report_path(project_root / args.output),
                )
            )
            return 0

        if args.command == "validate-osu":
            result = validate_osu_file(project_root / args.input)
            print(
                format_osu_validation_console_report(
                    result,
                    input_path=project_root / args.input,
                )
            )
            return 0

        if args.command == "package-osz":
            result = package_osz_archive(
                maps_dir=project_root / args.maps_dir,
                audio_path=project_root / args.audio,
                output_path=project_root / args.output,
                background_path=(project_root / args.background) if args.background else None,
            )
            print(format_package_console_report(result))
            return 0

        if args.command == "export-osu-mapset":
            result = export_osu_mapset(
                maps_dir=project_root / args.maps_dir,
                analysis_path=project_root / args.analysis,
                audio_path=project_root / args.audio,
                output_dir=project_root / args.output_dir,
                package_path=(project_root / args.package) if args.package else None,
            )
            lines = [
                "osu mapset export complete",
                "",
                f"Maps exported: {len(result.entries)}",
                f"Output directory: {(project_root / args.output_dir).as_posix()}",
            ]
            if result.package_path:
                lines.append(f"Package: {result.package_path}")
            print("\n".join(lines))
            return 0

        raise MapGeneratorError(f"Unknown command: {args.command}")
    except MapGeneratorError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # pragma: no cover - final fallback for unexpected issues.
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze local audio and generate playable browser beatmaps from scratch.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze an audio file and export rhythm and energy features.",
    )
    analyze_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    analyze_parser.add_argument("--output", required=True, type=Path, help="Path to write the analysis JSON.")

    difficulty_parser = subparsers.add_parser(
        "difficulty",
        help="Run the Phase 13 difficulty intelligence engine on a beatmap and export a difficulty report.",
    )
    difficulty_parser.add_argument("--map", required=True, type=Path, help="Path to the beatmap JSON.")
    difficulty_parser.add_argument("--analysis", type=Path, help="Optional path to the audio-analysis JSON.")
    difficulty_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset the map was generated for.",
    )
    difficulty_parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the difficulty report JSON.",
    )
    difficulty_parser.add_argument(
        "--sections",
        type=Path,
        help="Optional path to the section analysis JSON for section-level difficulty.",
    )
    difficulty_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Optional difficulty target profile override (easy, normal, hard, insane, expert, custom).",
    )
    difficulty_parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Deterministic seed for the rebalancing proposal.",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="Analyze audio and generate a browser-compatible circle beatmap.",
    )
    generate_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    generate_parser.add_argument("--title", required=True, help="Beatmap title to write into JSON.")
    generate_parser.add_argument("--artist", required=True, help="Beatmap artist to write into JSON.")
    generate_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset to apply.",
    )
    generate_parser.add_argument("--seed", required=True, type=int, help="Deterministic seed for position generation.")
    generate_parser.add_argument("--output", required=True, type=Path, help="Path to write the generated beatmap JSON.")
    generate_parser.add_argument(
        "--analysis-output",
        type=Path,
        help="Optional path to also write the analysis JSON during generation.",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a beatmap against analysis data and export a quality report.",
    )
    validate_parser.add_argument("--map", required=True, type=Path, help="Path to the beatmap JSON.")
    validate_parser.add_argument(
        "--analysis",
        required=True,
        type=Path,
        help="Path to the audio-analysis JSON.",
    )
    validate_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset to validate against.",
    )
    validate_parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the validation report JSON.",
    )
    validate_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every detected issue instead of only the top five.",
    )

    validate_all_parser = subparsers.add_parser(
        "validate-all",
        help="Validate every generated beatmap in a directory and write report JSON files.",
    )
    validate_all_parser.add_argument(
        "--maps-dir",
        required=True,
        type=Path,
        help="Directory containing generated beatmap JSON files.",
    )
    validate_all_parser.add_argument(
        "--analysis",
        required=True,
        type=Path,
        help="Path to the shared audio-analysis JSON.",
    )
    validate_all_parser.add_argument(
        "--reports-dir",
        required=True,
        type=Path,
        help="Directory where validation report JSON files will be written.",
    )
    validate_all_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every detected issue instead of only the top five for each map.",
    )

    compare_parser = subparsers.add_parser(
        "compare-reports",
        help="Compare multiple validation reports and rank them by overall score.",
    )
    compare_parser.add_argument(
        "--reports-dir",
        required=True,
        type=Path,
        help="Directory containing validation report JSON files.",
    )

    improve_parser = subparsers.add_parser(
        "improve",
        help="Create a deterministic improved copy of a generated beatmap.",
    )
    improve_parser.add_argument("--map", required=True, type=Path, help="Path to the source beatmap JSON.")
    improve_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared audio-analysis JSON.")
    improve_parser.add_argument("--report", required=True, type=Path, help="Path to the existing validation report JSON.")
    improve_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset to improve against.",
    )
    improve_parser.add_argument("--seed", required=True, type=int, help="Deterministic seed for correction choices.")
    improve_parser.add_argument("--output", required=True, type=Path, help="Path to write the improved beatmap JSON.")
    improve_parser.add_argument(
        "--report-output",
        required=True,
        type=Path,
        help="Path to write the final validation report JSON for the selected output map.",
    )
    improve_parser.add_argument(
        "--changes-output",
        required=True,
        type=Path,
        help="Path to write the correction report JSON.",
    )
    improve_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every attempted correction instead of only the top accepted or reverted ones.",
    )

    improve_all_parser = subparsers.add_parser(
        "improve-all",
        help="Improve every generated beatmap in a directory and export improved maps, reports, and correction logs.",
    )
    improve_all_parser.add_argument("--maps-dir", required=True, type=Path, help="Directory containing generated beatmap JSON files.")
    improve_all_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared audio-analysis JSON.")
    improve_all_parser.add_argument("--reports-dir", required=True, type=Path, help="Directory containing the original validation report JSON files.")
    improve_all_parser.add_argument("--output-dir", required=True, type=Path, help="Directory where improved beatmap JSON files will be written.")
    improve_all_parser.add_argument("--improved-reports-dir", required=True, type=Path, help="Directory where improved validation report JSON files will be written.")
    improve_all_parser.add_argument("--corrections-dir", required=True, type=Path, help="Directory where correction report JSON files will be written.")
    improve_all_parser.add_argument("--seed", required=True, type=int, help="Deterministic seed for correction choices.")
    improve_all_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every attempted correction instead of only the top accepted or reverted ones.",
    )

    compare_improvements_parser = subparsers.add_parser(
        "compare-improvements",
        help="Compare original validation reports against improved validation reports.",
    )
    compare_improvements_parser.add_argument(
        "--original-reports-dir",
        required=True,
        type=Path,
        help="Directory containing the original validation report JSON files.",
    )
    compare_improvements_parser.add_argument(
        "--improved-reports-dir",
        required=True,
        type=Path,
        help="Directory containing the improved validation report JSON files.",
    )

    evolution_parser = subparsers.add_parser(
        "evolution",
        help="Generate multiple candidate beatmaps, evaluate them, improve the champion, and export the evolution report.",
    )
    evolution_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    evolution_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    evolution_parser.add_argument("--title", required=True, help="Beatmap title to write into JSON.")
    evolution_parser.add_argument("--artist", required=True, help="Beatmap artist to write into JSON.")
    evolution_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset to apply.",
    )
    evolution_parser.add_argument("--count", type=int, help="Optional override for the number of candidates to generate.")
    evolution_parser.add_argument("--seed", required=True, type=int, help="Deterministic root seed.")
    evolution_parser.add_argument("--output-root", required=True, type=Path, help="Directory where candidate outputs will be written.")
    evolution_parser.add_argument("--champion-map", required=True, type=Path, help="Path to write the selected champion beatmap JSON.")
    evolution_parser.add_argument("--champion-report", required=True, type=Path, help="Path to write the selected champion validation report JSON.")
    evolution_parser.add_argument("--evolution-report", required=True, type=Path, help="Path to write the final evolution report JSON.")
    evolution_parser.add_argument("--sections", type=Path, help="Optional path to the section analysis JSON for section-aware difficulty.")
    evolution_parser.add_argument(
        "--max-passes",
        type=int,
        default=2,
        help="Maximum improvement passes (default 2; stops early when quality no longer improves).",
    )
    evolution_parser.add_argument(
        "--archive",
        type=str,
        default="all",
        choices=["champion", "top3", "top5", "all"],
        help="How many candidates to keep in place (default all).",
    )
    evolution_parser.add_argument("--timing-variation", action="store_true", help="Enable controlled timing variation between candidates.")
    evolution_parser.add_argument("--force", action="store_true", help="Regenerate every candidate even when a complete directory already exists.")
    evolution_parser.add_argument("--verbose", action="store_true", help="Print rejected-candidate reasons in the final console report.")
    evolution_parser.add_argument(
        "--replay-report",
        type=Path,
        help="Optional path to write the champion replay simulation report JSON. Defaults to <evolution-report stem>-replay.json next to the evolution report.",
    )
    evolution_parser.add_argument(
        "--player-profile",
        type=str,
        default="advanced",
        choices=["beginner", "intermediate", "advanced", "tournament", "custom"],
        help="Virtual player profile used by the Phase 15 replay simulation (default advanced).",
    )
    evolution_parser.add_argument(
        "--rebalance-passes",
        type=int,
        default=2,
        help="Maximum Phase 16 adaptive rebalancing passes per candidate (default 2; stops early when quality no longer improves).",
    )
    evolution_parser.add_argument(
        "--final-weight",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a Phase 17 final-ranking weight, e.g. --final-weight rhythm=0.18 (repeatable).",
    )
    evolution_parser.add_argument(
        "--no-diversity",
        action="store_true",
        help="Disable Phase 17 diversity protection during final ranking.",
    )

    evolution_all_parser = subparsers.add_parser(
        "evolution-all",
        help="Run the candidate evolution pipeline for easy, normal, and hard.",
    )
    evolution_all_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    evolution_all_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    evolution_all_parser.add_argument("--title", required=True, help="Beatmap title to write into JSON.")
    evolution_all_parser.add_argument("--artist", required=True, help="Beatmap artist to write into JSON.")
    evolution_all_parser.add_argument("--count", type=int, help="Optional override applied to every difficulty.")
    evolution_all_parser.add_argument("--seed", required=True, type=int, help="Deterministic root seed.")
    evolution_all_parser.add_argument("--sections", type=Path, help="Optional path to the section analysis JSON.")
    evolution_all_parser.add_argument(
        "--max-passes",
        type=int,
        default=2,
        help="Maximum improvement passes (default 2; stops early when quality no longer improves).",
    )
    evolution_all_parser.add_argument(
        "--archive",
        type=str,
        default="all",
        choices=["champion", "top3", "top5", "all"],
        help="How many candidates to keep in place (default all).",
    )
    evolution_all_parser.add_argument("--timing-variation", action="store_true", help="Enable controlled timing variation between candidates.")
    evolution_all_parser.add_argument("--force", action="store_true", help="Regenerate every candidate even when a complete directory already exists.")
    evolution_all_parser.add_argument("--verbose", action="store_true", help="Print rejected-candidate reasons in the final console report.")
    evolution_all_parser.add_argument(
        "--player-profile",
        type=str,
        default="advanced",
        choices=["beginner", "intermediate", "advanced", "tournament", "custom"],
        help="Virtual player profile used by the Phase 15 replay simulation (default advanced).",
    )
    evolution_all_parser.add_argument(
        "--rebalance-passes",
        type=int,
        default=2,
        help="Maximum Phase 16 adaptive rebalancing passes per candidate (default 2; stops early when quality no longer improves).",
    )
    evolution_all_parser.add_argument(
        "--final-weight",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a Phase 17 final-ranking weight, e.g. --final-weight rhythm=0.18 (repeatable).",
    )
    evolution_all_parser.add_argument(
        "--no-diversity",
        action="store_true",
        help="Disable Phase 17 diversity protection during final ranking.",
    )

    compare_evolutions_parser = subparsers.add_parser(
        "compare-evolutions",
        help="Compare generated evolution reports by champion score.",
    )
    compare_evolutions_parser.add_argument("--evolutions-dir", required=True, type=Path, help="Directory containing evolution report JSON files.")

    inspect_evolution_parser = subparsers.add_parser(
        "inspect-evolution",
        help="Inspect an evolution report JSON file.",
    )
    inspect_evolution_parser.add_argument("--report", required=True, type=Path, help="Path to the evolution report JSON file.")

    replay_parser = subparsers.add_parser(
        "replay",
        help="Run the Phase 15 replay simulation (virtual player) on a beatmap and export a replay report.",
    )
    replay_parser.add_argument("--map", required=True, type=Path, help="Path to the beatmap JSON.")
    replay_parser.add_argument("--analysis", type=Path, help="Optional path to the audio-analysis JSON (used for BPM).")
    replay_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset the map was generated for.",
    )
    replay_parser.add_argument(
        "--profile",
        type=str,
        default="advanced",
        choices=["beginner", "intermediate", "advanced", "tournament", "custom"],
        help="Virtual player profile (default advanced).",
    )
    replay_parser.add_argument("--seed", type=int, default=1, help="Deterministic simulation seed.")
    replay_parser.add_argument("--output", required=True, type=Path, help="Path to write the replay report JSON.")

    rebalance_parser = subparsers.add_parser(
        "rebalance",
        help="Run the Phase 16 adaptive rebalancing engine on a beatmap and export a rebalance report.",
    )
    rebalance_parser.add_argument("--map", required=True, type=Path, help="Path to the beatmap JSON.")
    rebalance_parser.add_argument(
        "--analysis",
        required=True,
        type=Path,
        help="Path to the shared audio-analysis JSON.",
    )
    rebalance_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset the map was generated for.",
    )
    rebalance_parser.add_argument(
        "--profile",
        type=str,
        default="advanced",
        choices=["beginner", "intermediate", "advanced", "tournament", "custom"],
        help="Virtual player profile used for replay re-evaluation (default advanced).",
    )
    rebalance_parser.add_argument("--seed", type=int, default=1, help="Deterministic rebalancing seed.")
    rebalance_parser.add_argument(
        "--passes",
        type=int,
        default=2,
        help="Maximum adaptive rebalancing passes (default 2).",
    )
    rebalance_parser.add_argument("--output", required=True, type=Path, help="Path to write the rebalance report JSON.")

    tournament_parser = subparsers.add_parser(
        "tournament",
        help="Generate multiple candidate beatmaps, rank them, and export a champion map.",
    )
    tournament_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    tournament_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    tournament_parser.add_argument("--title", required=True, help="Beatmap title to write into JSON.")
    tournament_parser.add_argument("--artist", required=True, help="Beatmap artist to write into JSON.")
    tournament_parser.add_argument(
        "--difficulty",
        required=True,
        choices=sorted(DIFFICULTY_PRESETS),
        help="Difficulty preset to apply.",
    )
    tournament_parser.add_argument("--count", type=int, help="Optional override for the number of candidates to generate.")
    tournament_parser.add_argument("--seed", required=True, type=int, help="Deterministic root seed.")
    tournament_parser.add_argument("--output-root", required=True, type=Path, help="Directory where candidate outputs will be written.")
    tournament_parser.add_argument("--champion-map", required=True, type=Path, help="Path to write the selected champion beatmap JSON.")
    tournament_parser.add_argument("--champion-report", required=True, type=Path, help="Path to write the selected champion validation report JSON.")
    tournament_parser.add_argument("--tournament-report", required=True, type=Path, help="Path to write the final tournament report JSON.")
    tournament_parser.add_argument("--timing-variation", action="store_true", help="Enable controlled timing variation between candidates.")
    tournament_parser.add_argument("--force", action="store_true", help="Regenerate every candidate even when a complete directory already exists.")
    tournament_parser.add_argument("--verbose", action="store_true", help="Print rejected-candidate reasons in the final console report.")

    tournament_all_parser = subparsers.add_parser(
        "tournament-all",
        help="Run the candidate tournament pipeline for easy, normal, and hard.",
    )
    tournament_all_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    tournament_all_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    tournament_all_parser.add_argument("--title", required=True, help="Beatmap title to write into JSON.")
    tournament_all_parser.add_argument("--artist", required=True, help="Beatmap artist to write into JSON.")
    tournament_all_parser.add_argument("--count", type=int, help="Optional override applied to every difficulty.")
    tournament_all_parser.add_argument("--seed", required=True, type=int, help="Deterministic root seed.")
    tournament_all_parser.add_argument("--timing-variation", action="store_true", help="Enable controlled timing variation between candidates.")
    tournament_all_parser.add_argument("--force", action="store_true", help="Regenerate every candidate even when a complete directory already exists.")
    tournament_all_parser.add_argument("--verbose", action="store_true", help="Print rejected-candidate reasons in the final console report.")

    compare_tournaments_parser = subparsers.add_parser(
        "compare-tournaments",
        help="Compare generated tournament reports by champion score.",
    )
    compare_tournaments_parser.add_argument("--tournaments-dir", required=True, type=Path, help="Directory containing tournament report JSON files.")

    inspect_candidate_parser = subparsers.add_parser(
        "inspect-candidate",
        help="Inspect a candidate summary JSON file.",
    )
    inspect_candidate_parser.add_argument("--summary", required=True, type=Path, help="Path to the candidate summary JSON file.")
    inspect_candidate_parser.add_argument("--verbose", action="store_true", help="Print the stored variation profile.")

    analyze_sections_parser = subparsers.add_parser(
        "analyze-sections",
        help="Detect song sections from existing audio analysis and export a deterministic section report.",
    )
    analyze_sections_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    analyze_sections_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    analyze_sections_parser.add_argument("--output", required=True, type=Path, help="Path to write the section analysis JSON.")
    analyze_sections_parser.add_argument("--force", action="store_true", help="Regenerate section analysis even when the existing artifact matches the current inputs.")

    evaluate_sections_parser = subparsers.add_parser(
        "evaluate-sections",
        help="Score every candidate map per detected section and export per-candidate section reports.",
    )
    evaluate_sections_parser.add_argument("--sections", required=True, type=Path, help="Path to the shared section analysis JSON.")
    evaluate_sections_parser.add_argument("--analysis", type=Path, help="Optional path to the shared analysis JSON. Defaults to public/analysis/<song>-analysis.json derived from --sections.")
    evaluate_sections_parser.add_argument("--candidates-root", required=True, type=Path, help="Directory containing candidate-### folders.")
    evaluate_sections_parser.add_argument("--difficulty", required=True, choices=sorted(DIFFICULTY_PRESETS), help="Difficulty preset to apply.")
    evaluate_sections_parser.add_argument("--output-dir", required=True, type=Path, help="Directory where candidate section reports will be written.")
    evaluate_sections_parser.add_argument("--force", action="store_true", help="Regenerate candidate section reports even when the existing artifact matches the current inputs.")
    evaluate_sections_parser.add_argument("--verbose", action="store_true", help="Reserved for future detailed section diagnostics.")

    assemble_hybrid_parser = subparsers.add_parser(
        "assemble-hybrid",
        help="Select the best section source sequence, optimize transitions, assemble a hybrid map, and validate it.",
    )
    assemble_hybrid_parser.add_argument("--sections", required=True, type=Path, help="Path to the section analysis JSON.")
    assemble_hybrid_parser.add_argument("--analysis", type=Path, help="Optional path to the shared analysis JSON. Defaults to public/analysis/<song>-analysis.json derived from --sections.")
    assemble_hybrid_parser.add_argument("--section-reports-dir", type=Path, help="Optional directory containing candidate section reports. Defaults to public/section-reports/<song>/<difficulty> derived from --sections and --difficulty.")
    assemble_hybrid_parser.add_argument("--candidates-root", required=True, type=Path, help="Directory containing candidate-### folders.")
    assemble_hybrid_parser.add_argument("--difficulty", required=True, choices=sorted(DIFFICULTY_PRESETS), help="Difficulty preset to apply.")
    assemble_hybrid_parser.add_argument("--output-map", required=True, type=Path, help="Path to write the assembled hybrid map JSON.")
    assemble_hybrid_parser.add_argument("--output-report", required=True, type=Path, help="Path to write the authoritative Python validation report JSON.")
    assemble_hybrid_parser.add_argument("--assembly-report", required=True, type=Path, help="Path to write the hybrid assembly report JSON.")
    assemble_hybrid_parser.add_argument("--transition-log", required=True, type=Path, help="Path to write the hybrid transition log JSON.")
    assemble_hybrid_parser.add_argument("--force", action="store_true", help="Reserved for future forced hybrid regeneration behavior.")
    assemble_hybrid_parser.add_argument("--verbose", action="store_true", help="Reserved for future detailed transition diagnostics.")

    hybrid_all_parser = subparsers.add_parser(
        "hybrid-all",
        help="Run section analysis, candidate section evaluation, and hybrid assembly for easy, normal, and hard.",
    )
    hybrid_all_parser.add_argument("--audio", required=True, type=Path, help="Path to the input audio file.")
    hybrid_all_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared analysis JSON.")
    hybrid_all_parser.add_argument("--seed", required=True, type=int, help="Deterministic pipeline seed placeholder for parity with other phases.")
    hybrid_all_parser.add_argument("--force", action="store_true", help="Regenerate section artifacts and candidate section reports even when the existing artifacts match the current inputs.")
    hybrid_all_parser.add_argument("--verbose", action="store_true", help="Reserved for future detailed hybrid diagnostics.")

    compare_hybrids_parser = subparsers.add_parser(
        "compare-hybrids",
        help="Compare hybrid assembly reports by hybrid score and Python quality.",
    )
    compare_hybrids_parser.add_argument("--hybrids-dir", required=True, type=Path, help="Directory containing hybrid assembly reports.")

    export_osu_parser = subparsers.add_parser(
        "export-osu",
        help="Export a project JSON beatmap to a circle-only .osu file.",
    )
    export_osu_parser.add_argument("--map", required=True, type=Path, help="Path to the source project JSON beatmap.")
    export_osu_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared audio-analysis JSON.")
    export_osu_parser.add_argument("--output", required=True, type=Path, help="Path to write the exported .osu file.")
    export_osu_parser.add_argument("--creator", help="Optional creator override written into Metadata.Creator.")
    export_osu_parser.add_argument("--version-name", help="Optional difficulty version override written into Metadata.Version.")
    export_osu_parser.add_argument("--beatmap-id", help="Optional BeatmapID override.")
    export_osu_parser.add_argument("--beatmap-set-id", help="Optional BeatmapSetID override.")
    export_osu_parser.add_argument("--background", help="Optional background filename to reference in [Events].")

    import_osu_parser = subparsers.add_parser(
        "import-osu",
        help="Import a circle-only .osu file into the project JSON beatmap format.",
    )
    import_osu_parser.add_argument("--input", required=True, type=Path, help="Path to the input .osu file.")
    import_osu_parser.add_argument("--output", required=True, type=Path, help="Path to write the imported project JSON beatmap.")
    import_osu_parser.add_argument(
        "--unsupported",
        default="reject",
        choices=["reject", "skip"],
        help="How unsupported sliders, spinners, and holds should be handled.",
    )

    validate_osu_parser = subparsers.add_parser(
        "validate-osu",
        help="Validate a circle-only .osu file for Phase 8A compatibility.",
    )
    validate_osu_parser.add_argument("--input", required=True, type=Path, help="Path to the input .osu file.")

    package_osz_parser = subparsers.add_parser(
        "package-osz",
        help="Package exported .osu files and a referenced audio file into a deterministic .osz archive.",
    )
    package_osz_parser.add_argument("--maps-dir", required=True, type=Path, help="Directory containing exported .osu files.")
    package_osz_parser.add_argument("--audio", required=True, type=Path, help="Audio file referenced by the exported mapset.")
    package_osz_parser.add_argument("--output", required=True, type=Path, help="Path to write the .osz archive.")
    package_osz_parser.add_argument("--background", type=Path, help="Optional background image file to package.")

    export_osu_mapset_parser = subparsers.add_parser(
        "export-osu-mapset",
        help="Export a directory of project JSON beatmaps to .osu files and optionally package them into one .osz archive.",
    )
    export_osu_mapset_parser.add_argument("--maps-dir", required=True, type=Path, help="Directory containing project JSON beatmaps to export.")
    export_osu_mapset_parser.add_argument("--analysis", required=True, type=Path, help="Path to the shared audio-analysis JSON.")
    export_osu_mapset_parser.add_argument("--audio", required=True, type=Path, help="Audio file referenced by the exported mapset.")
    export_osu_mapset_parser.add_argument("--output-dir", required=True, type=Path, help="Directory where the exported .osu files will be written.")
    export_osu_mapset_parser.add_argument("--package", type=Path, help="Optional .osz output path for deterministic packaging.")

    return parser


def _parse_weight_overrides(pairs: list[str]) -> dict[str, float] | None:
    """Parse repeatable ``KEY=VALUE`` final-weight overrides."""
    if not pairs:
        return None
    overrides: dict[str, float] = {}
    for pair in pairs:
        if "=" not in pair:
            raise MapGeneratorError(
                f"Invalid --final-weight override '{pair}': expected KEY=VALUE."
            )
        key, raw_value = pair.split("=", maxsplit=1)
        key = key.strip()
        try:
            value = float(raw_value)
        except ValueError as error:
            raise MapGeneratorError(
                f"Invalid --final-weight value '{raw_value}' for '{key}': must be a number."
            ) from error
        overrides[key] = value
    return overrides


def _song_slug_from_sections_path(sections_path: Path) -> str:
    stem = sections_path.stem
    if stem.endswith("-sections"):
        return stem[:-9]
    return stem


def _derive_analysis_path(project_root: Path, sections_path: Path) -> Path:
    slug = _song_slug_from_sections_path(sections_path)
    return project_root / "public" / "analysis" / f"{slug}-analysis.json"


def _derive_section_report_dir(project_root: Path, candidates_root: Path) -> Path:
    try:
        song_slug = candidates_root.parent.name
        difficulty = candidates_root.name
    except IndexError as error:
        raise MapGeneratorError(f"Could not derive section-report directory from {candidates_root}") from error
    return project_root / "public" / "section-reports" / song_slug / difficulty


def _derive_map_metadata(candidates_root: Path) -> dict[str, str]:
    candidate_map = candidates_root / "candidate-001" / "improved-map.json"
    raw_data = load_json_file(candidate_map, "Improved candidate map")
    if not isinstance(raw_data, dict):
        raise MapGeneratorError(f"Improved candidate map root must be an object: {candidate_map}")
    title = raw_data.get("title")
    artist = raw_data.get("artist")
    audio = raw_data.get("audio")
    if not isinstance(title, str) or not title.strip() or not isinstance(artist, str) or not artist.strip() or not isinstance(audio, str) or not audio.strip():
        raise MapGeneratorError(f"Improved candidate map is missing title, artist, or audio metadata: {candidate_map}")
    return {
        "title": title.strip(),
        "artist": artist.strip(),
        "audioPublicPath": audio.strip(),
    }


def _derive_osu_export_report_path(output_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "public" / "exports" / "reports" / f"{output_path.stem}-export.json"


def _derive_osu_import_report_path(output_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "public" / "imports" / "reports" / f"{output_path.stem}-import.json"


if __name__ == "__main__":
    raise SystemExit(main())
