# Architecture — osu! Map AI Generator

System architecture and the quality achievements locked in across the six
audit phases. For per-feature usage guides see `docs/`; for the audit reports
that drove this work see `audit_reports/phase_1_density.md` through
`phase_6_master_roadmap.md`.

---

## 1. System Overview

The project is a three-layer system that turns an audio file into a playable
osu! beatmap:

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (TypeScript + Vite + Phaser)                      │
│  generator.html  ·  editor.html  ·  src/generator, src/editor │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (localhost FastAPI bridge)
┌──────────────────────────▼──────────────────────────────────┐
│  Local API (tools/local_api — Python)                       │
│  app.py · upload_service · metadata_service · job_manager    │
│  pipeline_runner · workspace_manager · artifact_service      │
│  cleanup_service · security.py (magic bytes, path safety)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ in-process calls
┌──────────────────────────▼──────────────────────────────────┐
│  Map Generator engine (tools/map_generator — Python)        │
│  audio_analyzer → event_selector → rhythm/ → placement/      │
│  → sliders/ · spinners/ · postprocess/ · validation/         │
│  → osu_format/ (.osu export, .osz packaging)                 │
└─────────────────────────────────────────────────────────────┘
```

Supporting packages: `tools/map_generator/difficulty` (star rating),
`sections/`, `patterns/`, `phrase/`, `evolution/`, `rebalance/`, `recovery/`,
`replay/`, `candidates/`, `geometry/` (collision engine).

---

## 2. Six-Phase Audit Achievements

### 2.1 Ranking Criteria compliance (density, clearance, stacking)

Engine + tests pinning osu! Ranking Criteria behavior:

- **Object density bands** (`config.py` presets, enforced in
  `beatmap_generator._enforce_density_minimum`): Easy 0.8–2.0 obj/s,
  Normal 1.3–2.0 obj/s, Hard 2.5–3.8 obj/s. Pinned by
  `tests/test_density_pin.py` (P0.3) so a silent regression fails CI.
- **Minimum 35% slider ratio** for Normal/Hard, enforced at generation and
  re-checked after post-processing (`tests/test_slider_ratio_e2e.py`).
- **Spinner guarantees**: at least one spinner per difficulty, integer
  timestamps, `endTime > time`, and clearance windows that reject placement
  when a slider spans the candidate window
  (`spinners/spinner_pipeline._check_spinner_clearance`,
  `tests/test_density_phase2_fixes.py`).
- **Stacking / anti-overlap**: the `geometry/collision.py` engine plus the
  `rebalance/collisions.py` resolver prevent "ninja"/buried circles
  (radius-aware stacking, polyline distance checks), with an
  `evolution/` `COLLISION_FREE` hard gate (`tests/test_collision.py`).
- **Spinner recovery time** and rest intervals after spinners are respected
  for Easy/Normal/Hard per the RC.
- **Playfield containment**: `clamp_to_playfield` keeps objects (including
  curved slider control points) inside the 512×384 osu! coordinate space.

### 2.2 Unicode / i18n metadata pipeline

`tools/text_utils.py` (covered by `tests/test_i18n_support.py`):

- **NFC normalization** of all incoming metadata (title, artist, creator).
- **Script detection + transliteration fallback** (`romanize`) for Cyrillic,
  Greek, Georgian, CJK and other non-Latin metadata, so mapset filenames and
  `.osu` fields stay filesystem- and client-safe.
- **`TitleUnicode` / `ArtistUnicode` + ASCII mirror fields** emitted by the
  `.osu` exporter (audit I1): clients show native glyphs while the romanized
  pair guarantees interoperability.
- **Shared filename sanitization**: Windows reserved names, trailing dots,
  component length caps, one code path used by uploads, exports, and the
  workspace manifest (audit I4–I7).

### 2.3 Modular PlacementStrategy architecture (Standard / Catch / Mania seams)

`tools/map_generator/placement/` (P2.1, `tests/test_placement_strategy.py`):

- `PlacementStrategy` ABC (`base.py`) defines the seam: `playfield_width/height`,
  `generate(PlacementContext)`, and a `transform_position` hook.
- `OsuStandardPlacementStrategy` (`osu_standard.py`) is the production
  512×384 osu!standard placement (pattern-intelligence path), pinned to a
  golden baseline so refactors are provably regression-free.
- `OsuCatchPlacementStrategy` and `OsuManiaPlacementStrategy`
  (`osu_modes.py`) reuse the standard engine and remap coordinates:
  catch flattens `y` onto the catcher lane; mania quantizes `x` into
  column centers (default 4 columns, constructor-configurable).
- Strategies register by name in `placement/__init__.py`
  (`register_placement_strategy` / `get_placement_strategy` /
  `list_placement_strategies`); new modes plug in without editing the
  generator core. `position_generator.generate_positions` remains the
  public entry point and defaults to `"standard"`.

### 2.4 Security hardening (P0 batch, `tools/local_api/`)

- **Magic-byte upload validation** (`security.py`, P0.4): uploads are
  identified by actual bytes, not client-declared MIME —
  `ID3`/`OggS`/`fLaC` headers, MPEG frame sync, RIFF containers
  (WAV/WEBP disambiguated by fourcc at offset 8), `\x89PNG` and JPEG
  (`\xff\xd8\xff`) signatures. Canonical `Content-Type` values are derived
  from the sniff and served back to clients.
- **Per-stage execution watchdog** (`job_manager.py`, P0.2): every pipeline
  stage runs under a watchdog thread budget; overruns raise
  `StageWatchdogTimeout`, cancel the job, and cannot orphan the workspace.
  Orphaned `running` workspaces are reconciled on restart.
- **Atomic workspace manifest writes** (`workspace_manager.py`, P2.3):
  manifests are written to a sibling temp file and moved into place with
  `os.replace`, so readers never observe torn state and crashes leave the
  previous manifest intact.
- **Path-safety defense in depth**: workspace IDs are UUID-validated,
  stored names resolve under the workspace root, extension whitelists gate
  uploads, and streaming size caps bound memory use.
- **Scratch-directory hygiene** (P2.2): the e2e pipeline
  (`tools/e2e_generation.py`) discards stale state before runs and always
  removes its `.tmp-e2e-generation` working directory afterwards.
- **Bounded job-event log** (P3.4): job events live in a ring buffer (last
  200, monotonic `index`) and clients tail with a `?since=` watermark, so
  neither the API process nor the frontend accumulates an unbounded log
  (`tests/test_bounded_job_log.py`).

### 2.5 Timing & export correctness (P0 batch)

- **Multi-BPM timing export**: timing points are emitted per BPM region
  instead of one global assumption, keeping slider velocity correct on
  tempo changes.
- **Integer timestamps**: spinner and hit-object times are integers
  end-to-end (`tests/test_spinner_fix.py`, osu! converter contract).

---

## 3. Unified Validation Command (P3.3)

One exit-code-aware pass over every suite:

```bash
python tools/validate_all.py   # or: npm run validate:all
```

Stages (all run even if an earlier one fails; final exit code is non-zero
if any stage fails):

| # | Stage | Command |
|---|-------|---------|
| 1 | Python engine suite | `python -m unittest discover -s tools/map_generator/tests -t .` |
| 2 | Python local-API suite | `python -m unittest discover -s tools/local_api/tests -t .` |
| 3 | TypeScript typecheck | `tsc --noEmit` |
| 4 | Vitest frontend suite | `vitest run` |

Flags: `--skip-python`, `--skip-typecheck`, `--skip-vitest`, `--list`.
Python discovery is package-rooted (`-t .`) so the `tools.*` package layout
and package-relative test imports stay intact.

---

## 4. Pipeline Data Flow

1. **Analyze** — `audio_analyzer.analyze_audio` decodes audio (librosa),
   extracts BPM, beats, onsets, energy frames, quiet/high-energy regions,
   kiai sections, and enhanced multi-layer features (versioned
   `analysis_version: 2`).
2. **Select events** — `event_selector` chooses hit-object moments from
   beats/onsets under density targets.
3. **Rhythm & difficulty shaping** — `rhythm/rhythm_density` enforces
   density floors and maximum gaps (energy-aware), `phrase/` and
   `sections/` shape musical phrasing and section dynamics.
4. **Place objects** — `placement/` strategy resolves 512×384 coordinates
   with pattern intelligence, flow angles, anti-center bias, and stack
   offsets; `geometry/collision.py` resolves overlaps.
5. **Sliders & spinners** — `sliders/` enforces the slider ratio with
   sustained-audio intelligence; `spinners/` guarantees spinners with
   clearance windows.
6. **Post-process** — `postprocess/` repairs validator findings;
   `validation/` scores structure, density, collisions, and playability.
7. **Export** — `osu_format/` writes `.osu` (multi-BPM timing points,
   Unicode metadata) and packages `.osz` mapsets.

The local API wraps steps 1–7 as a job pipeline
(`pipeline_runner.py` + `job_manager.py`) with per-stage watchdogs,
cancel polling, and atomic workspace persistence.
