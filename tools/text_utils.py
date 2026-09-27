"""Shared Unicode, transliteration, and filename-safety helpers.

This module is the single source of truth for filename sanitization across the
map generator (``tools/map_generator``) and the local API (``tools/local_api``).
It is intentionally dependency-free so both sides can import it without pulling
in the heavy audio stack.

Rules enforced by :func:`sanitize_filename_component`:

* NFC-normalize the input (I9).
* Replace Windows-forbidden and control characters with spaces (I4).
* Collapse whitespace and trim leading/trailing dots and spaces (I7).
* Escape Windows reserved device names such as ``CON``/``NUL`` (I6).
* Bound the component length (I5).
"""

from __future__ import annotations

import unicodedata

# Windows forbidden filename characters plus ASCII control codes (handled by ord()).
WINDOWS_FORBIDDEN_FILENAME_CHARS = '<>:"/\\|?*'

# Reserved DOS device names (case-insensitive, with or without an extension).
WINDOWS_RESERVED_FILENAME_STEMS = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)

# Safe upper bound for a single path component / assembled filename. Chosen well
# below the 255-code-unit limit common to NTFS/APFS/ext4 to leave room for
# working-directory prefixes and tooling overhead.
DEFAULT_FILENAME_MAX_LENGTH = 200
DEFAULT_COMPONENT_MAX_LENGTH = 120


def normalize_unicode_text(value: str) -> str:
    """Return ``value`` normalized to Unicode NFC for stable cross-platform use."""
    return unicodedata.normalize("NFC", value)


def _is_windows_reserved_filename(value: str) -> bool:
    stem = value.split(".", 1)[0].strip().lower()
    return stem in WINDOWS_RESERVED_FILENAME_STEMS


def sanitize_filename_component(
    value: str,
    fallback: str = "untitled",
    *,
    max_length: int = DEFAULT_COMPONENT_MAX_LENGTH,
) -> str:
    """Return a filesystem-safe filename component.

    Never raises and never returns an empty string: an unusable input yields
    ``fallback`` (also sanitized/truncated).
    """
    normalized = normalize_unicode_text(value or "")
    cleaned = "".join(
        character
        if character not in WINDOWS_FORBIDDEN_FILENAME_CHARS and ord(character) >= 32
        else " "
        for character in normalized.strip()
    )
    compact = " ".join(cleaned.split()).strip(". ")

    if max_length > 0 and len(compact) > max_length:
        compact = compact[:max_length].strip(". ")

    if not compact:
        return sanitize_filename_component(fallback, "untitled", max_length=max_length)

    if _is_windows_reserved_filename(compact):
        compact = f"_{compact}"

    return compact


def build_osu_filename(
    artist: str,
    title: str,
    creator: str,
    version_name: str,
    *,
    max_length: int = DEFAULT_FILENAME_MAX_LENGTH,
) -> str:
    """Build a safe ``Artist - Title (Creator) [Version].osu`` filename."""
    artist_part = sanitize_filename_component(artist, "Unknown")
    title_part = sanitize_filename_component(title, "Unknown")
    creator_part = sanitize_filename_component(creator, "Unknown")
    version_part = sanitize_filename_component(version_name, "Unknown")

    stem = f"{artist_part} - {title_part} ({creator_part}) [{version_part}]"
    extension = ".osu"
    if len(stem) + len(extension) > max_length:
        stem = stem[: max_length - len(extension)].rstrip(" -([").strip(". ")
        if not stem:
            stem = "map"
    return f"{stem}{extension}"


def build_mapset_filename(
    artist: str,
    title: str,
    *,
    max_length: int = DEFAULT_FILENAME_MAX_LENGTH,
) -> str:
    """Build a safe ``Artist - Title`` mapset directory name."""
    stem = (
        f"{sanitize_filename_component(artist, 'Unknown')} - "
        f"{sanitize_filename_component(title, 'Unknown')}"
    )
    if len(stem) > max_length:
        stem = stem[:max_length].rstrip(" -").strip(". ")
    return stem or "generated-mapset"


# ---------------------------------------------------------------------------
# Transliteration / romanisation fallback (I3)
# ---------------------------------------------------------------------------

