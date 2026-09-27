from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import LocalApiConfig
from .errors import LocalApiNotFoundError
from .models import (
    ArtifactDescriptor,
    ArtifactGroup,
    FinalDifficultyResult,
    JobResultSummary,
    WorkspaceManifest,
)
from .security import guess_content_type
from .workspace_manager import WorkspaceManager


class ArtifactService:
    def __init__(
        self,
        config: LocalApiConfig,
        workspace_manager: WorkspaceManager,
    ) -> None:
        self.config = config
        self.workspace_manager = workspace_manager

    def build_audio_preview_url(self, workspace_id: str, filename: str) -> str:
        return f"{self.config.api_prefix}/workspaces/{workspace_id}/source-audio/{filename}"

    def refresh_workspace_artifacts(self, manifest: WorkspaceManifest) -> WorkspaceManifest:
        paths = self.workspace_manager.ensure_workspace_exists(manifest.workspace_id)
        items: list[ArtifactDescriptor] = []
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Analysis",
                "analysis-json",
                paths.analysis_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Analysis",
                "section-analysis",
                paths.sections_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Generated maps",
                "beatmap-json",
                paths.generated_maps_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Improved maps",
                "beatmap-json",
                paths.improved_maps_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Champion maps",
                "beatmap-json",
                paths.champion_maps_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Hybrid maps",
                "beatmap-json",
                paths.hybrid_maps_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Difficulty reports",
                "difficulty-report",
                paths.difficulty_reports_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Evolution reports",
                "evolution-report",
                paths.evolution_reports_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Validation reports",
                "report-json",
                paths.reports_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                ".osu files",
                "osu-file",
                paths.exports_osu_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                ".osz package",
                "osz-file",
                paths.exports_mapsets_dir,
            )
        )
        items.extend(
            self._scan_group(
                manifest.workspace_id,
                "Logs",
                "log-file",
                paths.logs_dir,
            )
        )
        refreshed = manifest.model_copy(update={"available_artifacts": items}, deep=True)
        return self.workspace_manager.save_manifest(refreshed)

    def list_artifact_groups(self, manifest: WorkspaceManifest) -> list[ArtifactGroup]:
        grouped: dict[str, list[ArtifactDescriptor]] = {}
        for item in manifest.available_artifacts:
            grouped.setdefault(item.group, []).append(item)
        return [
            ArtifactGroup(group=group, items=items)
            for group, items in grouped.items()
            if items
        ]

    def resolve_artifact(self, artifact_id: str) -> tuple[WorkspaceManifest, ArtifactDescriptor, Path]:
        workspace_id, _ = self._split_artifact_id(artifact_id)
        manifest = self.workspace_manager.load_manifest(workspace_id)
        artifact = next((item for item in manifest.available_artifacts if item.id == artifact_id), None)
        if artifact is None:
            raise LocalApiNotFoundError("Artifact was not found.")
        file_path = self.workspace_manager.resolve_relative_path(
            workspace_id,
            artifact.relative_path,
        )
        if not file_path.exists() or not file_path.is_file():
            raise LocalApiNotFoundError("Artifact file is missing on disk.")
        return manifest, artifact, file_path

    def build_result_summary(self, manifest: WorkspaceManifest) -> JobResultSummary | None:
        selected = manifest.metadata.selected_difficulties
        if not selected:
            return None
        paths = self.workspace_manager.ensure_workspace_exists(manifest.workspace_id)
        difficulty_results: list[FinalDifficultyResult] = []
        for difficulty in selected:
            final_kind = self._pick_final_map_kind(paths, difficulty)
            if final_kind is None:
                continue
            map_path = self._map_path_for_kind(paths, final_kind, difficulty)
            report_path = self._report_path_for_kind(paths, final_kind, difficulty)
            object_count = self._read_object_count(map_path)
            score = self._read_report_score(report_path)
            candidate_winner = self._read_candidate_winner(paths, difficulty)
            section_count = self._read_section_count(paths)
            phrase_count = self._read_phrase_count(paths)
            recovery = self._read_recovery_summary(paths, difficulty)
            promoted = self._read_hybrid_promoted(paths, difficulty) if final_kind == "hybrid" else None
            map_artifact_id = self._find_artifact_id(
                manifest.available_artifacts,
                map_path.relative_to(paths.root).as_posix(),
            )
            osu_artifact_id = next(
                (
                    item.id
                    for item in manifest.available_artifacts
                    if item.group == ".osu files" and item.difficulty == difficulty
                ),
                None,
            )
            difficulty_results.append(
                FinalDifficultyResult(
                    difficulty=difficulty,
                    finalMapKind=final_kind,
                    objectCount=object_count,
                    score=score,
                    candidateWinner=candidate_winner,
                    sectionCount=section_count,
                    phraseCount=phrase_count,
                    promoted=promoted,
                    mapArtifactId=map_artifact_id,
                    osuArtifactId=osu_artifact_id,
                    spinnerCount=(
                        recovery["spinnerCount"] if recovery is not None else None
                    ),
                    avgSpinnerDurationMs=(
                        recovery["avgSpinnerDurationMs"]
                        if recovery is not None
                        else None
                    ),
                    fatiguePeak=(
                        recovery["fatiguePeak"] if recovery is not None else None
                    ),
                    recoveryWindowCount=(
                        recovery["recoveryWindowCount"]
                        if recovery is not None
                        else None
                    ),
                )
            )
        package_artifact = next(
            (item for item in manifest.available_artifacts if item.group == ".osz package"),
            None,
        )
        detected_duration = (
            manifest.audio.detected_metadata.duration_ms
            if manifest.audio and manifest.audio.detected_metadata
            else None
        )
        return JobResultSummary(
            title=manifest.metadata.title,
            artist=manifest.metadata.artist,
            audioDurationMs=detected_duration,
            selectedDifficulties=selected,
            packageArtifactId=package_artifact.id if package_artifact else None,
            packageSizeBytes=package_artifact.size_bytes if package_artifact else None,
            sectionCount=self._read_section_count(paths),
            phraseCount=self._read_phrase_count(paths),
            difficulties=difficulty_results,
        )

    def _scan_group(
        self,
        workspace_id: str,
        group: str,
        kind: str,
        directory: Path,
    ) -> list[ArtifactDescriptor]:
        if not directory.exists():
            return []
        items: list[ArtifactDescriptor] = []
        workspace_root = self.workspace_manager.get_workspace_paths(workspace_id).root
        for file_path in sorted(directory.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(workspace_root).as_posix()
            difficulty = _infer_difficulty(file_path.stem)
            items.append(
                ArtifactDescriptor(
                    id=self._build_artifact_id(workspace_id, relative_path),
                    workspaceId=workspace_id,
                    group=group,
                    kind=kind,
                    label=file_path.name,
                    relativePath=relative_path,
                    fileName=file_path.name,
                    contentType=guess_content_type(file_path),
                    sizeBytes=file_path.stat().st_size,
                    difficulty=difficulty,
                    downloadUrl=f"{self.config.api_prefix}/artifacts/{self._build_artifact_id(workspace_id, relative_path)}/download",
                )
            )
        return items

    def _build_artifact_id(self, workspace_id: str, relative_path: str) -> str:
        digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:16]
        return f"{workspace_id}:{digest}"

    def _split_artifact_id(self, artifact_id: str) -> tuple[str, str]:
        workspace_id, _, digest = artifact_id.partition(":")
        if not workspace_id or not digest:
            raise LocalApiNotFoundError("Artifact ID is invalid.")
        return workspace_id, digest

    def _pick_final_map_kind(self, paths, difficulty: str) -> str | None:
        if self._map_path_for_kind(paths, "hybrid", difficulty).exists():
            return "hybrid"
        if self._map_path_for_kind(paths, "champion", difficulty).exists():
            return "champion"
        if self._map_path_for_kind(paths, "improved", difficulty).exists():
            return "improved"
        if self._map_path_for_kind(paths, "generated", difficulty).exists():
            return "generated"
        return None

    def _map_path_for_kind(self, paths, kind: str, difficulty: str) -> Path:
        if kind == "hybrid":
            return paths.hybrid_maps_dir / f"{difficulty}.json"
        if kind == "champion":
            return paths.champion_maps_dir / f"{difficulty}.json"
        if kind == "improved":
            return paths.improved_maps_dir / f"{difficulty}.json"
        return paths.generated_maps_dir / f"{difficulty}.json"

    def _report_path_for_kind(self, paths, kind: str, difficulty: str) -> Path:
        if kind == "hybrid":
            return paths.hybrid_reports_dir / f"{difficulty}-report.json"
        if kind == "champion":
            return paths.champion_reports_dir / f"{difficulty}-report.json"
        if kind == "improved":
            return paths.improved_reports_dir / f"{difficulty}-report.json"
        return paths.generated_reports_dir / f"{difficulty}-report.json"

    def _find_artifact_id(
        self,
        artifacts: list[ArtifactDescriptor],
        relative_path: str,
    ) -> str | None:
        for item in artifacts:
            if item.relative_path == relative_path:
                return item.id
        return None

    def _read_object_count(self, map_path: Path) -> int | None:
        if not map_path.exists():
            return None
        try:
            payload = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        objects = payload.get("objects")
        return len(objects) if isinstance(objects, list) else None

    def _read_report_score(self, report_path: Path) -> float | None:
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        scores = payload.get("scores")
        if isinstance(scores, dict) and isinstance(scores.get("overall"), (int, float)):
            return float(scores["overall"])
        return None

    def _read_candidate_winner(self, paths, difficulty: str) -> int | None:
        evolution_path = paths.evolution_reports_dir / f"{difficulty}-evolution.json"
        if evolution_path.exists():
            try:
                payload = json.loads(evolution_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
            else:
                champion = payload.get("champion")
                if isinstance(champion, dict) and isinstance(champion.get("candidateIndex"), (int, float)):
                    return int(champion["candidateIndex"])
        tournament_path = paths.tournaments_dir / f"{difficulty}-tournament.json"
        if not tournament_path.exists():
            return None
        try:
            payload = json.loads(tournament_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        champion = payload.get("champion")
        if isinstance(champion, dict) and isinstance(champion.get("candidateIndex"), (int, float)):
            return int(champion["candidateIndex"])
        return None

    def _read_section_count(self, paths) -> int | None:
        report_path = paths.sections_dir / "sections.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        sections = payload.get("sections")
        return len(sections) if isinstance(sections, list) else None

    def _read_phrase_count(self, paths) -> int | None:
        report_path = paths.sections_dir / "phrase-structure.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        phrases = payload.get("phrases")
        return len(phrases) if isinstance(phrases, list) else None

    def _read_recovery_summary(self, paths, difficulty: str) -> dict[str, Any] | None:
        report_path = paths.sections_dir / f"recovery-{difficulty}.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        fatigue = payload.get("fatigue") if isinstance(payload.get("fatigue"), dict) else {}
        windows = payload.get("recoveryWindows")
        return {
            "spinnerCount": (
                int(payload["spinnerCount"])
                if isinstance(payload.get("spinnerCount"), (int, float))
                else None
            ),
            "avgSpinnerDurationMs": (
                float(payload["avgSpinnerDurationMs"])
                if isinstance(payload.get("avgSpinnerDurationMs"), (int, float))
                else None
            ),
            "fatiguePeak": (
                float(fatigue["peakFatigue"])
                if isinstance(fatigue.get("peakFatigue"), (int, float))
                else None
            ),
            "recoveryWindowCount": len(windows) if isinstance(windows, list) else None,
        }

    def _read_hybrid_promoted(self, paths, difficulty: str) -> bool | None:
        report_path = paths.hybrid_details_dir / f"{difficulty}-assembly.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        promotion = payload.get("promotion")
        if isinstance(promotion, dict) and isinstance(promotion.get("promoted"), bool):
            return promotion["promoted"]
        return None


def _infer_difficulty(stem: str) -> str | None:
    lowered = stem.lower()
    if "easy" in lowered:
        return "easy"
    if "normal" in lowered:
        return "normal"
    if "hard" in lowered:
        return "hard"
    return None
