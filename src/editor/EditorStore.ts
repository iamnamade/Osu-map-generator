import { createInitialCandidateBrowserState } from "./candidates/candidateModels";
import {
  DEFAULT_BASELINE_OVERLAY_ENABLED,
  DEFAULT_HISTORY_LIMIT,
  DEFAULT_PLAYBACK_RATE,
  DEFAULT_SNAP_MODE,
  DEFAULT_SNAP_TOLERANCE_MS,
  DEFAULT_TIMELINE_STATE,
  DEFAULT_VALIDATION_ENABLED,
} from "./EditorSettings";
import type { EditorRootState } from "./EditorState";
import type { EditorComparisonSummary, EditorStatusText } from "./models/EditorModels";
import type { EditorLiveValidation } from "./models/EditorValidationModels";

type EditorListener = (state: EditorRootState) => void;

const EMPTY_VALIDATION: EditorLiveValidation = {
  issues: [],
  issuesByObjectId: {},
  summary: {
    critical: 0,
    errors: 0,
    warnings: 0,
    info: 0,
    total: 0,
  },
  metricsByObjectId: {},
};

const EMPTY_COMPARISON: EditorComparisonSummary = {
  unchanged: 0,
  moved: 0,
  retimed: 0,
  movedAndRetimed: 0,
  added: 0,
  removed: 0,
};

export function createInitialEditorState(): EditorRootState {
  return {
    session: {
      loadStatus: "idle",
      liveValidation: EMPTY_VALIDATION,
      comparisonSummary: EMPTY_COMPARISON,
      comparisonByObjectId: {},
      playheadMs: 0,
      audioDurationMs: 0,
      isPlaying: false,
      unsavedChanges: false,
      changedRevision: 0,
      changedObjectCount: 0,
      autosaveStatus: "idle",
      lastAutosaveMessage: "Autosave idle",
      statusText: emptyStatusText(),
    },
    ui: {
      mode: "select",
      snapMode: DEFAULT_SNAP_MODE,
      snapToleranceMs: DEFAULT_SNAP_TOLERANCE_MS,
      validationEnabled: DEFAULT_VALIDATION_ENABLED,
      baselineOverlayEnabled: DEFAULT_BASELINE_OVERLAY_ENABLED,
      playbackRate: DEFAULT_PLAYBACK_RATE,
      timeline: { ...DEFAULT_TIMELINE_STATE },
      lockedSectionIds: [],
      activeRightTab: "inspector",
      shortcutHelpOpen: false,
      exportMenuOpen: false,
    },
    history: {
      entries: [],
      cursor: 0,
      nextSequence: 1,
      limit: DEFAULT_HISTORY_LIMIT,
    },
    candidates: createInitialCandidateBrowserState(),
  };
}

export class EditorStore {
  private readonly listeners = new Set<EditorListener>();

  constructor(private state: EditorRootState = createInitialEditorState()) {}

  subscribe(listener: EditorListener): () => void {
    this.listeners.add(listener);
    listener(this.state);

    return () => {
      this.listeners.delete(listener);
    };
  }

  getState(): EditorRootState {
    return this.state;
  }

  setState(nextState: EditorRootState): void {
    this.state = nextState;
    this.emit();
  }

  update(updater: (currentState: EditorRootState) => EditorRootState): void {
    this.state = updater(this.state);
    this.emit();
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}

function emptyStatusText(): EditorStatusText {
  return {
    mode: "select",
    selectedObjectLabel: "No selection",
    playheadLabel: "00:00.000",
    zoomLabel: "Fit",
    snapLabel: "Beat",
    unsavedLabel: "Saved",
    issueLabel: "0 issues",
    autosaveLabel: "Autosave idle",
    audioLabel: "Audio not loaded",
  };
}
