# Phase 3 Audit — Full-Stack Web Platform & UI/UX Architecture

**Scope:** Frontend capabilities, customization depth, and UI compactness of the PULSE Practice osu! map generator.
**Method:** Static code review only (no production code written or edited), per audit mandate.
**Date:** 2026-09-27
**Audit reference:** `phase_3_frontend_ui.md` (task definition in repository root)

---

## Executive Summary

The frontend is a **dependency-free, vanilla-TypeScript single-page wizard** (`src/generator/`, mounted via `generator.html` → `src/generator/main.ts` → `GeneratorApp.ts`) backed by a **FastAPI local API** (`tools/local_api/app.py`, bound to `127.0.0.1:8765` per `GeneratorApp.ts:478` health copy and `tools/local_api/config.py`). A separate game workspace (`index.html` / `src/game/`) and a full map editor (`editor.html` / `src/editor/`) exist alongside the generator and are cross-linked from the generator's footer (`GeneratorApp.ts:renderFooter`, links via `buildEditorUrl`/`buildGameUrl` in `src/shared/mapCatalog.ts`).

**Overall verdict:** the wizard is functionally deep — background upload with live preview, per-difficulty parameter tuning with live plumbing into the Python pipeline, real stage telemetry, and artifact exports are all present and wired end-to-end. The main gaps are **(1) no waveform/audio visualization anywhere in the generator UI** (only a decorative static "waveform" mock), **(2) no manual timing-offset or global SV/AR/CS/HP override controls in the browser** (those are pipeline-derived, not user-facing), **(3) a synchronous full-DOM re-render architecture** that limits live interactivity, and **(4) background preview that does not survive page reload** (the backend serves it, but the frontend never requests it).

| Area | Status | Depth |
|---|---|---|
| Background upload / live preview / `[Events]` export | ✅ Implemented | Medium — 1 preview-persistence defect |
| Pre-generation parameter editing (browser) | ✅ Implemented | High — 11 mapping sliders + presets, all piped to pipeline |
| BPM offset / global SV / AR / CS / HP / density as *raw osu! values* | ❌ Not exposed | None — see §2.3 |
| Progress telemetry | ✅ Implemented | Good — stage timeline, per-candidate progress, elapsed time, logs |
| Waveform / audio visualizers | ❌ Missing | Static decorative mock only (`GenerationStep.ts:~95-108`) |
| Compactness / responsive layout | ✅ Mostly good | Collapsible panels, 5 breakpoints; sidebar duplicated in DOM |

---

## 1. Background Customization

### 1.1 Upload — YES, from the web interface

- **UI entry points (3):**
  - Dedicated artwork section on the Metadata step: `src/generator/components/MetadataForm.ts` — `panel-subsection--artwork` with an **"Add Background" / "Replace Background"** button (`data-action="pick-background"`).
  - Hidden file input `#generator-background-input` with `accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"` (`MetadataForm.ts`, input near the artwork section).
  - Sidebar status tile ("Background — Attached / Optional") in `GeneratorApp.ts:renderSidebar` (display-only).
- **Event wiring:** `GeneratorApp.ts` `handleClick` → `action === "pick-background"` triggers `this.root.querySelector<HTMLInputElement>("#generator-background-input")?.click()`; `handleChange` routes the picked `File` into `uploadBackground(file)`.
- **Transport:** `GeneratorApiClient.uploadBackground()` (`src/generator/GeneratorApiClient.ts`) performs an `XMLHttpRequest` multipart POST with **real upload progress callbacks** (`request.upload.addEventListener("progress", ...)`), surfaced as a percent progress bar in `MetadataForm.ts` (`backgroundProgressMarkup`, class `upload-progress--compact`).
- **Backend:** `POST /api/workspaces/{workspace_id}/background` (`tools/local_api/app.py:147-159`) → `UploadService.save_background()` (`tools/local_api/upload_service.py:71-110`): extension whitelist (`config.allowed_background_extensions`), size cap (`config.max_background_upload_bytes`), SHA-256 descriptor, **rename-to-canonical** `background{suffix}` (e.g. `background.jpg`), storage at `source/background.*`, previous background deleted (`_delete_previous_file`), manifest `metadata.background_filename` updated, and configuration signature recomputed (invalidating stale outputs).

