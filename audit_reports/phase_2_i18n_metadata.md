# Phase 2 Audit — i18n & File Systems Security

**Role:** Software Internationalization (i18n) & File Systems Security Specialist
**Scope:** Non-Latin (Unicode) audio-track support and file-export integrity for the generated
mapset pipeline (Python generator + local API + TypeScript editor/browser interop).
**Mode:** Read-only. No production code was modified for this audit.
**Date:** 2026-09-27

---

## 0. Executive Summary

The project has **strong path-traversal and encoding discipline at the low level** (explicit
UTF‑8 everywhere it writes `.osu`/`.json`, fixed ASCII upload filenames, RFC 5987 download
headers, UTF‑8 flagged zip entries) but the **i18n data flow is broken end-to-end for
generated maps**:

1. Users can enter `TitleUnicode` / `ArtistUnicode` in the UI, and the API **accepts and
   validates** them — but nothing ever writes them into the generated beatmap JSON, so the
   exporter never emits them. The Unicode fields are a dead end (I1).
2. Audio tag extraction reads only `title` / `artist` and never derives a separate
   romanised vs. native pair (I2).
3. There is **no transliteration/romanisation fallback** at all (I3).
4. Filename sanitization is implemented **three times with three different behaviors**
   (I4), is unbounded in length (I5), and ignores Windows reserved device names (I6).
5. One harness script reads JSON with the Windows locale encoding, which will crash on
   non-Latin metadata (I8).

Net effect: a Georgian/Japanese/Cyrillic song will export with only a native or only a
romanised name (never both), and only the *import* path round-trips Unicode correctly.

---

## 1. Unicode Metadata Extraction (audio tags: ID3 / Vorbis)

### 1.1 Detection entry point

`tools/local_api/metadata_service.py:140` `MetadataService.extract_audio_metadata()`:

```python
mutagen_easy = MutagenFile(audio_path, easy=True)
mutagen_full = MutagenFile(audio_path)
if mutagen_easy is not None:
    detected_title = _first_tag_value(mutagen_easy, "title")
    detected_artist = _first_tag_value(mutagen_easy, "artist")
```

`_first_tag_value` (`metadata_service.py:275`) simply returns the first list element for a
key from `tags`/mapping — it does no decoding, normalization, or field mapping.

### 1.2 Encoding behavior

- Mutagen returns Python `str` for both ID3 and Vorbis, so non-Latin script *content* is
  decoded correctly (this part is fine).
- The result is carried in `AudioMetadataSuggestion`
  (`tools/local_api/models.py:16`), which has only `title`, `artist`, `duration_ms`,
  `sample_rate`, `codec`, `bitrate_kbps` — **no `titleUnicode`/`artistUnicode` fields**.

### 1.3 Romanised vs. Unicode separation

There is **no separation of romanised and native fields on the audio-tag path**:

- `exif`-style romanisation is not read. For ID3 the standard native-vs-romanised carriers
  (`TSOT`/`TSOP` sort frames, `TXXX` user frames, `APIC` for artwork) are ignored; for
  Vorbis only the easy `TITLE`/`ARTIST` keys are read.
- The only place the concept exists is the **`.osu` import** path:
  `tools/map_generator/osu_format/hitobject_converter.py:298`
  ```python
  "titleUnicode": parsed.metadata.get("TitleUnicode"),
  "artistUnicode": parsed.metadata.get("ArtistUnicode"),
  ```
  and the local-API model (`models.py:142-144`):
  ```python
  title_unicode: str | None = Field(default=None, alias="titleUnicode")
  artist_unicode: str | None = Field(default=None, alias="artistUnicode")
  ```

The UI collects them (`src/generator/components/MetadataForm.ts:88-105`, "Unicode Title" /
"Unicode Artist"; persisted in `src/generator/GeneratorPersistence.ts:158-162` and
`GeneratorModels.ts:70-72, 313-343`), and the API validates their length
(`metadata_service.py:212-225`). See I1/I2.

---

## 2. `.osu` Header Conversion (`Title` / `TitleUnicode` / `Artist` / `ArtistUnicode`)

### 2.1 Writer

`tools/map_generator/osu_format/metadata_converter.py:40-66`:

