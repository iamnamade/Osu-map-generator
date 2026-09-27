from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import librosa
import soundfile
from mutagen import File as MutagenFile
from pydantic import ValidationError

from tools.text_utils import (
    normalize_unicode_text,
    resolve_detected_tag_pair,
    resolve_unicode_metadata,
)

from .config import LocalApiConfig
from .errors import LocalApiMetadataValidationError, LocalApiValidationError
from .models import AudioMetadataSuggestion, WorkspaceManifest, WorkspaceMetadata


@dataclass(frozen=True)
class GenerationReadiness:
    ready: bool


class MetadataService:
    def __init__(self, config: LocalApiConfig) -> None:
        self.config = config

    def parse_metadata_payload(self, payload: object) -> WorkspaceMetadata:
        try:
            metadata = WorkspaceMetadata.model_validate(payload)
        except ValidationError as error:
            raise self._metadata_error_from_validation(error) from error
        metadata = self._normalize_metadata(metadata)
        self.validate_metadata(metadata)
        return metadata

    def update_metadata(
        self,
        manifest: WorkspaceManifest,
        metadata: WorkspaceMetadata,
    ) -> WorkspaceManifest:
        metadata = self._normalize_metadata(metadata)
        self.validate_metadata(metadata)
        return manifest.model_copy(
            update={
                "metadata": metadata,
                "configuration_signature": self.compute_configuration_signature(
                    manifest.model_copy(update={"metadata": metadata}, deep=True)
                ),
            },
            deep=True,
        )

    def validate_generation_ready(self, manifest: WorkspaceManifest) -> None:
        if manifest.audio is None:
            raise LocalApiValidationError(
                "Upload an audio file before starting generation."
            )
        self.validate_metadata(manifest.metadata)

    def get_generation_readiness(
        self,
        manifest: WorkspaceManifest,
    ) -> GenerationReadiness:
        if manifest.audio is None:
            return GenerationReadiness(ready=False)
        try:
            self.validate_metadata(manifest.metadata)
            return GenerationReadiness(ready=True)
        except LocalApiValidationError:
            return GenerationReadiness(ready=False)

    def validate_metadata(self, metadata: WorkspaceMetadata) -> None:
        field_errors: dict[str, str] = {}
        self._collect_length_errors(metadata, field_errors)

        if not metadata.title.strip():
            field_errors.setdefault("title", "Title is required.")
        if not metadata.artist.strip():
            field_errors.setdefault("artist", "Artist is required.")
        if not metadata.creator.strip():
            field_errors.setdefault("creator", "Creator is required.")
        if not metadata.selected_difficulties:
            field_errors.setdefault(
                "selectedDifficulties",
                "Select at least one difficulty.",
            )

        for difficulty in metadata.selected_difficulties:
            settings = metadata.difficulty_settings.get(difficulty)
            if settings is None:
                field_errors.setdefault(
                    f"difficultySettings.{difficulty}",
                    f"Difficulty settings are missing for {difficulty}.",
                )
                continue
            if settings.candidate_count < 1 or settings.candidate_count > 64:
                field_errors.setdefault(
                    f"difficultySettings.{difficulty}.candidateCount",
                    "Candidate count must be between 1 and 64.",
                )
            if settings.root_seed < 0:
                field_errors.setdefault(
                    f"difficultySettings.{difficulty}.rootSeed",
                    "Root seed must be non-negative.",
                )
            if settings.evolution_passes < 1 or settings.evolution_passes > 5:
                field_errors.setdefault(
                    f"difficultySettings.{difficulty}.evolutionPasses",
                    "Evolution passes must be between 1 and 5.",
                )
            if settings.difficulty_target == "custom":
                values = [
                    settings.custom_target_star,
                    settings.custom_min_star,
                    settings.custom_max_star,
                ]
                if any(value is None for value in values):
                    field_errors.setdefault(
                        f"difficultySettings.{difficulty}.difficultyTarget",
                        "Custom difficulty requires target, minimum, and maximum star values.",
                    )
                else:
                    target, minimum, maximum = (float(value) for value in values)  # type: ignore[assignment]
                    if not (0.5 <= minimum <= target <= maximum <= 12.0):
                        field_errors.setdefault(
                            f"difficultySettings.{difficulty}.difficultyTarget",
                            "Custom difficulty range is impossible: min <= target <= max with all values between 0.5 and 12.0 stars.",
                        )
            if settings.hybrid_assembly_enabled and not settings.tournament_enabled:
                field_errors.setdefault(
                    f"difficultySettings.{difficulty}.hybridAssemblyEnabled",
                    "Hybrid assembly requires tournament mode.",
                )

        if field_errors:
            raise LocalApiMetadataValidationError(
                self._build_metadata_summary(field_errors),
                fields=field_errors,
            )

    def extract_audio_metadata(self, audio_path: Path) -> AudioMetadataSuggestion:
        detected_title: str | None = None
        detected_artist: str | None = None
        duration_ms: int | None = None
        sample_rate: int | None = None
        codec: str | None = None
        bitrate_kbps: int | None = None

        mutagen_easy = MutagenFile(audio_path, easy=True)
        mutagen_full = MutagenFile(audio_path)
        easy_tags = _collect_tag_values(mutagen_easy)
        full_tags = _collect_tag_values(mutagen_full)
        raw_title = easy_tags.get("title") or full_tags.get("title")
        raw_artist = easy_tags.get("artist") or full_tags.get("artist")
        title_unicode_tag = full_tags.get("titleunicode") or easy_tags.get("titleunicode")
        artist_unicode_tag = full_tags.get("artistunicode") or easy_tags.get("artistunicode")
        detected_title, detected_title_unicode = resolve_detected_tag_pair(
            raw_title, title_unicode_tag
        )
        detected_artist, detected_artist_unicode = resolve_detected_tag_pair(
            raw_artist, artist_unicode_tag
        )
        if mutagen_full is not None and getattr(mutagen_full, "info", None) is not None:
            info = mutagen_full.info
            if hasattr(info, "length") and info.length:
                duration_ms = int(round(float(info.length) * 1000))
            if hasattr(info, "sample_rate") and isinstance(info.sample_rate, int):
                sample_rate = info.sample_rate
            if hasattr(info, "bitrate") and isinstance(info.bitrate, int) and info.bitrate > 0:
                bitrate_kbps = int(round(info.bitrate / 1000))
            mime_types = getattr(mutagen_full, "mime", None)
            if isinstance(mime_types, list) and mime_types:
                codec = mime_types[0]

        if duration_ms is None or sample_rate is None:
            try:
                info = soundfile.info(audio_path)
                duration_ms = duration_ms or int(round(info.duration * 1000))
                sample_rate = sample_rate or int(info.samplerate)
                codec = codec or info.format
            except RuntimeError:
                samples, loaded_sample_rate = librosa.load(
                    audio_path.as_posix(),
                    sr=None,
                    mono=True,
                    duration=1.0,
                )
                if samples.size == 0:
                    raise LocalApiValidationError("Uploaded audio file could not be decoded.")
                sample_rate = sample_rate or int(loaded_sample_rate)

        return AudioMetadataSuggestion(
            title=detected_title,
            titleUnicode=detected_title_unicode,
            artist=detected_artist,
            artistUnicode=detected_artist_unicode,
            durationMs=duration_ms,
            sampleRate=sample_rate,
            codec=codec,
            bitrateKbps=bitrate_kbps,
        )

    def compute_configuration_signature(self, manifest: WorkspaceManifest) -> str | None:
        if manifest.audio is None:
            return None
        payload: dict[str, Any] = {
            "audioSha256": manifest.audio.sha256,
            "backgroundSha256": manifest.background.sha256 if manifest.background else None,
            "metadata": manifest.metadata.model_dump(by_alias=True, exclude_none=True),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _normalize_metadata(self, metadata: WorkspaceMetadata) -> WorkspaceMetadata:
        """NFC-normalize text fields and apply Unicode/romanisation fallbacks.

        - Every text field is normalized to NFC (I9).
        - When the romanised title/artist is empty but a Unicode value exists,
          the romanised field is filled from a transliteration fallback (I3).
        - When only a native-script value is supplied, it is also mirrored into
          the matching Unicode field so exports can emit TitleUnicode /
          ArtistUnicode (I1).
        """
        title, title_unicode, artist, artist_unicode = resolve_unicode_metadata(
            metadata.title,
            metadata.artist,
            metadata.title_unicode,
            metadata.artist_unicode,
        )
        candidate = {
            "title": title,
            "artist": artist,
            "title_unicode": title_unicode,
            "artist_unicode": artist_unicode,
            "creator": normalize_unicode_text(metadata.creator).strip()
            or metadata.creator,
            "source": normalize_unicode_text(metadata.source).strip(),
            "tags": normalize_unicode_text(metadata.tags).strip(),
        }
        updates = {
            key: value
            for key, value in candidate.items()
            if value != getattr(metadata, key)
        }
        if not updates:
            return metadata
        return metadata.model_copy(update=updates, deep=True)

    def _collect_length_errors(
        self,
        metadata: WorkspaceMetadata,
        field_errors: dict[str, str],
    ) -> None:
        if len(metadata.title) > self.config.max_title_length:
            field_errors.setdefault(
                "title",
                f"Title must be {self.config.max_title_length} characters or fewer.",
            )
        if metadata.title_unicode and len(metadata.title_unicode) > self.config.max_title_length:
            field_errors.setdefault(
                "titleUnicode",
                f"TitleUnicode must be {self.config.max_title_length} characters or fewer.",
            )
        if len(metadata.artist) > self.config.max_artist_length:
            field_errors.setdefault(
                "artist",
                f"Artist must be {self.config.max_artist_length} characters or fewer.",
            )
        if metadata.artist_unicode and len(metadata.artist_unicode) > self.config.max_artist_length:
            field_errors.setdefault(
                "artistUnicode",
                f"ArtistUnicode must be {self.config.max_artist_length} characters or fewer.",
            )
        if len(metadata.creator) > self.config.max_creator_length:
            field_errors.setdefault(
                "creator",
                f"Creator must be {self.config.max_creator_length} characters or fewer.",
            )
        if len(metadata.source) > self.config.max_source_length:
            field_errors.setdefault(
                "source",
                f"Source must be {self.config.max_source_length} characters or fewer.",
            )
        if len(metadata.tags) > self.config.max_tags_length:
            field_errors.setdefault(
                "tags",
                f"Tags must be {self.config.max_tags_length} characters or fewer.",
            )

    def _build_metadata_summary(self, field_errors: dict[str, str]) -> str:
        if "title" in field_errors and field_errors["title"] == "Title is required.":
            return "Song title is required before generation."
        if "artist" in field_errors and field_errors["artist"] == "Artist is required.":
            return "Artist is required before generation."
        if (
            "selectedDifficulties" in field_errors
            and field_errors["selectedDifficulties"] == "Select at least one difficulty."
        ):
            return "Select at least one difficulty before generation."
        return next(iter(field_errors.values()))

    def _metadata_error_from_validation(
        self,
        error: ValidationError,
    ) -> LocalApiMetadataValidationError:
        field_errors: dict[str, str] = {}
        for issue in error.errors():
            location = [
                str(part)
                for part in issue.get("loc", ())
                if part not in {"body"}
            ]
            field_name = ".".join(location) or "metadata"
            message = str(issue.get("msg", "Invalid metadata."))
            field_errors.setdefault(field_name, message)
        return LocalApiMetadataValidationError(
            self._build_metadata_summary(field_errors),
            fields=field_errors or {"metadata": "Invalid metadata."},
        )


def _collect_tag_values(mutagen_file: Any) -> dict[str, str]:
    """Return a normalized-key -> first-string-value view of a mutagen file.

    Keys are lower-cased with non-alphanumerics removed so ID3 ``TXXX:TitleUnicode``
    and Vorbis ``title_unicode``/``TITLE_UNICODE`` all collapse to ``titleunicode``.
    """
    if mutagen_file is None:
        return {}
    tags = getattr(mutagen_file, "tags", None)
    source = tags if isinstance(tags, dict) else (
        mutagen_file if isinstance(mutagen_file, dict) else {}
    )
    collected: dict[str, str] = {}
    for key, raw_value in source.items():
        if not isinstance(key, str):
            continue
        value = raw_value[0] if isinstance(raw_value, list) and raw_value else raw_value
        if isinstance(value, str) and value.strip():
            normalized_key = "".join(
                character for character in key.lower() if character.isalnum()
            )
            collected.setdefault(normalized_key, value.strip())
    return collected


def _first_tag_value(mutagen_file: Any, key: str) -> str | None:
    return _collect_tag_values(mutagen_file).get(
        "".join(character for character in key.lower() if character.isalnum())
    )
