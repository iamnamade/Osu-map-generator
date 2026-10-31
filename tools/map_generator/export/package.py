"""OSZ packaging with automatic video and storyboard asset registration.

Turns an exported ``.osu`` plus its audio (and optional video, background and
storyboard) into a deployable ``.osz``.

* A video file is registered in ``[Events]`` as ``Video,0,"<name>"`` -- without
  that line osu! ignores a video that is present in the archive.
* With ``with_storyboard``, lyrics are transcribed (Whisper), rendered to
  ``sb/lyrics/*.png`` and scripted into an ``.osb``; both the script and the
  whole ``sb/`` tree are archived.  Whisper is optional: when it is missing the
  storyboard is still written, with the background pulse and no lyrics, and the
  reason is reported in ``warnings``.

The source ``.osu`` file is never modified: the ``Video`` line is injected into
the copy written into the archive, so packaging stays a read-only operation on
the export directory.  Archive timestamps are fixed so repeated packages are
byte-stable.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Sequence

from ..osu_format.models import OszPackageResult
from ..osu_format.timing_converter import deterministic_archive_timestamp
from ..storyboard.lyric_engine import LyricGenerator
from ..utils import MapGeneratorError, ensure_existing_file, ensure_parent_directory
from .storyboard_writer import StoryboardGenerator

#: Section the Video event belongs to.
EVENTS_HEADER = "[Events]"


def create_osz_archive(
    osu_path: Path | str,
    audio_path: Path | str,
    video_path: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    with_storyboard: bool = False,
    background_path: Path | str | None = None,
    kiai_times: Sequence[tuple] | None = None,
    whisper_model: str = "base",
) -> OszPackageResult:
    """Package a beatmap, audio, optional video and optional storyboard.

    Args:
        osu_path: Exported ``.osu`` file.
        audio_path: Audio referenced by the beatmap.
        video_path: Optional video; zipped and registered in ``[Events]``.
        output_path: Archive destination.  Defaults to the ``.osu`` path with an
            ``.osz`` suffix.
        with_storyboard: Transcribe lyrics, render sprites and write an ``.osb``.
        background_path: Background image to include and pulse in the storyboard.
        kiai_times: ``(start_ms, end_ms)`` windows that get the pulse effect.
        whisper_model: Whisper model size used for transcription.

    Returns:
        :class:`OszPackageResult` with the archive path, entry names and any
        non-fatal warnings (for example, lyrics skipped because Whisper is not
        installed).
    """
    source_osu = ensure_existing_file(Path(osu_path), "osu beatmap file")
    source_audio = ensure_existing_file(Path(audio_path), "Audio file")
    source_video = (
        ensure_existing_file(Path(video_path), "Video file") if video_path is not None else None
    )
    source_background = (
        ensure_existing_file(Path(background_path), "Background file")
        if background_path is not None
        else None
    )

    destination = Path(output_path) if output_path is not None else source_osu.with_suffix(".osz")
    ensure_parent_directory(destination)

    try:
        osu_text = source_osu.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise MapGeneratorError(f"Could not read .osu file {source_osu}: {error}") from error

    warnings: list[str] = []
    entries: list[tuple[Path, str]] = []
    overrides: dict[str, bytes] = {}

    if source_video is not None:
        osu_text = _inject_video_event(osu_text, source_video.name)
        entries.append((source_video, source_video.name))

    overrides[source_osu.name] = osu_text.encode("utf-8")
    entries.append((source_osu, source_osu.name))
    entries.append((source_audio, source_audio.name))

    timestamp = deterministic_archive_timestamp()

    with tempfile.TemporaryDirectory(prefix="osb_") as scratch:
        if with_storyboard:
            storyboard_entries, storyboard_warnings = _build_storyboard(
                audio_path=source_audio,
                background=source_background,
                kiai_times=kiai_times,
                whisper_model=whisper_model,
                scratch=Path(scratch),
                osb_stem=source_osu.stem,
            )
            entries.extend(storyboard_entries)
            warnings.extend(storyboard_warnings)
        elif source_background is not None:
            # Without a storyboard the background still belongs in the mapset.
            entries.append((source_background, source_background.name))

        ordered = sorted(entries, key=lambda item: item[1].lower())
        try:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, name in ordered:
                    _validate_archive_name(name)
                    payload = overrides.get(name)
                    if payload is None:
                        payload = path.read_bytes()
                    info = zipfile.ZipInfo(name)
                    info.date_time = timestamp
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 0
                    archive.writestr(info, payload)
        except OSError as error:
            raise MapGeneratorError(
                f"Could not write .osz archive to {destination}: {error}"
            ) from error

    return OszPackageResult(
        output_path=destination.as_posix(),
        archived_files=[name for _, name in ordered],
        warnings=warnings,
    )


def _build_storyboard(
    *,
    audio_path: Path,
    background: Path | None,
    kiai_times: Sequence[tuple] | None,
    whisper_model: str,
    scratch: Path,
    osb_stem: str,
) -> tuple[list[tuple[Path, str]], list[str]]:
    """Transcribe, render and script the storyboard inside ``scratch``."""
    warnings: list[str] = []
    lyric_generator = LyricGenerator(audio_path, scratch, model_size=whisper_model)

    lyrics: list[dict] = []
    try:
        lyrics = lyric_generator.extract_lyrics()
    except MapGeneratorError as error:
        # Whisper missing or unusable: keep the storyboard, drop the lyrics.
        warnings.append(str(error))

    sprites: list[dict] = []
    if lyrics:
        sprites = lyric_generator.render_lyric_sprites(lyrics)
        if not sprites:
            warnings.append("Lyric sprites rendered empty; storyboard has no lyrics.")

    osb_path = scratch / f"{osb_stem}.osb"
    StoryboardGenerator().write_osb(
        sprites,
        background.name if background is not None else "",
        list(kiai_times or []),
        osb_path.as_posix(),
    )

    entries: list[tuple[Path, str]] = [(osb_path, osb_path.name)]
    for sprite in sprites:
        relative = str(sprite.get("sprite_path", ""))
        if not relative:
            continue
        sprite_path = scratch / relative
        if sprite_path.is_file():
            entries.append((sprite_path, relative))
    if background is not None:
        entries.append((background, background.name))
    return entries, warnings


def _inject_video_event(osu_text: str, video_name: str) -> str:
    """Return ``osu_text`` with a single ``Video,0,"<video_name>"`` event line.

    Any existing ``Video`` line is replaced so a re-package cannot accumulate
    duplicates.  When the file has no ``[Events]`` section one is created before
    ``[TimingPoints]`` (the conventional order), or appended if that section is
    also missing.
    """
    line = f'Video,0,"{video_name}"'
    lines = osu_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    header_index = next(
        (index for index, value in enumerate(lines) if value.strip() == EVENTS_HEADER),
        None,
    )
    if header_index is None:
        insert_at = next(
            (
                index
                for index, value in enumerate(lines)
                if value.strip() == "[TimingPoints]"
            ),
            len(lines),
        )
        new_lines = list(lines)
        new_lines[insert_at:insert_at] = [EVENTS_HEADER, line, ""]
        return "\n".join(new_lines)

    body_end = next(
        (
            index
            for index in range(header_index + 1, len(lines))
            if lines[index].strip().startswith("[") and lines[index].strip().endswith("]")
        ),
        len(lines),
    )

    rebuilt = lines[: header_index + 1]
    placed = False
    for index in range(header_index + 1, body_end):
        current = lines[index].strip()
        if current.lower().startswith("video,"):
            if not placed:
                rebuilt.append(line)
                placed = True
            continue
        rebuilt.append(lines[index])

    if not placed:
        while rebuilt and not rebuilt[-1].strip() and len(rebuilt) > header_index + 1:
            rebuilt.pop()
        rebuilt.append(line)
        rebuilt.append("")

    rebuilt.extend(lines[body_end:])
    return "\n".join(rebuilt)


def _validate_archive_name(value: str) -> None:
    """Reject absolute or traversing entry names; nested paths are allowed.

    ``sb/lyrics/lyric_0.png`` must be archived with its directory structure so
    the ``.osb`` sprite references resolve.
    """
    normalized = value.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or normalized in {".", ".."}:
        raise MapGeneratorError(f"Invalid .osz entry name: {value!r}")
    if any(segment in {"", ".", ".."} for segment in normalized.split("/")):
        raise MapGeneratorError(f"Invalid .osz entry name: {value!r}")
