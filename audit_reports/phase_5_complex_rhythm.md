# Phase 5 Audit — Complex Musicality & Alternate Game Modes

**Role enacted:** Rhythm Game Engine Architect.
**Scope:** Audit of audio-parsing adaptability for tempo drift / variable BPM / live-instrument timing, time-signature flexibility, and the architectural distance between the current osu!standard placement engine and osu!catch / osu!mania. Static analysis only — no production code written or edited.
**Date:** 2026-09-27
**Audit reference:** `phase_5_complex_rhythm.md` (task definition in repository root)
**Baseline:** commit `fca2d85` ("Implement Phase 2 fixes…")

---

## Executive Summary

The codebase exhibits a **"smart analysis, dumb export" asymmetry**. The analysis layer is genuinely modern: `audio_analyzer.py` computes enhanced multi-layer features including **sliding-window local BPM estimates, BPM regions with confidence scores, tempo stability, and subdivision grids** (`audio_analyzer.py:_compute_enhanced_features:107-192`, `rhythm/multi_layer_analysis.py`). The rhythm intelligence engine consumes these for **event selection** (which musical moments become objects) — but the **timing model itself is hardcoded to one global, constant BPM**: export emits exactly **one uninherited `[TimingPoints]` line** (`timing_converter.py:build_primary_timing_point:37-54`), and snapping math in the generator derives a single `beat_interval_ms = 60000 / analysis.bpm` (`beatmap_generator.py:700`). Variable-BPM tracks will therefore have their objects correctly *timed* to audio events (times come from detected beats/onsets, not from the grid) but the exported `.osu` will carry a **wrong beatmap-wide BPM label**, and any timing *derived* from the grid (density-fill snapping, slider durations, kiai spacing) will **drift out of sync** in sections whose true tempo deviates from the global estimate.

**Time signatures:** fully hardcoded to 4/4 (`timingDefaults.meter: 4` in `src/shared/osuInteropConstants.json`), single meter for the whole map. Downbeat phase is not tracked; `meter` is a constant in the only timing point. No 3/4, 6/8, or 7/8 support exists anywhere in the pipeline.

**Game modes:** the hit-object data model is only weakly coupled to osu!standard (a `type` literal + x/y fields), but **every placement subsystem hardcodes standard-mode assumptions**: 512×384 playfield constants (`position_generator.py:12-13`), `Mode: 0` in General defaults, and no abstraction boundary for mode-specific mechanics (catch fruit arcs / hyperdash windows, mania column quantization). Extending to catch/mania requires a **mode-strategy layer** with a defined seam — the audit maps exactly where that seam must be cut (§3.3).

| Audit question | Verdict |
|---|---|
| Tempo drift / variable BPM handling in analysis | ✅ Detected & quantified (local BPM, stability) |
| Variable BPM in *timing model / export* | ❌ Single fixed uninherited point; drift unsynced |
| Multiple `[TimingPoints]` | ❌ One point, ever (`writer.py` writes the list, export fills 1) |
| Non-4/4 time signatures | ❌ Hardcoded `meter=4`, no downbeat tracking |
| Off-beats forced onto 4/4 grid | ⚠️ Object times are audio-true (not grid-forced); only density-fill snaps to a single-BPM half-beat grid |
| HitObject engine decoupling | ⚠️ Partial — timing/selection decoupled; placement hardcodes standard |
| Effort to add osu!catch / osu!mania | Medium — one strategy seam, ~6 subsystems touched (§3.3) |

---

## 1. Variable BPM & Live Timing

### 1.1 What the analyzer actually computes

`tools/map_generator/audio_analyzer.py:analyze_audio` runs a classic single-pass pipeline:

1. **Load:** `librosa.load(sr=22_050, mono=True)` (`_load_audio:203-224`; FFmpeg-missing hint for MP3 decode failures).
2. **Global tempo:** `librosa.beat.beat_track(onset_envelope, start_bpm=120.0, tightness=90, units="frames")` (`:65-72`). Returns **one scalar tempo** for the whole track (`bpm=float(np.atleast_1d(tempo)[0])`, `:126`). `tightness=90` is librosa's default-ish rigidity — the beat tracker *will follow* moderate drift in its output beat *positions*, but the returned scalar BPM cannot represent a tempo curve.
3. **Onsets:** `librosa.onset.onset_detect(pre_max/post_max/pre_avg/post_avg=3, delta=0.03)` (`:73-82`) — raw, unsnapped musical event times.
4. **Offset:** `_estimate_offset_ms` (`:414-440`) picks the first sufficiently strong beat/onset with non-trivial energy — a **global** phase anchor.