_TRANSLITERATION_TABLE: dict[str, str] = {}


def _register(source: str, target: str) -> None:
    _TRANSLITERATION_TABLE[source] = target
    upper_target = target.capitalize() if target else target
    _TRANSLITERATION_TABLE[source.upper()] = upper_target


def _build_transliteration_table() -> None:
    cyrillic = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
        "ђ": "dj", "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz", "ѝ": "i",
    }
    greek = {
        "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
        "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
        "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
        "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
    }
    georgian = {
        "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
        "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
        "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
        "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts", "ძ": "dz",
        "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
    }
    for source, target in (*cyrillic.items(), *greek.items(), *georgian.items()):
        _register(source, target)


_build_transliteration_table()


def romanize(text: str) -> str:
    """Best-effort romanisation/transliteration of ``text``.

    Handles Latin diacritics via Unicode decomposition plus built-in Cyrillic,
    Greek, and Georgian tables. Characters with no known mapping (for example
    Han or Kana) are preserved verbatim so no information is lost; callers
    should treat the result as a fallback suggestion, never a silent overwrite.
    """
    if not text:
        return ""
    output: list[str] = []
    for character in normalize_unicode_text(text):
        if ord(character) < 128:
            output.append(character)
            continue
        mapped = _TRANSLITERATION_TABLE.get(character)
        if mapped is None:
            # Accented forms (é, ά, …) decompose to a base character plus
            # combining marks; map the base and drop the marks.
            parts: list[str] = []
            for part in unicodedata.normalize("NFKD", character):
                if unicodedata.combining(part):
                    continue
                if ord(part) < 128:
                    parts.append(part)
                else:
                    parts.append(_TRANSLITERATION_TABLE.get(part, part))
            mapped = "".join(parts)
        output.append(mapped)
    return " ".join("".join(output).split())


def has_non_ascii(value: str) -> bool:
    """Return True when ``value`` contains any non-ASCII character."""
    return any(ord(character) > 127 for character in value)


def _clean_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = normalize_unicode_text(value).strip()
    return stripped or None


def resolve_unicode_metadata(
    title: str | None,
    artist: str | None,
    title_unicode: str | None,
    artist_unicode: str | None,
) -> tuple[str, str | None, str, str | None]:
    """Normalize metadata and apply Unicode/romanisation fallbacks.

    Returns ``(title, title_unicode, artist, artist_unicode)`` where:

    * every value is NFC-normalised;
    * an empty romanised field is filled by transliterating the Unicode value;
    * a native-script romanised field is mirrored into the Unicode field so
      exports can emit ``TitleUnicode``/``ArtistUnicode``.
    """
    clean_title = _clean_or_none(title) or ""
    clean_artist = _clean_or_none(artist) or ""
    clean_title_unicode = _clean_or_none(title_unicode)
    clean_artist_unicode = _clean_or_none(artist_unicode)

    if not clean_title and clean_title_unicode:
        clean_title = romanize(clean_title_unicode)
    if not clean_artist and clean_artist_unicode:
        clean_artist = romanize(clean_artist_unicode)
    if not clean_title_unicode and clean_title and has_non_ascii(clean_title):
        clean_title_unicode = clean_title
    if not clean_artist_unicode and clean_artist and has_non_ascii(clean_artist):
        clean_artist_unicode = clean_artist

    return clean_title, clean_title_unicode, clean_artist, clean_artist_unicode


def resolve_detected_tag_pair(
    primary: str | None,
    explicit_unicode: str | None,
) -> tuple[str | None, str | None]:
    """Split a detected audio tag into a (romanised, unicode) pair.

    * An explicit Unicode tag always becomes the Unicode value.
    * A non-ASCII primary value is treated as the native/Unicode value.
    * The romanised value is the primary when ASCII, otherwise a transliteration
      fallback of the native value.
    """
    primary_value = _clean_or_none(primary)
    explicit_value = _clean_or_none(explicit_unicode)
    native = explicit_value or (
        primary_value if primary_value and has_non_ascii(primary_value) else None
    )
    if native is None:
        return primary_value, None
    romanised = (
        primary_value
        if primary_value and not has_non_ascii(primary_value)
        else romanize(native)
    )
    return (romanised or None), native
