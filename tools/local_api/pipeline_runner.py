from __future__ import annotations

import json
import logging
import shutil
import time
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tools.map_generator.analysis_io import load_analysis_json
from tools.map_generator.audio_analyzer import analyze_audio
from tools.map_generator.beatmap_generator import generate_beatmap_from_analysis
from tools.map_generator.config import DifficultyPreset, get_difficulty_preset
from tools.map_generator.difficulty import analyze_difficulty
from tools.map_generator.difficulty.models import DifficultyTarget
from tools.map_generator.evolution import run_candidate_evolution
from tools.map_generator.generation_config import (
    MappingControls,
    apply_custom_star_adjustment,
    apply_mapping_controls,
    build_position_variation_biases,
    build_section_config,
    custom_star_adjustment,
    resolve_difficulty_target,
    resolve_mapping_controls,
)
from tools.map_generator.osu_format import export_osu_file, package_osz_archive
from tools.map_generator.phrase import analyze_phrase_structure, build_phrase_rhythm_info, load_phrase_report
from tools.map_generator.postprocess import improve_beatmap
from tools.map_generator.sections import analyze_sections, assemble_hybrid, evaluate_candidate_sections
from tools.map_generator.sections.section_config import SectionPipelineConfig
from tools.map_generator.utils import MapGeneratorError, copy_file, write_json
from tools.map_generator.validation import validate_beatmap
from tools.map_generator.variation import PositionVariation

from .artifact_service import ArtifactService
from .config import LocalApiConfig
from .errors import LocalApiCancellationRequested, LocalApiValidationError
from .metadata_service import MetadataService
from .models import DifficultyName, WorkspaceManifest
from .security import (
    build_mapset_filename,
    build_osu_filename,
    sanitize_filename_component,
)
from .workspace_manager import WorkspaceManager, WorkspacePaths

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineStage:
    code: str
    label: str
    action: Callable[[], None]
    difficulty: DifficultyName | None = None


