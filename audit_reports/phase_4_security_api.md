# Phase 4 Audit — Application Security & Systems Reliability

**Scope:** Security and resource lifecycle audit of the local API (`tools/local_api/`) and the pipeline runner, covering upload validation, path handling, resource limits, temp-file hygiene, and concurrency. Static analysis only — no production code written or edited.
**Date:** 2026-09-27
**Audit reference:** `phase_4_security_api.md` (task definition in repository root)
**Baseline:** commit `fca2d85` ("Implement Phase 2 fixes…")

---

## Executive Summary

The local API is a **FastAPI + uvicorn application hard-bound to `127.0.0.1:8765`** (`tools/local_api/config.py`: `host` defaults to `127.0.0.1`, overridable via `PULSE_LOCAL_API_HOST`) with CORS restricted to the two local Vite dev origins (`config.py` `allowed_vite_origins`, applied in `app.py:create_app`). It is designed as a localhost-only companion service, which dramatically shrinks the attack surface; nonetheless the audit evaluated every layer as if inputs were hostile.

**Headline findings:**

- ✅ **Uploads:** extension whitelist + streaming size caps + atomic rename are solid. **However, there is NO magic-byte / content sniffing** — a renamed `.mp3` that is actually arbitrary data (or a PE/ELF binary, or a polyglot) is accepted, as the checks are filename- and size-only. The declared `content_type` is stored but never verified against actual bytes. Risk is mitigated by the localhost binding and by the fact that uploads are never executed nor served with attacker-controlled `Content-Type` headers at uncontrolled origins.
- ✅ **Path traversal:** consistently defended. Workspace IDs are UUID-regex-validated (`security.py:WORKSPACE_ID_PATTERN`), relative paths pass `ensure_safe_relative_path` + a `resolve()` containment check (`security.py:resolve_workspace_relative_path`), uploads are renamed to canonical server-chosen filenames, and artifact resolution re-validates every path against the workspace root. No `extractall` on untrusted zips exists anywhere — the only zip *read* is over a locally produced `.osz` (`pipeline_runner.py:1018`), and the only zip *write* is the packager (`mapset_packager.py:66`).
- ❌ **No execution timeouts or memory limits** on any pipeline stage. A hung `librosa` decode or a pathological candidate-evolution run blocks its worker thread forever; cancellation is cooperative only.
- ⚠️ **Temp/debug directories leak.** `.tmp-e2e-generation/`, `.tmp-local-api-debug/`, `.tmp-phase7/8`, `.tmp-postprocess-check/`, `.tmp-osu-tests/` are created ad-hoc by scripts/tests and are **never garbage-collected by any service**. The API's `CleanupService` only manages `workspaces/`.
- ✅ **Concurrency:** per-workspace job exclusivity is correctly enforced under a lock (`JobManager._active_by_workspace` + `LocalApiConflictError` 409). Residual races exist in manifest read-modify-write (last-writer-wins) and in delete-vs-job lifecycle.

| Area | Verdict | Severity of gaps |
|---|---|---|
| Upload validation (ext/size/atomicity) | ✅ Strong | — |
| Upload magic-byte / MIME verification | ❌ Missing | Medium (localhost-bound) |
| Path traversal / arbitrary overwrite | ✅ Defended | Low (residual: manifest symlink swap) |
| Stage timeouts / memory caps | ❌ Missing | High (reliability) |
| Cancellation | ⚠️ Cooperative, stage-granular | Medium |
| Temp dir GC (`workspaces/`) | ✅ Manual CLI (`cleanup` subcommand) | — |
| Temp dir GC (`.tmp-*` scratch dirs) | ❌ Leaks | Medium (disk) |
| Concurrency / races | ✅ Mostly sound | Medium (manifest writes, delete races) |

---

## 1. Endpoint & Input Security

### 1.1 Upload validation — extension + size + atomicity, but no content inspection