```python
"Title": beatmap.title,
**({"TitleUnicode": title_unicode}
   if (title_unicode := _read_nested_string(beatmap.extra_fields, ["osu", "titleUnicode"]))
   else {}),
"Artist": beatmap.artist,
**({"ArtistUnicode": artist_unicode}
   if (artist_unicode := _read_nested_string(beatmap.extra_fields, ["osu", "artistUnicode"]))
   else {}),
```

The TS mirror is identical in intent: `src/shared/osuInterop.ts:349-351` emits
`TitleUnicode`/`ArtistUnicode` only when present in `extraFields.osu`. Parsing side:
`src/shared/osuInterop.ts:915-916`.

### 2.2 The data-flow gap (I1)

`TitleUnicode`/`ArtistUnicode` are read **only** from the project beatmap JSON's
`extra_fields["osu"]`. That dictionary is populated in exactly two ways:

- **Import** (`hitobject_converter.py:291-315`) — an imported `.osu` carries its
  `TitleUnicode`/`ArtistUnicode` through.
- **Generation** — never. The generation call
  (`tools/local_api/pipeline_runner.py:537-569`) passes only:
  ```python
  title=manifest.metadata.title,
  artist=manifest.metadata.artist,
  ```
  and `generate_beatmap_from_analysis` (`tools/map_generator/beatmap_generator.py:108-108`)
  has no unicode parameters; `generator_metadata` is stored under the `generator` payload
  key (`beatmap_generator.py:386-387`), **not** top-level, so it does not become
  `extra_fields`.

A repo-wide search for `title_unicode|artist_unicode|titleUnicode|artistUnicode` in
`*.py` returns **zero** writer-side hits in the generation path (only the import reader,
the exporter reader, the model, and validation). Therefore:

> A user-supplied Unicode Title/Artist is silently dropped from every newly generated
> `.osu`; only imported maps can ever emit `TitleUnicode`/`ArtistUnicode`.

### 2.3 Encoding of the `.osu` file

`tools/map_generator/osu_format/writer.py:32-38`:
```python
path.write_text(text, encoding="utf-8", newline="\n")
```
UTF-8 without BOM and LF newlines — correct for osu!. The reader
(`parser.py:17-19`) uses `encoding="utf-8-sig"`, tolerating both BOM and no-BOM inputs —
correct. Browser import uses `await file.text()` (`src/editor/EditorMapLoader.ts:98`),
which the WHATWG spec mandates to be UTF-8 — correct.

### 2.4 Download naming

`tools/local_api/app.py:218-223` serves artifacts with
`FileResponse(..., filename=artifact.file_name)`. Starlette emits an RFC 5987
`filename*=utf-8''…` header for non-ASCII names — correct. `artifact.file_name` comes
unchanged from `file_path.name` (`artifact_service.py:_scan_group`), so native-script
filenames are preserved on download (but see I4–I7 for how they are produced).

---

## 3. File System & Path Sanitization

### 3.1 Upload normalization (strong)

`tools/local_api/upload_service.py:35,66,77` rewrites every user-uploaded filename to a
**fixed ASCII name**:

```python
normalized_name = f"source-audio{suffix}"   # audio
normalized_name = f"background{suffix}"     # background
```

The original filename is retained only as `originalFilename` in the manifest JSON. The
browser audio path is derived from the normalized name
(`artifact_service.build_audio_preview_url` → `…/source-audio/source-audio.mp3`), and the
exporter extracts the basename (`timing_converter.osu_audio_filename_from_browser_path`).
Consequently the `.osu` `AudioFilename` and the packaged audio file are **always safe
ASCII** in the API path. This is the single most effective i18n/FS control in the system.

### 3.2 Filename builders — three divergent sanitizers (I4)

| Location | Function | Behavior |
|---|---|---|
| `tools/local_api/security.py:28-35` | `sanitize_filename_component` | strips `<>:"/\|?*` + control chars, **replaces with a space**, collapses whitespace, strips leading/trailing `. `, fallback `untitled` |
| `tools/map_generator/osu_format/export_pipeline.py:348-350` | `_sanitize_filename` | removes forbidden chars entirely (**no space**), only `.strip()`, fallback `Unknown`, **does not strip trailing dots** |
| `src/shared/osuInterop.ts:807-817` | `buildOsuFilename` inline `sanitize` | removes forbidden chars entirely, `.trim()`, fallback `Unknown`, **does not collapse internal whitespace or strip trailing dots** |