**Enhanced layer** (`_compute_enhanced_features:107-192`, delegated to `rhythm/multi_layer_analysis.py`):
- `extract_enhanced_features` — spectral flux (hop 512), multi-band onset strengths (mean/median/max aggregates), **`local_bpm_estimates`**: 8 s windows stepping 2 s, median inter-beat interval → local BPM, confidence = interval CV consistency (0.6) blended with onset density (0.4) (`multi_layer_analysis.py:64-139`).
- **`tempo_stability`** — `1 − 1.5·(σ/μ)` of local BPMs, clamped 0–1 (`:140-152`). A live/drummer-driven track scores low; a quantized EDM track scores ~1.0.
- `compute_bpm_regions` — merged adjacent windows with <5 BPM difference into up to 20 `BpmRegion{start,end,bpm,confidence,beat_count}` (`:144-233`).
- `detect_subdivisions` — 4 s windows testing half/quarter/eighth/sixteenth grids against onset alignment (`:259-337`).

### 1.2 Live instruments & drift — how well does it cope?

- **Beat *positions*** (the `beats: list[TimedStrength]`): `beat_track` with `tightness=90` yields positions that track gradual drift reasonably; onset detection is drift-agnostic. So the *object timeline* inherits audio-true times.
- **Tempo *model***: only the scalar. `tempo_stability` and `bpmRegions` faithfully *quantify* instability — e.g., a rubato intro or a mid-song double-time section will show as low-stability + disjoint BPM regions — but **nothing downstream changes timing behavior** based on them (verified: `grep bpmRegions|localBpmEstimates|tempoStability` outside analysis code hits only `rhythm_pipeline.py:58-125`, which passes them into `RhythmModel` and diagnostics).
- **Rhythm model fallback:** `rhythm_pipeline.build_rhythm_model:80-89` — if no raw samples or enhanced analysis disabled, a single `BpmRegion(0→duration, bpm=analysis.bpm, confidence=0.5)` is synthesized. Either way, the region list is used for **selection confidence** (`timing_quality.compute_timing_confidence`) and diagnostics, **not** for time mapping.

### 1.3 Where the single-BPM assumption actually bites

Consumers of `analysis.bpm` / `offset_ms` that assume global constancy:

| Consumer | Use | Drift impact |
|---|---|---|
| `timing_converter.build_primary_timing_point:37-54` | `beat_length = 60000/bpm` at `time=offset_ms`, `meter=4` | **The exported BPM is wrong for every section whose true tempo differs** — osu! will display the global BPM and warp its visual beat grid accordingly; gameplay hit windows are unaffected (object times are absolute ms), but editors/players reading the map see a wrong tempo and the editor's snap grid will not line up with the music outside the anchor section |
| `beatmap_generator.py:700-705` | `beat_interval_ms = 60000/bpm`; `half_beat_ms` for density-fill snapping (`_snap_fill_time:807-824` snaps to `offset + k·half_beat`) | Fill circles inserted in a fast section land on a grid that is *too wide* (musically late/lazy); in a slow section, *too narrow*. Snapping also anchors on `offset_ms` — a constant phase — so phase drift accumulates |
| Slider duration/velocity math (slider pipeline consumes beat length implicitly via preset spacing) | Pixel-length ↔ ms conversions assume constant tempo | Slider end times drift off-beat in changed-tempo sections |
| `replay/` simulation, `difficulty/` analysis | Beat-interval-based stamina/reading heuristics | Statistical skew only; no sync error |
| `sections/boundary_detector.py` | Energy/structural boundaries | Tempo-agnostic — unaffected |

**Crucial nuance:** object *times* are never quantized to the global grid in the main path — `event_selector.select_events` picks audio-true beat/onset times verbatim, and `select_rhythmic_timings` (`rhythm_pipeline.py:135-243`) likewise uses raw `time_ms` values plus optional subdivision-grid fillers (which *are* global-BPM-derived grids via `_median_beat_interval` — `multi_layer_analysis.py:340-360` — another drift-sensitive path). So maps remain *playable* on variable-BPM songs; they are **mis-labeled and mis-snapped**, not mis-timed.

### 1.4 Multi-timing-point support