**Endpoint surface** (`tools/local_api/app.py`): `POST /api/workspaces`, `GET /api/workspaces/{id}`, `POST .../audio`, `POST .../background`, `PUT .../metadata`, `POST .../generate`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE), `POST /api/jobs/{id}/cancel`, `GET .../artifacts`, `GET /api/artifacts/{artifact_id}/download`, `GET .../source-audio/{filename}`, `DELETE .../workspaces/{id}`, `GET /api/health`.

**What is enforced** (`tools/local_api/upload_service.py`):

1. **Extension whitelist** — `ensure_allowed_extension(filename, config.allowed_audio_extensions)` (`security.py:31-40`): suffix must be exactly one of `.mp3/.wav/.ogg/.flac` (audio) or `.jpg/.jpeg/.png/.webp` (background); otherwise `LocalApiUnsupportedMediaTypeError` → HTTP 415. Empty/missing suffix rejected. Note: the whitelist check uses `Path(filename).suffix` on the *client-supplied* filename; the stored name is then replaced entirely by the server (`source-audio{suffix}` / `background{suffix}`, `upload_service.py:22`/`:78`), so client filenames never touch the filesystem.
2. **Size limits — streamed and enforced mid-flight** (`_write_upload_file`, `upload_service.py:104-142`): the body is consumed in 1 MiB chunks and `total_size > max_size_bytes` raises `LocalApiPayloadTooLargeError` → HTTP 413 mid-stream (default caps: **200 MiB audio**, **25 MiB background**, env-tunable via `PULSE_LOCAL_API_MAX_AUDIO_BYTES` / `PULSE_LOCAL_API_MAX_BACKGROUND_BYTES`, `config.py:54-62`). Empty uploads rejected (0-byte check).
3. **Atomic write:** chunks land in a `NamedTemporaryFile` in the destination directory, then `os.replace(temporary_path, destination)` — readers never observe a partially written file, and the `finally` block unlinks the temp file on any failure (`upload_service.py:141-144`). ⚠ Minor: the temp file inherits `NamedTemporaryFile`'s 0600 permissions on POSIX, and after `os.replace` the final file keeps those restrictive bits — harmless here, worth noting.
4. **Previous-file deletion** (`_delete_previous_file`) prevents accumulation of stale `source-audio.*` variants when the extension changes between uploads.
5. **SHA-256 + descriptor:** every stored file gets a `sha256_hex` digest and manifest descriptor including `sizeBytes`, `contentType`, and `relativePath` (`upload_service.py:25-33`).
6. **Decode-time validation (audio only):** `MetadataService.extract_audio_metadata` (`metadata_service.py:132+`) runs mutagen → soundfile → librosa decode; if nothing can decode the file, `LocalApiValidationError("Uploaded audio file could not be decoded.")` is raised. This is an *effective* (though unintentional-looking) content check for audio: garbage renamed `.mp3` fails at upload time (the decode runs inside `save_audio` via `expect_audio=True`). **Backgrounds get no equivalent check** — any bytes with a `.png` name are stored, manifest-registered, and packaged.

**What is NOT enforced:**

