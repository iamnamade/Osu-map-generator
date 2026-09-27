# OSU Format Interoperability

## 1. Purpose

Phase 8A adds original circle-only interoperability between this project's JSON beatmap format and osu!standard `.osu` / `.osz` assets.

This implementation is original. It does not use official osu! source code, existing osu! parser/writer libraries, remote services, or official star-rating logic.

## 2. Supported `.osu` subset

Phase 8A parses and writes:

- `[General]`
- `[Editor]`
- `[Metadata]`
- `[Difficulty]`
- `[Events]`
- `[TimingPoints]`
- `[Colours]`
- `[HitObjects]`

Comments and blank lines are ignored during parsing. Unknown safe fields are preserved where practical through stored metadata on imported maps and re-exported browser/Python output.

## 3. Circle hit-object conversion

Phase 8A supports circles only.

Every exported project circle becomes one `.osu` hit object with:

- `x`
- `y`
- `time`
- circle type flag
- hit sound
- hit sample data

The project already uses a logical `512 x 384` playfield, so coordinates map directly.

Export validation requires:

- finite coordinates and times
- `0 <= x <= 512`
- `0 <= y <= 384`
- non-negative integer timestamps
- unique integer object ids
- strictly increasing export order

Temporary editor-only fields such as `editorId` are stripped from exported beatmaps.

## 4. Timing-point generation

Phase 8A exports one primary uninherited timing point from the shared analysis BPM and offset estimate.

Current exported defaults:

- meter: `4`
- sample set id: `1`
- sample index: `0`
- volume: `70`
- uninherited: `1`
- effects: `0`

Beat length uses:

`beatLengthMs = 60000 / bpm`

If analysis does not provide a positive BPM, export falls back to `120 BPM` and records a warning.

Songs with BPM changes are not modeled yet. The code is structured so multiple timing points can be added in Phase 8B or later.

## 5. BPM and offset conversion

Python and TypeScript both read the same shared constants file: [src/shared/osuInteropConstants.json](/C:/Users/Admin/Desktop/osu%20(vtestav)/src/shared/osuInteropConstants.json).

The current timing conversion uses:

- exported offset: first shared analysis offset in milliseconds
- exported BPM: shared analysis BPM estimate
- fallback BPM: `120`

## 6. Difficulty conversion formulas

Circle size uses the shared approximation:

`CircleSize = clamp((54.4 - circleRadius) / 4.48, 0, 10)`

Approach rate uses the shared piecewise approximation:

- if `approachTime >= 1200`: `AR = (1800 - approachTime) / 120`
- otherwise: `AR = 5 + (1200 - approachTime) / 150`

Values are rounded consistently and clamped to legal `0..10` ranges.

Phase 8A preset values:

- Easy: `HP 4.0`, `OD 4.0`
- Normal: `HP 5.5`, `OD 5.5`
- Hard: `HP 7.0`, `OD 7.0`

Slider fields are still written even though sliders are unsupported:

- `SliderMultiplier: 1.4`
- `SliderTickRate: 1`

Phase 8A does not calculate official star ratings.

## 7. Metadata conversion

Export writes:

- `Title`
- `TitleUnicode` when present
- `Artist`
- `ArtistUnicode` when present
- `Creator`
- `Version`
- `Source`
- `Tags`
- `BeatmapID`
- `BeatmapSetID`

Default creator:

- `osu-map-ai`

Version names are derived from imported metadata or editor source type when possible, for example:

- `Easy`
- `Normal`
- `Hard`
- `Hybrid Easy`
- `Hybrid Normal`
- `Hybrid Hard`
- `Imported`

CLI overrides are supported through `--creator`, `--version-name`, `--beatmap-id`, and `--beatmap-set-id`.

## 8. Audio filename handling

Project beatmaps use browser paths such as:

`/audio/test-song.mp3`

Exported `.osu` files must use relative filenames such as:

`AudioFilename: test-song.mp3`

Absolute Windows paths are rejected. Relative path normalization is shared across Python and TypeScript.

## 9. Events and backgrounds

Phase 8A supports an optional background filename in `[Events]`.

When no background is provided, the `[Events]` section is still written as a valid empty section.

The tooling does not automatically copy or discover external artwork.

## 10. Import behavior

Import flow:

1. Read UTF-8 text.
2. Validate the format header.
3. Parse supported sections.
4. Parse metadata and difficulty values.
5. Parse timing points.
6. Parse hit objects.
7. Detect unsupported sliders, spinners, holds, and unknown objects.
8. Convert circles into project JSON objects.
9. Normalize ids and output ordering.
10. Validate project-map compatibility with the existing Phaser/editor/validator stack.