**Note:** Unlike audio, the background has **no drag-and-drop zone** — `handleDrop` only matches `[data-dropzone='audio']` (`GeneratorApp.ts:handleDrop`).

### 1.2 Live preview — YES, with a persistence defect

- `uploadBackground()` calls `this.replaceBackgroundPreviewUrl(URL.createObjectURL(file))` (`GeneratorApp.ts`, inside `uploadBackground` success path) and passes `backgroundPreviewUrl` down: `renderMain` → `renderMetadataStep(state, this.backgroundPreviewUrl ?? undefined)` → `renderMetadataForm`.
- `MetadataForm.ts` renders `<img class="background-preview-image" src="...">` when a preview URL exists, otherwise a placeholder card (`background-preview-placeholder`).
- Blob URLs are correctly revoked on replacement and disposal (`replaceBackgroundPreviewUrl`, called in `dispose()` and `startNewSong()`).

**⚠ Defect — preview is session-only.** `backgroundPreviewUrl` is a client-side blob URL that is **not persisted** and **not rebuilt** on `bootstrap()`. After a page reload, the form shows the placeholder text *"Preview available after replacing this image in the current session."* even though the workspace still holds the file. The backend already has everything needed to fix this: `manifest.background.normalized_filename` is exposed on `WorkspaceResponse.workspace.background` (`GeneratorModels.ts:UploadedFileDescriptor`), and an audio preview route pattern exists (`GET .../preview-audio/{filename}` at `app.py:226-231`, built by `ArtifactService.build_audio_preview_url`, `tools/local_api/artifact_service.py:30`). **No equivalent `GET .../preview-background/{filename}` route exists** — that plus a one-line conditional in `bootstrap()` would restore cross-reload preview.

### 1.3 Linkage into the `.osu` `[Events]` section during export — YES, end-to-end verified

Full data path (all verified in code):

1. **Manifest:** `tools/local_api/models.py:150` — `metadata.background_filename` (aliased `backgroundFilename`); file descriptor `workspace.background.normalized_filename == "background.jpg"` (canonical name from `upload_service.py:78`).
2. **Pipeline runner:** `tools/local_api/pipeline_runner.py:943-946` (`_export_osu_files`): `background_filename = manifest.background.normalized_filename if manifest.background else None`, passed to every exported difficulty.
3. **Export:** `tools/map_generator/osu_format/export_pipeline.py:50` (parameter) and **`:89-93`** — injected verbatim into `OsuWriterSections.events` as the standard background line:
   ```python
   events=[f'0,0,"{background_filename}",0,0'] if background_filename else [],
   ```
4. **Serialization:** `tools/map_generator/osu_format/writer.py:17-19` — `lines.append("[Events]"); lines.extend(sections.events)`.
5. **Packaging:** `tools/local_api/pipeline_runner.py:989-1000` (`_package_mapset`) copies the background into the mapset directory as `manifest.background.normalized_filename` and calls `package_osz_archive(..., background_path=background_copy)`; `tools/map_generator/osu_format/mapset_packager.py:17-57` **cross-validates** that the archive's background file name matches the filename referenced by the parsed `.osu` files (`normalize_osu_relative_path(parsed.background_filename)`) and raises `MapGeneratorError` on mismatch — a nice integrity guarantee.
6. **Final verification:** `pipeline_runner.py:_verify_package_contents` re-opens the `.osz` and asserts the audio is present and `.osu` count matches the selection (background presence is indirectly guaranteed by step 5).
7. **Results reporting:** `ResultsStep.ts` renders a "Background Included — Yes/No" stat card from `workspace.workspace.background` (`ResultsStep.ts`, results-stat-grid).

**Consistency note:** because the canonical filename is always `background{ext}`, the `[Events]` reference and the archive entry can never diverge, even after repeated replacements (each upload deletes the previous file and updates the manifest signature).

---

## 2. In-Browser Parameter Controls

### 2.1 What users CAN edit before generation — extensive

Step 3 ("Select Difficulties", `src/generator/steps/DifficultyStep.ts` → `src/generator/components/DifficultySelector.ts`) exposes per-difficulty (Easy / Normal / Hard, independently tuned) controls. Mapping controls are collapsed by default ("Mapping controls stay collapsed to keep the main selection flow compact") behind a **"Show Mapping Controls"** toggle (`data-action="toggle-advanced-settings"`, persisted across reloads via `GeneratorPersistence`).

