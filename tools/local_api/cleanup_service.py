from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .errors import LocalApiConflictError
from .workspace_manager import WorkspaceManager


class CleanupService:
    def __init__(self, workspace_manager: WorkspaceManager, job_manager) -> None:
        self.workspace_manager = workspace_manager
        self.job_manager = job_manager

    def delete_workspace(self, workspace_id: str) -> None:
        manifest = self.workspace_manager.load_manifest(workspace_id)
        if manifest.job_status in {"queued", "running"}:
            raise LocalApiConflictError("Active workspaces cannot be deleted.")
        self.workspace_manager.delete_workspace(workspace_id)

    def delete_failed_workspaces(self, older_than_hours: int | None = None) -> list[str]:
        deleted: list[str] = []
        cutoff = (
            datetime.now(UTC) - timedelta(hours=older_than_hours)
            if older_than_hours is not None
            else None
        )
        for workspace_path in sorted(self.workspace_manager.config.workspaces_root.iterdir()):
            if not workspace_path.is_dir():
                continue
            try:
                manifest = self.workspace_manager.load_manifest(workspace_path.name)
            except Exception:
                continue
            if manifest.job_status not in {"failed", "cancelled"}:
                continue
            if cutoff is not None and manifest.updated_at > cutoff:
                continue
            self.workspace_manager.delete_workspace(workspace_path.name)
            deleted.append(workspace_path.name)
        return deleted

    def delete_older_than(self, older_than_hours: int) -> list[str]:
        deleted: list[str] = []
        cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
        for workspace_path in sorted(self.workspace_manager.config.workspaces_root.iterdir()):
            if not workspace_path.is_dir():
                continue
            try:
                manifest = self.workspace_manager.load_manifest(workspace_path.name)
            except Exception:
                continue
            if manifest.job_status in {"queued", "running"}:
                continue
            if manifest.updated_at > cutoff:
                continue
            self.workspace_manager.delete_workspace(workspace_path.name)
            deleted.append(workspace_path.name)
        return deleted