`pipeline_runner.py:1066-1076` uses the local-API sanitizer; `export_pipeline.py:342-345`
uses the exporter sanitizer; the browser editor uses the TS one. The same metadata can thus
produce **three different filenames**. All three preserve non-ASCII characters (so native
scripts survive), which is good, but the divergence is a correctness/interop risk.

### 3.3 Length and Windows legality (I5, I6, I7)

- The local-API config allows `max_title_length=160`, `max_artist_length=160`,
  `max_creator_length=80` (`tools/local_api/config.py:67-71`). The `.osu` filename is
  `"{artist} - {title} ({creator}) [{version}].osu"` with no truncation. Worst-case is
  > 400 characters, exceeding the 255-code-unit limit of NTFS/APFS/ext4 components; the
  write then fails with `OSError` (wrapped as `MapGeneratorError`), aborting export.
- **Reserved DOS device names** (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`,
  optionally with an extension) are not handled. A title/artist equal to `CON` yields an
  uncreatable file on Windows.
- **Trailing dots** are stripped only by `security.sanitize_filename_component`; the other
  two sanitizers allow them. Windows silently removes trailing dots, so a directory
  listing mismatch can occur (stale-output cleanup in
  `export_pipeline._remove_stale_mapset_outputs` compares `existing_path.name` against
  planned names).
- **Unicode normalization (NFC/NFD)** is never applied. A name typed on macOS (NFD) and
  re-read on Windows/Linux (NFC) can compare/sort as different (I9).

### 3.4 Mapset directory and `.osz` name

`pipeline_runner.py:962-1006` `_package_mapset` builds:

```python
mapset_name = sanitize_filename_component(f"{artist} - {title}", fallback="generated-mapset")
mapset_directory = paths.exports_mapset_root / mapset_name
...
package_path = paths.exports_mapsets_dir / f"{mapset_name}.osz"
```

`_verify_package_contents` (`pipeline_runner.py:997-1036`) re-derives the same name and
asserts `manifest.audio.normalized_filename in archive.namelist()`. Because the audio name
is fixed ASCII and the mapset name is derived deterministically from the same sanitizer,
this is self-consistent. Note it re-derives (not persists) the name, so any future change
to the sanitizer must be mirrored here.

### 3.5 Archive (`.osz`) integrity

`tools/map_generator/osu_format/mapset_packager.py`:

- Entry names are validated flat: `_validate_archive_name` (`:101-104`) rejects any name
  containing `/` after `normalize_osu_relative_path`.
- Entries are written with `zipfile.ZipInfo` + `archive.writestr(info, source_path.read_bytes())`
  (`:88-92`) — binary-safe, no text re-encoding.
- Python's `zipfile` sets the general-purpose bit 11 (`0x800`, UTF‑8 filename flag)
  automatically for non-ASCII entry names, and `create_system = 0` (MS-DOS). So Unicode
  entry names are correctly flagged. (In the API path entry names are ASCII anyway.)
- `deterministic_archive_timestamp()` gives reproducible archives.
- Read-back verification uses `zipfile.ZipFile(...).namelist()`, which honors the UTF‑8
  flag — safe.

### 3.6 Traversal defenses (strong)

- `security.ensure_safe_relative_path` (`:51-58`) and `resolve_workspace_relative_path`
  (`:61-66`) reject `../` and escape beyond the workspace root.
- `timing_converter.normalize_osu_relative_path` (`:10-21`) rejects absolute paths,
  `../`, and Windows drive letters (`_looks_like_windows_drive`).
- `utils.derive_browser_audio_path`/`resolve_browser_audio_path` constrain audio to
  `public/` and require a leading `/`.
- `workspace_manager` validates `normalized_filename` has no directory component
  (`:186-192`).
- `osuInterop.ts:Qe` mirrors the Python relative-path normalization for the browser side.

### 3.7 JSON/text I/O encoding

All production writers use explicit UTF‑8: `utils.write_json`
(`json.dump(..., ensure_ascii=False)` + `encoding="utf-8"`, `:40-44`), `writer.write_osu_file`
(`utf-8`), `pipeline_runner._append_log` (`utf-8`). Readers use `utf-8-sig`
(`analysis_io.load_json_file`, `parser.parse_osu_file`, report readers). Export reports are
written via `write_json` (UTF‑8).

**Exception (I8):** the harness `tools/e2e_generation.py` reads JSON without an encoding:
`json.loads(output_path.read_text())` and `map_path.read_text()` at lines 184, 239, 318, 393.
On Windows `Path.read_text()` defaults to the locale codec (commonly `cp1252`), so any
non-ASCII character in the map/analysis JSON — which is guaranteed because
`write_json` uses `ensure_ascii=False` — raises `UnicodeDecodeError`.

---

## 4. Fallback Romanisation

**None exists.** A repository-wide search for `romaniz|translit|romanis|unidecode` yields no
hits in `tools/` or `src/`. The dependency manifests
(`tools/map_generator/requirements.txt`, `tools/local_api/requirements.txt`) contain no
transliteration library. If an audio file's tag is native-script and the user leaves the
required `Title`/`Artist` fields filled with the same native string, the generated `.osu`
writes that native string into `Title`/`Artist` (and, per I1, no `TitleUnicode`). osu!'s
convention is `Title` = romanised, `TitleUnicode` = native; the project cannot satisfy this
automatically or even preserve the pair.

---

## 5. Defect Table

| ID | Severity | Location | Description |
|---|---|---|---|
| I1 | 🔴 High | `pipeline_runner.py:537-569`; exporter reads `extra_fields["osu"]["titleUnicode"]` (`metadata_converter.py:48-57`) | User-supplied `TitleUnicode`/`ArtistUnicode` are validated then **never written** into generated beatmap JSON, so generated `.osu` files omit them. Only imported maps round-trip Unicode. |
| I2 | 🔴 High | `metadata_service.py:140-185`; `models.py:16-24` | Audio tag extraction reads only easy `title`/`artist`; `AudioMetadataSuggestion` has no Unicode field. No ID3 `TSOT/TSOP/TXXX` or Vorbis native-key handling. |
| I3 | 🟠 Medium | repo-wide (absent) | No transliteration/romanisation fallback; native-only tags leave `Title`/`Artist` non-romanised and never produce a Unicode pair. |
| I4 | 🟠 Medium | `security.py:28`; `export_pipeline.py:348`; `osuInterop.ts:807-817` | Three divergent filename sanitizers (space-replacement vs removal vs TS removal) produce inconsistent filenames for identical metadata. |
| I5 | 🟠 Medium | `pipeline_runner.py:1066-1076`; `export_pipeline.py:342-345`; `config.py:67-71` | No filename length bounding; 160+160+80-char metadata can exceed the 255-char filesystem limit and abort export with `OSError`. |
| I6 | 🟠 Medium | all three sanitizers | Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1..`, `LPT1..`) are not rejected, producing uncreatable filenames on Windows. |
| I7 | 🟡 Low | `export_pipeline.py:348-350`; `osuInterop.ts:810-816` | Trailing dots/spaces are not stripped by two of the three sanitizers; Windows strips them silently, risking stale-output cleanup mismatches. |
| I8 | 🟠 Medium | `tools/e2e_generation.py:184,239,318,393` | `read_text()` without `encoding=` uses the Windows locale codec (cp1252) and raises `UnicodeDecodeError` on non-ASCII JSON written by `ensure_ascii=False`. |
| I9 | 🟡 Low | all three sanitizers | No Unicode normalization (NFC/NFD) on filenames/metadata; cross-OS filename comparison can diverge. |
| I10 | 🟡 Low | `metadata_converter.py:40-66`; `osuInterop.ts:345-352` | No canonicalization/dedup of `Title` vs `TitleUnicode` (or `Artist` vs `ArtistUnicode`); identical or native-only pairs are emitted verbatim. |