| Control | Widget | Range / Values | Code |
|---|---|---|---|
| Mapping Preset | Chip buttons: Balanced / Technical / Aim / Rhythm / Tournament / Custom | Full control sets per preset (`MAPPING_PRESETS`, `GeneratorModels.ts`) | `renderPresetPicker` |
| Circle Density | Range slider 0–100% | normalized 0–1 (`data-scale="percent"`) | `renderMappingSliders` |
| Slider Density | Range slider 0–100% | 0–1 | 〃 |
| Spinner Frequency | Range slider 0–100% (0% = "None" disables spinners) | 0–1 | 〃 |
| Jump Intensity | Range slider 0–100% | 0–1 | 〃 |
| Stream Intensity | Range slider 0–100% | 0–1 | 〃 |
| Burst Intensity | Range slider 0–100% | 0–1 | 〃 |
| Rhythm Complexity | Range slider 0–100% | 0–1 | 〃 |
| Pattern Variety | Range slider 0–100% | 0–1 | 〃 |
| Spacing | Range slider 0–100% | 0–1 | 〃 |
| Mapping Aggression | Range slider 0–100% | 0–1 | 〃 |
| Section Sensitivity | Range slider 0–100% | 0–1 | `renderPercentField` |
| Difficulty Target | Radio: Auto / Custom stars + Min/Target/Max star number fields (0.5–12, step 0.1) | | `renderDifficultyTarget`, `renderStarField` |
| Candidate Count | Number 1–64 (defaults 8/10/12 per tier) | | `renderAdvancedFields` |
| Evolution Passes | Number 1–5 | | 〃 |
| Generation Seed | Auto/Manual radio + numeric seed + **Randomize button** (`data-action="randomize-seed"`) | | `renderSeedField` |
| Replay Profile | Select: Beginner / Intermediate / Advanced / Tournament / Custom | | `renderSelectField` |
| Timing Variation | Toggle | | `renderToggleField` |
| Tournament Mode | Toggle | | 〃 |
| Hybrid Assembly | Toggle | | 〃 |

State handling: `GeneratorApp.updateDifficultySetting()` (per-key store update; percent scaling `value/100` clamped 0–1; integer rounding for counts/seeds). **Smart preset semantics:** editing any of the 11 mapping sliders (the `MAPPING_CONTROL_KEYS` set, `GeneratorApp.ts:31-43`) auto-flips `mappingPreset` to `"custom"` so manual edits are not silently overwritten by the stored preset (explicit comment at `GeneratorApp.ts` inside `updateDifficultySetting`). Seed "auto" mode is materialized to a concrete manual seed at save time (`materializeAutomaticSeeds`) so re-runs stay deterministic.

Draft validation gates: `GeneratorValidation.validateMetadataDraft` / `validateDifficultySelection` / `validateMappingWarnings` disable Continue and render inline error/warning lists (`DifficultyStep.ts`, `errorsMarkup` / `warningsMarkup`).

### 2.2 Dynamic piping to the local API pipeline runner — YES, verified end-to-end

1. **Save:** `handleClick("continue-to-generate")` → `saveConfiguration()` → `GeneratorApiClient.updateMetadata()` → `PUT /api/workspaces/{id}/metadata` with the full `WorkspaceMetadata` payload (`GeneratorApiClient.ts`).
2. **Backend persistence:** manifest `metadata.difficulty_settings` (`tools/local_api/models.py:150` region, `WorkspaceMetadata` with camelCase↔snake_case aliases); `configuration_signature` recomputed so a changed config invalidates previous outputs (`pipeline_runner.py:run_job` clears previous outputs when `last_run_signature != configuration_signature`).
3. **Consumption:** `PipelineRunner._effective_preset()` (`pipeline_runner.py:88-106`) → `resolve_mapping_controls(settings.mapping_preset, self._mapping_controls(settings))` → `apply_mapping_controls(base, controls)` over the tier base preset; custom star targets route through `apply_custom_star_adjustment(preset, custom_star_adjustment(difficulty, target))`. Positional variation derives from the same controls (`_base_variation` → `build_position_variation_biases`).
4. **Per-candidate payload:** `_generation_config_payload()` (`pipeline_runner.py:131-160`) emits `difficulty`, `mappingPreset`, `difficultyTarget`, `controls{...10 values}`, `candidateCount`, `evolutionPasses`, `rootSeed`, `seedMode`, `replayProfile`, `sectionSensitivity`, `timingVariation`, `tournamentEnabled`, `hybridAssemblyEnabled`, `customStars{target,min,max}` — i.e. **every UI control reaches the generator deterministically**.
5. **Pre-flight confirmation:** Step 4 renders a full read-only config preview of the exact values that will drive the run (`GenerationStep.renderGenerationConfigPreview`, with the caption "The exact values below drive the pipeline. Identical configuration reproduces identical maps.").

