import type { EditorPlaybackRate, EditorSnapMode, EditorTimelineState } from "./models/EditorModels";

export const EDITOR_AUTOSAVE_KEY = "pulse-practice-editor-session-v1";
export const EDITOR_AUTOSAVE_SCHEMA_VERSION = 1;
export const DEFAULT_HISTORY_LIMIT = 200;
export const DEFAULT_SNAP_TOLERANCE_MS = 90;
export const DEFAULT_PLAYBACK_RATE: EditorPlaybackRate = 1;
export const DEFAULT_SNAP_MODE: EditorSnapMode = "beat";
export const DEFAULT_TIMELINE_STATE: EditorTimelineState = {
  visibleStartMs: 0,
  visibleDurationMs: 15000,
};
export const DEFAULT_VALIDATION_ENABLED = true;
export const DEFAULT_BASELINE_OVERLAY_ENABLED = true;
