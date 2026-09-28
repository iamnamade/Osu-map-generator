# Phase 6 — Final Audit: osu! Ranking Criteria Compliance & Master Roadmap

**Role enacted:** Principal osu! Beatmap Quality Inspector & Technical Lead.
**Scope:** (1) Direct osu! Ranking Criteria (RC) compliance audit of the placement engine — off-screen clipping, spinner recovery, stacking/ninja circles; (2) synthesis of the full six-phase audit campaign into core strengths, critical vulnerabilities, and a prioritized master roadmap. Static analysis only — no production code written or edited.
**Date:** 2026-09-27
**Audit reference:** `phase_6_master_roadmap.md` (task definition in repository root)
**Baseline:** commit `fca2d85` + Phase 1 remediation commit `69f26ae`

---

## Part I — osu! Ranking Criteria Compliance Audit

### 1. Off-screen boundaries & slider curve clipping

**RC rule audited:** 2.3.1 / Skinning & skill expression — "beatmap elements … must not extend beyond the playfield" (512×384 osu!pixels); sliders whose bodies or control points clip off-screen create unreadable follow-points and cursor excursions.

**Verdict: ✅ COMPLIANT for control points and object anchors; ⚠️ PARTIAL for curved slider *bodies*.**

**Evidence:**

1. **Anchor/control-point clamping (primary defense):** `tools/map_generator/sliders/slider_geometry.py` clamps every generated control point to `[0,512]×[0,384]` at construction time — bezier insertion (`:65-66`, `:100-101`, `:139-140`), path sampling (`:223-224`), perfect-circle arcs (`:362-363` clamps the arc center to `radius+4 … 512-radius-4` before sampling), catmull/tangent construction (`:271-276, :389-390`), and final point lists (`:307-308`). Because sampling also clamps sampled points (`:223-224`), the *serialized* control points are all in-bounds.
2. **Playfield constants are canonical:** `position_generator.py:12-13` (`PLAYFIELD_WIDTH=512`, `PLAYFIELD_HEIGHT=384`); `geometry/collision.py:24-25` (`PLAYFIELD_X_MAX=512.0`, `PLAYFIELD_Y_MAX=384.0`); objects are generated clamped to `[32,480]×[32,352]` interior margins in `beatmap_generator.py` (density-fill interpolation `clamp(…, 32, 480)` / `clamp(…, 32, 352)`), leaving radius headroom.
3. **Validation backstop:** `validation/structural_validator.py:264` raises `OBJECT_OUT_OF_BOUNDS` (severity **error**) for any object coordinate outside 512×384, measured per object with exact overflow amounts. Note: it validates **object anchors** (circle centers, slider head/tail anchors), not interpolated curve bodies.
4. **Collision engine:** `geometry/collision.py:683-702` computes flow-nudge vectors clamped to the playfield; the overlap detector builds slider path polylines via a bounded LRU cache (`:230-258`).

