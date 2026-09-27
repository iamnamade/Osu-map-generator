from __future__ import annotations

from pathlib import Path

from ..utils import MapGeneratorError, ensure_parent_directory
from ._constants import load_osu_interop_constants
from .models import OsuWriterSections


def write_osu_text(sections: OsuWriterSections) -> str:
    constants = load_osu_interop_constants()
    lines: list[str] = [f"osu file format v{int(constants['fileFormatVersion'])}", ""]
    _write_key_value_section(lines, "General", sections.general)
    _write_key_value_section(lines, "Editor", sections.editor)
    _write_key_value_section(lines, "Metadata", sections.metadata)
    _write_key_value_section(lines, "Difficulty", sections.difficulty)
    lines.append("[Events]")
    lines.extend(sections.events)
    lines.append("")
    lines.append("[TimingPoints]")
    lines.extend(item.to_line() for item in sections.timing_points)
    lines.append("")
    lines.append("[Colours]")
    lines.extend(sections.colours)
    lines.append("")
    lines.append("[HitObjects]")
    lines.extend(item.to_line() for item in sections.hit_objects)
    lines.append("")
    return "\n".join(lines)


def write_osu_file(path: Path, text: str) -> None:
    ensure_parent_directory(path)
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as error:
        raise MapGeneratorError(f"Could not write osu file to {path}: {error}") from error


def _write_key_value_section(lines: list[str], name: str, values: dict[str, str]) -> None:
    lines.append(f"[{name}]")
    for key, value in values.items():
        lines.append(f"{key}: {value}")
    lines.append("")
