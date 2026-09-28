from __future__ import annotations

import argparse
from functools import lru_cache

import uvicorn
from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from .artifact_service import ArtifactService
from .cleanup_service import CleanupService
from .config import get_local_api_config
from .errors import LocalApiError, LocalApiNotFoundError
from .job_manager import JobManager
from .metadata_service import MetadataService
from .models import (
    AudioMetadataSuggestion,
    AudioUploadResponse,
    BackgroundUploadResponse,
    HealthResponse,
    WorkspaceManifest,
    WorkspaceResponse,
)
from .pipeline_runner import PipelineRunner
from .upload_service import UploadService
from .workspace_manager import WorkspaceManager


@lru_cache(maxsize=1)
def _services():
    config = get_local_api_config()
    workspace_manager = WorkspaceManager(config)
    metadata_service = MetadataService(config)
    artifact_service = ArtifactService(config, workspace_manager)
    upload_service = UploadService(config, workspace_manager, metadata_service)
    pipeline_runner = PipelineRunner(
        config,
        workspace_manager,
        metadata_service,
        artifact_service,
    )
    job_manager = JobManager(workspace_manager, artifact_service, pipeline_runner)
    cleanup_service = CleanupService(workspace_manager, job_manager)
    return {
        "config": config,
        "workspace_manager": workspace_manager,
        "metadata_service": metadata_service,
        "artifact_service": artifact_service,
        "upload_service": upload_service,
        "pipeline_runner": pipeline_runner,
        "job_manager": job_manager,
        "cleanup_service": cleanup_service,
    }