- **Writer:** fully capable — `writer.py:write_osu_text` iterates `sections.timing_points` (`writer.py:25-27`); `OsuTimingPoint.to_line()` serializes any list. The parser (`parser.py:46,94,152`) reads multiple timing points from imported `.osu` files, including inherited points.
- **Producer:** `export_pipeline.py:58,94` calls `build_primary_timing_point` which returns exactly one point; `OsuWriterSections.timing_points=[timing_point]`. **The pipeline generates precisely one uninherited point at `offset_ms` with `beat_length=60000/global_bpm`.**
- No inherited-point (SV) generation exists either — SV is fixed at `SliderMultiplier` from `difficultyDefaults`, with no `[TimingPoints]` SV automation (kiai SV pushes, etc. are not implemented; kiai is only used for object-density decisions).
- **What exists and is unused:** `bpmRegions` is *exactly* the data structure needed to emit one uninherited point per region (merge already done, confidence available for filtering). Emitting `N` points where N = len(bpmRegions) would be a ~30-line change in `export_pipeline` + a region-to-point converter — the plumbing (writer, models, parser) is already multi-point-capable. This is the single highest-leverage fix in this audit's scope.

---

## 2. Time Signature Flexibility

### 2.1 Current state — 4/4 only, by constant

- `src/shared/osuInteropConstants.json` → `"timingDefaults": { "meter": 4, ... }`; `timing_converter.py:45` writes `meter=int(constants["meter"])`. No code path ever varies it.
- **No time-signature detection exists**: the analyzer computes no downbeat phase, no bar length, no meter hypotheses. librosa offers no native meter detection; typical approaches (beat-spectrum / autocorrelation over bar hypotheses, or onset-energy accent pattern at multiples of the beat interval) are absent.
- **No downbeat tracking**: `_estimate_offset_ms` finds a strong first event, not a bar-aligned downbeat. Consequently even the 4/4 assumption's bar phase is unanchored — "beat 1" of the exported grid is arbitrary.
- **Downstream grid math is bar-blind:** `_build_subdivision_grid` (`multi_layer_analysis.py:277-301`) builds grids as `offset + k·step` from the *global* beat interval — measures as a concept do not exist in the code. `beatmap_generator._snap_fill_time` snaps to half-beats only. The editor's `BeatGridRenderer.ts` has no meter/time-signature logic either (grep confirms no `timeSignature`/`meter` tokens in the TS timeline).
- The `[Editor]` section exports `beatDivisor: 4` constant (`osuInteropConstants.json editorDefaults`).

### 2.2 Does the engine force off-beats onto a 4/4 snap?

**Mostly no — with two exceptions:**
- Primary object times (beats/onsets selected by `event_selector.py` / `rhythm_pipeline.select_rhythmic_timings`) are **audio-true**, never quantized to a bar grid. Syncopations in a 7/8 track would land at the right *milliseconds*; the map would even be *playable* — rhythmically correct, just mis-labeled (wrong BPM, wrong meter) and with an editor grid that disagrees with the music.
- **Exception 1 — density-fill snapping:** `beatmap_generator.py:_snap_fill_time:807-824` snaps inserted circles to `offset_ms + k·half_beat_ms` from the global BPM. In a 7/8 or drifting passage these inserts can land off the actual pulse.
- **Exception 2 — subdivision fillers:** `rhythm_pipeline._add_subdivision_candidates:245+` uses subdivision grids derived from the *global median beat interval* (`_median_beat_interval:340-353`), so 16th-fillers in a tempo-changed region are misplaced relative to the true local pulse.
- **Accent/emphasis model is bar-blind:** `is_emphasis` derives from strength thresholds and energy regions (`event_selector.py:_candidate_from_timed_strength:213-228`), not from metrical position (downbeat vs. upbeat), so patterns cannot respect bar-level musical accents even in 4/4.

### 2.3 What non-4/4 support would require

1. **Meter hypothesis engine** in the analysis layer: for each BPM region, test meter candidates {2,3,4,6,8,7,5}/4 via accent-periodicity scoring over onsets (bar-length autocorrelation at `meter·beat_interval`), returning per-region `{meter, downbeat_offset_ms, confidence}` — mirrors the existing `BpmRegion` architecture.
2. **Emit meter changes:** osu! supports meter per uninherited point — multi-point export (§1.4) carries `meter` per region naturally.
3. **Downbeat-anchored grids:** subdivide per-region from `downbeat_offset` with bar-length strides so fills/keywords land on bar phase.
4. **UI:** surface detected meter per region in reports (diagnostics already carry subdivisions/bpm regions into `RhythmDiagnostics`, so the reporting channel exists).

---

## 3. Game Mode Extensibility (osu!catch / osu!mania)

