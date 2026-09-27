from __future__ import annotations

from typing import Any

from ...text_utils import normalize_unicode_text
from ._constants import load_osu_interop_constants
from .models import ProjectBeatmap


def _nfc(value: str) -> str:
    return normalize_unicode_text(value)


def build_general_section(audio_filename: str, preserved: dict[str, str] | None = None) -> dict[str, str]:
    constants = load_osu_interop_constants()["generalDefaults"]
    return {
        **(preserved or {}),
        "AudioFilename": audio_filename,
        "AudioLeadIn": str(int(constants["audioLeadIn"])),
        "PreviewTime": str(int(constants["previewTime"])),
        "Countdown": str(int(constants["countdown"])),
        "SampleSet": str(constants["sampleSet"]),
        "StackLeniency": _fixed_decimal(float(constants["stackLeniency"])),
        "Mode": str(int(constants["mode"])),
        "LetterboxInBreaks": str(int(constants["letterboxInBreaks"])),
        "SpecialStyle": str(int(constants["specialStyle"])),
        "WidescreenStoryboard": str(int(constants["widescreenStoryboard"])),
        "SamplesMatchPlaybackRate": str(int(constants["samplesMatchPlaybackRate"])),
    }


def build_editor_section(preserved: dict[str, str] | None = None) -> dict[str, str]:
    constants = load_osu_interop_constants()["editorDefaults"]
    return {
        **(preserved or {}),
        "DistanceSpacing": _fixed_decimal(float(constants["distanceSpacing"])),
        "BeatDivisor": str(int(constants["beatDivisor"])),
        "GridSize": str(int(constants["gridSize"])),
        "TimelineZoom": _fixed_decimal(float(constants["timelineZoom"])),
    }


def build_metadata_section(
    beatmap: ProjectBeatmap,
    creator: str,
    version_name: str,
    beatmap_id: str | None,
    beatmap_set_id: str | None,
    preserved: dict[str, str] | None = None,
    *,
    title_unicode: str | None = None,
    artist_unicode: str | None = None,
) -> dict[str, str]:
    # Explicit caller-supplied Unicode wins; otherwise fall back to values
    # carried on the project beatmap (imports, earlier generation passes).
    resolved_title_unicode = (
        normalize_optional_text(title_unicode)
        or _read_nested_string(beatmap.extra_fields, ["osu", "titleUnicode"])
    )
    resolved_artist_unicode = (
        normalize_optional_text(artist_unicode)
        or _read_nested_string(beatmap.extra_fields, ["osu", "artistUnicode"])
    )
    return {
        **(preserved or {}),
        "Title": _nfc(beatmap.title),
        **({"TitleUnicode": _nfc(resolved_title_unicode)} if resolved_title_unicode else {}),
        "Artist": _nfc(beatmap.artist),
        **({"ArtistUnicode": _nfc(resolved_artist_unicode)} if resolved_artist_unicode else {}),
        "Creator": _nfc(creator),
        "Version": _nfc(version_name),
        "Source": _nfc(_read_nested_string(beatmap.extra_fields, ["osu", "source"]) or ""),
        "Tags": _nfc(_read_nested_string(beatmap.extra_fields, ["osu", "tags"]) or "pulse-practice circle-only"),
        "BeatmapID": beatmap_id or "0",
        "BeatmapSetID": beatmap_set_id or "-1",
    }


def sanitize_key_value_section(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    output: dict[str, str] = {}
    for key, item in raw_value.items():
        if isinstance(key, str):
            normalized = normalize_optional_text(item)
            if normalized is not None:
                output[key] = normalized
    return output


def extract_preserved_sections(extra_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    osu_section = extra_fields.get("osu")
    if not isinstance(osu_section, dict):
        return {
            "general": {},
            "editor": {},
            "metadata": {},
            "difficulty": {},
        }
    return {
        "general": sanitize_key_value_section(osu_section.get("general")),
        "editor": sanitize_key_value_section(osu_section.get("editor")),
        "metadata": sanitize_key_value_section(osu_section.get("metadata")),
        "difficulty": sanitize_key_value_section(osu_section.get("difficulty")),
    }


def extract_preserved_colours(extra_fields: dict[str, Any]) -> list[str]:
    osu_section = extra_fields.get("osu")
    if not isinstance(osu_section, dict):
        return []
    raw_colours = osu_section.get("colours")
    if not isinstance(raw_colours, list):
        return []
    return [item.strip() for item in raw_colours if isinstance(item, str) and item.strip()]


def normalize_optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and float(value) == float(value) and float(value) not in (float("inf"), float("-inf")):
        return str(value)
    return None


def _read_nested_string(value: dict[str, Any], path: list[str]) -> str | None:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current.strip() if isinstance(current, str) and current.strip() else None


def _fixed_decimal(value: float) -> str:
    rounded = round(value, 2)
    return f"{rounded:.0f}" if float(rounded).is_integer() else str(rounded)