- ❌ **No magic-byte signature check** (no `python-magic`, no manual header sniff of `ID3`/`0xFFEx`/`RIFF`/`OggS`/`fLaC`/`RIFF....WEBP`/`\x89PNG`). A polyglot or a mislabeled file whose *audio frames* still decode would pass. Mutagen parse errors on hostile-but-decodable files raise inside `extract_audio_metadata` — wrapped where? `save_audio` does not catch exceptions around `_write_upload_file`, so mutagen/library exceptions other than the explicit `RuntimeError` around `soundfile.info` would surface as unhandled 500s rather than 422s (FastAPI would still return a generic 500 without stack details leaking to the client, and the temp-file `finally` cleanup still runs — so impact is availability/noise, not disclosure).
- ❌ **Declared MIME type never verified.** `upload_file.content_type` is trusted for storage and later re-served verbatim by `FileResponse` in `preview_audio` (`app.py:226-243`). On a localhost-only app the blast radius is small, but a `Content-Type: text/html` audio upload would be re-served with that type by the preview endpoint from the *api origin* — a stored-XSS-adjacent pattern that is currently neutralized only by the origin being `127.0.0.1:8765` rather than a shared web origin.
- ❌ **No count/quota limits:** a client can create unbounded workspaces (`POST /api/workspaces` has no rate limit, no max-workspace cap) — see §2.4.
- ✅ Metadata `PUT` payloads are pydantic-validated with strict length caps (title/artist 160, source 160, tags 512, creator 80 — `config.py:63-68`, enforced in `metadata_service.py:validate_metadata/_collect_length_errors`) and NFC normalization (`_normalize_metadata`). Numeric ranges validated (candidateCount 1–64, evolutionPasses 1–5, seed ≥ 0, custom star band ordering 0.5 ≤ min ≤ target ≤ max ≤ 12.0). This is genuinely good input hygiene.

### 1.2 Path traversal & arbitrary file overwrite — well defended

Layered defenses verified:

1. **Workspace ID validation** (`security.py:14-24`): every `workspace_id` is checked against a strict lowercase-UUID regex before any filesystem use. No `..`, no separators possible.
2. **Relative-path containment** (`security.py:ensure_safe_relative_path` + `resolve_workspace_relative_path`): backslashes normalized, leading slashes stripped, `../` patterns rejected, and then a **`resolve()` + parents check** ensures the final path stays under the workspace root. Used by `WorkspaceManager.resolve_relative_path` for every descriptor-based file access (`workspace_manager.py:151-154`).
3. **Server-chosen filenames:** uploads never use client filenames on disk (§1.1), eliminating the classic "filename=../../x" upload vector by construction.
4. **Artifact download path safety** (`artifact_service.py:resolve_artifact:145-160`): the artifact ID (`{workspaceId}:{sha1-16}`) is split, the manifest is reloaded from disk, and the matched artifact's `relative_path` is re-resolved through the containment check — a client cannot request an arbitrary path, only paths that the server itself registered in the manifest.
5. **Descriptor double-checks** (`workspace_manager.py:_resolve_uploaded_file_path:186-219`): filename must be a bare name (`Path(name).name == name`), must match the registered `relative_path` basename, suffix must be in the whitelist, and the target must exist, be a file, and pass `stat.S_ISREG` — this rejects symlinks disguised as audio (`S_ISREG` is true for symlink *targets*; a symlink pointing inside the workspace to another file would still pass, a negligible local-only concern) and rejects devices/dirs.
6. **No untrusted zip extraction:** grep confirms `zipfile` appears only in `pipeline_runner.py:1018` (read-mode verification of the self-produced `.osz`) and `mapset_packager.py:66` (write-mode packaging of locally generated files). **There is no `extractall` on any user-supplied archive anywhere** — the mapset import path (`osu_format/import_pipeline.py`) parses `.osu` text rather than extracting archives, so Zip-Slip is structurally out of scope. (`_validate_archive_name` in `mapset_packager.py` additionally enforces flat entry names on write.)
7. **Background `[Events]` injection:** the export writes `0,0,"{background_filename}",0,0` (`export_pipeline.py:89`) using the server-canonicalized `background.*` name — no quoting/escape path exists for client text to enter that line.
8. **`preview_audio` filename match** (`app.py:226-231`): the requested `filename` must equal `manifest.audio.normalized_filename` exactly — no path components can be smuggled.

**Residual (low) risks:**