### 3.1 Where the engine is already mode-agnostic (good seams)

- **Timing core is mode-free:** `AudioAnalysis → RhythmModel → select_events/SelectedEvent` produces a list of `(time_ms, strength, energy, confidence, is_emphasis)` — pure musical decisions with zero playfield semantics. Both catch (fruit *timing*) and mania (note *timing*) need exactly this.
- **Hit object data model is shallow:** `GeneratedCircleHitObject/SliderHitObject/SpinnerHitObject` (`models.py:168-226`) with `type: Literal[...]` + generic fields and an `extra_fields: dict` escape hatch; `hitobject_converter.py` serializes per-type. A mania column or catch direction can live in `extra_fields` without schema surgery.
- **Writer/parser are mode-blind:** `[HitObjects]` lines are formatted from object fields; `Mode` is just a General key from constants (`osuInteropConstants.json generalDefaults.mode: 0`). Nothing structurally prevents `mode: 3` output.
- **Pipeline orchestration is mode-free:** `pipeline_runner._build_stage_plan` chains generic stages; validation/reporting operate on the object list.

### 3.2 Where osu!standard is hardcoded (the real coupling)

| Location | Hardcode | Blocks |
|---|---|---|
| `position_generator.py:12-13` | `PLAYFIELD_WIDTH = 512`, `PLAYFIELD_HEIGHT = 384` | Catch uses the same 512×384 field (x only matters for fruit landing); mania uses columns, not x/y |
| `beatmap_generator.py` (object construction: `GeneratedCircleHitObject(x=…, y=…)`) | x/y placement inline with generation | Mania objects need `x = column·(512/columnCount)` and no y |
| `position_generator.py` flow/angle/jump engines (`mode_scores`, angle sets `:204-229`) | Standard-only cursor-motion semantics | Meaningless for mania; catch needs horizontal-reachability arcs instead |
| `sliders/` + `postprocess/` (stacking, collisions, movement correctors) | Distance/overlap math in 512×384 xy-space | Mania ignores xy; catch needs catchable-arc validation (dash/hyperdash windows) |
| `difficulty/` (aim/stamina/reading models) | Standard star heuristics | Each mode has its own difficulty model (catch: pattern density + dash load; mania: chordjacks/streams/LN) |
| `validation/` (movement/collision validators) | Standard spacing rules | Would false-reject valid mania/catch maps |
| `osuInteropConstants.json` | `mode: 0`, CS/AR/HP formulas standard-shaped | Mania needs `keyCount` (CircleSize 1–18) and column-specific settings; catch needs CS (fruit size) and AR |
| `editor` + `game` frontends (`src/editor/playfield/*`, `src/game/GameScene.ts`) | Draw circles/sliders in xy | Need mode-specific renderers (fruit arcs; column lanes) |

### 3.3 Required refactor — the strategy seam

The minimal-disruption architecture is a **mode strategy layer** cut along the existing timing/placement boundary:

1. **Define `GenerationMode` enum** (`osu`, `catch`, `mania`) plumbed from API metadata → `pipeline_runner` → generator entry.
2. **Extract a `PlacementStrategy` protocol** with per-mode implementations, absorbing the xy-coupled subsystems:
   - `osu`: current `position_generator` + `patterns/` + `sliders/` as-is.
   - `catch`: new strategy mapping each `SelectedEvent` to fruit x-trajectories — horizontal movement budget per ms (catcher speed ≈ 0.62·CS·SV), dash/hyperdash classification from consecutive x deltas, spinner equivalents become fruit showers. Reuses `SelectedEvent` stream verbatim.
   - `mania`: new strategy quantizing `time_ms` to per-column note placements — k-sort decomposition into 4/5/6/7 columns using onset strength for column assignment (strong onset → outer columns), chord detection via sub-30ms onset clustering. Ignores xy entirely; emits `x = column·(512/keys), y = 192` per osu!mania conventions.
3. **Mode-specific validators/difficulty:** gate `validation/` and `difficulty/` modules per mode (standard validators must not run on mania output).
4. **Constants:** extend `osuInteropConstants.json` with per-mode General/Difficulty defaults (`mode`, mania `keyCount`, catch CS/AR mappings).
5. **Exporter:** `hitobject_converter` gains per-mode line formats (mania holds `x|y:column:hitsound...`; catch uses circle/slider lines with catch semantics — mostly identical text, different semantic interpretation).
6. **Frontend:** mode toggle in `MetadataStep`/`DifficultyStep`; per-mode playfield renderers in editor/game (largest UI cost).

