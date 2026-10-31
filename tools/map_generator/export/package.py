"""OSZ packaging with automatic video asset registration.

Turns an exported ``.osu`` plus its audio (and optional video) into a deployable
``.osz``.  The video file is registered in the ``[Events]`` section as
``Video,0,"<name>"`` -- without that line osu! ignores a video that is present
in the archive, which is the failure mode this module exists to prevent.

The source ``.osu`` file is never modified: the ``Video`` line is injected into
the copy written into the archive, so packaging stays a read-only operation on
the export directory.  Archive entry names stay flat, matching the existing
mapset packager, and timestamps are fixed so repeated packages are byte-stable.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from ..osu_format.models import OszPackageResult
from ..osu_format.timing_converter import deterministic_archive_timestamp
from ..utils import MapGeneratorError, ensure_existing_file, ensure_parent_directory

#: Section the Video event belongs to.
EVENTS_HEADER = "[Events]"


def create_osz_archive(
    osu_path: Path | str,
    audio_path: Path | str,
    video_path: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
) -> OszPackageResult:
    """Package a beatmap, its audio and an optional video into ``.osz``.

    Args:
        osu_path: Exported ``.osu`` file.
        audio_path: Audio referenced by the beatmap's ``AudioFilename``.
        video_path: Optional video; when given it is zipped and registered in
            ``[Events]``.
        output_path: Archive destination.  Defaults to the ``.osu`` path with an
            ``.osz`` suffix.

    Returns:
        :class:`OszPackageResult` with the archive path and entry names.
    """
    source_osu = ensure_existing_file(Path(osu_path), "osu beatmap file")
    source_audio = ensure_existing_file(Path(audio_path), "Audio file")
    source_video = (
        ensure_existing_file(Path(video_path), "Video file") if video_path is not None else None
    )

    destination = Path(output_path) if output_path is not None else source_osu.with_suffix(".osz")
    ensure_parent_directory(destination)

    try:
        osu_text = source_osu.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise MapGeneratorError(f"Could not read .osu file {source_osu}: {error}") from error

    entries: list[tuple[Path, str, bytes | None]] = []
    if source_video is not None:
        osu_text = _inject_video_event(osu_text, source_video.name)
        entries.append((source_video, source_video.name, None))

    entries.append((source_osu, source_osu.name, osu_text.encode("utf-8")))
    entries.append((source_audio, source_audio.name, None))

    ordered = sorted(entries, key=lambda item: item[1].lower())
    timestamp = deterministic_archive_timestamp()
    try:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name, override in ordered:
                _validate_archive_name(name)
                payload = override if override is not None else path.read_bytes()
                info = zipfile.ZipInfo(name)
                info.date_time = timestamp
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                archive.writestr(info, payload)
    except OSError as error:
        raise MapGeneratorError(f"Could not write .osz archive to {destination}: {error}") from error

    return OszPackageResult(
        output_path=destination.as_posix(),
        archived_files=[name for _, name, _ in ordered],
    )


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

    # Replace the first Video line in place; drop any further ones.
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
        # Keep events above the blank separator that precedes the next section.
        while rebuilt and not rebuilt[-1].strip() and len(rebuilt) > header_index + 1:
            rebuilt.pop()
        rebuilt.append(line)
        rebuilt.append("")

    rebuilt.extend(lines[body_end:])
    return "\n".join(rebuilt)


def _validate_archive_name(value: str) -> None:
    """Reject nested paths; osu! mapset entries are flat."""
    normalized = value.replace("\\", "/").strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise MapGeneratorError(f"Invalid .osz entry name: {value!r}")
