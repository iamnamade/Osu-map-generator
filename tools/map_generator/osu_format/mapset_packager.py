from __future__ import annotations

import zipfile
from pathlib import Path

from ..utils import MapGeneratorError, ensure_existing_file, ensure_parent_directory
from .parser import parse_osu_file
from .timing_converter import deterministic_archive_timestamp, normalize_osu_relative_path, osu_audio_filename_from_browser_path
from .models import OszPackageResult


def package_osz_archive(
    *,
    maps_dir: Path,
    audio_path: Path,
    output_path: Path,
    background_path: Path | None = None,
) -> OszPackageResult:
    directory = maps_dir
    if not directory.exists() or not directory.is_dir():
        raise MapGeneratorError(f"Maps directory does not exist: {maps_dir}")
    audio_file = ensure_existing_file(audio_path, "Audio file")
    background_file = ensure_existing_file(background_path, "Background file") if background_path else None
    osu_files = sorted(directory.glob("*.osu"))
    if not osu_files:
        raise MapGeneratorError(f"No .osu files were found in {maps_dir}")

    parsed_files = [parse_osu_file(path) for path in osu_files]
    referenced_audio_names = {
        normalize_osu_relative_path(parsed.general.get("AudioFilename", ""))
        for parsed in parsed_files
        if parsed.general.get("AudioFilename", "").strip()
    }
    if not referenced_audio_names:
        raise MapGeneratorError("The exported .osu files are missing AudioFilename entries.")
    if len(referenced_audio_names) != 1:
        raise MapGeneratorError("The exported .osu files do not agree on a single audio filename.")
    expected_audio_filename = next(iter(referenced_audio_names))
    if expected_audio_filename != osu_audio_filename_from_browser_path(audio_file.name):
        raise MapGeneratorError(
            f"The provided audio file {audio_file.name} does not match the referenced mapset audio {expected_audio_filename}."
        )

    archive_entries = [(path, path.name) for path in osu_files]
    archive_entries.append((audio_file, expected_audio_filename))

    if background_file is not None:
        background_names = {
            normalize_osu_relative_path(parsed.background_filename)
            for parsed in parsed_files
            if parsed.background_filename
        }
        if background_names and background_file.name not in background_names:
            raise MapGeneratorError(
                f"The provided background file {background_file.name} does not match the referenced background filename(s): {', '.join(sorted(background_names))}."
            )
        archive_entries.append((background_file, background_file.name))

    ensure_parent_directory(output_path)
    ordered_entries = sorted(
        archive_entries,
        key=lambda item: item[1].lower(),
    )
    timestamp = deterministic_archive_timestamp()
    try:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_path, archive_name in ordered_entries:
                _validate_archive_name(archive_name)
                info = zipfile.ZipInfo(archive_name)
                info.date_time = timestamp
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                archive.writestr(info, source_path.read_bytes())
    except OSError as error:
        raise MapGeneratorError(f"Could not write .osz archive to {output_path}: {error}") from error

    return OszPackageResult(
        output_path=output_path.as_posix(),
        archived_files=[archive_name for _, archive_name in ordered_entries],
    )


def _validate_archive_name(value: str) -> None:
    normalized = normalize_osu_relative_path(value)
    if "/" in normalized:
        raise MapGeneratorError(f"Archive entry names must stay flat for this phase: {value}")
