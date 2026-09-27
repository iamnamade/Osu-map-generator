# Map Editor

## Purpose

Phase 6 adds a browser-based map review and editing tool for the existing rhythm-game project. The editor is for human inspection and manual correction of project-format JSON beatmaps. It does not perform automatic section regeneration, hybrid assembly, machine learning, or `.osu` export.

## Opening the editor

- Game URL: `/index.html`
- Editor URL: `/editor.html`
- Launcher flow: use `Open Map Editor` from the existing start overlay
- Return path: use `Back to Game` in the editor toolbar

## Supported map sources

The editor reads the centralized catalog in `src/shared/mapCatalog.ts` and currently exposes:

- `Manual`: `/maps/test-map.json`
- `Generated`: `/maps/generated/test-song-easy.json`, `/maps/generated/test-song-normal.json`, `/maps/generated/test-song-hard.json`
- `Improved`: `/maps/improved/test-song-easy-improved.json`, `/maps/improved/test-song-normal-improved.json`, `/maps/improved/test-song-hard-improved.json`
- `Champions`: `/maps/champions/test-song-easy.json`, `/maps/champions/test-song-normal.json`, `/maps/champions/test-song-hard.json`

You can also import:

- A local project-format beatmap JSON file
- A previously exported editor project file

Browser imports stay local until you export downloads. The editor does not overwrite workspace files directly.

## Architecture

Key editor modules live under `src/editor/`:

- `EditorApp.ts`: page shell, toolbar, tabs, dialogs, layout wiring
- `EditorController.ts`: audio, map mutations, selection, history, autosave, export
- `EditorStore.ts` and `EditorState.ts`: local editor state container
- `EditorMapLoader.ts`: catalog loading, import validation, editor-project loading
- `EditorHistory.ts`: deterministic undo/redo serialization
- `EditorValidator.ts`: lightweight browser-side live checks
- `EditorAudioController.ts`: authoritative audio clock from `audio.currentTime * 1000`
- `playfield/EditorScene.ts`: Phaser editing scene for the 512 x 384 playfield
- `timeline/*`: canvas timeline rendering and interactions
- `panels/*`: map library, inspector, validation, history, export, settings

Vite is configured as a multi-page app through `vite.config.ts`, so both `index.html` and `editor.html` build into production output.

## Baseline and working copy

Each loaded session keeps:

- `baselineMap`: immutable reference map
- `workingMap`: editable copy

Comparison state tracks:

- unchanged
- moved
- retimed
- moved-and-retimed
- added
- removed

New circles receive stable temporary editor IDs during editing. Final gameplay export normalizes public object IDs sequentially from `1`.

## Playfield controls

The editor playfield uses a dedicated Phaser scene and shows:

- circles only
- object numbers
- selection and hover states
- approach preview for active notes
- optional baseline ghost overlays
- safe bounds and edge warning areas
- path lines between consecutive objects

Supported editing:

- click to select
- click empty space to clear selection
- drag to move the selected circle
- arrow keys for `1 px` nudges
- `Shift + Arrow` for `10 px` nudges
- `Add Circle` mode to insert a circle at the current playhead
- `Delete`, `Backspace`, toolbar delete, or inspector delete
- reset position, reset timing, reset object, or reset the full map

## Timeline controls

The timeline is a canvas renderer, not a large DOM list. It displays:

- waveform or decoded peaks when available
- RMS energy
- beat markers
- onset markers
- hit-object markers
- issue markers
- current playhead

Supported interactions:

- click to seek
- drag the playhead to scrub
- click object markers to select
- drag object markers to retime
- mouse wheel pan
- `Ctrl/Cmd + wheel` zoom
- toolbar `+`, `-`, and `Fit`

## Waveform and analysis

When `public/analysis/test-song-analysis.json` or another source analysis file is available, the editor uses:

- beat timestamps and strengths
- onset timestamps and strengths
- energy frames

The editor then tries to decode the audio for denser waveform peaks with Web Audio. If decoding fails, editing still works and the energy track remains available.

## Timing editing and snap modes

Timing can be changed by:

- dragging object markers in the timeline
- editing the inspector time field
- inserting a circle at the current playhead

Supported snap modes:

- `Off`
- `Beat`
- `Onset`
- `Strongest`

Default snap tolerance is `90 ms`. Snapping never silently moves unrelated objects, prevents duplicate timestamps, and keeps objects chronologically sorted.

## Inspector and metadata editing

The inspector exposes:

- object `ID`
- object `Type`
- `X`
- `Y`
- `Time`

Read-only context includes:

- baseline position and timing deltas
- previous and next gap
- previous and next distance
- cursor-speed estimates
- nearest beat and onset
- local energy
- current object issues

The settings panel supports editing:

- title
- artist
- audio path
- approach time
- circle radius
- playback rate
- snap tolerance
- baseline overlay toggle
- live validation toggle

Unknown JSON-safe metadata is preserved through import and export where possible.

## Undo, redo, history, and autosave

Undo/redo supports:

- move object
- retime object
- add object
- delete object
- reset object
- reset map
- batch metadata edit

Shortcuts:

- `Ctrl/Cmd + Z`
- `Ctrl/Cmd + Y`
- `Ctrl/Cmd + Shift + Z`

History is deterministic and sequence-based. Drag edits commit once at drag end.

Browser-local autosave stores:

- source identity
- baseline and working maps
- history
- selected object
- playhead
- timeline view
- active tool and settings

On load, the editor offers `Restore Session` or `Discard Session`.

## Live validation

The browser validator is a fast frontend subset. It checks:

- structural validity
- timing alignment and minimum gap
- movement speed, stacking, large jumps, edge proximity
- simple readability warnings

Severity levels:

- `info`
- `warning`
- `error`
- `critical`

Important: this is not the full Phase 3 scorer. The Python validator remains authoritative.

## Export formats

Browser export creates downloads with Blob URLs:

- edited gameplay map JSON
- edit log JSON
- editor project JSON

Gameplay export:

- sorts by time
- rounds coordinates and time
- renumbers public IDs sequentially
- strips editor-only fields
- keeps safe optional metadata

Exported maps are project-format JSON maps, not `.osu` files.

## Authoritative Python validation workflow

Recommended flow:

1. Export the edited map JSON.
2. Place it under a project map folder such as `public/maps/edited/`.
3. Run the Python validator.
4. Review the generated report.
5. Reopen the map in the editor if needed.

Windows PowerShell examples:

```powershell
python -m tools.map_generator.cli validate `
  --map public/maps/edited/test-song-normal-edited.json `
  --analysis public/analysis/test-song-analysis.json `
  --difficulty normal `
  --output public/reports/edited/test-song-normal-edited-report.json
```

```powershell
npm run validate:edited -- normal
```

```powershell
npm run validate:edited -- --map public/maps/edited/test-song-normal-edited.json --analysis public/analysis/test-song-analysis.json --difficulty normal --output public/reports/edited/test-song-normal-edited-report.json
```

## Keyboard shortcuts

- `Space`: play or pause
- `S`: select mode
- `A`: add circle mode
- `Delete` or `Backspace`: delete selected object
- `Ctrl/Cmd + Z`: undo
- `Ctrl/Cmd + Y`: redo
- `Ctrl/Cmd + Shift + Z`: redo
- `Arrow Keys`: move selection by `1 px`
- `Shift + Arrow Keys`: move selection by `10 px`
- `Home`: seek to song start
- `Escape`: clear selection or cancel tool
- `+`: zoom in
- `-`: zoom out
- `F`: fit timeline
- `B`: toggle baseline overlay

Shortcuts are ignored while typing in form fields.

## Known limitations

- Circles only. Sliders and spinners are not supported.
- No `.osu` export.
- No multiplayer, collaboration, accounts, backend, or cloud saving.
- Live validation is intentionally lighter than the Python validator.
- The browser cannot write directly back into project source files.
- Human review is still required after algorithmic generation and after manual edits.

## Why automatic regeneration is not included yet

Phase 6 is focused on visual inspection, synchronized editing, validation feedback, and export. Automatic section regeneration or hybrid map assembly would change scope substantially and belongs to a later phase.