### 2.3 What is NOT exposed as raw osu!-format values

- **BPM offset / timing offset:** ❌ no browser control. Timing comes from audio analysis (`build_primary_timing_point(analysis_path)`, `export_pipeline.py:69`); no UI field for manual offset nudge, no beatmap editor hook from the metadata step. The editor (`editor.html`) is the intended venue for manual timing fixes, but there is no handoff from the generator wizard.
- **Slider Velocity (SV), AR, CS, HP, OD as direct user inputs:** ❌ not user-settable in the browser. They are **derived**: `convert_project_difficulty_to_osu_values(beatmap, difficulty_name)` (`export_pipeline.py:72-78`) computes `HPDrainRate / CircleSize / OverallDifficulty / ApproachRate / SliderMultiplier / SliderTickRate` from the project difficulty model and tier. The closest user lever is the **Custom Stars target band** (`customMinStar/customTargetStar/customMaxStar`), which steers the difficulty adjustment indirectly through `apply_custom_star_adjustment`.
- **"Target density":** ✅ covered, but as **abstract normalized mapping controls** (`circleDensity`, `sliderDensity`) rather than an objects-per-second figure. There is no numeric "objects/second" or measured-density display.
- **Assessment:** this is a deliberate abstraction (tier presets + 0–1 influence knobs) rather than a deficiency per se — it keeps the wizard approachable. However, power users must drop to the editor or CLI for raw values; the UI offers no "advanced/raw" mode, no live difficulty-star estimation feedback while dragging sliders, and no per-control reset-to-preset affordance beyond re-clicking a preset chip.

### 2.4 Editor parameter settings for contrast

`src/editor/EditorSettings.ts` (settings panel: `src/editor/panels/SettingsPanel.ts`) shows the codebase *is* capable of editor-side settings; the generator wizard simply doesn't expose raw osu! fields. There is no shared settings model between the two apps.

---

## 3. UI Deficits & Compactness

### 3.1 Missing interactive controls (ranked)

1. **No audio waveform / playback visualizer in the generator.** The hero "waveform" on Step 4 (`GenerationStep.ts`, `generation-waveform` block) is **decorative** — 18 hardcoded bar heights `Array.from({length:18}, ...)` with `aria-hidden="true"`, identical for every song. Meanwhile a real waveform renderer exists in the editor (`src/editor/timeline/WaveformRenderer.ts`, plus `EditorAudioController.ts`), so the capability exists in-repo and is simply not reused. There is also **no `<audio>` playback** in the generator despite the backend exposing an audio preview endpoint (`app.py:226-231` `preview_audio`, URL built by `ArtifactService.build_audio_preview_url` — currently only consumed internally for pipeline config, not surfaced as a player).
2. **No per-section density preview / timeline scrubber before generation.** Section analysis artifacts (`sections/sections.json`, recovery reports) are produced *after* generation; the configuration step shows numeric sliders only. A waveform with detected section overlays would let users sanity-check mapping intensity against musical structure pre-run.
3. **No raw timing offset / BPM correction input** (§2.3). If audio analysis mis-detects BPM/offset, the only remedy is leaving the wizard.
4. **No global "apply to all difficulties" control.** Each of the 10 mapping sliders must be set per tier; a "copy Easy → Normal/Hard" or lock-link affordance is absent (`DifficultySelector.renderAdvancedSettings` renders three independent cards).
5. **No background drag-and-drop** (audio-only dropzone, §1.1) and **no background preview after reload** (§1.2 defect).
6. **No "estimated objects / estimated star rating" live feedback** when adjusting sliders or star targets — the config preview card only echoes the chosen values back.
7. **No difficulty-settings comparison view** (side-by-side of the three tiers) — the config preview grid stacks cards vertically (`config-preview-grid`).
8. **No job history / resume affordance in the sidebar** — only the current job tile; previous workspaces are deleted on "Start New Song" (`startNewSong()` → `deleteWorkspace`, with `window.confirm`), so there is no archive browsing (artifacts are per-workspace, `GET /api/workspaces/{id}/artifacts`).
9. **Keyboard accessibility is partial:** wizard stepper and chips are real `<button>`s (good), but range sliders have no keyboard-value display beyond `<output>` binding, and there are no shortcut keys for step navigation (the editor has `EditorKeyboard.ts`; the generator has none).