class PipelineRunner:
    def __init__(
        self,
        config: LocalApiConfig,
        workspace_manager: WorkspaceManager,
        metadata_service: MetadataService,
        artifact_service: ArtifactService,
    ) -> None:
        self.config = config
        self.workspace_manager = workspace_manager
        self.metadata_service = metadata_service
        self.artifact_service = artifact_service

    # ------------------------------------------------------------------
    # Phase 19 generation configuration helpers
    # ------------------------------------------------------------------

    def _mapping_controls(self, settings) -> MappingControls:
        return MappingControls(
            circle_density=settings.circle_density,
            slider_density=settings.slider_density,
            spinner_frequency=settings.spinner_frequency,
            jump_intensity=settings.jump_intensity,
            stream_intensity=settings.stream_intensity,
            burst_intensity=settings.burst_intensity,
            rhythm_complexity=settings.rhythm_complexity,
            pattern_variety=settings.pattern_variety,
            spacing=settings.spacing,
            aggression=settings.aggression,
        )

    def _effective_preset(self, difficulty: DifficultyName, settings) -> DifficultyPreset:
        base = get_difficulty_preset(difficulty)
        controls = resolve_mapping_controls(
            settings.mapping_preset,
            self._mapping_controls(settings),
        )
        preset = apply_mapping_controls(base, controls)
        if settings.difficulty_target == "custom":
            target = self._difficulty_target(difficulty, settings)
            if target is not None:
                preset = apply_custom_star_adjustment(
                    preset,
                    custom_star_adjustment(difficulty, target),
                )
        return preset

    def _base_variation(self, settings) -> PositionVariation:
        controls = resolve_mapping_controls(
            settings.mapping_preset,
            self._mapping_controls(settings),
        )
        return build_position_variation_biases(controls)

    def _difficulty_target(
        self,
        difficulty: DifficultyName,
        settings,
    ) -> DifficultyTarget | None:
        if settings.difficulty_target != "custom":
            return None
        return resolve_difficulty_target(
            difficulty,
            target_mode="custom",
            custom_target_star=settings.custom_target_star,
            custom_min_star=settings.custom_min_star,
            custom_max_star=settings.custom_max_star,
        )

    def _generation_config_payload(
        self,
        difficulty: DifficultyName,
        settings,
    ) -> dict[str, object]:
        controls = resolve_mapping_controls(
            settings.mapping_preset,
            self._mapping_controls(settings),
        )
        payload: dict[str, object] = {
            "difficulty": difficulty,
            "mappingPreset": settings.mapping_preset,
            "difficultyTarget": settings.difficulty_target,
            "controls": controls.to_dict(),
            "candidateCount": settings.candidate_count,
            "evolutionPasses": settings.evolution_passes,
            "rootSeed": settings.root_seed,
            "seedMode": settings.seed_mode,
            "replayProfile": settings.replay_profile,
            "sectionSensitivity": settings.section_sensitivity,
            "timingVariation": settings.timing_variation,
            "tournamentEnabled": settings.tournament_enabled,
            "hybridAssemblyEnabled": settings.hybrid_assembly_enabled,
        }
        if settings.difficulty_target == "custom":
            payload["customStars"] = {
                "target": settings.custom_target_star,
                "min": settings.custom_min_star,
                "max": settings.custom_max_star,
            }
        return payload

    def run_job(self, job_manager, job_id: str, workspace_id: str) -> None:
        manifest = self.workspace_manager.load_manifest(workspace_id)
        self.metadata_service.validate_generation_ready(manifest)
        paths = self.workspace_manager.ensure_workspace_exists(workspace_id)
        log_path = paths.logs_dir / f"{job_id}.log"
        if (
            manifest.last_run_signature
            and manifest.configuration_signature
            and manifest.last_run_signature != manifest.configuration_signature
        ):
            self._clear_previous_outputs(paths)
            manifest = self.workspace_manager.load_manifest(workspace_id)

        browser_audio_path = self.artifact_service.build_audio_preview_url(
            workspace_id,
            manifest.audio.normalized_filename if manifest.audio else "source-audio.mp3",
        )
        final_map_kinds = self._build_final_map_kinds(manifest)
        stages = self._build_stage_plan(
            manifest=manifest,
            paths=paths,
            browser_audio_path=browser_audio_path,
            final_map_kinds=final_map_kinds,
            job_manager=job_manager,
            job_id=job_id,
        )
        job_manager.set_total_stages(job_id, len(stages))
        job_manager.log(job_id, "info", "Local generation pipeline started.")

        for index, stage in enumerate(stages, start=1):
            self._check_cancellation(job_manager, job_id)
            job_manager.begin_stage(
                job_id,
                stage_number=index,
                stage_code=stage.code,
                stage_label=stage.label,
                difficulty=stage.difficulty,
            )
            self._append_log(log_path, f"[stage {index}/{len(stages)}] {stage.label}")
            _stage_start = time.monotonic()
            try:
                # P0.2: every stage runs under the execution watchdog so a
                # hung analysis/evolution stage fails the job instead of
                # blocking the worker thread forever.
                job_manager.run_stage_with_watchdog(job_id, stage.label, stage.action)
            except LocalApiCancellationRequested:
                _stage_ms = (time.monotonic() - _stage_start) * 1000
                _cancel_msg = (
                    f"Stage {index}/{len(stages)} ({stage.label}) cancelled "
                    f"after {_stage_ms:.0f} ms."
                )
                _logger.warning(_cancel_msg)
                # P2.4: record the cancelled stage's measured duration too.
                job_manager.record_stage_timing(
                    job_id,
                    index=index,
                    stage_code=stage.code,
                    stage_label=stage.label,
                    difficulty=stage.difficulty,
                    duration_ms=_stage_ms,
                    status="cancelled",
                )
                job_manager.log(job_id, "warning", _cancel_msg)
                self._append_log(log_path, f"[cancelled] {_cancel_msg}")
                refreshed_manifest = self.artifact_service.refresh_workspace_artifacts(
                    self.workspace_manager.load_manifest(workspace_id)
                )
                cancelled_manifest = refreshed_manifest.model_copy(
                    update={"job_status": "cancelled"},
                    deep=True,
                )
                self.workspace_manager.save_manifest(cancelled_manifest)
                job_manager.cancel(
                    job_id,
                    artifact_ids=[item.id for item in cancelled_manifest.available_artifacts],
                )
                return
            except Exception as error:
                _stage_ms = (time.monotonic() - _stage_start) * 1000
                _traceback = traceback.format_exc()
                _error_header = (
                    f"Stage {index}/{len(stages)} ({stage.label}) failed "
                    f"after {_stage_ms:.0f} ms: {type(error).__name__}: {error}"
                )
                _error_detail = (
                    f"{_error_header}\n\n"
                    f"--- Full stack trace ---\n"
                    f"{_traceback}"
                )
                _logger.error(_error_detail)
                # P2.4: record the failed stage's measured duration.
                job_manager.record_stage_timing(
                    job_id,
                    index=index,
                    stage_code=stage.code,
                    stage_label=stage.label,
                    difficulty=stage.difficulty,
                    duration_ms=_stage_ms,
                    status="failed",
                )
                job_manager.log(job_id, "error", _error_header)
                job_manager.log(job_id, "error", f"Stack trace:\n{_traceback}")
                self._append_log(log_path, _error_detail)
                refreshed_manifest = self.artifact_service.refresh_workspace_artifacts(
                    self.workspace_manager.load_manifest(workspace_id)
                )
                failed_manifest = refreshed_manifest.model_copy(
                    update={"job_status": "failed"},
                    deep=True,
                )
                self.workspace_manager.save_manifest(failed_manifest)
                readable_message = str(error) if isinstance(error, (MapGeneratorError, LocalApiValidationError)) else "Generation failed unexpectedly."
                job_manager.fail(
                    job_id,
                    f"{_error_header}\n\n{readable_message}",
                    technical_details=_traceback,
                    artifact_ids=[item.id for item in failed_manifest.available_artifacts],
                )
                return
            _stage_ms = (time.monotonic() - _stage_start) * 1000
            _logger.info(
                "[stage %d/%d] %s — %.1f ms",
                index,
                len(stages),
                stage.label,
                _stage_ms,
            )
            # P2.4: surface the server-measured stage duration to the client.
            job_manager.record_stage_timing(
                job_id,
                index=index,
                stage_code=stage.code,
                stage_label=stage.label,
                difficulty=stage.difficulty,
                duration_ms=_stage_ms,
                status="completed",
            )
            job_manager.complete_stage(job_id, stage.label)

        refreshed_manifest = self.artifact_service.refresh_workspace_artifacts(
            self.workspace_manager.load_manifest(workspace_id)
        )
        result_summary = self.artifact_service.build_result_summary(refreshed_manifest)
        completed_manifest = refreshed_manifest.model_copy(
            update={
                "job_status": "completed",
                "last_run_signature": refreshed_manifest.configuration_signature,
                "last_result": result_summary,
            },
            deep=True,
        )
        completed_manifest = self.workspace_manager.save_manifest(completed_manifest)
        job_manager.complete(
            job_id,
            artifact_ids=[item.id for item in completed_manifest.available_artifacts],
            result=result_summary,
        )

    def _build_stage_plan(
        self,
        *,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        browser_audio_path: str,
        final_map_kinds: dict[DifficultyName, str],
        job_manager,
        job_id: str,
    ) -> list[PipelineStage]:
        metadata = manifest.metadata
        selected = list(metadata.selected_difficulties)
        audio_path = self.workspace_manager.resolve_audio_source_path(manifest)
        analysis_path = paths.analysis_dir / "analysis.json"
        section_config = self._build_section_config_for_selection(metadata)
        phrase_config = self._phrase_pipeline_config(metadata)
        stages: list[PipelineStage] = [
            PipelineStage(
                code="validate-audio",
                label="Validate uploaded audio",
                action=lambda: self._validate_audio(
                    job_manager,
                    job_id,
                    audio_path,
                ),
            ),
            PipelineStage(
                code="analyze-audio",
                label="Analyze audio",
                action=lambda: self._analyze_audio(
                    manifest,
                    audio_path,
                    analysis_path,
                ),
            ),
        ]
        for difficulty in selected:
            settings = metadata.difficulty_settings[difficulty]
            stages.extend(
                [
                    PipelineStage(
                        code=f"generate-{difficulty}",
                        label=f"{difficulty.capitalize()} base map",
                        difficulty=difficulty,
                        action=lambda difficulty=difficulty, settings=settings: self._generate_base_map(
                            manifest,
                            paths,
                            analysis_path,
                            audio_path,
                            browser_audio_path,
                            difficulty,
                            settings,
                        ),
                    ),
                    PipelineStage(
                        code=f"validate-{difficulty}",
                        label=f"{difficulty.capitalize()} base validation",
                        difficulty=difficulty,
                        action=lambda difficulty=difficulty, settings=settings: self._validate_map_kind(
                            paths,
                            analysis_path,
                            difficulty,
                            kind="generated",
                            preset=self._effective_preset(difficulty, settings),
                        ),
                    ),
                    PipelineStage(
                        code=f"improve-{difficulty}",
                        label=f"{difficulty.capitalize()} post-processing",
                        difficulty=difficulty,
                        action=lambda difficulty=difficulty, settings=settings: self._improve_map(
                            job_manager,
                            job_id,
                            paths,
                            analysis_path,
                            difficulty,
                            settings,
                        ),
                    ),
                ]
            )
            if settings.tournament_enabled:
                stages.append(
                    PipelineStage(
                        code=f"evolution-{difficulty}",
                        label=f"{difficulty.capitalize()} candidate evolution",
                        difficulty=difficulty,
                        action=lambda difficulty=difficulty, settings=settings: self._run_evolution(
                            job_manager,
                            job_id,
                            manifest,
                            paths,
                            analysis_path,
                            audio_path,
                            browser_audio_path,
                            difficulty,
                            settings,
                        ),
                    )
                )
        if any(
            metadata.difficulty_settings[difficulty].hybrid_assembly_enabled for difficulty in selected
        ):
            stages.append(
                PipelineStage(
                    code="sections",
                    label="Analyze song sections",
                    action=lambda: self._analyze_sections(
                        paths,
                        audio_path,
                        analysis_path,
                        browser_audio_path,
                        section_config,
                    ),
                )
            )
            stages.append(
                PipelineStage(
                    code="phrases",
                    label="Analyze musical phrases",
                    action=lambda: self._analyze_phrases(
                        paths,
                        analysis_path,
                        phrase_config,
                    ),
                )
            )
            for difficulty in selected:
                settings = metadata.difficulty_settings[difficulty]
                if not settings.hybrid_assembly_enabled:
                    continue
                stages.extend(
                    [
                        PipelineStage(
                            code=f"section-eval-{difficulty}",
                            label=f"{difficulty.capitalize()} section evaluation",
                            difficulty=difficulty,
                            action=lambda difficulty=difficulty: self._evaluate_sections(
                                paths,
                                analysis_path,
                                difficulty,
                                section_config,
                            ),
                        ),
                        PipelineStage(
                            code=f"hybrid-{difficulty}",
                            label=f"{difficulty.capitalize()} hybrid assembly",
                            difficulty=difficulty,
                            action=lambda difficulty=difficulty: self._assemble_hybrid_with_fallback(
                                manifest,
                                paths,
                                audio_path,
                                analysis_path,
                                browser_audio_path,
                                difficulty,
                                section_config,
                                final_map_kinds,
                            ),
                        ),
                    ]
                )
        stages.append(
            PipelineStage(
                code="validate-final",
                label="Validate final maps",
                action=lambda: self._validate_final_maps(
                    manifest,
                    paths,
                    analysis_path,
                    selected,
                    final_map_kinds,
                ),
            )
        )
        stages.append(
            PipelineStage(
                code="difficulty",
                label="Difficulty intelligence",
                action=lambda: self._analyze_difficulty(
                    manifest,
                    paths,
                    analysis_path,
                    selected,
                    final_map_kinds,
                ),
            )
        )
        stages.append(
            PipelineStage(
                code="recovery",
                label="Analyze recovery & fatigue",
                action=lambda: self._analyze_recovery(
                    paths,
                    selected,
                    final_map_kinds,
                ),
            )
        )
        stages.append(
            PipelineStage(
                code="export-osu",
                label="Export .osu files",
                action=lambda: self._export_osu_files(
                    manifest,
                    paths,
                    analysis_path,
                    selected,
                    final_map_kinds,
                ),
            )
        )
        stages.append(
            PipelineStage(
                code="package-osz",
                label="Package .osz",
                action=lambda: self._package_mapset(
                    manifest,
                    paths,
                ),
            )
        )
        stages.append(
            PipelineStage(
                code="verify-package",
                label="Verify package contents",
                action=lambda: self._verify_package_contents(
                    manifest,
                    paths,
                    selected,
                ),
            )
        )
        return stages

    def _validate_audio(self, job_manager, job_id: str, audio_path: Path) -> None:
        suggestions = self.metadata_service.extract_audio_metadata(audio_path)
        summary = f"Decoded {audio_path.name}"
        if suggestions.duration_ms is not None:
            summary += f" ({suggestions.duration_ms} ms)"
        job_manager.log(job_id, "info", summary)

    def _analyze_audio(
        self,
        manifest: WorkspaceManifest,
        audio_path: Path,
        analysis_path: Path,
    ) -> None:
        if self._can_reuse(manifest, analysis_path):
            return
        analysis = analyze_audio(audio_path)
        write_json(analysis_path, analysis.to_dict())

    def _generate_base_map(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        analysis_path: Path,
        audio_path: Path,
        browser_audio_path: str,
        difficulty: DifficultyName,
        settings,
    ) -> None:
        output_path = paths.generated_maps_dir / f"{difficulty}.json"
        if self._can_reuse(manifest, output_path):
            return
        analysis = load_analysis_json(analysis_path)
        generate_beatmap_from_analysis(
            analysis=analysis,
            audio_path=audio_path,
            title=manifest.metadata.title,
            artist=manifest.metadata.artist,
            difficulty=difficulty,
            seed=settings.root_seed,
            output_path=output_path,
            analysis_output_path=None,
            project_root=self.config.project_root,
            preset=self._effective_preset(difficulty, settings),
            base_variation=self._base_variation(settings),
            generator_metadata={
                "generationConfig": self._generation_config_payload(
                    difficulty,
                    settings,
                )
            },
            browser_audio_path_override=browser_audio_path,
            title_unicode=manifest.metadata.title_unicode,
            artist_unicode=manifest.metadata.artist_unicode,
        )

    def _validate_map_kind(
        self,
        paths: WorkspacePaths,
        analysis_path: Path,
        difficulty: DifficultyName,
        *,
        kind: str,
        preset: DifficultyPreset | None = None,
    ) -> None:
        map_path = self._map_path_for_kind(paths, kind, difficulty)
        report_path = self._report_path_for_kind(paths, kind, difficulty)
        validate_beatmap(
            map_path=map_path,
            analysis_path=analysis_path,
            difficulty=difficulty,
            output_path=report_path,
            map_label=map_path.relative_to(self.config.project_root).as_posix(),
            preset=preset,
        )

    def _improve_map(
        self,
        job_manager,
        job_id: str,
        paths: WorkspacePaths,
        analysis_path: Path,
        difficulty: DifficultyName,
        settings,
    ) -> None:
        output_path = paths.improved_maps_dir / f"{difficulty}.json"
        report_output_path = paths.improved_reports_dir / f"{difficulty}-report.json"
        corrections_path = paths.corrections_dir / f"{difficulty}-corrections.json"
        if output_path.exists() and report_output_path.exists() and corrections_path.exists():
            job_manager.log(job_id, "info", f"{difficulty.capitalize()} post-processing cached — reusing existing output.")
            return
        job_manager.log(
            job_id, "info",
            f"{difficulty.capitalize()} post-processing starting — analyzing structural safety.",
        )
        _logger.info("[%s] post-processing starting…", difficulty)
        _improve_start = time.monotonic()
        try:
            improve_beatmap(
                map_path=paths.generated_maps_dir / f"{difficulty}.json",
                analysis_path=analysis_path,
                report_path=paths.generated_reports_dir / f"{difficulty}-report.json",
                difficulty=difficulty,
                seed=settings.root_seed,
                output_path=output_path,
                report_output_path=report_output_path,
                changes_output_path=corrections_path,
                source_map_label=(
                    paths.generated_maps_dir / f"{difficulty}.json"
                ).relative_to(self.config.project_root).as_posix(),
                output_map_label=output_path.relative_to(self.config.project_root).as_posix(),
                preset=self._effective_preset(difficulty, settings),
            )
        except Exception:
            _improve_ms = (time.monotonic() - _improve_start) * 1000
            _logger.error(
                "[%s] post-processing FAILED after %.1fs",
                difficulty,
                _improve_ms,
            )
            job_manager.log(
                job_id, "error",
                f"{difficulty.capitalize()} post-processing failed after {_improve_ms:.0f} ms.",
            )
            raise
        _improve_ms = (time.monotonic() - _improve_start) * 1000
        _logger.info(
            "[%s] post-processing complete — %.1f ms",
            difficulty,
            _improve_ms,
        )
        job_manager.log(
            job_id, "info",
            f"{difficulty.capitalize()} post-processing complete — {_improve_ms:.0f} ms.",
        )

    def _run_evolution(
        self,
        job_manager,
        job_id: str,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        analysis_path: Path,
        audio_path: Path,
        browser_audio_path: str,
        difficulty: DifficultyName,
        settings,
    ) -> None:
        def progress_callback(current: int, total: int, message: str) -> None:
            # P0.2: poll cancellation between candidates so long evolution
            # stages can be interrupted mid-pass instead of only at the next
            # stage boundary.
            self._check_cancellation(job_manager, job_id)
            job_manager.update_candidate_progress(
                job_id,
                difficulty=difficulty,
                current_candidate=current,
                candidates_completed=max(0, current - 1),
                candidates_total=total,
                message=message,
            )

        sections_path = paths.sections_dir / "sections.json"
        phrase_report_path = paths.sections_dir / "phrase-structure.json"
        run_candidate_evolution(
            audio_path=audio_path,
            analysis_path=analysis_path,
            title=manifest.metadata.title,
            artist=manifest.metadata.artist,
            difficulty=difficulty,
            root_seed=settings.root_seed,
            output_root=paths.difficulty_candidates_dir(difficulty),
            champion_map_path=paths.champion_maps_dir / f"{difficulty}.json",
            champion_report_path=paths.champion_reports_dir / f"{difficulty}-report.json",
            evolution_report_path=paths.evolution_reports_dir / f"{difficulty}-evolution.json",
            project_root=self.config.project_root,
            count=settings.candidate_count,
            timing_variation=settings.timing_variation,
            force=False,
            verbose=False,
            archive_policy="all",
            sections_path=sections_path if sections_path.exists() else None,
            browser_audio_path_override=browser_audio_path,
            champion_map_browser_path_override=f"workspaces/{manifest.workspace_id}/maps/champions/{difficulty}.json",
            champion_report_browser_path_override=f"workspaces/{manifest.workspace_id}/reports/champions/{difficulty}-report.json",
            progress_callback=progress_callback,
            max_passes=settings.evolution_passes,
            player_profile=settings.replay_profile,
            preset=self._effective_preset(difficulty, settings),
            target=self._difficulty_target(difficulty, settings),
            base_variation=self._base_variation(settings),
            generation_config=self._generation_config_payload(difficulty, settings),
            phrase_report_path=(
                phrase_report_path if phrase_report_path.exists() else None
            ),
        )
        job_manager.update_candidate_progress(
            job_id,
            difficulty=difficulty,
            current_candidate=settings.candidate_count,
            candidates_completed=settings.candidate_count,
            candidates_total=settings.candidate_count,
            message=f"{difficulty.capitalize()} candidate evolution complete.",
        )

    def _analyze_sections(
        self,
        paths: WorkspacePaths,
        audio_path: Path,
        analysis_path: Path,
        browser_audio_path: str,
        config: SectionPipelineConfig,
    ) -> None:
        analyze_sections(
            audio_path=audio_path,
            analysis_path=analysis_path,
            output_path=paths.sections_dir / "sections.json",
            project_root=self.config.project_root,
            config=config,
            force=False,
            audio_browser_path_override=browser_audio_path,
        )

    def _analyze_phrases(
        self,
        paths: WorkspacePaths,
        analysis_path: Path,
        config,
    ) -> None:
        sections_path = paths.sections_dir / "sections.json"
        if not sections_path.exists():
            return
        analyze_phrase_structure(
            analysis_path=analysis_path,
            sections_path=sections_path,
            output_path=paths.sections_dir / "phrase-structure.json",
            config=config,
            force=False,
        )

    def _phrase_pipeline_config(self, metadata) -> Any:
        from tools.map_generator.phrase import PhrasePipelineConfig
        return PhrasePipelineConfig()

    def _build_section_config_for_selection(
        self,
        metadata,
    ) -> SectionPipelineConfig:
        selected = list(metadata.selected_difficulties)
        if not selected:
            return SectionPipelineConfig()
        sensitivities = [
            metadata.difficulty_settings[difficulty].section_sensitivity
            for difficulty in selected
        ]
        average_sensitivity = sum(sensitivities) / len(sensitivities)
        return build_section_config(average_sensitivity)

    def _evaluate_sections(
        self,
        paths: WorkspacePaths,
        analysis_path: Path,
        difficulty: DifficultyName,
        config: SectionPipelineConfig,
    ) -> None:
        try:
            evaluate_candidate_sections(
                sections_path=paths.sections_dir / "sections.json",
                analysis_path=analysis_path,
                candidates_root=paths.difficulty_candidates_dir(difficulty),
                difficulty=difficulty,
                output_dir=paths.difficulty_section_reports_dir(difficulty),
                config=config,
                force=False,
            )
        except Exception as exc:
            _logger.warning(
                "Section evaluation failed for %s, using un-evaluated default sections: %s",
                difficulty,
                exc,
            )

    def _assemble_hybrid(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        audio_path: Path,
        analysis_path: Path,
        browser_audio_path: str,
        difficulty: DifficultyName,
        config: SectionPipelineConfig,
    ) -> None:
        assemble_hybrid(
            song_slug=self._song_slug(manifest),
            title=manifest.metadata.title,
            artist=manifest.metadata.artist,
            audio_path=audio_path,
            analysis_path=analysis_path,
            sections_path=paths.sections_dir / "sections.json",
            section_reports_dir=paths.difficulty_section_reports_dir(difficulty),
            candidates_root=paths.difficulty_candidates_dir(difficulty),
            difficulty=difficulty,
            output_map=paths.hybrid_maps_dir / f"{difficulty}.json",
            output_report=paths.hybrid_reports_dir / f"{difficulty}-report.json",
            assembly_report_path=paths.hybrid_details_dir / f"{difficulty}-assembly.json",
            transition_log_path=paths.hybrid_details_dir / f"{difficulty}-transitions.json",
            project_root=self.config.project_root,
            config=config,
            audio_browser_path_override=browser_audio_path,
        )

    def _assemble_hybrid_with_fallback(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        audio_path: Path,
        analysis_path: Path,
        browser_audio_path: str,
        difficulty: DifficultyName,
        config: SectionPipelineConfig,
        final_map_kinds: dict[DifficultyName, str],
    ) -> None:
        """Run hybrid assembly with graceful fallback to the improved map.

        If the assembly step raises an exception, log a warning and downgrade
        *final_map_kinds* for *difficulty* from ``"hybrid"`` to ``"improved"``
        so that downstream stages (validation, export, packaging) use the
        best available post-processed candidate instead of failing the entire job.
        """
        try:
            self._assemble_hybrid(
                manifest,
                paths,
                audio_path,
                analysis_path,
                browser_audio_path,
                difficulty,
                config,
            )
        except Exception as exc:
            _logger.warning(
                "Hybrid assembly failed for %s, falling back to improved map: %s",
                difficulty,
                exc,
            )
            final_map_kinds[difficulty] = "improved"

    def _validate_final_maps(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        analysis_path: Path,
        selected: list[DifficultyName],
        final_map_kinds: dict[DifficultyName, str],
    ) -> None:
        for difficulty in selected:
            final_kind = final_map_kinds[difficulty]
            settings = manifest.metadata.difficulty_settings[difficulty]
            self._validate_map_kind(
                paths,
                analysis_path,
                difficulty,
                kind=final_kind,
                preset=self._effective_preset(difficulty, settings),
            )

    def _analyze_difficulty(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        analysis_path: Path,
        selected: list[DifficultyName],
        final_map_kinds: dict[DifficultyName, str],
    ) -> None:
        sections_path = paths.sections_dir / "sections.json"
        for difficulty in selected:
            final_kind = final_map_kinds[difficulty]
            map_path = self._map_path_for_kind(paths, final_kind, difficulty)
            output_path = paths.difficulty_reports_dir / f"{difficulty}-difficulty.json"
            if output_path.exists():
                continue
            settings = manifest.metadata.difficulty_settings[difficulty]
            analyze_difficulty(
                map_path=map_path,
                analysis_path=analysis_path,
                difficulty=difficulty,
                output_path=output_path,
                map_label=map_path.relative_to(self.config.project_root).as_posix(),
                sections_path=sections_path if sections_path.exists() else None,
                target=self._difficulty_target(difficulty, settings),
            )

    def _analyze_recovery(
        self,
        paths: WorkspacePaths,
        selected: list[DifficultyName],
        final_map_kinds: dict[DifficultyName, str],
    ) -> None:
        """Persist the Phase 22 recovery structure for every final map."""
        from tools.map_generator.recovery.recovery_report import analyze_recovery_structure

        phrase_report_path = paths.sections_dir / "phrase-structure.json"
        for difficulty in selected:
            final_kind = final_map_kinds[difficulty]
            map_path = self._map_path_for_kind(paths, final_kind, difficulty)
            if not map_path.exists():
                continue
            analyze_recovery_structure(
                map_path=map_path,
                phrase_report_path=(
                    phrase_report_path if phrase_report_path.exists() else None
                ),
                output_path=paths.sections_dir / f"recovery-{difficulty}.json",
                difficulty=difficulty,
                force=False,
            )

    def _export_osu_files(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        analysis_path: Path,
        selected: list[DifficultyName],
        final_map_kinds: dict[DifficultyName, str],
    ) -> None:
        creator = manifest.metadata.creator or self.config.default_creator
        background_filename = (
            manifest.background.normalized_filename if manifest.background else None
        )
        if paths.exports_osu_dir.exists():
            for file_path in paths.exports_osu_dir.glob("*.osu"):
                file_path.unlink(missing_ok=True)
        for difficulty in selected:
            final_kind = final_map_kinds[difficulty]
            version_name = self._version_name_for_kind(final_kind, difficulty)
            output_path = paths.exports_osu_dir / self._build_osu_filename(
                manifest.metadata.artist,
                manifest.metadata.title,
                creator,
                version_name,
            )
            export_osu_file(
                map_path=self._map_path_for_kind(paths, final_kind, difficulty),
                analysis_path=analysis_path,
                output_path=output_path,
                report_output_path=paths.export_reports_dir / f"{output_path.stem}-export.json",
                creator=creator,
                version_name=version_name,
                background_filename=background_filename,
                title_unicode=manifest.metadata.title_unicode,
                artist_unicode=manifest.metadata.artist_unicode,
            )

    def _package_mapset(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
    ) -> None:
        if manifest.audio is None:
            raise LocalApiValidationError("Workspace audio is missing.")
        mapset_name = build_mapset_filename(
            manifest.metadata.artist,
            manifest.metadata.title,
        )
        mapset_directory = paths.exports_mapset_root / mapset_name
        if mapset_directory.exists():
            shutil.rmtree(mapset_directory)
        mapset_directory.mkdir(parents=True, exist_ok=True)
        audio_source = self.workspace_manager.resolve_audio_source_path(manifest)
        audio_copy = mapset_directory / manifest.audio.normalized_filename
        copy_file(audio_source, audio_copy)
        background_copy: Path | None = None
        if manifest.background is not None:
            background_source = self.workspace_manager.resolve_background_source_path(
                manifest
            )
            background_copy = mapset_directory / manifest.background.normalized_filename
            copy_file(background_source, background_copy)
        for osu_file in sorted(paths.exports_osu_dir.glob("*.osu")):
            copy_file(osu_file, mapset_directory / osu_file.name)
        package_path = paths.exports_mapsets_dir / f"{mapset_name}.osz"
        package_osz_archive(
            maps_dir=mapset_directory,
            audio_path=audio_copy,
            output_path=package_path,
            background_path=background_copy,
        )

    def _verify_package_contents(
        self,
        manifest: WorkspaceManifest,
        paths: WorkspacePaths,
        selected: list[DifficultyName],
    ) -> None:
        mapset_name = build_mapset_filename(
            manifest.metadata.artist,
            manifest.metadata.title,
        )
        package_path = paths.exports_mapsets_dir / f"{mapset_name}.osz"
        if not package_path.exists():
            raise LocalApiValidationError("Final .osz package is missing.")
        with zipfile.ZipFile(package_path, "r") as archive:
            names = archive.namelist()
        if manifest.audio is None or manifest.audio.normalized_filename not in names:
            raise LocalApiValidationError("Final package is missing the audio file.")
        osu_names = [name for name in names if name.lower().endswith(".osu")]
        if len(osu_names) != len(selected):
            raise LocalApiValidationError("Final package does not contain the selected number of .osu files.")
        forbidden = [
            name
            for name in names
            if name.endswith(".json")
            or "candidate" in name.lower()
            or "report" in name.lower()
            or name.startswith(".")
        ]
        if forbidden:
            raise LocalApiValidationError(
                "Final package contains temporary or non-export artifacts."
            )

    def _map_path_for_kind(self, paths: WorkspacePaths, kind: str, difficulty: DifficultyName) -> Path:
        if kind == "hybrid":
            return paths.hybrid_maps_dir / f"{difficulty}.json"
        if kind == "champion":
            return paths.champion_maps_dir / f"{difficulty}.json"
        if kind == "improved":
            return paths.improved_maps_dir / f"{difficulty}.json"
        return paths.generated_maps_dir / f"{difficulty}.json"

    def _report_path_for_kind(self, paths: WorkspacePaths, kind: str, difficulty: DifficultyName) -> Path:
        if kind == "hybrid":
            return paths.hybrid_reports_dir / f"{difficulty}-report.json"
        if kind == "champion":
            return paths.champion_reports_dir / f"{difficulty}-report.json"
        if kind == "improved":
            return paths.improved_reports_dir / f"{difficulty}-report.json"
        return paths.generated_reports_dir / f"{difficulty}-report.json"

    def _version_name_for_kind(self, kind: str, difficulty: DifficultyName) -> str:
        capitalized = difficulty.capitalize()
        if kind == "hybrid":
            return f"Hybrid {capitalized}"
        return capitalized

    def _build_final_map_kinds(self, manifest: WorkspaceManifest) -> dict[DifficultyName, str]:
        output: dict[DifficultyName, str] = {}
        for difficulty in manifest.metadata.selected_difficulties:
            settings = manifest.metadata.difficulty_settings[difficulty]
            if settings.hybrid_assembly_enabled:
                output[difficulty] = "hybrid"
            elif settings.tournament_enabled:
                output[difficulty] = "champion"
            else:
                output[difficulty] = "improved"
        return output

    def _build_osu_filename(
        self,
        artist: str,
        title: str,
        creator: str,
        version_name: str,
    ) -> str:
        return build_osu_filename(artist, title, creator, version_name)

    def _song_slug(self, manifest: WorkspaceManifest) -> str:
        source = sanitize_filename_component(
            f"{manifest.metadata.artist}-{manifest.metadata.title}",
            fallback=manifest.workspace_id,
        )
        return source.lower().replace(" ", "-")

    def _append_log(self, log_path: Path, message: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(message.rstrip() + "\n")

    def _can_reuse(self, manifest: WorkspaceManifest, *paths: Path) -> bool:
        return (
            manifest.configuration_signature is not None
            and manifest.last_run_signature == manifest.configuration_signature
            and all(path.exists() for path in paths)
        )

    def _check_cancellation(self, job_manager, job_id: str) -> None:
        if job_manager.is_cancel_requested(job_id):
            raise LocalApiCancellationRequested("Job cancellation was requested.")

    def _clear_previous_outputs(self, paths: WorkspacePaths) -> None:
        output_directories = [
            paths.analysis_dir,
            paths.generated_maps_dir,
            paths.improved_maps_dir,
            paths.champion_maps_dir,
            paths.hybrid_maps_dir,
            paths.generated_reports_dir,
            paths.improved_reports_dir,
            paths.champion_reports_dir,
            paths.hybrid_reports_dir,
            paths.corrections_dir,
            paths.tournaments_dir,
            paths.evolution_reports_dir,
            paths.section_reports_root,
            paths.sections_dir,
            paths.hybrid_details_dir,
            paths.candidates_root,
            paths.exports_dir,
        ]
        for directory in output_directories:
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