---

## 6. Verified Positives

- **P1** Uploaded audio/background filenames are normalized to fixed ASCII names
  (`upload_service.py:35,77`), removing user-controlled filesystem names.
- **P2** All production `.osu`/`.json` writes are explicit UTF‑8; `.osu` is UTF‑8 without BOM
  with LF newlines (`writer.py:34`); readers tolerate BOM (`utf-8-sig`).
- **P3** Robust path-traversal defenses (`security.py:51-66`, `timing_converter.py:10-21`,
  `workspace_manager.py:186-192`, archive flat-name check).
- **P4** `.osz` entries are written binary-safe with Python `zipfile` (UTF‑8 filename flag set
  automatically for non-ASCII) and deterministic timestamps.
- **P5** Browser `.osu` import decodes via `File.text()` — spec-mandated UTF‑8
  (`EditorMapLoader.ts:98`).
- **P6** Non-ASCII download names are served with RFC 5987 `filename*=utf-8''…`
  (Starlette `FileResponse`, `app.py:220-238`).
- **P7** The TS `.osu` writer/parser handles `TitleUnicode`/`ArtistUnicode`
  (`osuInterop.ts:349-351, 915-916`), so the editor's import→export round-trip preserves
  Unicode.
- **P8** JSON is written with `ensure_ascii=False`, preserving native scripts rather than
  escaping them.