### 3.2 Progress telemetry — present and honest, minor gaps

- **Polling:** 1-second `setTimeout` poll loop (`GeneratorApp.startPolling`, 1000 ms) against `GET /api/jobs/{jobId}`; auto-stops on terminal status and refreshes the workspace. Survives reload via persisted `jobId` (`bootstrap` re-fetches and resumes polling for non-terminal jobs).
- **Metrics panel** (`PipelineProgress.ts`): Overall Progress % (with track bar), Current Stage label + latest message, **Elapsed wall time** (`computeElapsedMs`), "Stages Closed X of Y". Explicitly *no synthetic progress* ("Progress is reported from the actual Python stages. No synthetic progress is shown between stage boundaries." — `GenerationStep.ts` head copy).
- **Stage timeline:** per-stage cards with OK/RUN/FAIL/CANCELLED/WAIT badges (`PipelineStageCard.ts`), difficulty chips, and candidate chips (`Candidate 3/12`) for evolution stages; plus a numbered progress line (`pipeline-stage-progress-nodes`).
- **Candidate telemetry:** `renderCurrentCandidateProgress` shows current difficulty evolution and candidate index with a bar (`PipelineProgress.ts`).
- **Logs:** collapsible terminal feed with per-entry level styling (`job-log-entry--info/warning/error`), "Copy Logs" to clipboard, and a collapsible **technical details** `<pre>` (full stack trace) on failure (`JobLogPanel.ts`).
- **Gaps:** (a) **no ETA / per-stage duration display** — elapsed time only, though stage timings are already computed server-side (`_stage_ms` in `run_job`) and merely logged; (b) no WebSocket/SSE push (1 Hz polling is fine locally, but log tailing is chunky); (c) no in-panel retry-per-stage (retry restarts the whole job); (d) warning counts are not surfaced as a badge — warnings live inside `job.warnings` and the log stream only.

### 3.3 Compactness & layout assessment

- **Strengths:** 5-step wizard with clickable stepper (`wizard-stepper`, gated by `canJumpToStep`); persistent left sidebar with live status tiles (audio/background/difficulties/job) that doubles as state summary; progressive disclosure (mapping controls collapsed by default; logs collapsed unless a job exists; technical details collapsed); footer with cross-links to editor/game/docs; **responsive breakpoints at 1320/1180/940/720 px** plus `prefers-reduced-motion` support (`generator.css:2024,2051,2086,2419,2471`); visual-hidden inputs with button-driven file pickers; `aria-label`s on most controls; banners are `aria-live="polite"` in the generate step.
- **Deficits:**
  1. **Full re-render on every keystroke.** `handleInput` → store update → `render()` rebuilds `root.innerHTML` wholesale. On text-heavy fields (Tags textarea, metadata inputs) this loses **focus and caret position** mid-typing whenever a re-render interleaves with composition of multibyte text (IME input for the Phase 2 Unicode fields is the risky case). There is no DOM diffing, no focused-element preservation. This is the single largest architectural debt in the UI layer.
  2. **XSS-safety is manual but consistently applied** — every interpolation passes through `escapeHtml` (`src/shared/format.ts`); audited spots (metadata values, filenames, log messages, artifact names) all comply. `renderIcon` outputs are static. Residual risk: any future template author forgetting `escapeHtml` has no framework guard.
  3. **Sidebar duplication during generate step:** the global banners are suppressed on the generate step (`showGlobalBanners = state.currentStep !== "generate"`) and replaced by inline banners — good — but the sidebar job tile and the generate metrics panel show overlapping data (double "overall %" surfaces).
  4. **Unbounded log DOM:** the log panel appends all events on each render (`job.events` grows monotonically); long jobs (evolution × many candidates) will grow the DOM without a virtualization cap or auto-scroll-to-bottom behavior.
  5. **No loading/skeleton states** for artifact lists (results step renders nothing until `refresh` completes) — minor.
  6. **`window.confirm` for destructive actions** (`startNewSong`) — functional but stylistically inconsistent with the polished wizard chrome; a modal would match better.