def create_app() -> FastAPI:
    services = _services()
    config = services["config"]
    workspace_manager = services["workspace_manager"]
    metadata_service = services["metadata_service"]
    artifact_service = services["artifact_service"]
    upload_service = services["upload_service"]
    job_manager = services["job_manager"]
    cleanup_service = services["cleanup_service"]

    app = FastAPI(title="Pulse Practice Local API", version="1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_vite_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # P0.2 (Phase 6 roadmap): boot reconciliation. Job records are in-memory
    # only, so any workspace manifest still flagged queued/running at startup
    # is an orphan from a previous process. Flip them to failed so cleanup
    # tooling can remove them again.
    recovered = cleanup_service.recover_orphaned_workspaces()
    if recovered:
        import logging

        logging.getLogger(__name__).warning(
            "Boot reconciliation marked %d orphaned running workspace(s) as failed: %s",
            len(recovered),
            ", ".join(recovered),
        )

    @app.exception_handler(LocalApiError)
    async def handle_local_api_error(_, error: LocalApiError):
        return JSONResponse(
            status_code=error.status_code,
            content=error.to_response_content(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ):
        return JSONResponse(
            status_code=422,
            content={"detail": build_validation_detail(request.url.path, error.errors())},
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, error: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": build_validation_detail(request.url.path, error.errors())},
        )

    @app.get(f"{config.api_prefix}/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(status="ok", version=1, pipelineAvailable=True)

    @app.post(f"{config.api_prefix}/workspaces", response_model=WorkspaceResponse)
    async def create_workspace():
        manifest = workspace_manager.create_workspace()
        return build_workspace_response(
            artifact_service,
            metadata_service,
            manifest,
        )

    @app.get(f"{config.api_prefix}/workspaces/{{workspace_id}}", response_model=WorkspaceResponse)
    async def get_workspace(workspace_id: str):
        manifest = workspace_manager.load_manifest(workspace_id)
        return build_workspace_response(
            artifact_service,
            metadata_service,
            manifest,
        )

    @app.post(
        f"{config.api_prefix}/workspaces/{{workspace_id}}/audio",
        response_model=AudioUploadResponse,
    )
    async def upload_audio(workspace_id: str, file: UploadFile = File(...)):
        manifest = upload_service.save_audio(workspace_id, file)
        response = build_workspace_response(
            artifact_service,
            metadata_service,
            manifest,
        )
        return AudioUploadResponse(
            workspace=response.workspace,
            artifacts=response.artifacts,
            readyForGeneration=response.ready_for_generation,
            detectedMetadata=(
                response.workspace.audio.detected_metadata
                if response.workspace.audio and response.workspace.audio.detected_metadata
                else AudioMetadataSuggestion()
            ),
        )

    @app.post(
        f"{config.api_prefix}/workspaces/{{workspace_id}}/background",
        response_model=BackgroundUploadResponse,
    )
    async def upload_background(workspace_id: str, file: UploadFile = File(...)):
        manifest = upload_service.save_background(workspace_id, file)
        response = build_workspace_response(
            artifact_service,
            metadata_service,
            manifest,
        )
        return BackgroundUploadResponse(
            workspace=response.workspace,
            artifacts=response.artifacts,
            readyForGeneration=response.ready_for_generation,
        )

    @app.put(
        f"{config.api_prefix}/workspaces/{{workspace_id}}/metadata",
        response_model=WorkspaceResponse,
    )
    async def update_metadata(workspace_id: str, payload: dict = Body(...)):
        manifest = workspace_manager.load_manifest(workspace_id)
        metadata = metadata_service.parse_metadata_payload(payload)
        updated = metadata_service.update_metadata(manifest, metadata)
        updated = workspace_manager.save_manifest(updated)
        return build_workspace_response(
            artifact_service,
            metadata_service,
            updated,
        )

    @app.post(f"{config.api_prefix}/workspaces/{{workspace_id}}/generate")
    async def start_generation(workspace_id: str):
        manifest = workspace_manager.load_manifest(workspace_id)
        if manifest.audio is not None:
            audio_path = workspace_manager.resolve_relative_path(
                workspace_id,
                manifest.audio.relative_path,
            )
            if not audio_path.exists():
                raise LocalApiNotFoundError("Uploaded audio file is missing from the workspace.")
        metadata_service.validate_generation_ready(manifest)
        return job_manager.create_job(workspace_id)

    @app.get(f"{config.api_prefix}/jobs/{{job_id}}")
    async def get_job(job_id: str):
        return job_manager.get_job(job_id)

    @app.get(f"{config.api_prefix}/jobs/{{job_id}}/events")
    async def stream_job_events(job_id: str):
        return StreamingResponse(
            job_manager.stream_events(job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post(f"{config.api_prefix}/jobs/{{job_id}}/cancel")
    async def cancel_job(job_id: str):
        return job_manager.request_cancel(job_id)

    @app.get(f"{config.api_prefix}/workspaces/{{workspace_id}}/artifacts")
    async def list_artifacts(workspace_id: str):
        manifest = artifact_service.refresh_workspace_artifacts(
            workspace_manager.load_manifest(workspace_id)
        )
        return {
            "workspaceId": workspace_id,
            "artifacts": artifact_service.list_artifact_groups(manifest),
        }

    @app.get(f"{config.api_prefix}/artifacts/{{artifact_id}}/download")
    async def download_artifact(artifact_id: str):
        _, artifact, file_path = artifact_service.resolve_artifact(artifact_id)
        return FileResponse(
            file_path,
            media_type=artifact.content_type,
            filename=artifact.file_name,
        )

    @app.get(f"{config.api_prefix}/workspaces/{{workspace_id}}/source-audio/{{filename}}")
    async def preview_audio(workspace_id: str, filename: str):
        manifest = workspace_manager.load_manifest(workspace_id)
        if manifest.audio is None or filename != manifest.audio.normalized_filename:
            raise LocalApiNotFoundError("Audio preview file was not found.")
        file_path = workspace_manager.resolve_relative_path(
            workspace_id,
            manifest.audio.relative_path,
        )
        return FileResponse(
            file_path,
            media_type=manifest.audio.content_type,
            filename=manifest.audio.normalized_filename,
        )

    @app.get(
        f"{config.api_prefix}/workspaces/{{workspace_id}}"
        "/preview-background/{filename}"
    )
    async def preview_background(workspace_id: str, filename: str):
        # P1.1: mirror preview_audio so the background preview survives a page
        # reload instead of relying on a short-lived client-side blob URL.
        manifest = workspace_manager.load_manifest(workspace_id)
        if manifest.background is None or filename != manifest.background.normalized_filename:
            raise LocalApiNotFoundError("Background preview file was not found.")
        file_path = workspace_manager.resolve_relative_path(
            workspace_id,
            manifest.background.relative_path,
        )
        return FileResponse(
            file_path,
            media_type=manifest.background.content_type,
            filename=manifest.background.normalized_filename,
        )

    @app.delete(f"{config.api_prefix}/workspaces/{{workspace_id}}")
    async def delete_workspace(workspace_id: str):
        cleanup_service.delete_workspace(workspace_id)
        return {"status": "deleted", "workspaceId": workspace_id}

    return app


def build_workspace_response(
    artifact_service: ArtifactService,
    metadata_service: MetadataService,
    manifest: WorkspaceManifest,
) -> WorkspaceResponse:
    refreshed = artifact_service.refresh_workspace_artifacts(manifest)
    readiness = metadata_service.get_generation_readiness(refreshed)
    return WorkspaceResponse(
        workspace=refreshed,
        artifacts=artifact_service.list_artifact_groups(refreshed),
        readyForGeneration=readiness.ready,
    )


def build_validation_detail(path: str, errors: list[dict[str, object]]) -> dict[str, object]:
    fields: dict[str, str] = {}
    for issue in errors:
        location = [
            str(part)
            for part in issue.get("loc", ())
            if part not in {"body"}
        ]
        field_name = ".".join(location) or "request"
        fields.setdefault(field_name, str(issue.get("msg", "Invalid request.")))

    code = "INVALID_METADATA" if path.endswith("/metadata") else "INVALID_REQUEST"
    message = next(iter(fields.values()), "Request validation failed.")
    return {
        "code": code,
        "message": message,
        "fields": fields,
    }


app = create_app()


def main(argv: list[str] | None = None) -> int:
    services = _services()
    config = services["config"]
    cleanup_service = services["cleanup_service"]

    parser = argparse.ArgumentParser(description="Run the Pulse Practice local API.")
    subparsers = parser.add_subparsers(dest="command")
    cleanup_parser = subparsers.add_parser("cleanup", help="Delete local workspaces.")
    cleanup_parser.add_argument("--workspace-id", help="Delete one specific workspace.")
    cleanup_parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Delete only failed or cancelled workspaces.",
    )
    cleanup_parser.add_argument(
        "--older-than-hours",
        type=int,
        help="Delete workspaces older than the provided age.",
    )
    args = parser.parse_args(argv)

    if args.command == "cleanup":
        if args.workspace_id:
            cleanup_service.delete_workspace(args.workspace_id)
            print(f"Deleted workspace {args.workspace_id}")
            return 0
        if args.failed_only:
            deleted = cleanup_service.delete_failed_workspaces(args.older_than_hours)
            print(f"Deleted {len(deleted)} failed or cancelled workspace(s).")
            return 0
        if args.older_than_hours is not None:
            deleted = cleanup_service.delete_older_than(args.older_than_hours)
            print(f"Deleted {len(deleted)} workspace(s) older than {args.older_than_hours} hour(s).")
            return 0
        parser.error("cleanup requires --workspace-id, --failed-only, or --older-than-hours")

    uvicorn.run(
        "tools.local_api.app:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
