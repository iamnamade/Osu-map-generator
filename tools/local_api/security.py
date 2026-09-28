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

# P0.4 (Phase 6 roadmap): magic-byte signatures for content verification.
# Uploads are validated by their actual bytes, not by client-declared MIME
# types, which are trivially spoofed. RIFF files (WAV/WEBP) share a container
# header and are disambiguated by their fourcc at offset 8.
_AUDIO_MAGIC_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    # "ID3" tag or MPEG audio frame sync variants.
    ("mp3", b"ID3", 0),
    ("ogg", b"OggS", 0),
    ("flac", b"fLaC", 0),
)
_IMAGE_MAGIC_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    ("jpeg", b"\xff\xd8\xff", 0),
    ("png", b"\x89PNG\r\n\x1a\n", 0),
)

# Canonical Content-Type per detected signature (served back to clients).
CANONICAL_CONTENT_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# P0.4: claimed extension → the ONLY content kind that extension may carry.
_EXTENSION_CONTENT_KINDS: dict[str, str] = {
    ".mp3": "mp3",
    ".wav": "wav",
    ".ogg": "ogg",
    ".flac": "flac",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}


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


def detect_content_kind(head: bytes) -> str | None:
    """Return the canonical content kind for a file header, or None.

    P0.4: verifies magic bytes for the upload allow-list (audio + images).
    ``head`` should be at least the first 16 bytes of the file. RIFF files
    (WAV/WEBP) share a container header and are disambiguated by the fourcc
    at offset 8.
    """
    if head[:4] == b"RIFF":
        fourcc = head[8:12]
        if fourcc == b"WAVE":
            return "wav"
        if fourcc == b"WEBP":
            return "webp"
        return None
    for kind, signature, offset in _AUDIO_MAGIC_SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return kind
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        # MPEG audio frame sync (11-bit): covers remaining MP3 variants.
        return "mp3"
    for kind, signature, offset in _IMAGE_MAGIC_SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return kind
    return None


def verify_upload_content(path: Path, extension: str) -> str:
    """Verify magic bytes against the file's declared extension.

    P0.4: the detected content kind must exactly match the claimed extension
    (``.mp3`` must contain MPEG/ID3 data, ``.webp`` must be a RIFF/WEBP
    container, and so on). This rejects renamed arbitrary payloads AND
    mismatched containers (a PNG renamed to ``.webp`` is rejected even though
    both are images). Returns the canonical content type for the detected
    kind. Raises ``LocalApiUnsupportedMediaTypeError`` on any mismatch.
    """
    expected_kind = _EXTENSION_CONTENT_KINDS.get(extension.lower())
    if expected_kind is None:
        raise LocalApiUnsupportedMediaTypeError(
            f"Unsupported file extension: {extension}"
        )
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError as error:
        raise LocalApiValidationError(f"Uploaded file could not be read: {error}") from error

    detected_kind = detect_content_kind(head)
    if detected_kind != expected_kind:
        raise LocalApiUnsupportedMediaTypeError(
            f"File content does not match its declared format: expected {expected_kind}, "
            f"detected {detected_kind or 'unknown'}."
        )
    return CANONICAL_CONTENT_TYPES[detected_kind]