- **CSS:** 2,479 lines of hand-written CSS, BEM-ish class conventions, design tokens via CSS custom properties, icon set as inline SVG functions (`GeneratorIcons.ts`). Well-organized; no dead-framework weight.

---

## 4. Verdict Table — Audit Questions

| # | Audit Question | Answer |
|---|---|---|
| 1a | Upload custom background from web UI? | **Yes** — file picker with progress (`MetadataForm.ts`, `GeneratorApiClient.uploadBackground` → `app.py:147`) |
| 1b | Replace existing background? | **Yes** — "Replace Background" re-uses the same flow; old file deleted, manifest signature invalidated (`upload_service.py:87-110`) |
| 1c | Live-preview in browser? | **Yes, per-session only** — blob URL preview (`GeneratorApp.uploadBackground`); ⚠ lost on reload (no background GET route; audio GET exists at `app.py:226`) |
| 1d | Linked into `.osu` `[Events]` on export? | **Yes** — `export_pipeline.py:89-93` writes `0,0,"background.jpg",0,0`; writer `writer.py:17-19`; verified against archive in `mapset_packager.py:47-57` |
| 2a | Modify generator params in UI pre-generation? | **Yes** — 11 mapping sliders + presets + star targets + candidate/evolution/seed controls per difficulty (`DifficultySelector.ts`) |
| 2b | BPM offset, raw SV/AR/CS/HP as direct inputs? | **No** — derived from difficulty model (`export_pipeline.py:72-78`); only indirect via custom star band; no timing-offset field |
| 2c | Target density control? | **Yes, abstract** (`circleDensity`/`sliderDensity` 0–1), not objects-per-second |
| 2d | Settings piped dynamically to local API runner? | **Yes, fully** — `PUT /metadata` → manifest → `_effective_preset`/`_generation_config_payload` (`pipeline_runner.py:88-160`); signature-gated determinism |
| 3 | Missing essentials? | Waveform/audio visualizer (only a static mock), playback, ETA/per-stage timing display, raw-value override mode, per-difficulty copy/lock, background DnD + reload-persistent preview, focus-preserving re-renders, log virtualization |

---

## 5. Recommended Remediations (non-binding, for Phase 4+ planning)

1. **P0 — Restore background preview after reload:** add `GET /api/workspaces/{id}/preview-background/{filename}` (mirror `preview_audio`, `app.py:226`) and in `GeneratorApp.bootstrap()` set `backgroundPreviewUrl` from `workspace.workspace.background.relativePath`-based URL when a background exists.
2. **P0 — Preserve input focus across re-renders:** capture `document.activeElement` id + selection before `render()` and restore after, or patch only the changed subtree. Protects Unicode/IME metadata entry (Phase 2 regression risk).
3. **P1 — Real waveform component:** reuse `src/editor/timeline/WaveformRenderer.ts` in the Upload/Generate steps fed by `preview_audio`; overlay `sections.json` bands post-generation; make the Step 4 hero use live data instead of the static 18-bar mock.
4. **P1 — Surface stage timings + ETA:** server already computes `_stage_ms` per stage (`run_job`); include in job events and render a per-stage duration column and naive ETA.
5. **P2 — "Copy settings to all difficulties" + per-control reset** in `DifficultySelector`.
6. **P2 — Global advanced mode** exposing timing offset and direct AR/CS/HP/SV overrides (written into `[Difficulty]` at export), for power users who don't want to leave the wizard.
7. **P3 — Log virtualization / cap** (e.g. render last N events) and auto-scroll; **P3 — replace `window.confirm` with an in-app modal**.

---

*Report generated by static analysis of the working tree at commit `fca2d85` ("Implement Phase 2 fixes…"). No production code was modified.*