**Residual gap (the "body" caveat):** clamping *control points* does not mathematically guarantee the *interpolated curve* stays in-bounds (a bezier segment between in-bounds points can still bow outside; the perfect-circle routine's center clamp mitigates its case). No post-construction **curve polyline bounds check** exists — the overlap detector builds polylines for collisions but never asserts `min/max(x,y)` within 512×384. RC risk is low (anchors clamped + 32px interior margins + radius ≤ ~54px gives substantial headroom), but a `CURVE_BOUNDS` assertion in `structural_validator` would close it completely. The osu! **client** also renders out-of-bounds slider bodies without crashing (they simply extend off-screen), so this is a polish/RC-formality gap, not a gameplay-breaking one.

### 2. Spinner recovery time (RC 2.5.2 / rest-interval rules)

**RC rule audited:** spinners must not be followed immediately by high-intensity objects; adequate recovery time after (and entry buffer before) spinners, scaled by difficulty.

**Verdict: ✅ COMPLIANT — enforced at three layers, per-difficulty, with a validator backstop.**

**Evidence (three enforcement layers):**

1. **Generation-time clearance:** `spinners/spinner_pipeline.py` — gap candidates require `gap >= preset.spinner_min_gap_ms` (`:125`); acceptance is gated by musical trigger type; and the clearance window check `_check_spinner_clearance` (`:380-397`) requires every other object to satisfy `padded_start = start − clearance` … `padded_end = end + clearance`, i.e. **no object may intersect the spinner window padded by the clearance on both sides**. Forced spinners use the *full* buffers: `clearance_ms = max(preset.min_gap_ms, spinner_entry_buffer_ms, spinner_recovery_after_ms)` (`:310-315`).
2. **Recovery engine (per-difficulty constants):** `recovery/recovery_engine.py:33-38` —
   | Difficulty | min spinner duration | post-spinner clearance |
   |---|---|---|
   | Easy | 1000 ms | **600 ms** |
   | Normal | 800 ms | **450 ms** |
   | Hard | 600 ms | **350 ms** |
   | insane | 500 ms | 280 ms |
   `post_spinner_clearance` (`:217-237`) verifies the gap to the next object; `spinner_pipeline.py:166-183` applies `guidelines["post_clearance_ms"]` during acceptance (`_record_rejection(diagnostics, "clearance")` on failure). Entry buffer per tier: Easy 160 ms / Normal 150 ms (base `config.py:62-63`) → Normal 400/150, Hard 300/120 (`config.py:115-121,171-177,227-233`).
3. **Post-processing & validation backstops:** the Phase 1 remediation commit (`69f26ae` "…resolve spinner clearance overlaps") hardened this; the validator emits `SPINNER_OVERLAPS_PREVIOUS` (critical) and `SPINNER_TOO_SHORT/LONG` (`validation/spinner_validator.py:19-60`); `rebalance/spinners.py` and `postprocess/` can relocate spinner-adjacent objects.

**Residual risks (low):** (a) clearance is a **time-window** check only — it does not model the *spatial* recentering distance the cursor must travel after a spinner ends (RC spirit is "distance to next object", which the movement corrector handles elsewhere); (b) Phase 1 observed `SPINNER_OVERLAPS_PREVIOUS` criticals in stale artifacts (`spinner_pipeline.py:125` validated only `spinner_min_gap_ms` against the previous object end) — the `69f26ae` commit specifically targeted "spinner clearance overlaps", and the pipeline now applies the full triple-max clearance, but the committed e2e artifacts predate this fix, so the fix is verified in code, not in committed output.

### 3. Stacking & overlaps — ninja/buried circles

**RC rule audited:** objects must not be visually indistinct (ninja/buried circles: a circle hidden completely behind another with a near-simultaneous time).

**Verdict: ✅ COMPLIANT by design — a dedicated collision engine + corrector + validator.**

**Evidence:**

1. **Canonical overlap detector** (`geometry/collision.py`): `disc_disc_floor(radius, gap_ms, margin)` implements **time-aware spacing floors** — pattern-density pairs (gap ≤ 250 ms) use a relaxed tight floor (`2r × 0.55`), all other pairs require full `2r + 2px margin` separation (`:26-50`). This encodes the osu! convention that *intentional stacks* (≥1.5 s apart, `STACK_TIME_WINDOW_MS`) are legal while near-time buried/ninja pairs are not: pairs closer than the stack window must clear the disc floor, so a fully-hidden circle under a near-time neighbor is geometrically impossible without flagging.
2. **Generation-time prevention:** `position_generator` rejects candidate positions via the collision engine during placement (rejected candidates tracked in `PositionGenerationResult`).
3. **Post-processing correction:** `postprocess/stacking_corrector.py` relocates offending objects using deterministic candidate positions — perpendicular offsets `max(r×1.35, min_jump×0.55)` (`:98-140`), angle sweeps (`:127-133`), seeded RNG (`seed × 29 + id × 17`) for reproducibility, respecting neighbor flow.
4. **Validation backstop:** `validation/collision_validator.py:69-114` scans via `detect_map_overlaps` and emits `overlapCount` / `maxOverlapPx` metrics with issues feeding the evolution hard gate ("the evolution hard gate" per module docstring) — i.e., candidates with unresolved collisions cannot win evolution.
5. **Perfect-stack semantics:** `PERFECT_STACK_PX = 2.0` — near-coincident centers are treated as legal *intentional* stacks only when time-separated beyond the stack window; near-time perfect stacks are caught by the time-aware floor.

**Residual gap (low):** detection is disc-disc (+slider polyline) **on the generated set**; there is no dedicated "ninja" metric in reports (a buried circle would surface as a generic collision). The 17 ms `SPINNER_OVERLAPS_PREVIOUS` criticals in Phase 1's stale artifacts show the historical failure mode; the current three-layer defense plus `69f26ae` addresses the generation path.

### RC compliance summary

| RC area | Verdict | Key evidence |
|---|---|---|
| Slider/object bounds (512×384) | ✅ Compliant (anchors, control points, sampled points); ⚠️ no curve-body polyline bounds assertion | `slider_geometry.py:65-66,223-224,362-363`; `structural_validator.py:264` |
| Spinner recovery/rest intervals | ✅ Compliant — 3-layer enforcement, per-difficulty constants (600/450/350 ms) | `recovery_engine.py:33-38`, `spinner_pipeline.py:310-397`, `spinner_validator.py` |
| Stacking / ninja / buried circles | ✅ Compliant — time-aware collision floors + corrector + evolution hard gate | `collision.py:26-50`, `stacking_corrector.py:88-140`, `collision_validator.py:69-114` |

---

## Part II — Master Gap Analysis (synthesis of Phases 1–5)

### a) Top 3 Core Strengths (production-ready modules)

**S1. The event-timing core (`AudioAnalysis → RhythmModel → SelectedEvent`) is genuinely mode-agnostic and audio-true.**
`event_selector.py` + `rhythm/rhythm_pipeline.py` produce playfield-free `(time_ms, strength, energy, confidence, is_emphasis)` streams with deterministic, seeded variation; density/gap/phrase logic is coherent (Phase 1's Normal tier passes its band at 1.70 obj/s). Both future game modes could consume this stream unchanged (Phase 5 §3.1). Verified positives across phases: audio-true timing (never grid-quantized), phrase-aware gap scaling (0.6–1.4×), energy-responsive density targets, deterministic seeds end-to-end.

**S2. The osu! format I/O layer is export-grade and integrity-checked.**
`osu_format/` writer (UTF-8 no-BOM, LF, deterministic archive timestamps), parser (multi-timing-point, BOM-tolerant), mapset packager (flat-name validation, binary-safe zip, **archive cross-validates background filename against parsed `.osu` `[Events]`** — `mapset_packager.py:47-57`), and `pipeline_runner._verify_package_contents` re-opens the shipped `.osz` asserting audio presence and `.osu` count. Phase 2's committed fix added Unicode metadata passthrough (`pipeline_runner._generate_base_map` passes `title_unicode`/`artist_unicode` → `export_pipeline.py`), and the unified `tools/text_utils.py` sanitizer (NFC, reserved-name, length-bounded) replaced the Phase 2 finding of three divergent sanitizers — verified at `pipeline_runner.py:1084` and `text_utils.py:53-96`.

**S3. The API hardening & workspace isolation layer is defense-in-depth.**
UUID-regex workspace IDs, `resolve()`-containment on every descriptor path, server-chosen canonical filenames, atomic upload writes, streamed size caps, SHA-256 configuration signatures gating deterministic output reuse, sanitized error surfaces (stack traces kept server-side, `technicalDetails` opt-in), and no untrusted-archive extraction anywhere (Phase 4 §1.2). The localhost-only binding shrinks the remaining attack surface to local-user threats.

*Honorable mentions:* the layered validation suite (`validation/` — structural/collision/spinner/density/rhythm/spinner validators with severity-tagged issues feeding evolution hard gates); kiai/section detection integrated into selection; the editor's real waveform renderer and playfield tools (ready for reuse in the generator UI per Phase 3).

### b) Top 5 Critical Vulnerabilities & Deficits (campaign-wide)

**V1. No timeouts, memory caps, or crash recovery on the job pipeline (Phase 4, S1/S2/R3) — *the* operational defect.**
Stages run as bare daemon threads with no watchdog; a hung `librosa` decode blocks the job forever. Job records are in-memory only; an API restart orphans `running` workspaces that `CleanupService` then *refuses to delete* — a zombie-workspace lifecycle bug. Cancellation is stage-granular only (evolution `progress_callback` never polls `cancel_requested`).

**V2. Single fixed BPM timing model despite multi-BPM analysis existing (Phase 5, T1/T2).**
Export emits exactly one uninherited `[TimingPoints]` point from the global scalar BPM (`timing_converter.py:37-54`); `bpmRegions`/`localBpmEstimates`/`tempoStability` are computed but never drive timing. Variable-BPM tracks get a wrong map-wide tempo label; density-fill snapping and subdivision fillers drift off-pulse in tempo-changed sections (`beatmap_generator.py:700-705,807-824`).

**V3. Hard-tier density shortfall with a structurally broken minimum floor (Phase 1, F3 + empirical 1.64 vs 2.5–3.8 obj/s).**
`max(min_density_target, target_density)` collapses the minimum into the target (`beatmap_generator.py:652-653`); committed artifacts measure Hard at 1.64 obj/s (Normal 1.70 passes). Dead config was removed in `69f26ae` and the engine claims fixes, but committed artifacts predate it — **the density gate has no regression test pinning Hard to its band**. Risk of silent regression remains because the density guarantee is enforced only by convention, not by a pinned test.

*Status note:* Phase 1's F1/F2 (dead config), F4 (`last_time`), and F7 (debug stderr) are **verified fixed** at baseline (`config.py` no longer declares them; `rhythm_pipeline.py:340-389` advances `last_time` on every path; no `stderr` writes remain). F5/F6/F9 remain open as designed-limitations (average-energy gap gating; circles-only single-pass fill; three unreconciled density authorities).

**V4. Security hardening gaps in upload content validation and cross-site mutation (Phase 4, S3/S4).**
No magic-byte/MIME verification — a background image is any bytes with an image extension; declared `Content-Type` is trusted and re-served verbatim by `preview_audio`. No `Origin`/CSRF enforcement on mutating endpoints (simple requests like `DELETE` are fireable cross-site; only unguessable UUIDs stand in the way). Manifest writes are non-atomic unlocked read-modify-write (R1), and `DELETE /workspaces` can race a job start (R2).

**V5. Frontend re-render architecture risks Unicode/IME input and lacks live audio feedback (Phase 3, focus-preservation + waveform deficits).**
`GeneratorApp` rebuilds `root.innerHTML` on every state change with no focus/caret preservation — typing multibyte metadata (the exact Phase 2 feature) risks caret jumps/IME breakage mid-composition. The Step-4 "waveform" is a static 18-bar decorative mock while a real renderer exists unused in `src/editor/timeline/WreamformRenderer.ts` *(sic — `WaveformRenderer.ts`)*; background preview dies on reload (no `preview-background` route); no ETA/per-stage timing in telemetry despite server-side stage timings being computed.

### Remaining (non-top-5) campaign findings carried forward

Phase 1: F5 (average-energy gap gating), F6 (circles-only single-pass fill), F9 (three unreconciled density authorities: preset 1.2/1.8/3.2, analyzer 1.1/1.5/2.4, rhythm model 1.0–5.0), F10 (spinner-vs-`min_gap_ms` re-validation post-insertion). Phase 2: I8 (harness `read_text()` without encoding — Windows cp1252 crash on Unicode JSON). Phase 3: background DnD, per-difficulty settings copy/lock, log virtualization, `window.confirm` replacement. Phase 4: D1 (`.tmp-*` scratch dirs never GC'd), S5 (unbounded workspaces/artifacts), S6/S7 (cancellation granularity, unbounded event lists), T1 (missing 413/415/409/traversal tests). Phase 5: T3 (global-grid fill snapping — see V2), T4 (meter hardcoded 4/4, no downbeat tracking), T5 (no SV automation), T6 (placement hardcodes standard-mode; no `PlacementStrategy` seam), T7/T8/T9 (single-pass beat tracking, bar-blind emphasis, asymmetric multi-point capability).

### c) Master Roadmap (ranked by urgency × impact)

**P0 — Correctness & operability that block trust in every generated map (do first)**

1. **P0-1 · Density regression pin (closes V3):** add a CI-pinned test asserting per-tier obj/s within the spec bands on the standard fixture (Hard ∈ 2.5–3.8, Normal ∈ 1.3–2.0, Easy within its band) *with the current engine*, plus per-map `RHYTHM_GAP_BELOW_MINIMUM`-free assertion; make the density floor independently enforced (`min_density_target` as a true floor, target as soft goal — Phase 1 F3). Without this, every other fix is unverifiable.
2. **P0-2 · Pipeline watchdog + boot reconciliation (closes V1):** per-stage `ThreadPoolExecutor` timeout (env-tunable), job → `failed` on expiry; on `create_app`, reconcile orphaned `running` manifests to `failed`; teach `delete_older_than` to treat stale-running as deletable after N hours; poll `cancel_requested` inside `progress_callback` between candidates.
3. **P0-3 · Multi-BPM timing-point export (closes V2's export half):** convert high-confidence `bpmRegions` to uninherited `[TimingPoints]` (one per merged region, `beat_length=60000/region.bpm`); writer/parser already support multi-point. Single-point path preserved when `tempo_stability ≥ 0.85` for determinism.
4. **P0-4 · Content validation + Origin enforcement (closes V4's exposure):** magic-byte sniffing before `os.replace` (ID3/0xFFEx/RIFF/OggS/fLaC; PNG/JPEG/WEBP), derive stored `content_type` from the sniff; `Origin` allow-list middleware on mutating verbs; atomic manifest writes (`tmp + os.replace`) under a per-workspace lock (R1/R2).

**P1 — Musical correctness deepening**

5. **P1-1 · Local-grid snapping (completes V2):** resolve the *local* beat interval from `bpm_regions` in `_snap_fill_time` and subdivision-grid construction (binary search over regions); re-track beats per region when `tempoStability < 0.6`.
6. **P1-2 · Fix the Unicode/IME re-render hazard (V5):** preserve `activeElement` id + selection across `render()` (or subtree-patch the metadata inputs); regression-test with IME composition events.
7. **P1-3 · Background preview persistence + real waveform:** add `GET /api/workspaces/{id}/preview-background/{filename}`; wire `src/editor/timeline/WaveformRenderer.ts` into Upload/Generate steps fed by `preview_audio`; surface server-computed per-stage durations as ETA.
8. **P1-4 · Remaining Phase 1 rhythm gaps:** peak-energy (not mean) gap-window tightening (F5); multi-pass, type-aware density fill protecting slider ratio (F6); reconcile the three density authorities into one (F9); re-validate spinner spacing against `min_gap_ms` post-insertion (F10).

**P2 — Extensibility & polish**

9. **P2-1 · Curve-bounds assertion:** add `CURVE_BOUNDS` polyline min/max check to `structural_validator` (closes Part I residual 1).
10. **P2-2 · Meter/downbeat engine:** per-region meter hypotheses + downbeat phase; per-point `meter` export (Phase 5 T4).
11. **P2-3 · `PlacementStrategy` seam:** extract the mode-agnostic timing/placement boundary; port standard unchanged (golden-map regression via e2e fixtures); then mania (column quantization over `SelectedEvent`s), then catch (Phase 5 T6).
12. **P2-4 · Scratch-dir hygiene:** `e2e_generation.py` → `tempfile.mkdtemp` + `--keep`; `cleanup --scratch` CLI mode (Phase 4 D1); fix I8 (`encoding="utf-8"` in harness `read_text`).
13. **P2-5 · Missing API tests:** 413/415/409 paths, artifact-ID traversal, corrupt manifests, restart reconciliation (Phase 4 T1).
14. **P2-6 · UI QoL:** per-difficulty settings copy/lock; log virtualization cap + auto-scroll; replace `window.confirm` with in-app modal; background drag-and-drop.

**P3 — Long-tail**

15. **P3-1 · SV automation:** inherited points on kiai boundaries from `KiaiSection` data (Phase 5 T5).
16. **P3-2 · Metrical emphasis:** downbeat/bar-phase-aware `is_emphasis` for pattern accents (Phase 5 T8).
17. **P3-3 · Disk quotas:** workspace count/disk caps; candidate archive retention policy (`archive_policy="all"` → bounded) (Phase 4 S5).
18. **P3-4 · Bounded telemetry:** ring-buffer job events (last N) + `?since=` tailing (Phase 4 S7).
19. **P3-5 · SSRF-style hardening:** assert `Origin`/`Host` even for same-origin requests; security-headers pass (CSP for the served HTML shells).

---

## Terminal Summary Table

| Phase | Focus | Verdict | Headline finding |
|---|---|---|---|
| 1 | Density & intervals | ✅ Fixed (`69f26ae`) | Hard 1.64 vs 3.2 obj/s target; dead config removed; min-floor still `max()`-collapsed → **needs pinned test** |
| 2 | i18n & metadata | ✅ Fixed (`fca2d85`) | Unicode passthrough now wired; unified `text_utils.py` sanitizer; harness encoding bug (I8) remains |
| 3 | Frontend & UI/UX | ⚠️ Good, gaps | Deep param controls, verified `[Events]` wiring; innerHTML re-render IME hazard; static waveform mock; background preview dies on reload |
| 4 | Security & lifecycle | ⚠️ Strong core, gaps | Path safety defense-in-depth; **no stage timeouts**; restart orphans `running` workspaces; no magic-byte checks; `.tmp-*` leak |
| 5 | Complex rhythm & modes | ⚠️ Smart analysis, dumb export | Local BPM/bpmRegions computed but unused for timing; single fixed BPM export; 4/4-only; no mode strategy seam |
| 6 | RC compliance + synthesis | ✅ RC-compliant | Bounds/spinner-recovery/stacking all enforced at 3 layers; curve-body polyline check is the only formal RC gap |

**Roadmap totals:** 4 × P0 · 4 × P1 · 6 × P2 · 5 × P3 items across 19 workstreams.

---

*Report generated by static analysis at commit `fca2d85` (+ remediation `69f26ae`). No production code was modified during this audit campaign.*
