from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from pathlib import Path

from tools.text_utils import (  # noqa: F401  (re-exported for existing importers)
    build_mapset_filename,
    build_osu_filename,
    normalize_unicode_text,
    sanitize_filename_component,
)

from .errors import LocalApiUnsupportedMediaTypeError, LocalApiValidationError

WORKSPACE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def generate_workspace_id() -> str:
    return str(uuid.uuid4())


def validate_workspace_id(workspace_id: str) -> str:
    normalized = workspace_id.strip().lower()
    if not WORKSPACE_ID_PATTERN.fullmatch(normalized):
        raise LocalApiValidationError("Workspace ID is invalid.")
    return normalized


def ensure_allowed_extension(filename: str, allowed_extensions: tuple[str, ...]) -> str:
    suffix = Path(filename).suffix.lower()
    if not suffix or suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise LocalApiUnsupportedMediaTypeError(
            f"Unsupported file extension. Allowed: {allowed}"
        )
    return suffix


def ensure_safe_relative_path(path_value: str) -> str:
    normalized = path_value.replace("\\", "/").strip().lstrip("/")
    if not normalized:
        raise LocalApiValidationError("Relative path is required.")
    if normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise LocalApiValidationError("Relative path traversal is not allowed.")
    return normalized


def resolve_workspace_relative_path(workspace_root: Path, relative_path: str) -> Path:
    normalized = ensure_safe_relative_path(relative_path)
    resolved = (workspace_root / normalized).resolve()
    if workspace_root.resolve() not in resolved.parents and resolved != workspace_root.resolve():
        raise LocalApiValidationError("Requested path escapes the workspace.")
    return resolved


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"
