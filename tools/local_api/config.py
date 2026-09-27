from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class LocalApiConfig:
    project_root: Path
    workspaces_root: Path
    host: str
    port: int
    api_prefix: str
    max_audio_upload_bytes: int
    max_background_upload_bytes: int
    allowed_audio_extensions: tuple[str, ...]
    allowed_background_extensions: tuple[str, ...]
    allowed_vite_origins: tuple[str, ...]
    default_creator: str
    max_title_length: int
    max_artist_length: int
    max_source_length: int
    max_tags_length: int
    max_creator_length: int
    default_root_seed: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@lru_cache(maxsize=1)
def get_local_api_config() -> LocalApiConfig:
    project_root = Path(__file__).resolve().parents[2]
    workspaces_root = Path(
        os.getenv(
            "PULSE_LOCAL_API_WORKSPACES_ROOT",
            str(project_root / "workspaces"),
        )
    ).resolve()
    origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "PULSE_LOCAL_API_CORS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )
    return LocalApiConfig(
        project_root=project_root,
        workspaces_root=workspaces_root,
        host=os.getenv("PULSE_LOCAL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("PULSE_LOCAL_API_PORT", "8765")),
        api_prefix="/api",
        max_audio_upload_bytes=int(
            os.getenv("PULSE_LOCAL_API_MAX_AUDIO_BYTES", str(200 * 1024 * 1024))
        ),
        max_background_upload_bytes=int(
            os.getenv("PULSE_LOCAL_API_MAX_BACKGROUND_BYTES", str(25 * 1024 * 1024))
        ),
        allowed_audio_extensions=(".mp3", ".wav", ".ogg", ".flac"),
        allowed_background_extensions=(".jpg", ".jpeg", ".png", ".webp"),
        allowed_vite_origins=origins,
        default_creator="osu-map-ai",
        max_title_length=160,
        max_artist_length=160,
        max_source_length=160,
        max_tags_length=512,
        max_creator_length=80,
        default_root_seed=42,
    )