- **Manifest TOCTOU/symlink swap:** `save_manifest` writes `workspace.json` with a plain `write_text` (`workspace_manager.py:132-141`). A local process that can write into `workspaces/{id}/` could replace `workspace.json` with a symlink to another file and have the API rewrite that file (it runs with user privileges; on Windows, symlink creation needs privileges, further lowering risk). There is no `os.open` with `O_NOFOLLOW` hardening. Local-host threat model keeps this Low.
- **`ensure_safe_relative_path` edge cases:** it rejects `../` and absolute paths, and the subsequent `resolve().parents` check catches encodings/oddities anyway — defense in depth holds. Windows drive-letter absolutes (`C:\x`) survive normalization as `C:/x` but the parents-containment check rejects them.
- **Workspace delete glob** (`workspace_manager.py:delete_workspace:157-166`): deletes files then directories deepest-first within the workspace root only; the UUID-validated root makes path escape implausible. `missing_ok=True` + `rmdir` tolerates concurrent additions poorly (see §3.3).

### 1.3 Other endpoint hardening notes

- **CORS:** `allow_credentials=False` with an explicit origin list (`app.py:77-82`) — a rogue website in the user's browser *could still fire requests* at `127.0.0.1:8765` (CORS blocks reading responses, not sending), so CSRF-style drive-by workspace deletion is *attemptable* but the JSON-content-type `PUT`/`POST` bodies would be blocked by the CORS preflight for non-simple requests; `DELETE` with no custom headers is a simple request and would execute cross-site (browser sends it, CORS blocks only the *response read*). ⚠ **No CSRF token / no `Origin` header validation on mutating endpoints** — a malicious public webpage can trigger `POST /api/workspaces` and `DELETE /api/workspaces/{known-id}` cross-origin (workspace IDs are unguessable UUIDs, which is the only thing keeping deletion targeted). Severity: Low-Medium, worth an `Origin: localhost` assertion.
- **SSE endpoint** (`app.py:203-209` + `job_manager.stream_events`): unbounded `while True` with 1 s condition wait; loop exits on terminal status, but if a client disconnects, the generator keeps yielding until the job terminates (uvicorn discards the yields; the job itself is unaffected). Acceptable locally; a client-count cap is absent.
- **Error hygiene:** `LocalApiError` handlers return structured `{"detail": ...}` (`app.py:84-106`); pipeline failures deliberately sanitize unexpected messages to `"Generation failed unexpectedly."` while keeping the full traceback server-side/in-logs (`pipeline_runner.py` failure path, `readable_message` logic) and only expose the traceback via `technicalDetails` to the workspace owner's UI. No stack traces leak by default. Good.

---

## 2. Resource Exhaustion & Timeouts

### 2.1 Stage execution timeouts — **none exist** ❌

There is **no timeout wrapper anywhere in the pipeline execution path**:

