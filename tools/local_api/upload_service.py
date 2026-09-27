from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import UploadFile

from .config import LocalApiConfig
from .errors import LocalApiPayloadTooLargeError, LocalApiValidationError
from .metadata_service import MetadataService
from .models import UploadedFileDescriptor, WorkspaceManifest
from .security import ensure_allowed_extension, sha256_hex
from .workspace_manager import WorkspaceManager


class UploadService:
    def __init__(
        self,
        config: LocalApiConfig,
        workspace_manager: WorkspaceManager,
        metadata_service: MetadataService,
    ) -> None:
        self.config = config
        self.workspace_manager = workspace_manager
        self.metadata_service = metadata_service

    def save_audio(self, workspace_id: str, upload_file: UploadFile) -> WorkspaceManifest:
        suffix = ensure_allowed_extension(
            upload_file.filename or "",
            self.config.allowed_audio_extensions,
        )
        manifest = self.workspace_manager.load_manifest(workspace_id)
        paths = self.workspace_manager.ensure_workspace_exists(workspace_id)
        normalized_name = f"source-audio{suffix}"
        destination = paths.source_dir / normalized_name
        detected_metadata = self._write_upload_file(
            upload_file,
            destination,
            self.config.max_audio_upload_bytes,
            "audio upload",
            expect_audio=True,
        )
        self._delete_previous_file(paths.source_dir, "source-audio", exclude=destination)
        descriptor = UploadedFileDescriptor(
            originalFilename=upload_file.filename or normalized_name,
            normalizedFilename=normalized_name,
            relativePath=f"source/{normalized_name}",
            sizeBytes=destination.stat().st_size,
            contentType=upload_file.content_type or "application/octet-stream",
            sha256=sha256_hex(destination),
            detectedMetadata=detected_metadata,
        )
        updated = manifest.model_copy(
            update={
                "audio": descriptor,
                "configuration_signature": None,
            },
            deep=True,
        )
        updated = updated.model_copy(
            update={
                "configuration_signature": self.metadata_service.compute_configuration_signature(
                    updated
                )
            },
            deep=True,
        )
        return self.workspace_manager.save_manifest(updated)

    def save_background(self, workspace_id: str, upload_file: UploadFile) -> WorkspaceManifest:
        suffix = ensure_allowed_extension(
            upload_file.filename or "",
            self.config.allowed_background_extensions,
        )
        manifest = self.workspace_manager.load_manifest(workspace_id)
        paths = self.workspace_manager.ensure_workspace_exists(workspace_id)
        normalized_name = f"background{suffix}"
        destination = paths.source_dir / normalized_name
        self._write_upload_file(
            upload_file,
            destination,
            self.config.max_background_upload_bytes,
            "background upload",
            expect_audio=False,
        )
        self._delete_previous_file(paths.source_dir, "background", exclude=destination)
        descriptor = UploadedFileDescriptor(
            originalFilename=upload_file.filename or normalized_name,
            normalizedFilename=normalized_name,
            relativePath=f"source/{normalized_name}",
            sizeBytes=destination.stat().st_size,
            contentType=upload_file.content_type or "application/octet-stream",
            sha256=sha256_hex(destination),
            detectedMetadata=None,
        )
        metadata = manifest.metadata.model_copy(
            update={"background_filename": normalized_name},
            deep=True,
        )
        updated = manifest.model_copy(
            update={
                "background": descriptor,
                "metadata": metadata,
                "configuration_signature": None,
            },
            deep=True,
        )
        updated = updated.model_copy(
            update={
                "configuration_signature": self.metadata_service.compute_configuration_signature(
                    updated
                )
            },
            deep=True,
        )
        return self.workspace_manager.save_manifest(updated)

    def _write_upload_file(
        self,
        upload_file: UploadFile,
        destination: Path,
        max_size_bytes: int,
        label: str,
        *,
        expect_audio: bool,
    ):
        if not upload_file.filename or not upload_file.filename.strip():
            raise LocalApiValidationError(f"{label.capitalize()} filename is required.")
        temporary_path: Path | None = None
        total_size = 0
        detected_metadata = None
        try:
            with NamedTemporaryFile(delete=False, dir=destination.parent) as temp_handle:
                temporary_path = Path(temp_handle.name)
                while True:
                    chunk = upload_file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_size_bytes:
                        raise LocalApiPayloadTooLargeError(
                            f"{label.capitalize()} exceeds the configured size limit."
                        )
                    temp_handle.write(chunk)
            if total_size <= 0:
                raise LocalApiValidationError(f"{label.capitalize()} must not be empty.")
            if expect_audio:
                detected_metadata = self.metadata_service.extract_audio_metadata(temporary_path)
            os.replace(temporary_path, destination)
            temporary_path = None
            return detected_metadata
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
            upload_file.file.close()

    def _delete_previous_file(
        self,
        directory: Path,
        stem_prefix: str,
        *,
        exclude: Path | None = None,
    ) -> None:
        for existing in directory.glob(f"{stem_prefix}.*"):
            if exclude is not None and existing.resolve() == exclude.resolve():
                continue
            existing.unlink(missing_ok=True)