---

## 7. Recommendations (no code changed)

1. **Fix the Unicode dead-end (I1):** thread `manifest.metadata.title_unicode` /
   `artist_unicode` into every generation entry point
   (`pipeline_runner._generate_base_map`, candidate/evolution/hybrid pipelines) and persist
   them as `extra_fields["osu"]["titleUnicode"/"artistUnicode"]` on the project beatmap
   JSON, so both the Python and TS exporters emit them. Add a round-trip test:
   set Unicode metadata → generate → export → parse → assert headers present.
2. **Extract native tags (I2):** on the audio path, read raw ID3 frames (`TSOT`/`TSOP`,
   `TXXX`) and Vorbis native keys, and populate new `AudioMetadataSuggestion.titleUnicode`/
   `artistUnicode` fields for UI prefill; never overwrite user input silently.
3. **Optional romanisation (I3):** offer a transliteration fallback (e.g. an optional
   `unidecode`-style dependency) behind a config flag, with the user's explicit value always
   winning; surface it as a suggestion, not an automatic rewrite.
4. **Unify and harden filename handling (I4–I7, I9):** one shared sanitizer (Python) mirrored
   by the TS module, that (a) normalizes to NFC, (b) strips/rejects Windows reserved names,
   (c) strips trailing dots/spaces, (d) bounds each component and the total filename length
   (e.g. truncate with an 8-char hash suffix), and (e) is used for `.osu`, mapset dir, and
   `.osz` names consistently.
5. **Fix harness encoding (I8):** add `encoding="utf-8"` to the `read_text()` calls in
   `tools/e2e_generation.py`.
6. **Add i18n regression coverage:** fixtures with Georgian (`დაგდაგანი`), Japanese
   (Kanji/Kana), Cyrillic, and an NFD/NFC accent pair, asserted through
   generate → export → package → parse for both `TitleUnicode` emission and filename
   integrity.

---

## 8. Evidence Index (key references)

- Tag extraction: `tools/local_api/metadata_service.py:140-185, 275-291`
- Unicode model/validation: `tools/local_api/models.py:16-24, 139-144`; `metadata_service.py:212-225`
- UI collection: `src/generator/components/MetadataForm.ts:88-105`;
  `src/generator/GeneratorPersistence.ts:158-162`; `src/generator/GeneratorModels.ts:70-72, 313-343`
- Generation data flow: `tools/local_api/pipeline_runner.py:537-569`;
  `tools/map_generator/beatmap_generator.py:108-108, 386-387`
- Export metadata: `tools/map_generator/osu_format/metadata_converter.py:40-66`;
  `src/shared/osuInterop.ts:296-297, 349-351, 915-916`
- Import metadata: `tools/map_generator/osu_format/hitobject_converter.py:291-315`
- File writing: `tools/map_generator/osu_format/writer.py:32-38`; `utils.py:40-44`
- File reading: `tools/map_generator/osu_format/parser.py:17-19`; `analysis_io.py:13`;
  `tools/e2e_generation.py:184,239,318,393`
- Sanitizers: `tools/local_api/security.py:28-35`;
  `tools/map_generator/osu_format/export_pipeline.py:342-350`;
  `src/shared/osuInterop.ts:807-817`; `src/editor/EditorExporter.ts:209-216`
- Package/zip: `tools/map_generator/osu_format/mapset_packager.py:39-104`;
  `tools/local_api/pipeline_runner.py:962-1036`
- Upload normalization: `tools/local_api/upload_service.py:35,66,77`
- Path safety: `tools/local_api/security.py:51-66`;
  `tools/map_generator/osu_format/timing_converter.py:10-21`
- Download headers: `tools/local_api/app.py:218-238`
