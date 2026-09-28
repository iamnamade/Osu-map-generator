from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import LocalApiConfig
from .errors import LocalApiNotFoundError, LocalApiValidationError
from .models import (
    UploadedFileDescriptor,
    WorkspaceManifest,
    build_default_workspace_metadata,
)
from .security import generate_workspace_id, resolve_workspace_relative_path, validate_workspace_id


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    source_dir: Path
    analysis_dir: Path
    maps_dir: Path
    generated_maps_dir: Path
    improved_maps_dir: Path
    champion_maps_dir: Path
    hybrid_maps_dir: Path
    reports_dir: Path
    generated_reports_dir: Path
    improved_reports_dir: Path
    champion_reports_dir: Path
    hybrid_reports_dir: Path
    corrections_dir: Path
    tournaments_dir: Path
    section_reports_root: Path
    sections_dir: Path
    hybrid_details_dir: Path
    candidates_root: Path
    exports_dir: Path
    exports_osu_dir: Path
    exports_mapset_root: Path
    exports_mapsets_dir: Path
    logs_dir: Path
    export_reports_dir: Path
    difficulty_reports_dir: Path
    evolution_reports_dir: Path
    manifest_path: Path

    def difficulty_candidates_dir(self, difficulty: str) -> Path:
        return self.candidates_root / difficulty

    def difficulty_section_reports_dir(self, difficulty: str) -> Path:
        return self.section_reports_root / difficulty