Imported beatmaps remain compatible with the existing browser game, editor, and Python validation pipeline.

## 11. Unsupported object handling

Phase 8A support policy:

- Circle: supported
- Slider: unsupported
- Spinner: unsupported
- Hold object: unsupported

CLI and browser import default to reject mode.

Available modes:

- `reject`
- `skip`

Skip mode never discards unsupported objects silently. Reports always include counts and warnings.

## 12. Export commands

Single-map export:

```bash
python -m tools.map_generator.cli export-osu \
  --map public/maps/hybrid/test-song-normal.json \
  --analysis public/analysis/test-song-analysis.json \
  --output public/exports/osu/test-song-normal.osu \
  --creator "osu-map-ai" \
  --version-name "Hybrid Normal"
```

Mapset export:

```bash
python -m tools.map_generator.cli export-osu-mapset \
  --maps-dir public/maps/hybrid \
  --analysis public/analysis/test-song-analysis.json \
  --audio public/audio/test-song.mp3 \
  --output-dir public/exports/osu/test-song \
  --package public/exports/mapsets/test-song.osz
```

## 13. Import commands

```bash
python -m tools.map_generator.cli import-osu \
  --input path/to/map.osu \
  --output public/maps/imported/imported-map.json \
  --unsupported reject
```

## 14. Validation commands

```bash
python -m tools.map_generator.cli validate-osu \
  --input public/exports/osu/test-song-normal.osu
```

Validation checks include:

- format header
- required sections
- required difficulty fields
- audio filename rules
- timing-point presence
- coordinate bounds
- timestamp validity
- duplicate hit-object lines
- unsupported-object counts

## 15. Mapset packaging and `.osz` structure

Packaging command:

```bash
python -m tools.map_generator.cli package-osz \
  --maps-dir public/exports/osu/test-song \
  --audio public/audio/test-song.mp3 \
  --output public/exports/mapsets/test-song.osz
```

Phase 8A `.osz` archives contain only:

- exported `.osu` files
- the referenced audio file
- an optional explicitly supplied background file

Archive entry ordering is deterministic, archive timestamps are pinned to `2020-01-01 00:00:00`, and filenames must remain flat and relative.

## 16. Browser editor integration

The editor now supports:

- `Export Project JSON`
- `Export .osu Circle Map`
- `Export Edit Log`
- `Export Editor Project`

It also supports:

- `Import Project JSON`
- `Import Circle-only .osu`
- `Import Editor Project`

Browser `.osu` export writes the text file directly from shared TypeScript conversion logic.

Python remains authoritative for:

- CLI export/import
- validation reports
- mapset packaging
- `.osz` creation

## 17. Imported-map catalog integration

CLI imports written to `public/maps/imported/*.json` update:

- `public/maps/imported/index.json`

The browser game and editor load that manifest at startup and only add imported entries whose referenced project JSON file actually exists.

Local one-off browser file imports are not persisted into the catalog automatically.

## 18. Round-trip guarantees

For circle-only content, the Phase 8A target guarantees are:

- object count preserved
- coordinates preserved
- timestamps preserved
- title preserved
- artist preserved
- audio filename meaning preserved
- difficulty values remain within the documented conversion rules

Round-trip JSON is not expected to be byte-for-byte identical because ids and metadata may be normalized.

## 19. Determinism

Phase 8A is designed to be deterministic for:

- `.osu` writer ordering
- shared conversion formulas
- export text output
- `.osz` archive entry ordering
- `.osz` archive timestamps

Repeated exports of the same validated input should produce identical `.osu` text.

## 20. Known limitations

- Circles only. Sliders, spinners, and hold objects are deferred.
- No official star rating calculation.
- No BPM-change modeling yet.
- Browser import still depends on referenced audio files existing under `public/audio/...` if the map should play locally after import.
- Browser export does not package `.osz` archives.

## 21. Copyright and asset responsibility

The user is responsible for the rights to any packaged audio or background images.

The tooling only prepares locally supplied assets. It does not grant redistribution rights.

## 22. Why sliders and spinners are deferred to Phase 8B

Sliders and spinners would require new gameplay logic, editor interactions, path modeling, import/export geometry rules, and validation heuristics.

Phase 8A intentionally limits scope to reliable circle-map interoperability first.
