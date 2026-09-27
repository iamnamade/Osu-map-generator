# Local Generator Workflow

## What This Adds

This workflow adds a local-only song upload and generation wizard at `generator.html`.

It keeps uploads, intermediate analysis, generated beatmaps, reports, exports, and logs inside repo-local workspace folders:

- `workspaces/<workspace-id>/source/`
- `workspaces/<workspace-id>/analysis/`
- `workspaces/<workspace-id>/maps/`
- `workspaces/<workspace-id>/reports/`
- `workspaces/<workspace-id>/exports/`
- `workspaces/<workspace-id>/logs/`

Nothing in this flow uses remote APIs or cloud services.

This remains Phase 8A.1 scope:

- circle-only output
- deterministic generation
- existing game and editor preview reuse
- no slider, spinner, or hold authoring yet

## Python Version

Use Python 3.10 or newer.

The repo launcher prefers `.venv` when it exists.

## Install Dependencies

PowerShell:

```powershell
python -m pip install --upgrade pip
python -m pip install -r tools/local_api/requirements.txt
```

That requirements file includes both the local API stack and the existing map-generator audio dependencies.

## Start The Full Local Wizard

PowerShell:

```powershell
npm.cmd run generator:dev
```

That starts:

- FastAPI on `http://127.0.0.1:8765`
- Vite on `http://127.0.0.1:5173`

Open:

```text
http://127.0.0.1:5173/generator.html
```

## Start The API Only

PowerShell:

```powershell
npm.cmd run api:dev
```

Useful endpoints:

- `GET /api/health`
- `POST /api/workspaces`
- `POST /api/workspaces/{workspaceId}/audio`
- `POST /api/workspaces/{workspaceId}/background`
- `PUT /api/workspaces/{workspaceId}/metadata`
- `POST /api/workspaces/{workspaceId}/generate`
- `GET /api/jobs/{jobId}`
- `POST /api/jobs/{jobId}/cancel`
- `GET /api/artifacts/{artifactId}/download`
- `DELETE /api/workspaces/{workspaceId}`

## Start The Frontend Only

PowerShell:

```powershell
npm.cmd run generator:frontend
```

Vite proxies `/api` requests to `http://127.0.0.1:8765`.

## Wizard Flow

1. Upload an audio file.
2. Optionally upload background art.
3. Confirm or edit song metadata.
4. Pick one or more difficulties and adjust advanced settings.
5. Start the background generation job.
6. Watch progress, logs, and cancellation state.
7. Download the generated `.osz` package or preview the result in the existing game/editor runtime.

## Runtime Preview

The results step reuses the existing runtime instead of copying generated maps into the static catalog.

Preview buttons open:

- the Phaser game with a runtime `mapUrl` selection
- the editor with the same runtime map selection

Artifact downloads continue to point at the local API workspace output.

## Cleanup

Delete one workspace:

```powershell
.\.venv\Scripts\python.exe -m tools.local_api.app cleanup --workspace-id <workspace-id>
```

Delete only failed or cancelled workspaces:

```powershell
.\.venv\Scripts\python.exe -m tools.local_api.app cleanup --failed-only
```

Delete workspaces older than a chosen age:

```powershell
.\.venv\Scripts\python.exe -m tools.local_api.app cleanup --older-than-hours 24
```

## Focused Verification

PowerShell:

```powershell
npm.cmd run typecheck
npm.cmd exec vitest run tests/generator
npm.cmd run generator:test
npm.cmd run build
```

`generator:test` runs the focused TypeScript generator suite and the focused Python local API suite.