class WorkspaceManager:
    def __init__(self, config: LocalApiConfig) -> None:
        self.config = config
        self.config.workspaces_root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self) -> WorkspaceManifest:
        workspace_id = generate_workspace_id()
        paths = self.get_workspace_paths(workspace_id)
        self._ensure_directory_tree(paths)
        now = datetime.now(UTC)
        manifest = WorkspaceManifest(
            workspaceId=workspace_id,
            createdAt=now,
            updatedAt=now,
            metadata=build_default_workspace_metadata(),
        )
        self.save_manifest(manifest)
        return manifest

    def get_workspace_paths(self, workspace_id: str) -> WorkspacePaths:
        normalized_id = validate_workspace_id(workspace_id)
        root = self.config.workspaces_root / normalized_id
        return WorkspacePaths(
            root=root,
            source_dir=root / "source",
            analysis_dir=root / "analysis",
            maps_dir=root / "maps",
            generated_maps_dir=root / "maps" / "generated",
            improved_maps_dir=root / "maps" / "improved",
            champion_maps_dir=root / "maps" / "champions",
            hybrid_maps_dir=root / "maps" / "hybrid",
            reports_dir=root / "reports",
            generated_reports_dir=root / "reports" / "generated",
            improved_reports_dir=root / "reports" / "improved",
            champion_reports_dir=root / "reports" / "champions",
            hybrid_reports_dir=root / "reports" / "hybrid",
            corrections_dir=root / "reports" / "corrections",
            tournaments_dir=root / "reports" / "tournaments",
            section_reports_root=root / "reports" / "sections",
            sections_dir=root / "sections",
            hybrid_details_dir=root / "hybrids",
            candidates_root=root / "candidates",
            exports_dir=root / "exports",
            exports_osu_dir=root / "exports" / "osu",
            exports_mapset_root=root / "exports" / "mapset",
            exports_mapsets_dir=root / "exports" / "mapsets",
            logs_dir=root / "logs",
            export_reports_dir=root / "reports" / "exports",
            difficulty_reports_dir=root / "reports" / "difficulty",
            evolution_reports_dir=root / "reports" / "evolution",
            manifest_path=root / "workspace.json",
        )

    def ensure_workspace_exists(self, workspace_id: str) -> WorkspacePaths:
        paths = self.get_workspace_paths(workspace_id)
        if not paths.root.exists():
            raise LocalApiNotFoundError(f"Workspace {workspace_id} was not found.")
        return paths

    def load_manifest(self, workspace_id: str) -> WorkspaceManifest:
        paths = self.ensure_workspace_exists(workspace_id)
        if not paths.manifest_path.exists():
            raise LocalApiNotFoundError(f"Workspace manifest is missing for {workspace_id}.")
        try:
            raw_payload = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise LocalApiValidationError(
                f"Workspace manifest is malformed for {workspace_id}: {error.msg}"
            ) from error
        return WorkspaceManifest.model_validate(raw_payload)

    def save_manifest(self, manifest: WorkspaceManifest) -> WorkspaceManifest:
        paths = self.get_workspace_paths(manifest.workspace_id)
        self._ensure_directory_tree(paths)
        updated_manifest = manifest.model_copy(
            update={"updated_at": datetime.now(UTC)},
            deep=True,
        )
        payload = (
            updated_manifest.model_dump_json(
                indent=2,
                by_alias=True,
                exclude_none=True,
            )
            + "\n"
        )
        # P2.3: write atomically (temp file in the same directory + os.replace)
        # so a crash or a concurrent read/update can never observe a truncated
        # or half-written manifest.
        _atomic_write_text(paths.manifest_path, payload)
        return updated_manifest

    def resolve_relative_path(self, workspace_id: str, relative_path: str) -> Path:
        paths = self.ensure_workspace_exists(workspace_id)
        return resolve_workspace_relative_path(paths.root, relative_path)

    def resolve_audio_source_path(self, manifest: WorkspaceManifest) -> Path:
        return self._resolve_uploaded_file_path(
            manifest,
            manifest.audio,
            label="audio",
            allowed_extensions=self.config.allowed_audio_extensions,
        )

    def resolve_background_source_path(self, manifest: WorkspaceManifest) -> Path:
        return self._resolve_uploaded_file_path(
            manifest,
            manifest.background,
            label="background",
            allowed_extensions=self.config.allowed_background_extensions,
        )

    def delete_workspace(self, workspace_id: str) -> None:
        paths = self.ensure_workspace_exists(workspace_id)
        for path in sorted(paths.root.glob("**/*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
        for path in sorted(paths.root.glob("**/*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
        paths.root.rmdir()

    def _resolve_uploaded_file_path(
        self,
        manifest: WorkspaceManifest,
        descriptor: UploadedFileDescriptor | None,
        *,
        label: str,
        allowed_extensions: tuple[str, ...],
    ) -> Path:
        if descriptor is None:
            raise LocalApiValidationError(f"Workspace {label} is missing.")
        normalized_filename = descriptor.normalized_filename.strip()
        if not normalized_filename:
            raise LocalApiValidationError(f"Workspace {label} filename is missing.")
        if Path(normalized_filename).name != normalized_filename:
            raise LocalApiValidationError(f"Workspace {label} filename is invalid.")
        resolved_path = self.resolve_relative_path(manifest.workspace_id, descriptor.relative_path)
        if resolved_path.name != normalized_filename:
            raise LocalApiValidationError(
                f"Workspace {label} path does not match the registered filename."
            )
        if resolved_path.suffix.lower() not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise LocalApiValidationError(f"Workspace {label} must use one of: {allowed}")
        if not resolved_path.exists():
            raise LocalApiValidationError(f"Workspace {label} file is missing.")
        if not resolved_path.is_file():
            raise LocalApiValidationError(f"Workspace {label} path is not a file.")
        try:
            mode = resolved_path.stat().st_mode
        except OSError as error:
            raise LocalApiValidationError(
                f"Workspace {label} file could not be read: {error}"
            ) from error
        if not stat.S_ISREG(mode):
            raise LocalApiValidationError(f"Workspace {label} path is not a regular file.")
        return resolved_path

    def _ensure_directory_tree(self, paths: WorkspacePaths) -> None:
        directories = [
            paths.root,
            paths.source_dir,
            paths.analysis_dir,
            paths.maps_dir,
            paths.generated_maps_dir,
            paths.improved_maps_dir,
            paths.champion_maps_dir,
            paths.hybrid_maps_dir,
            paths.reports_dir,
            paths.generated_reports_dir,
            paths.improved_reports_dir,
            paths.champion_reports_dir,
            paths.hybrid_reports_dir,
            paths.corrections_dir,
            paths.tournaments_dir,
            paths.section_reports_root,
            paths.sections_dir,
            paths.hybrid_details_dir,
            paths.candidates_root,
            paths.exports_dir,
            paths.exports_osu_dir,
            paths.exports_mapset_root,
            paths.exports_mapsets_dir,
            paths.logs_dir,
            paths.export_reports_dir,
            paths.difficulty_reports_dir,
            paths.evolution_reports_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via a sibling temp file.

    ``os.replace`` is atomic on the same filesystem, so readers see either the
    old complete file or the new complete file, never a partial write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