**Effort estimate:** timing/selection/export/packaging (~60% of the pipeline) is reusable as-is for both modes; the placement/validation/difficulty/UI layers (≈40%) need new mode implementations behind the strategy seam. Mania is the *cheaper* second mode (no trajectory math — column quantization over the existing `SelectedEvent` stream); catch is medium (arc feasibility + hyperdash constraints).

---

## 4. Findings Register

| ID | Severity | Finding | Code reference |
|---|---|---|---|
| T1 | **High** | Export emits exactly one uninherited timing point from the global scalar BPM — variable-BPM tracks get a wrong map-wide tempo label and drifting grid alignment | `timing_converter.py:37-54`, `export_pipeline.py:58,94` |
| T2 | **High** | Rich multi-BPM analysis (`bpmRegions`, local BPM, tempo stability) is computed but consumed only for selection confidence/diagnostics — never for the timing model | `audio_analyzer.py:107-192`, `rhythm_pipeline.py:58-125` |
| T3 | **Medium** | Density-fill snapping and subdivision fillers use global-BPM grids anchored at a constant `offset_ms` — inserts drift off-pulse in tempo-changed sections | `beatmap_generator.py:700-705,807-824`, `multi_layer_analysis.py:277-360` |
| T4 | **Medium** | Meter hardcoded `4/4` via constants; no meter detection, no downbeat phase tracking; bar-accent-aware patterning impossible | `osuInteropConstants.json timingDefaults.meter`, `timing_converter.py:45` |
| T5 | **Medium** | No inherited (SV) timing points generated; kiai/section energy never modulates SV | `export_pipeline.py:94` (single-point list) |
| T6 | **Medium** | Placement subsystems hardcode standard-mode semantics (512×384 xy, jump/angle engines, standard validators) without a strategy seam | `position_generator.py:12-13,204-229`, `validation/`, `difficulty/` |
| T7 | **Low** | `beat_track(tightness=90)` single-pass tracker; no per-region re-tracking or beat-position refinement against local BPM curves (positions are good for moderate drift, weaker for rubato) | `audio_analyzer.py:65-72` |
| T8 | **Low** | `is_emphasis` is energy/strength-based only; metrical position (downbeat/upbeat/bar) never influences patterning | `event_selector.py:213-228` |
| T9 | **Low** | Parser reads multi-point `[TimingPoints]` from imports but the generator never produces them (asymmetric capability) | `parser.py:46,94,152` vs `writer` consumers |

**Strengths verified:** audio-true object timing (no global quantization of the main event path); genuinely multi-layer rhythm analysis with deterministic confidence scoring; clean `SelectedEvent` abstraction that both modes could consume unchanged; mode-blind writer/parser; `extra_fields` escape hatch on every hit object; kiai/section detection integrated into selection density.

---

## 5. Recommended Remediations (non-binding, for Phase 6+ planning)

1. **P0 — Multi-point export from `bpmRegions` (highest leverage / lowest cost):** convert high-confidence `BpmRegion`s to uninherited timing points (one per merged region, `beat_length=60000/region.bpm`, carry meter), emit via the already-multi-point-capable writer; when `tempo_stability ≥ ~0.85` and single-region, keep the current single point for backward determinism. ~30–60 lines in `export_pipeline`/`timing_converter` + a flag on the analysis→export path.
2. **P1 — Local-grid snapping:** pass `bpm_regions` into `beatmap_generator` so `_snap_fill_time` resolves the *local* interval at the fill position (binary search over regions) instead of the global one; same for subdivision grid construction (per-region beat interval).
3. **P1 — Beat-position re-tracking under low stability:** when `tempoStability < 0.6`, re-run `librosa.beat.beat_track` per BPM region (or use `librosa.plp`-style tempo curves) and splice region-local beat tracks, keeping the deterministic-selection behavior intact.
4. **P2 — Meter/downbeat engine:** per-region meter hypotheses + downbeat phase as §2.3; export per-point `meter`; anchor subdivision grids at bar phase.
5. **P2 — Mode strategy seam:** introduce `PlacementStrategy` (§3.3) and port standard into it unchanged (pure refactor, golden-map regression via existing e2e `.tmp-e2e-generation` artifacts as fixtures); then implement `mania` first (column quantization over `SelectedEvent`s), `catch` second.
6. **P3 — SV automation:** emit inherited points (SV multiplier) on kiai boundaries from existing `KiaiSection` data for section-energy feel.

---

*Report generated by static analysis of the working tree at commit `fca2d85`. No production code was modified.*