- `JobManager.create_job` (`job_manager.py:37-70`) starts a bare `Thread(target=self._run_job, daemon=True)`; `pipeline_runner.run_job` executes `stage.action()` synchronously (`pipeline_runner.py:196`) with no watchdog, no `threading.Timer`, no `concurrent.futures` with timeout, and no per-stage wall-clock budget. A stage that hangs (e.g. `librosa.load` stuck on a pathological file, a deadlock in the evolution loop) runs forever.
- **Job records are in-memory only** (`self._jobs: dict[str, JobRecord]`) — on process restart, running jobs vanish from the manager (the manifest keeps `job_status: "running"`, orphaned; `CleanupService` would consider such a workspace `running` and **refuse to delete it** via `delete_workspace`'s conflict check `cleanup_service.py:12-16`, though `delete_older_than` also skips `running` status — so an orphaned "running" workspace is permanently protected from both APIs until the manifest is hand-edited). This is a genuine lifecycle bug surface: crash mid-job → zombie workspace that the cleanup CLI cannot remove (`--older-than` skips `queued/running`; `--failed-only` skips non-failed).
- **No request-level timeouts** are configured on uvicorn (defaults), and no `TimeoutMiddleware` exists. For a localhost tool this is tolerable for HTTP, but the *pipeline* timeouts matter most and they are absent.

### 2.2 Memory limits — **none** ❌

- `analyze_audio` / `_load_audio` load raw PCM samples into memory (the e2e script explicitly fetches `raw_samples` via `audio_analyzer._load_audio`; the generation path does the same for slider intelligence). A 200 MiB MP3 at 44.1 kHz mono float32 is ~30 minutes ≈ 150+ MiB RAM per load; multi-candidate evolution regenerates per candidate. No streaming/chunked analysis, no `resource.setrlimit`, no process isolation (`multiprocessing` with memory caps), no container cgroup (local dev assumption).
- Multiple concurrent jobs across *different* workspaces each spawn their own thread and their own audio loads — RAM usage scales linearly with concurrent jobs, unbounded (§3.1: no global concurrency cap).
- Job telemetry accumulates **unboundedly in memory**: every `append_event` grows `JobRuntimeState.events` (`job_models.py:60-68`) for the process lifetime; `warnings`/`errors` lists likewise. Long evolution runs with per-candidate messages produce thousands of events, all retained and all serialized into every `GET /jobs/{id}` response (`to_response(include_events=True)` default) — O(events) payload per 1 s poll, per client.

### 2.3 Cancellation — cooperative and stage-granular ⚠️

- `POST /api/jobs/{id}/cancel` sets `cancel_requested` under the record condition (`job_manager.py:141-149`).
- The runner checks it **only between stages** (`pipeline_runner.py:193` `_check_cancellation`) plus inside `_improve_map`-adjacent code paths where `LocalApiCancellationRequested` is caught per-stage (`pipeline_runner.py:203-222`). The evolution stage passes `progress_callback` → `update_candidate_progress` (`pipeline_runner.py:666-679`), which updates state but **does not check cancellation** — so a 12-candidate × 5-pass evolution run cannot be interrupted mid-way; the UI's "The pipeline will stop between safe stage boundaries" notice (`GeneratorApp.cancelGeneration`) accurately describes this limitation.
- Long stages (`analyze-audio`, `generate-*`, `evolution-*`) therefore have cancellation latency equal to full stage duration — combined with §2.1 (no timeouts), a runaway stage is neither interruptible nor killable from the API.

### 2.4 Disk exhaustion vectors

- **Workspace creation is unbounded:** `POST /api/workspaces` always succeeds and creates ~27 directories (`workspace_manager.py:_ensure_directory_tree`); no cap on total workspaces or total disk usage; no rate limiting on any endpoint.
- **Per-job output size is unbounded by config:** candidate archives with `archive_policy="all"` (`pipeline_runner.py:707`) persist every candidate map + report per difficulty (up to 64 candidates × 5 passes per the validation bounds).
- **Upload temp files** are cleaned by `finally` (good), but a client streaming indefinitely against a slow reader holds the temp file open for the duration — bounded by the 200 MiB cap.

---

## 3. Workspace Cleanup & Concurrency

### 3.1 `workspaces/` lifecycle — manual GC only, no automation ✅/⚠️

- **Automated garbage collection: none at runtime.** `CleanupService` (`cleanup_service.py`) exposes: `delete_workspace` (blocked while `job_status ∈ {queued, running}` → 409), `delete_failed_workspaces(older_than_hours)` (failed/cancelled only), and `delete_older_than(hours)` (skips active jobs). All are reachable only via (a) `DELETE /api/workspaces/{id}` (single, user-triggered from the UI "Start New Song") or (b) the **CLI subcommand** `python -m tools.local_api.app cleanup [--workspace-id|--failed-only|--older-than-hours]` (`app.py:main:263-283`). **Nothing schedules or invokes these automatically** — no TTL sweeper thread, no on-boot sweep, no max-workspace quota. A user who abandons workspaces accumulates them until they manually run the CLI.
- Orphaned-running edge (§2.1) makes abandoned workspaces *uncleanable through the provided tooling* — the `delete_older_than` skip of `queued/running` statuses is correct for live jobs but has no staleness override (no "running for > N hours" exception, and `updated_at` is not consulted for running workspaces).

### 3.2 `.tmp-e2e-generation/` and sibling scratch dirs — **leak confirmed** ❌

Verified inventory of temp/debug dirs in the repo root and their producers:

| Directory | Producer | GC mechanism |
|---|---|---|
| `.tmp-e2e-generation/` | `tools/e2e_generation.py:54` — `WORK = PROJECT_ROOT / ".tmp-e2e-generation"`; `setup_dirs()` only `mkdir(parents=True, exist_ok=True)` | **None.** Reused (exist_ok), never wiped at start, never deleted at end. Stale maps/reports/osz from old runs persist indefinitely and are silently reused-if-present only where the pipeline caches (`e2e` regenerates unconditionally, but old artifacts of *removed* code paths linger) |
| `.tmp-local-api-debug/` | local debug harness (no reference found in `tools/`, `scripts/`, or `tests/` — created by an ad-hoc/out-of-tree run) | **None.** Orphaned output (workspace exports, hybrid assemblies) from a past debug session |
| `.tmp-phase7/`, `.tmp-phase8/`, `.tmp-postprocess-check/`, `.tmp-osu-tests/` | ad-hoc test scripts | **None** |
| `tools/.tmp-e2e-generation/` | test runs executed with `tools/` as cwd (relative-path bug in scripts) | **None** |
| `workspaces/`, `public/`, `exports/` | runtime outputs of the API | Manual CLI cleanup for `workspaces/` only; `exports/` (e2e `.osz` output, `e2e_generation.py:65`) has none |

- **Assessment:** these scratch dirs are *out-of-band developer tooling*, not part of the served API, so they pose no security risk — but they are a **real disk-leak vector** (audio-sized intermediates: maps JSON, reports, `.osz` packages, the `tests/editor` 8.6 MB fixture copies etc.) and a hygiene problem now visible in `git status` noise (mitigated by the new `.gitignore` from commit `fca2d85`, which excludes `.tmp-*/`). Recommendation: have `e2e_generation.py` build under `tempfile.mkdtemp(prefix="pulse-e2e-")` (auto-OS-cleaned on Windows temp schedules) or add an explicit `--keep` flag defaulting to wipe-on-start + wipe-on-success; add a `cleanup --scratch` CLI mode for `.tmp-*`.

### 3.3 Concurrency — mostly correct, with three races ⚠️

**Correctly handled:**

1. **Per-workspace job exclusivity** (`job_manager.py:42-50`): `create_job` checks `_active_by_workspace[workspace_id]` **inside `self._lock`** and raises `LocalApiConflictError` (409) if a `queued/running` job exists. Two simultaneous "generate" clicks on one workspace cannot double-run. The registry entry is popped on `complete`/`fail`/`cancel` under the same lock.
2. **Job state mutation is condition-guarded:** every mutation goes through `_mutate` with `record.condition` + `notify_all` (`job_manager.py:190-196`); SSE waiters wake on each event. Clean design.
3. **Cross-workspace parallelism is intentional and safe-ish:** jobs on *different* workspaces run in independent threads on disjoint directory trees (UUID-scoped paths) — no shared-path collision is possible.

**Races found:**

- **R1 — Manifest read-modify-write (last-writer-wins).** `save_manifest` does a non-atomic `write_text` of the full manifest, and every service follows load→copy→save without any lock shared *between* services (`workspace_manager.py:122-141`). Concrete interleavings: (a) a running job's `begin_stage` writes `job_status: "running"` while the user concurrently `PUT`s metadata → the metadata save (stale `job_status: "queued"`) can clobber the running status, or vice versa — the job's later save resurrects old metadata-free state fields; (b) two metadata PUTs race and silently drop one edit; (c) `compute_configuration_signature` is computed against a manifest that may change between compute and write. No file lock (`msvcrt.locking`/`portalocker`), no `os.replace` atomic swap of a temp manifest, no version/etag field. Impact: UI-visible state flapping and signature desync (worst case: `last_run_signature == configuration_signature` mismatch causes spurious output wipes via `_clear_previous_outputs`); no corruption of generated artifacts themselves, which are written to distinct paths.
- **R2 — Delete vs. running job.** `CleanupService.delete_workspace` blocks deletion only if the *manifest* says `queued/running` (`cleanup_service.py:12-16`). Because job state and manifest status are updated at different moments (job created → manifest saved inside the same lock at `job_manager.py:53-58`, but stage transitions save the manifest *outside* the record lock), a `DELETE` racing a just-created job can read a stale manifest (`job_status: None`) and delete the workspace tree while the pipeline thread is writing into it — the pipeline then fails with cascading `FileNotFoundError`s (caught by the stage error handler, job marked failed, but artifacts of a deleted workspace may be re-created as stray directories). The frontend's own guard ("Cancel the active generation job before starting a new song") mitigates the UI path, but the API is open.
- **R3 — Job record memory vs. manifest divergence on crash/restart.** Covered in §2.1: after an API restart, `_jobs` is empty while manifests claim `running`. `GET /api/jobs/{id}` → 404; the UI cannot resume telemetry, and the workspace is cleanup-blocked (status `running`). No boot-time reconciliation job exists (e.g., mark `running` → `failed` on startup).

- **Thread-safety of shared services:** `PipelineRunner`/`ArtifactService`/`MetadataService` are stateless singletons shared across job threads (`app.py:_services`) — they hold no mutable state, so cross-job interference is limited to the filesystem races above. `lru_cache` on `get_local_api_config` is fine (frozen dataclass).

### 3.4 Test coverage of the security surface

`tools/local_api/tests/test_local_api.py` (18 tests) covers: workspace lifecycle, upload with/without metadata suggestions, **failed-upload atomicity** (`test_failed_audio_upload_does_not_leave_incomplete_manifest_state:148`), controlled 422s, generate gating, model round-trips, and — notably — **path escape rejection** (`test_resolve_audio_source_path_rejects_workspace_escape:505`). Gaps: no tests for oversized payloads (413 path), unsupported extensions (415 path), concurrent job creation (409 path), traversal via artifact IDs, or duplicate/corrupt manifests. The security-critical error paths are enforced in code but unpinned by tests.

---

## 4. Findings Register (prioritized)

| ID | Severity | Finding | Primary code reference |
|---|---|---|---|
| S1 | **High (reliability)** | No timeouts/memory caps on pipeline stages; hung stage = hung job thread, unrecoverable without process kill | `job_manager.py:60-70`, `pipeline_runner.py:196` |
| S2 | **High (reliability)** | Jobs are in-memory only; API restart orphans `running` workspaces that cleanup then refuses to delete; no boot reconciliation | `job_manager.py:31-33`, `cleanup_service.py:12-16`, `app.py:main` |
| R1 | **Medium** | Manifest saves are non-atomic, unlocked read-modify-write → last-writer-wins races between job status updates, metadata PUTs, uploads | `workspace_manager.py:122-141` |
| R2 | **Medium** | `DELETE /workspaces` can race a job start (stale-manifest window) and delete a live workspace tree | `cleanup_service.py:12-16`, `job_manager.py:53-58` |
| S3 | **Medium** | No magic-byte/content validation on uploads; background images accepted with arbitrary bytes; declared `content_type` trusted and re-served | `upload_service.py:104-142`, `app.py:226-243` |
| S4 | **Medium** | No CSRF/`Origin` enforcement on mutating endpoints; simple requests (`DELETE`) fireable cross-site by public webpages (unguessable UUIDs are the only mitigations) | `app.py:77-82`, `app.py:245-249` |
| D1 | **Medium (hygiene)** | `.tmp-*` scratch directories never garbage-collected; `e2e_generation.py` reuses-but-never-wipes its workdir | `tools/e2e_generation.py:54-67`; repo-root `.tmp-*` inventory |
| S5 | **Low-Medium** | Unbounded workspace creation + per-job artifact retention (`archive_policy="all"`, ≤64 candidates ×5 passes) with no disk quota | `app.py:97-100`, `pipeline_runner.py:707` |
| S6 | **Low** | Cancellation only between stages; `progress_callback` does not poll `cancel_requested` → long evolution stages uninterruptible | `pipeline_runner.py:193`, `:666-679` |
| S7 | **Low** | Job event/warning/error lists grow unboundedly in memory and serialize fully on every poll | `job_models.py:47-68`, `job_manager.py:127-135` |
| S8 | **Low** | Manifest write lacks `O_NOFOLLOW`/atomic-replace hardening (symlink swap needs local write access) | `workspace_manager.py:132-141` |
| S9 | **Low** | Mutagen/librosa exceptions during audio metadata extraction can surface as 500s instead of 422s (only `soundfile` RuntimeError is handled) | `metadata_service.py:168-190` |
| T1 | **Low (quality)** | Security-critical error paths (413/415/409, traversal) lack dedicated tests | `tools/local_api/tests/test_local_api.py` |

**Strengths worth keeping (verified, not just claimed):** strict UUID workspace IDs; resolve()-based path containment applied at *every* descriptor use; server-side canonical filenames; atomic upload writes with `finally` cleanup; streamed size enforcement; SHA-256 configuration signatures gating output reuse; sanitized error messages with stack traces kept server-side; localhost-only binding; no archive extraction of untrusted input anywhere.

---

## 5. Recommended Remediations (non-binding, for Phase 5+ planning)

1. **P0 — Stage watchdog:** run each `stage.action()` in a `ThreadPoolExecutor` future with `result(timeout=stage_budget)` (env-configurable, generous defaults), transitioning the job to `failed` on timeout; add `progress_callback` cancellation polling in `_run_evolution` so candidate loops check `cancel_requested` between candidates.
2. **P0 — Boot reconciliation + unstick cleanup:** on `create_app`, scan manifests with `job_status ∈ {queued, running}` and no live in-memory job → mark `failed` with a "process restarted" event; or teach `CleanupService.delete_older_than` to treat `running` workspaces with `updated_at` older than N hours as stale and deletable.
3. **P1 — Atomic manifest writes:** serialize to `workspace.json.tmp` + `os.replace`; add a per-workspace `threading.Lock` (or a process-wide `WeakValueDictionary[workspace_id → Lock]`) around every load→mutate→save cycle in `UploadService`, `MetadataService`, `JobManager`, and `DELETE`.
4. **P1 — Content sniffing:** verify magic bytes (ID3/0xFFEx, RIFF, OggS, fLaC; \x89PNG, \xFF\xD8\xFF, RIFF-WEBP) before `os.replace`; derive and store `content_type` from the sniffed signature instead of the client header; reject background decodes that fail a probe (e.g. PIL `verify()`).
5. **P1 — `Origin` allow-list middleware** for mutating verbs (reject requests whose `Origin` is present and not in `allowed_vite_origins`/same-origin) to close the cross-site DELETE gap.
6. **P2 — Scratch-dir hygiene:** `e2e_generation.py` → `tempfile.mkdtemp` + `--keep` flag; add `tools.local_api.app cleanup --scratch` sweeping `.tmp-*` older than N days.
7. **P2 — Bounded telemetry:** cap `events` (ring buffer, e.g. last 500) and expose `GET /jobs/{id}/events?since=` for tailing; stop sending full event arrays in the 1 Hz poll.
8. **P3 — Add the missing tests:** 413 oversize, 415 extension, 409 duplicate job, workspace-escape via artifact ID, corrupt manifest handling, and a restart-orphan reconciliation test.

---

*Report generated by static analysis of the working tree at commit `fca2d85`. No production code was modified.*
