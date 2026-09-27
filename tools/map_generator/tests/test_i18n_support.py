"""Regression tests for the Phase 2 i18n and file-systems fixes (I1-I9).

Covers:
  * Unicode NFC normalization and transliteration fallback (I2/I3/I9).
  * Shared filename sanitization: reserved names, trailing dots, length cap (I4-I7).
  * Unicode metadata fallbacks (romanise when empty, mirror native titles).
  * ``.osu`` export emits ``TitleUnicode`` / ``ArtistUnicode`` (I1).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

for _mod in ("librosa", "soundfile"):
    sys.modules.setdefault(_mod, MagicMock())

from tools.text_utils import (
    build_mapset_filename,
    build_osu_filename,
    normalize_unicode_text,
    resolve_detected_tag_pair,
    resolve_unicode_metadata,
    romanize,
    sanitize_filename_component,
)

GEORGIAN_TITLE = "\u10db\u10d4\u10e0\u10d4 \u10e0\u10d0"  # "მერე რა"
GEORGIAN_ARTIST = "\u10d3\u10d0\u10d2\u10d3\u10d0\u10d2\u10d0\u10dc\u10d8"  # "დაგდაგანი"
CYRILLIC_TITLE = "\u041f\u0435\u0441\u043d\u044f"  # "Песня"
GREEK_TITLE = "\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac"  # "Ελληνικά"


class TransliterationTests(unittest.TestCase):
    def test_georgian(self) -> None:
        self.assertEqual(romanize(GEORGIAN_ARTIST), "dagdagani")

    def test_cyrillic(self) -> None:
        self.assertEqual(romanize(CYRILLIC_TITLE), "Pesnya")

    def test_greek_with_accent(self) -> None:
        self.assertEqual(romanize(GREEK_TITLE), "Ellinika")

    def test_latin_diacritics(self) -> None:
        self.assertEqual(romanize("Caf\u00e9 D\u00e9j\u00e0 Vu"), "Cafe Deja Vu")

    def test_cjk_is_preserved_when_unmappable(self) -> None:
        self.assertEqual(romanize("\u65e5\u672c\u8a9e"), "\u65e5\u672c\u8a9e")
        self.assertEqual(romanize("\u4e2d\u6587"), "\u4e2d\u6587")

    def test_empty_input(self) -> None:
        self.assertEqual(romanize(""), "")


class UnicodeNormalizationTests(unittest.TestCase):
    def test_precomposed_and_combining_forms_match(self) -> None:
        precomposed = "Caf\u00e9"  # é as one code point
        combining = "Cafe\u0301"  # e + combining acute
        self.assertEqual(normalize_unicode_text(precomposed), normalize_unicode_text(combining))
        self.assertEqual(len(normalize_unicode_text(combining)), 4)


class SanitizeFilenameTests(unittest.TestCase):
    def test_windows_reserved_names_are_escaped(self) -> None:
        self.assertEqual(sanitize_filename_component("CON"), "_CON")
        self.assertEqual(sanitize_filename_component("nul.txt"), "_nul.txt")
        self.assertEqual(sanitize_filename_component("LPT9"), "_LPT9")

    def test_forbidden_characters_become_spaces(self) -> None:
        self.assertEqual(sanitize_filename_component('a/b\\c:d*e?f'), "a b c d e f")

    def test_trailing_dots_and_spaces_are_stripped(self) -> None:
        self.assertEqual(sanitize_filename_component("  trailing.  "), "trailing")

    def test_non_ascii_is_preserved(self) -> None:
        self.assertEqual(sanitize_filename_component(GEORGIAN_ARTIST), GEORGIAN_ARTIST)

    def test_length_is_capped(self) -> None:
        self.assertEqual(len(sanitize_filename_component("x" * 500, max_length=120)), 120)

    def test_empty_input_uses_fallback(self) -> None:
        self.assertEqual(sanitize_filename_component("..."), "untitled")
        self.assertEqual(
            sanitize_filename_component("...", fallback="Unknown"), "Unknown"
        )

    def test_build_osu_filename_length_cap(self) -> None:
        filename = build_osu_filename("A" * 200, "B" * 200, "C" * 80, "Hard")
        self.assertTrue(filename.endswith(".osu"))
        self.assertLessEqual(len(filename), 200)

    def test_build_osu_filename_is_windows_safe(self) -> None:
        filename = build_osu_filename("a:b", "c?d", "e*f", "g|h")
        for forbidden in '<>:"/\\|?*':
            self.assertNotIn(forbidden, filename)
        self.assertTrue(filename.endswith(".osu"))

    def test_mapset_filename_is_capped(self) -> None:
        name = build_mapset_filename("A" * 300, "B" * 300)
        self.assertLessEqual(len(name), 200)


class MetadataFallbackTests(unittest.TestCase):
    def test_romanises_title_when_missing(self) -> None:
        title, title_unicode, artist, artist_unicode = resolve_unicode_metadata(
            "", "", GEORGIAN_TITLE, GEORGIAN_ARTIST
        )
        self.assertEqual(title, "mere ra")
        self.assertEqual(artist, "dagdagani")
        self.assertEqual(title_unicode, GEORGIAN_TITLE)
        self.assertEqual(artist_unicode, GEORGIAN_ARTIST)

    def test_mirrors_native_title_into_unicode(self) -> None:
        title, title_unicode, _artist, _artist_unicode = resolve_unicode_metadata(
            GEORGIAN_TITLE, "", None, None
        )
        self.assertEqual(title, GEORGIAN_TITLE)
        self.assertEqual(title_unicode, GEORGIAN_TITLE)

    def test_explicit_ascii_metadata_untouched(self) -> None:
        title, title_unicode, artist, artist_unicode = resolve_unicode_metadata(
            "Mere Ra", "Dagdagani", None, None
        )
        self.assertEqual((title, artist), ("Mere Ra", "Dagdagani"))
        self.assertIsNone(title_unicode)
        self.assertIsNone(artist_unicode)

    def test_detected_tag_pair_explicit_unicode(self) -> None:
        romanised, native = resolve_detected_tag_pair("Mere Ra", GEORGIAN_TITLE)
        self.assertEqual(romanised, "Mere Ra")
        self.assertEqual(native, GEORGIAN_TITLE)

    def test_detected_tag_pair_native_primary(self) -> None:
        romanised, native = resolve_detected_tag_pair(GEORGIAN_TITLE, None)
        self.assertEqual(native, GEORGIAN_TITLE)
        self.assertEqual(romanised, "mere ra")


class ExportUnicodeTests(unittest.TestCase):
    def _write_fixtures(self, tmp: Path, extra_osu: dict | None = None) -> tuple[Path, Path]:
        map_payload = {
            "title": "Mere Ra",
            "artist": "Dagdagani",
            "audio": "/api/workspaces/w/source-audio/source-audio.mp3",
            "approachTime": 720,
            "circleRadius": 34,
            "objects": [{"id": 1, "type": "circle", "x": 100, "y": 100, "time": 1000}],
        }
        if extra_osu is not None:
            map_payload["osu"] = extra_osu
        map_path = tmp / "hard.json"
        map_path.write_text(json.dumps(map_payload), encoding="utf-8")
        analysis_path = tmp / "analysis.json"
        analysis_path.write_text(
            json.dumps(
                {
                    "audio": {
                        "filename": "source-audio.mp3",
                        "durationMs": 20000,
                        "sampleRate": 22050,
                    },
                    "rhythm": {"bpm": 120, "offsetMs": 0, "beats": [], "onsets": []},
                    "energy": {
                        "frames": [],
                        "quietRegions": [],
                        "highEnergyRegions": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return map_path, analysis_path

    def test_explicit_unicode_params_are_written(self) -> None:
        from tools.map_generator.osu_format.export_pipeline import export_osu_file
        from tools.map_generator.osu_format.parser import parse_osu_text

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            map_path, analysis_path = self._write_fixtures(tmp)
            result = export_osu_file(
                map_path=map_path,
                analysis_path=analysis_path,
                output_path=tmp / "out.osu",
                title_unicode=GEORGIAN_TITLE,
                artist_unicode=GEORGIAN_ARTIST,
            )
            parsed = parse_osu_text(result.text)
            self.assertEqual(parsed.metadata.get("TitleUnicode"), GEORGIAN_TITLE)
            self.assertEqual(parsed.metadata.get("ArtistUnicode"), GEORGIAN_ARTIST)
            self.assertEqual(parsed.metadata.get("Title"), "Mere Ra")

    def test_extra_fields_unicode_is_preserved(self) -> None:
        from tools.map_generator.osu_format.export_pipeline import export_osu_file
        from tools.map_generator.osu_format.parser import parse_osu_text

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            map_path, analysis_path = self._write_fixtures(
                tmp,
                extra_osu={
                    "titleUnicode": GEORGIAN_TITLE,
                    "artistUnicode": GEORGIAN_ARTIST,
                },
            )
            result = export_osu_file(
                map_path=map_path,
                analysis_path=analysis_path,
                output_path=tmp / "out.osu",
            )
            parsed = parse_osu_text(result.text)
            self.assertEqual(parsed.metadata.get("TitleUnicode"), GEORGIAN_TITLE)
            self.assertEqual(parsed.metadata.get("ArtistUnicode"), GEORGIAN_ARTIST)

    def test_export_filename_uses_shared_sanitizer(self) -> None:
        from tools.map_generator.osu_format.export_pipeline import _build_osu_filename

        built = _build_osu_filename(GEORGIAN_ARTIST, GEORGIAN_TITLE, "osu-map-ai", "Hard")
        self.assertEqual(built, build_osu_filename(GEORGIAN_ARTIST, GEORGIAN_TITLE, "osu-map-ai", "Hard"))


if __name__ == "__main__":
    unittest.main()
