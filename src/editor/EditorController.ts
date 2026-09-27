import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  hasHitObjectPosition,
  type SliderPathType,
  type ValidationReport,
} from "../game/types";
import { parseBeatmapDocument } from "../shared/beatmapSchema";
import { isJsonObject } from "../shared/JsonTypes";
import type { ProjectMapCatalogEntry } from "../shared/mapCatalog";
import type { EvolutionReport } from "../shared/evolutionReport";
import { clamp, formatTimeMs } from "../shared/format";
import { convertProjectBeatmapToOsuText } from "../shared/osuInterop";
import { buildVisualDiff, buildSectionComparison } from "./candidates/candidateCompare";
import {
  loadCandidateDetails,
  loadCandidateMapDocument,
  toBrowserPath,
} from "./candidates/candidateData";
import {
  appendChampionHistory,
  buildCandidateWorkspaceKey,
  candidateNoteKey,
  createChampionHistoryEntry,
  loadCandidateWorkspace,
  parseChampionHistory,
  saveCandidateWorkspace,
  serializeChampionHistory,
} from "./candidates/championHistory";
import {
  buildCandidateBrowserEntries,
  createInitialCandidateBrowserState,
  findCandidateEntry,
  type CandidateBrowserEntry,
  type CandidateFilters,
  type CandidateSortKey,
} from "./candidates/candidateModels";
import {
  applyHistoryEntry,
  deserializeHistory,
  pushHistoryEntry,
  serializeHistory,
  undoHistoryEntry,
} from "./EditorHistory";
import {
  type EditorFileImportOptions,
  loadEditorBundleFromCatalog,
  loadEditorBundleFromFile,
  loadEditorBundleFromProject,
  serializeEditorMapDocumentForProject,
} from "./EditorMapLoader";
import {
  DEFAULT_PLAYBACK_RATE,
  DEFAULT_SNAP_TOLERANCE_MS,
  DEFAULT_TIMELINE_STATE,
  EDITOR_AUTOSAVE_KEY,
  EDITOR_AUTOSAVE_SCHEMA_VERSION,
} from "./EditorSettings";
import type { EditorRootState } from "./EditorState";
import { EditorStore, createInitialEditorState } from "./EditorStore";
import { EditorAudioController } from "./EditorAudioController";
import {
  downloadTextFile,
  exportEditedMap,
  exportEditLog,
  exportEditorProject,
  hasBlockingIssues,
  normalizeMapForExport,
  summarizeChanges,
} from "./EditorExporter";
import type { EditorHistoryEntry } from "./models/EditorActions";
import {
  compareObjectToBaseline,
  findSongSectionById,
  isEditorAutosavePayload,
  mapDurationMs,
  type ComparisonStatus,
  type EditorAutosavePayload,
  type EditorHitObject,
  type EditorMapBundle,
  type EditorMapDocument,
  type EditorPlaybackRate,
  type EditorProjectExport,
  type EditorSnapMode,
  type EditorSourceIdentity,
} from "./models/EditorModels";
import { type JsonObject } from "../shared/JsonTypes";
import { validateEditorMap } from "./EditorValidator";

interface DragSession {
  objectId: string;
  before: { x: number; y: number; time: number };
}

interface EndTimeDragSession {
  objectId: string;
  before: { time: number; endTime: number };
}

export class EditorController {
  private readonly audioController: EditorAudioController;
  private validationTimer: number | null = null;
  private autosaveTimer: number | null = null;
  private activeDrag?: DragSession;
  private activeEndTimeDrag?: EndTimeDragSession;
  private clipboard?: JsonObject;
  private loopRange?: { sectionId: number; startMs: number; endMs: number };
  private previewRange?: { sectionId: number; startMs: number; endMs: number };

  constructor(private readonly store: EditorStore) {
    this.audioController = new EditorAudioController({
      onTimeUpdate: (timeMs) => {
        if (
          this.loopRange &&
          this.audioController.isPlaying() &&
          timeMs >= this.loopRange.endMs
        ) {
          this.audioController.seek(this.loopRange.startMs);
          return;
        }

        if (this.previewRange && timeMs >= this.previewRange.endMs) {
          const previewEndMs = this.previewRange.endMs;
          this.previewRange = undefined;
          this.audioController.pause();
          this.audioController.seek(previewEndMs);
          this.store.update((state) =>
            this.withDerivedState({
              ...state,
              session: {
                ...state.session,
                isPlaying: false,
                playheadMs: previewEndMs,
              },
            }),
          );
          return;
        }

        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              playheadMs: timeMs,
            },
          }),
        );
      },
      onReady: (durationMs) => {
        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              audioDurationMs: durationMs,
              loadStatus: "ready",
              errorMessage: undefined,
            },
          }),
        );
      },
      onEnded: () => {
        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              isPlaying: false,
            },
          }),
        );
      },
      onError: (message) => {
        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              loadStatus: "error",
              errorMessage: message,
            },
          }),
        );
      },
    });
  }

  getState(): EditorRootState {
    return this.store.getState();
  }

  bootstrap(): void {
    this.store.setState(this.withDerivedState(createInitialEditorState()));
    const autosave = this.readAutosave();
    if (autosave) {
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          ui: {
            ...state.ui,
            modal: {
              kind: "restore-session",
              title: "Recovered unsaved editor session",
              message:
                "A browser-local editor session is available. Restore it or discard it before loading a different map.",
            },
          },
        }),
      );
    }
  }

  async loadCatalogMap(entry: ProjectMapCatalogEntry): Promise<void> {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          loadStatus: "loading-map",
          errorMessage: undefined,
        },
      }),
    );

    try {
      const bundle = await loadEditorBundleFromCatalog(entry);
      await this.applyLoadedBundle(bundle);
    } catch (error) {
      this.handleLoadFailure(error, "Could not load map");
    }
  }

  async openEvolutionCandidate(params: {
    path: string;
    label?: string;
    kind?: "champion" | "improved" | "generated";
    difficulty?: string;
    evolutionReportPath?: string;
  }): Promise<void> {
    const entry: ProjectMapCatalogEntry = {
      id: `evolution:${params.path}`,
      label: params.label ?? "Evolution Candidate",
      path: params.path,
      kind: params.kind ?? "champion",
      group: "Evolution",
      description:
        "Candidate promoted or reviewed through the deterministic evolution engine.",
      difficulty: toDifficultyName(params.difficulty),
      evolutionReportPath: params.evolutionReportPath,
    };
    await this.loadCatalogMap(entry);
  }

  selectCandidate(candidateIndex: number): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...state.candidates,
          selectedCandidateIndex: candidateIndex,
        },
      }),
    );
    void this.loadCandidateDetail(candidateIndex);
  }

  clearCandidateSelection(): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...state.candidates,
          selectedCandidateIndex: undefined,
        },
      }),
    );
  }

  async loadCandidateDetail(candidateIndex: number): Promise<void> {
    const state = this.store.getState();
    const entry = findCandidateEntry(state.candidates.entries, candidateIndex);
    if (!entry) {
      return;
    }

    const existing = state.candidates.details[candidateIndex];
    if (existing?.loading || existing?.loaded) {
      return;
    }

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          details: {
            ...currentState.candidates.details,
            [candidateIndex]: {
              loading: true,
              loaded: false,
              replay: null,
              rebalance: null,
            },
          },
        },
      }),
    );

    const details = await loadCandidateDetails(entry);
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          details: {
            ...currentState.candidates.details,
            [candidateIndex]: {
              loading: false,
              loaded: true,
              replay: details.replay,
              rebalance: details.rebalance,
            },
          },
        },
      }),
    );
  }

  setCandidateFilters(patch: Partial<CandidateFilters>): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...state.candidates,
          filters: {
            ...state.candidates.filters,
            ...patch,
          },
        },
      }),
    );
  }

  setCandidateSort(key: CandidateSortKey, direction: "asc" | "desc"): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...state.candidates,
          sort: {
            key,
            direction,
          },
        },
      }),
    );
  }

  openCandidateInEditor(candidateIndex: number): void {
    const state = this.store.getState();
    const entry = findCandidateEntry(state.candidates.entries, candidateIndex);
    if (!entry) {
      return;
    }

    const isChampion =
      entry.candidateIndex === state.candidates.championCandidateIndex;
    void this.openEvolutionCandidate({
      path: toBrowserPath(entry.mapPath),
      label: `Candidate ${String(entry.candidateIndex).padStart(3, "0")} (rank ${entry.rank})${isChampion ? " · Champion" : ""}`,
      kind: isChampion ? "champion" : "improved",
      difficulty: entry.difficulty,
      evolutionReportPath: state.session.source?.evolutionReportPath,
    });
  }

  async startComparison(candidateIndex: number): Promise<void> {
    const state = this.store.getState();
    const selected = state.candidates.selectedCandidateIndex;
    if (selected === undefined || selected === candidateIndex) {
      return;
    }

    const entryA = findCandidateEntry(state.candidates.entries, selected);
    const entryB = findCandidateEntry(state.candidates.entries, candidateIndex);
    if (!entryA || !entryB) {
      return;
    }

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          comparisonEnabled: true,
          compareCandidateIndex: candidateIndex,
          diffModeEnabled: true,
          comparison: {
            state: "loading",
          },
        },
      }),
    );

    const [mapA, mapB, detailA, detailB] = await Promise.all([
      loadCandidateMapDocument(entryA.mapPath),
      loadCandidateMapDocument(entryB.mapPath),
      loadCandidateDetails(entryA),
      loadCandidateDetails(entryB),
    ]);

    if (!mapA || !mapB) {
      this.store.update((currentState) =>
        this.withDerivedState({
          ...currentState,
          candidates: {
            ...currentState.candidates,
            comparison: {
              state: "error",
              error: "Could not load one of the candidate maps for comparison.",
            },
          },
        }),
      );
      return;
    }

    const currentState = this.store.getState();
    const sections = currentState.session.sectionAnalysis?.sections ?? [];
    const visualDiff = buildVisualDiff(mapA, mapB);
    const sectionComparison =
      sections.length > 0
        ? buildSectionComparison(mapA, mapB, sections, detailA, detailB)
        : undefined;

    this.store.update((s) =>
      this.withDerivedState({
        ...s,
        candidates: {
          ...s.candidates,
          compareCandidateIndex: candidateIndex,
          comparisonEnabled: true,
          diffModeEnabled: true,
          comparison: {
            state: "ready",
            candidateA: { index: selected, map: mapA },
            candidateB: { index: candidateIndex, map: mapB },
            visualDiff,
            sectionComparison,
          },
        },
      }),
    );
  }

  exitComparison(): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...state.candidates,
          comparisonEnabled: false,
          compareCandidateIndex: undefined,
          diffModeEnabled: false,
          comparison: {
            state: "idle",
          },
        },
      }),
    );
  }

  setDiffMode(enabled?: boolean): void {
    const state = this.store.getState();
    const nextEnabled =
      enabled ?? !state.candidates.diffModeEnabled;
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          diffModeEnabled: nextEnabled,
        },
      }),
    );
  }

  setCandidateNote(candidateIndex: number, note: string): void {
    const state = this.store.getState();
    if (state.candidates.entries.length === 0) {
      return;
    }

    const key = candidateNoteKey(
      state.candidates.workspaceKey,
      candidateIndex,
    );
    const notes = { ...state.candidates.notes };
    const trimmed = note.trim();
    if (trimmed.length > 0) {
      notes[key] = trimmed;
    } else {
      delete notes[key];
    }

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          notes,
        },
      }),
    );
    this.persistCandidateWorkspace();
  }

  async requestPromoteCandidate(candidateIndex: number): Promise<void> {
    const state = this.store.getState();
    const entry = findCandidateEntry(state.candidates.entries, candidateIndex);
    if (!entry) {
      return;
    }

    const check = await this.checkCandidatePromotable(entry);
    if (!check.ok) {
      this.showMessageModal(
        "Cannot promote candidate",
        `Promotion was blocked: ${check.reasons.join(" ")}`,
      );
      return;
    }

    const currentChampion =
      state.candidates.championCandidateIndex ?? -1;
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          pendingPromotionIndex: candidateIndex,
        },
        ui: {
          ...currentState.ui,
          modal: {
            kind: "confirm-promote",
            title: `Promote Candidate ${String(candidateIndex).padStart(3, "0")} to Champion?`,
            message:
              `Candidate ${String(candidateIndex).padStart(3, "0")} scores ${entry.finalScore.toFixed(1)} overall. ` +
              `The current champion (candidate ${currentChampion < 0 ? "none" : String(currentChampion).padStart(3, "0")}) is preserved in the champion history and can be restored at any time.`,
          },
        },
      }),
    );
  }

  async confirmPromoteCandidate(): Promise<void> {
    const state = this.store.getState();
    const candidateIndex = state.candidates.pendingPromotionIndex;
    const entry = findCandidateEntry(state.candidates.entries, candidateIndex);

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        ui: {
          ...currentState.ui,
          modal: undefined,
        },
        candidates: {
          ...currentState.candidates,
          pendingPromotionIndex: undefined,
        },
      }),
    );

    if (!entry) {
      return;
    }

    const check = await this.checkCandidatePromotable(entry);
    if (!check.ok) {
      this.showMessageModal(
        "Cannot promote candidate",
        `Promotion was blocked: ${check.reasons.join(" ")}`,
      );
      return;
    }

    await this.promoteCandidate(
      entry,
      "Manual promotion from the Candidate Browser.",
      true,
    );
    this.showMessageModal(
      "Champion promoted",
      `Candidate ${String(entry.candidateIndex).padStart(3, "0")} is now the Champion. The previous champion is preserved in the Champion History and can be restored at any time.`,
    );
  }

  async restorePreviousChampion(): Promise<void> {
    const state = this.store.getState();
    const last =
      state.candidates.championHistory[
        state.candidates.championHistory.length - 1
      ];
    if (!last || last.previousChampionIndex === null) {
      return;
    }

    const entry = findCandidateEntry(
      state.candidates.entries,
      last.previousChampionIndex,
    );
    if (!entry) {
      return;
    }

    await this.promoteCandidate(
      entry,
      "Manual revert to the previous champion from the Champion History.",
      true,
    );
    this.showMessageModal(
      "Previous champion restored",
      `Candidate ${String(entry.candidateIndex).padStart(3, "0")} is Champion again. The promotion was recorded in the Champion History.`,
    );
  }

  async importFile(
    file: File,
    options: EditorFileImportOptions = {},
  ): Promise<void> {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          loadStatus: "loading-map",
          errorMessage: undefined,
        },
      }),
    );

    try {
      const bundle = await loadEditorBundleFromFile(file, options);
      await this.applyLoadedBundle(bundle);
      if (bundle.restoredProject) {
        this.applyRestoredProjectState(bundle.restoredProject);
      }

      if (
        options.kind === "osu" &&
        bundle.source.description?.includes("unsupported object")
      ) {
        this.showMessageModal("Imported circles only", bundle.source.description);
      }
    } catch (error) {
      this.handleLoadFailure(error, "Could not import map");
    }
  }

  async importProjectJsonFile(file: File): Promise<void> {
    await this.importFile(file, { kind: "project-json" });
  }

  async importEditorProjectFile(file: File): Promise<void> {
    await this.importFile(file, { kind: "editor-project" });
  }

  async importOsuFile(
    file: File,
    unsupportedMode: EditorFileImportOptions["unsupportedMode"] = "reject",
  ): Promise<void> {
    await this.importFile(file, {
      kind: "osu",
      unsupportedMode,
    });
  }

  async restoreAutosaveIfAvailable(): Promise<void> {
    const autosave = this.readAutosave();
    if (!autosave) {
      return;
    }

    await this.restoreProject(autosave);
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          modal: undefined,
        },
        session: {
          ...state.session,
          autosaveStatus: "restored",
          lastAutosaveMessage: "Recovered unsaved editor session",
        },
      }),
    );
  }

  discardAutosave(): void {
    localStorage.removeItem(EDITOR_AUTOSAVE_KEY);
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          modal: undefined,
        },
      }),
    );
  }

  async restoreProject(project: EditorProjectExport): Promise<void> {
    const bundle = await loadEditorBundleFromProject(
      project,
      `${project.editorProject.source.label}.editor.json`,
    );
    await this.applyLoadedBundle(bundle);
    this.applyRestoredProjectState(bundle.restoredProject ?? project);
  }

  togglePlayPause(): void {
    if (this.audioController.isPlaying()) {
      this.audioController.pause();
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          session: {
            ...state.session,
            isPlaying: false,
          },
        }),
      );
      return;
    }

    void this.audioController.play().then(() => {
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          session: {
            ...state.session,
            isPlaying: true,
          },
        }),
      );
    });
  }

  stopPlayback(): void {
    this.previewRange = undefined;
    this.audioController.stop();
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          isPlaying: false,
        },
      }),
    );
  }

  restartPlayback(): void {
    this.previewRange = undefined;
    this.audioController.restart();
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          playheadMs: 0,
        },
      }),
    );
  }

  seek(timeMs: number): void {
    this.audioController.seek(timeMs);
  }

  seekToStart(): void {
    this.seek(0);
  }

  playFromSelectedObject(offsetMs = 0): void {
    const selected = this.store.getState().session.selectedObject;
    if (!selected) {
      return;
    }

    this.seek(Math.max(0, selected.time - offsetMs));
    void this.audioController.play().then(() => {
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          session: {
            ...state.session,
            isPlaying: true,
          },
        }),
      );
    });
  }

  setPlaybackRate(rate: EditorPlaybackRate): void {
    this.audioController.setPlaybackRate(rate);
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          playbackRate: rate,
        },
      }),
    );
    this.scheduleAutosave();
  }

  setMode(mode: "select" | "add-circle"): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          mode,
        },
      }),
    );
  }

  cancelActiveTool(): void {
    this.clearSelection();
    this.setMode("select");
  }

  setSnapMode(mode: EditorSnapMode): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          snapMode: mode,
        },
      }),
    );
    this.scheduleAutosave();
  }

  setSnapToleranceMs(value: number): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          snapToleranceMs: Math.max(0, Math.round(value)),
        },
      }),
    );
    this.scheduleAutosave();
  }

  toggleBaselineOverlay(): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          baselineOverlayEnabled: !state.ui.baselineOverlayEnabled,
        },
      }),
    );
    this.scheduleAutosave();
  }

  toggleValidation(): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          validationEnabled: !state.ui.validationEnabled,
        },
      }),
    );
    this.scheduleValidation();
    this.scheduleAutosave();
  }

  setActiveRightTab(tab: EditorRootState["ui"]["activeRightTab"]): void {
    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        activeRightTab: tab,
      },
    }));
  }

  toggleShortcutHelp(open?: boolean): void {
    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        shortcutHelpOpen: open ?? !state.ui.shortcutHelpOpen,
      },
    }));
  }

  toggleExportMenu(open?: boolean): void {
    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        exportMenuOpen: open ?? !state.ui.exportMenuOpen,
      },
    }));
  }

  setTimelineWindow(startMs: number, durationMs: number): void {
    const boundedDuration = clamp(durationMs, 1200, Math.max(1200, this.totalDurationMs()));
    const boundedStart = clamp(
      startMs,
      0,
      Math.max(0, this.totalDurationMs() - boundedDuration),
    );
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          timeline: {
            visibleStartMs: Math.round(boundedStart),
            visibleDurationMs: Math.round(boundedDuration),
          },
        },
      }),
    );
    this.scheduleAutosave();
  }

  panTimeline(deltaMs: number): void {
    const state = this.store.getState();
    this.setTimelineWindow(
      state.ui.timeline.visibleStartMs + deltaMs,
      state.ui.timeline.visibleDurationMs,
    );
  }

  zoomTimeline(multiplier: number): void {
    const state = this.store.getState();
    const current = state.ui.timeline;
    const centerMs = current.visibleStartMs + current.visibleDurationMs / 2;
    const nextDuration = current.visibleDurationMs * multiplier;
    this.setTimelineWindow(centerMs - nextDuration / 2, nextDuration);
  }

  fitTimeline(): void {
    const durationMs = this.totalDurationMs();
    this.setTimelineWindow(0, durationMs > 0 ? durationMs : DEFAULT_TIMELINE_STATE.visibleDurationMs);
  }

  selectSection(
    sectionId?: number,
    options: {
      seek?: boolean;
      openHybridTab?: boolean;
    } = {},
  ): void {
    const section = findSongSectionById(
      this.store.getState().session.sectionAnalysis,
      sectionId,
    );
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          selectedSectionId: section?.id,
          activeRightTab: options.openHybridTab ? "hybrid" : state.ui.activeRightTab,
        },
      }),
    );
    if (section && options.seek !== false) {
      this.seek(section.startMs);
    }
    this.scheduleAutosave();
  }

  seekToSectionStart(sectionId?: number): void {
    const section = findSongSectionById(
      this.store.getState().session.sectionAnalysis,
      sectionId ?? this.store.getState().ui.selectedSectionId,
    );
    if (!section) {
      return;
    }

    this.seek(section.startMs);
  }

  playSection(sectionId?: number): void {
    const section = findSongSectionById(
      this.store.getState().session.sectionAnalysis,
      sectionId ?? this.store.getState().ui.selectedSectionId,
    );
    if (!section) {
      return;
    }

    this.previewRange = {
      sectionId: section.id,
      startMs: section.startMs,
      endMs: section.endMs,
    };
    this.seek(section.startMs);
    void this.audioController.play().then(() => {
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          session: {
            ...state.session,
            isPlaying: true,
          },
        }),
      );
    });
  }

  toggleSectionLoop(sectionId?: number): void {
    const section = findSongSectionById(
      this.store.getState().session.sectionAnalysis,
      sectionId ?? this.store.getState().ui.selectedSectionId,
    );
    if (!section) {
      return;
    }

    const currentLoopSectionId = this.store.getState().ui.loopSectionId;
    const nextLoopSectionId =
      currentLoopSectionId === section.id ? undefined : section.id;
    this.loopRange =
      nextLoopSectionId === undefined
        ? undefined
        : {
            sectionId: section.id,
            startMs: section.startMs,
            endMs: section.endMs,
          };
    this.previewRange = undefined;
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          selectedSectionId: section.id,
          loopSectionId: nextLoopSectionId,
        },
      }),
    );
    this.scheduleAutosave();
  }

  zoomToSection(sectionId?: number): void {
    const section = findSongSectionById(
      this.store.getState().session.sectionAnalysis,
      sectionId ?? this.store.getState().ui.selectedSectionId,
    );
    if (!section) {
      return;
    }

    const paddingMs = Math.min(1800, Math.round(section.durationMs * 0.24));
    this.setTimelineWindow(
      Math.max(0, section.startMs - paddingMs),
      section.durationMs + paddingMs * 2,
    );
  }

  toggleSectionLock(sectionId?: number): void {
    const resolvedSectionId = sectionId ?? this.store.getState().ui.selectedSectionId;
    if (typeof resolvedSectionId !== "number") {
      return;
    }

    this.store.update((state) => {
      const currentlyLocked = state.ui.lockedSectionIds.includes(resolvedSectionId);
      return this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          lockedSectionIds: currentlyLocked
            ? state.ui.lockedSectionIds.filter((item) => item !== resolvedSectionId)
            : [...state.ui.lockedSectionIds, resolvedSectionId].sort((left, right) => left - right),
        },
      });
    });
    this.scheduleAutosave();
  }

  selectObject(editorId?: string): void {
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        ui: {
          ...state.ui,
          selectedObjectId: editorId,
        },
      }),
    );
    this.scheduleAutosave();
  }

  clearSelection(): void {
    this.selectObject(undefined);
  }

  beginObjectDrag(objectId: string): void {
    if (this.isComparisonActive()) {
      return;
    }

    const object = this.findWorkingObject(objectId);
    if (!object || !hasHitObjectPosition(object)) {
      return;
    }

    this.activeDrag = {
      objectId,
      before: {
        x: object.x,
        y: object.y,
        time: object.time,
      },
    };
  }

  updateDraggedObjectPosition(objectId: string, x: number, y: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const nextMap = replaceWorkingObject(workingMap, objectId, {
      x: clampCoordinate(x, workingMap.circleRadius, PLAYFIELD_WIDTH),
      y: clampCoordinate(y, workingMap.circleRadius, PLAYFIELD_HEIGHT),
    });
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.scheduleValidation();
  }

  commitDraggedObject(): void {
    if (!this.activeDrag) {
      return;
    }

    const object = this.findWorkingObject(this.activeDrag.objectId);
    if (!object || !hasHitObjectPosition(object)) {
      this.activeDrag = undefined;
      return;
    }

    if (
      object.x !== this.activeDrag.before.x ||
      object.y !== this.activeDrag.before.y
    ) {
      this.commitHistoryEntry({
        action:
          object.time !== this.activeDrag.before.time
            ? "move_and_retime_object"
            : "move_object",
        objectId: object.editorId,
        before: {
          x: this.activeDrag.before.x,
          y: this.activeDrag.before.y,
          time: this.activeDrag.before.time,
        },
        after: {
          x: object.x,
          y: object.y,
          time: object.time,
        },
        sequence: this.store.getState().history.nextSequence,
        timeMs: object.time,
        summary: `Moved object ${object.id}`,
      });
    }

    this.activeDrag = undefined;
  }

  retimeObject(objectId: string, targetTimeMs: number, commit = true): void {
    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const existing = this.findWorkingObject(objectId);
    if (!existing) {
      return;
    }

    const snappedTime = this.snapTime(Math.round(targetTimeMs), objectId);
    const clampedTime = clamp(snappedTime, 0, Math.max(0, this.totalDurationMs()));
    if (
      workingMap.objects.some(
        (object) => object.editorId !== objectId && object.time === clampedTime,
      )
    ) {
      return;
    }

    const nextMap = replaceWorkingObject(workingMap, objectId, { time: clampedTime });
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.scheduleValidation();

    if (commit && existing.time !== clampedTime) {
      const snapshot = snapshotObject(existing);
      this.commitHistoryEntry({
        action: "retime_object",
        objectId,
        before: snapshot,
        after: { ...snapshot, time: clampedTime },
        sequence: state.history.nextSequence,
        timeMs: clampedTime,
        summary: `Retimed object ${existing.id}`,
      });
    }
  }

  nudgeSelection(deltaX: number, deltaY: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const selected = this.store.getState().session.selectedObject;
    if (!selected || !hasHitObjectPosition(selected)) {
      return;
    }

    this.beginObjectDrag(selected.editorId);
    this.updateDraggedObjectPosition(
      selected.editorId,
      selected.x + deltaX,
      selected.y + deltaY,
    );
    this.commitDraggedObject();
  }

  updateSelectedPositionFromInspector(x: number, y: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const selected = this.store.getState().session.selectedObject;
    if (!selected || !hasHitObjectPosition(selected)) {
      return;
    }

    this.beginObjectDrag(selected.editorId);
    this.updateDraggedObjectPosition(selected.editorId, x, y);
    this.commitDraggedObject();
  }

  updateSelectedTimeFromInspector(timeMs: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const selected = this.store.getState().session.selectedObject;
    if (!selected) {
      return;
    }

    this.retimeObject(selected.editorId, timeMs, true);
  }

  updateSelectedEndTimeFromInspector(endTimeMs: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const selected = this.store.getState().session.selectedObject;
    if (!selected || selected.type !== "spinner") {
      return;
    }

    const snappedEndTime = this.snapTime(Math.round(endTimeMs), selected.editorId);
    const clampedEndTime = Math.max(
      selected.time + 1,
      clamp(snappedEndTime, 0, Math.max(0, this.totalDurationMs())),
    );
    if (clampedEndTime === selected.endTime) {
      return;
    }

    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const nextMap = replaceWorkingObject(workingMap, selected.editorId, {
      endTime: clampedEndTime,
    });
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.scheduleValidation();

    const snapshot = snapshotObject(selected);
    this.commitHistoryEntry({
      action: "retime_object",
      objectId: selected.editorId,
      before: snapshot,
      after: { ...snapshot, endTime: clampedEndTime },
      sequence: state.history.nextSequence,
      timeMs: clampedEndTime,
      summary: `Resized spinner ${selected.id} end time`,
    });
  }

  beginEndTimeDrag(objectId: string): void {
    if (this.isComparisonActive()) {
      return;
    }

    const object = this.findWorkingObject(objectId);
    if (!object || object.type !== "spinner") {
      return;
    }

    this.activeEndTimeDrag = {
      objectId,
      before: { time: object.time, endTime: object.endTime },
    };
  }

  updateEndTimeDrag(targetTimeMs: number): void {
    if (!this.activeEndTimeDrag) {
      return;
    }

    const object = this.findWorkingObject(this.activeEndTimeDrag.objectId);
    if (!object || object.type !== "spinner") {
      return;
    }

    const nextEndTime = Math.max(
      object.time + 1,
      Math.round(targetTimeMs),
    );
    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const nextMap = replaceWorkingObject(workingMap, object.editorId, {
      endTime: nextEndTime,
    });
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.scheduleValidation();
  }

  commitEndTimeDrag(): void {
    if (!this.activeEndTimeDrag) {
      return;
    }

    const object = this.findWorkingObject(this.activeEndTimeDrag.objectId);
    if (!object || object.type !== "spinner") {
      this.activeEndTimeDrag = undefined;
      return;
    }

    if (object.endTime !== this.activeEndTimeDrag.before.endTime) {
      const snapshot = snapshotObject(object);
      this.commitHistoryEntry({
        action: "retime_object",
        objectId: object.editorId,
        before: { ...snapshot, endTime: this.activeEndTimeDrag.before.endTime },
        after: snapshot,
        sequence: this.store.getState().history.nextSequence,
        timeMs: object.endTime,
        summary: `Resized spinner ${object.id} end time`,
      });
    }

    this.activeEndTimeDrag = undefined;
  }

  cancelEndTimeDrag(): void {
    this.activeEndTimeDrag = undefined;
  }

  copySelectedObject(): void {
    const selected = this.store.getState().session.selectedObject;
    if (!selected) {
      return;
    }

    this.clipboard = snapshotObject(selected);
  }

  pasteObject(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap || !this.clipboard) {
      return;
    }

    const snappedTime = this.snapTime(state.session.playheadMs);
    if (workingMap.objects.some((object) => object.time === snappedTime)) {
      return;
    }

    const pasted = snapshotToPastedObject(
      this.clipboard,
      `add-${String(state.history.nextSequence).padStart(6, "0")}`,
      workingMap.objects.length + 1,
      snappedTime,
    );
    const insertIndex = workingMap.objects.findIndex(
      (object) => object.time > snappedTime,
    );
    const safeIndex = insertIndex === -1 ? workingMap.objects.length : insertIndex;
    const nextMap = {
      ...workingMap,
      objects: [
        ...workingMap.objects.slice(0, safeIndex),
        pasted,
        ...workingMap.objects.slice(safeIndex),
      ],
    };

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
        ui: {
          ...currentState.ui,
          selectedObjectId: pasted.editorId,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "add_object",
      objectId: pasted.editorId,
      objectSnapshot: snapshotObject(pasted),
      objectIndex: safeIndex,
      sequence: state.history.nextSequence,
      timeMs: snappedTime,
      summary: `Pasted ${pasted.type} at ${formatTimeMs(snappedTime)}`,
    });
  }

  updateMetadata(patch: Partial<Pick<EditorMapDocument, "title" | "artist" | "audio" | "approachTime" | "circleRadius">>): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const before = {
      title: workingMap.title,
      artist: workingMap.artist,
      audio: workingMap.audio,
      approachTime: workingMap.approachTime,
      circleRadius: workingMap.circleRadius,
    };
    const nextMap: EditorMapDocument = {
      ...workingMap,
      title: patch.title ?? workingMap.title,
      artist: patch.artist ?? workingMap.artist,
      audio: patch.audio ?? workingMap.audio,
      approachTime: patch.approachTime ?? workingMap.approachTime,
      circleRadius: patch.circleRadius ?? workingMap.circleRadius,
    };

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "batch_metadata_edit",
      before,
      after: {
        title: nextMap.title,
        artist: nextMap.artist,
        audio: nextMap.audio,
        approachTime: nextMap.approachTime,
        circleRadius: nextMap.circleRadius,
      },
      sequence: state.history.nextSequence,
      summary: "Updated map metadata",
    });
  }

  addCircleAtPlayhead(x: number, y: number): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const snappedTime = this.snapTime(state.session.playheadMs);
    if (workingMap.objects.some((object) => object.time === snappedTime)) {
      return;
    }

    const nextObject = {
      editorId: `add-${String(state.history.nextSequence).padStart(6, "0")}`,
      id: workingMap.objects.length + 1,
      type: "circle" as const,
      x: clampCoordinate(x, workingMap.circleRadius, PLAYFIELD_WIDTH),
      y: clampCoordinate(y, workingMap.circleRadius, PLAYFIELD_HEIGHT),
      time: snappedTime,
      extraFields: {},
    };
    const insertIndex = workingMap.objects.findIndex((object) => object.time > snappedTime);
    const safeIndex = insertIndex === -1 ? workingMap.objects.length : insertIndex;
    const nextMap = {
      ...workingMap,
      objects: [
        ...workingMap.objects.slice(0, safeIndex),
        nextObject,
        ...workingMap.objects.slice(safeIndex),
      ],
    };

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
        ui: {
          ...currentState.ui,
          selectedObjectId: nextObject.editorId,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "add_object",
      objectId: nextObject.editorId,
      objectSnapshot: snapshotObject(nextObject),
      objectIndex: safeIndex,
      sequence: state.history.nextSequence,
      timeMs: snappedTime,
      summary: `Added object at ${formatTimeMs(snappedTime)}`,
    });
  }

  deleteSelectedObject(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const selected = state.session.selectedObject;
    const workingMap = state.session.workingMap;
    if (!selected || !workingMap) {
      return;
    }

    const objectIndex = workingMap.objects.findIndex(
      (object) => object.editorId === selected.editorId,
    );
    const nextMap = {
      ...workingMap,
      objects: workingMap.objects.filter(
        (object) => object.editorId !== selected.editorId,
      ),
    };

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
        ui: {
          ...currentState.ui,
          selectedObjectId: undefined,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "delete_object",
      objectId: selected.editorId,
      objectSnapshot: snapshotObject(selected),
      objectIndex,
      sequence: state.history.nextSequence,
      timeMs: selected.time,
      summary: `Deleted object ${selected.id}`,
    });
  }

  resetSelectedPosition(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const selected = state.session.selectedObject;
    const baseline = this.findBaselineObject(selected?.editorId);
    if (!selected || !baseline || !hasHitObjectPosition(selected) || !hasHitObjectPosition(baseline)) {
      return;
    }

    this.beginObjectDrag(selected.editorId);
    this.updateDraggedObjectPosition(selected.editorId, baseline.x, baseline.y);
    this.commitDraggedObject();
  }

  resetSelectedTiming(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const selected = this.store.getState().session.selectedObject;
    const baseline = this.findBaselineObject(selected?.editorId);
    if (!selected || !baseline) {
      return;
    }

    this.retimeObject(selected.editorId, baseline.time, true);
  }

  resetSelectedObject(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const selected = state.session.selectedObject;
    const baseline = this.findBaselineObject(selected?.editorId);
    if (!selected) {
      return;
    }

    if (!baseline) {
      this.deleteSelectedObject();
      return;
    }

    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const objectIndex = workingMap.objects.findIndex(
      (object) => object.editorId === selected.editorId,
    );
    const nextMap = replaceWorkingObject(workingMap, selected.editorId, baseline);
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "reset_object",
      objectId: selected.editorId,
      before: snapshotObject(selected),
      after: snapshotObject(baseline),
      objectIndex,
      sequence: state.history.nextSequence,
      timeMs: baseline.time,
      summary: `Reset object ${selected.id} to baseline`,
    });
  }

  confirmResetMap(): void {
    if (this.isComparisonActive()) {
      return;
    }

    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        modal: {
          kind: "confirm-reset-map",
          title: "Reset current map to baseline",
          message:
            "This will discard all current edits in the working copy. You can still undo the reset afterward.",
        },
      },
    }));
  }

  resetMapToBaseline(): void {
    if (this.isComparisonActive()) {
      return;
    }

    const state = this.store.getState();
    const baselineMap = state.session.baselineMap;
    const workingMap = state.session.workingMap;
    if (!baselineMap || !workingMap) {
      return;
    }

    const nextMap = {
      ...baselineMap,
      objects: baselineMap.objects.map((object) => ({ ...object })),
      extraFields: { ...baselineMap.extraFields },
    };
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          workingMap: nextMap,
        },
        ui: {
          ...currentState.ui,
          modal: undefined,
          selectedObjectId: undefined,
        },
      }),
    );
    this.commitHistoryEntry({
      action: "reset_map",
      beforeMap: workingMap,
      afterMap: nextMap,
      sequence: state.history.nextSequence,
      summary: "Reset map to baseline",
    });
  }

  closeModal(): void {
    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        modal: undefined,
      },
    }));
  }

  showMessageModal(title: string, message: string): void {
    this.store.update((state) => ({
      ...state,
      ui: {
        ...state.ui,
        modal: {
          kind: "message",
          title,
          message,
        },
      },
    }));
  }

  jumpToIssue(issueId: string): void {
    const issue = this.store.getState().session.liveValidation.issues.find(
      (item) => item.id === issueId,
    );
    if (!issue) {
      return;
    }

    if (issue.objectId) {
      this.selectObject(issue.objectId);
    }

    if (typeof issue.timeMs === "number") {
      this.seek(Math.max(0, issue.timeMs - 600));
      const timeline = this.store.getState().ui.timeline;
      const nextStart = issue.timeMs - timeline.visibleDurationMs * 0.3;
      this.setTimelineWindow(nextStart, timeline.visibleDurationMs);
    }
  }

  undo(): void {
    const state = this.store.getState();
    if (state.history.cursor === 0 || !state.session.workingMap) {
      return;
    }

    const entry = state.history.entries[state.history.cursor - 1];
    const nextMap = undoHistoryEntry(state.session.workingMap, entry);
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        history: {
          ...currentState.history,
          cursor: currentState.history.cursor - 1,
        },
        session: {
          ...currentState.session,
          workingMap: nextMap,
          unsavedChanges: true,
          changedRevision: currentState.session.changedRevision + 1,
        },
      }),
    );
    this.scheduleValidation();
    this.scheduleAutosave();
  }

  redo(): void {
    const state = this.store.getState();
    if (
      state.history.cursor >= state.history.entries.length ||
      !state.session.workingMap
    ) {
      return;
    }

    const entry = state.history.entries[state.history.cursor];
    const nextMap = applyHistoryEntry(state.session.workingMap, entry);
    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        history: {
          ...currentState.history,
          cursor: currentState.history.cursor + 1,
        },
        session: {
          ...currentState.session,
          workingMap: nextMap,
          unsavedChanges: true,
          changedRevision: currentState.session.changedRevision + 1,
        },
      }),
    );
    this.scheduleValidation();
    this.scheduleAutosave();
  }

  exportCurrentMap(): void {
    const state = this.store.getState();
    if (!state.session.workingMap || !state.session.source) {
      return;
    }

    if (hasBlockingIssues(state.session.liveValidation)) {
      this.store.update((currentState) =>
        this.withDerivedState({
          ...currentState,
          session: {
            ...currentState.session,
            errorMessage:
              "Export is blocked by critical structural live-validation issues.",
          },
        }),
      );
      return;
    }

    const result = exportEditedMap(
      state.session.workingMap,
      state.session.source,
      state.history.cursor,
    );
    downloadTextFile(result.filename, result.json);
  }

  exportCurrentOsuMap(): void {
    const state = this.store.getState();
    if (!state.session.workingMap || !state.session.source) {
      return;
    }

    if (hasBlockingIssues(state.session.liveValidation)) {
      this.showMessageModal(
        "Export blocked",
        "The current map has critical structural live-validation issues. Fix them before exporting a circle-only .osu file.",
      );
      return;
    }

    try {
      const normalized = parseBeatmapDocument(
        normalizeMapForExport(
          state.session.workingMap,
          state.session.source,
          state.history.cursor,
        ),
      );
      const result = convertProjectBeatmapToOsuText(
        normalized,
        {
          bpm: state.session.analysis?.bpm,
          offsetMs: state.session.analysis?.offsetMs,
        },
        {
          sourcePath: state.session.source.path,
        },
      );
      downloadTextFile(result.filename, result.text, "text/plain;charset=utf-8");

      if (result.report.warnings.length > 0) {
        this.showMessageModal(
          "Exported with warnings",
          result.report.warnings.join(" "),
        );
      }
    } catch (error) {
      this.showMessageModal(
        "Could not export .osu",
        error instanceof Error ? error.message : "Unknown export failure.",
      );
    }
  }

  exportCurrentEditLog(): void {
    const state = this.store.getState();
    if (
      !state.session.baselineMap ||
      !state.session.workingMap ||
      !state.session.source
    ) {
      return;
    }

    const result = exportEditLog(
      state.session.baselineMap,
      state.session.workingMap,
      state.session.source,
      serializeHistory(
        state.history.entries,
        state.history.cursor,
        state.history.nextSequence,
      ),
      state.session.liveValidation,
    );
    downloadTextFile(result.filename, result.json);
  }

  exportCurrentProject(): void {
    const state = this.store.getState();
    if (
      !state.session.baselineMap ||
      !state.session.workingMap ||
      !state.session.source
    ) {
      return;
    }

    const project = this.createProjectExport(
      state.session.source,
      state.session.baselineMap,
      state.session.workingMap,
    );
    const result = exportEditorProject(project);
    downloadTextFile(result.filename, result.json);
  }

  dispose(): void {
    this.audioController.dispose();

    if (this.validationTimer !== null) {
      window.clearTimeout(this.validationTimer);
      this.validationTimer = null;
    }

    if (this.autosaveTimer !== null) {
      window.clearTimeout(this.autosaveTimer);
      this.autosaveTimer = null;
    }
  }

  private async applyLoadedBundle(bundle: EditorMapBundle): Promise<void> {
    this.store.setState(
      this.withDerivedState({
        ...createInitialEditorState(),
        session: {
          ...createInitialEditorState().session,
          loadStatus: bundle.analysis ? "loading-audio" : "loading-audio",
          baselineMap: bundle.baselineMap,
          workingMap: bundle.workingMap,
          source: bundle.source,
          analysis: bundle.analysis,
          sectionAnalysis: bundle.sectionAnalysis,
          phraseAnalysis: bundle.phraseAnalysis,
          recoveryAnalysis: bundle.recoveryAnalysis,
          hybridAssembly: bundle.hybridAssembly,
          difficultyReport: bundle.difficultyReport,
          evolutionReport: bundle.evolutionReport,
          pythonReport: bundle.pythonReport as ValidationReport | undefined,
          audioDurationMs:
            bundle.analysis?.audioDurationMs ??
            bundle.sectionAnalysis?.audio.durationMs ??
            mapDurationMs(bundle.workingMap),
          playheadMs: 0,
        },
        ui: {
          ...createInitialEditorState().ui,
          selectedSectionId: bundle.sectionAnalysis?.sections[0]?.id,
        },
      }),
    );

    if (bundle.evolutionReport) {
      this.loadCandidateBrowser(bundle.evolutionReport);
    }

    this.loopRange = undefined;
    this.previewRange = undefined;
    await this.audioController.load(bundle.workingMap.audio);
    this.audioController.setPlaybackRate(DEFAULT_PLAYBACK_RATE);

    if (bundle.analysis) {
      this.store.update((state) =>
        this.withDerivedState({
          ...state,
          session: {
            ...state.session,
            loadStatus: "decoding-waveform",
          },
        }),
      );

      try {
        const waveform = await this.audioController.decodeWaveformPeaks();
        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              waveform,
              loadStatus: "ready",
            },
          }),
        );
      } catch {
        this.store.update((state) =>
          this.withDerivedState({
            ...state,
            session: {
              ...state.session,
              loadStatus: "ready",
            },
          }),
        );
      }
    }

    this.revalidateNow();
  }

  private createProjectExport(
    source: EditorSourceIdentity,
    baselineMap: EditorMapDocument,
    workingMap: EditorMapDocument,
  ): EditorProjectExport {
    const state = this.store.getState();
    const candidates = state.candidates;
    return {
      editorProject: {
        name: "pulse-practice-editor",
        version: 1,
        source,
      },
      baselineMap: serializeEditorMapDocumentForProject(baselineMap),
      workingMap: serializeEditorMapDocumentForProject(workingMap),
      history: serializeHistory(
        state.history.entries,
        state.history.cursor,
        state.history.nextSequence,
      ),
      timeline: state.ui.timeline,
      selectedObjectId: state.ui.selectedObjectId,
      selectedSectionId: state.ui.selectedSectionId,
      playheadMs: state.session.playheadMs,
      mode: state.ui.mode,
      snapMode: state.ui.snapMode,
      snapToleranceMs: state.ui.snapToleranceMs,
      baselineOverlayEnabled: state.ui.baselineOverlayEnabled,
      validationEnabled: state.ui.validationEnabled,
      playbackRate: state.ui.playbackRate,
      loopSectionId: state.ui.loopSectionId,
      lockedSectionIds: state.ui.lockedSectionIds,
      championCandidateIndex: candidates.championCandidateIndex,
      championHistory:
        candidates.championHistory.length > 0
          ? serializeChampionHistory(candidates.championHistory)
          : undefined,
      candidateNotes:
        Object.keys(candidates.notes).length > 0
          ? { ...candidates.notes }
          : undefined,
    };
  }

  private commitHistoryEntry(entry: EditorHistoryEntry): void {
    const state = this.store.getState();
    const nextHistory = pushHistoryEntry(
      state.history.entries,
      state.history.cursor,
      entry,
      state.history.limit,
    );

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        history: {
          ...currentState.history,
          entries: nextHistory.entries,
          cursor: nextHistory.cursor,
          nextSequence: currentState.history.nextSequence + 1,
        },
        session: {
          ...currentState.session,
          unsavedChanges: true,
          changedRevision: currentState.session.changedRevision + 1,
        },
      }),
    );
    this.scheduleValidation();
    this.scheduleAutosave();
  }

  private scheduleValidation(): void {
    if (this.validationTimer !== null) {
      window.clearTimeout(this.validationTimer);
    }

    this.validationTimer = window.setTimeout(() => {
      this.validationTimer = null;
      this.revalidateNow();
    }, 48);
  }

  private revalidateNow(): void {
    const state = this.store.getState();
    const workingMap = state.session.workingMap;
    if (!workingMap) {
      return;
    }

    const validation = state.ui.validationEnabled
      ? validateEditorMap(workingMap, {
          difficulty: state.session.source?.difficulty,
          audioDurationMs:
            state.session.audioDurationMs ||
            state.session.analysis?.audioDurationMs ||
            state.session.sectionAnalysis?.audio.durationMs,
          beats: state.session.analysis?.beats,
          onsets: state.session.analysis?.onsets,
          energyFrames: state.session.analysis?.energyFrames,
        })
      : createInitialEditorState().session.liveValidation;

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        session: {
          ...currentState.session,
          liveValidation: validation,
        },
      }),
    );
  }

  private scheduleAutosave(): void {
    if (this.autosaveTimer !== null) {
      window.clearTimeout(this.autosaveTimer);
    }

    this.autosaveTimer = window.setTimeout(() => {
      this.autosaveTimer = null;
      this.writeAutosave();
    }, 180);
  }

  private writeAutosave(): void {
    const state = this.store.getState();
    if (
      !state.session.source ||
      !state.session.baselineMap ||
      !state.session.workingMap
    ) {
      return;
    }

    const payload: EditorAutosavePayload = {
      ...this.createProjectExport(
        state.session.source,
        state.session.baselineMap,
        state.session.workingMap,
      ),
      autosave: {
        version: EDITOR_AUTOSAVE_SCHEMA_VERSION,
        savedRevision: state.session.changedRevision,
      },
    };

    try {
      localStorage.setItem(EDITOR_AUTOSAVE_KEY, JSON.stringify(payload));
      this.store.update((currentState) =>
        this.withDerivedState({
          ...currentState,
          session: {
            ...currentState.session,
            autosaveStatus: "saved",
            lastAutosaveMessage: `Autosave: revision ${payload.autosave.savedRevision}`,
          },
        }),
      );
    } catch {
      this.store.update((currentState) =>
        this.withDerivedState({
          ...currentState,
          session: {
            ...currentState.session,
            autosaveStatus: "error",
            lastAutosaveMessage: "Autosave failed",
          },
        }),
      );
    }
  }

  private readAutosave(): EditorAutosavePayload | undefined {
    const rawValue = localStorage.getItem(EDITOR_AUTOSAVE_KEY);
    if (!rawValue) {
      return undefined;
    }

    try {
      const parsed = JSON.parse(rawValue) as unknown;
      if (!isEditorAutosavePayload(parsed)) {
        return undefined;
      }

      return parsed as EditorAutosavePayload;
    } catch {
      return undefined;
    }
  }

  private applyRestoredProjectState(project: EditorProjectExport): void {
    const stateBefore = this.store.getState();
    const candidates = stateBefore.candidates;
    const restoredChampionIndex =
      typeof project.championCandidateIndex === "number" &&
      Number.isFinite(project.championCandidateIndex) &&
      candidates.entries.some(
        (entry) => entry.candidateIndex === project.championCandidateIndex,
      )
        ? project.championCandidateIndex
        : candidates.championCandidateIndex;
    const restoredHistory = project.championHistory
      ? parseChampionHistory(project.championHistory)
      : candidates.championHistory;
    const restoredNotes =
      project.candidateNotes && isJsonObject(project.candidateNotes)
        ? sanitizeCandidateNotes(project.candidateNotes)
        : candidates.notes;

    const entries = deserializeHistory(project.history);
    const durationLimit = this.totalDurationMs();
    const playheadMs = clamp(project.playheadMs, 0, Math.max(0, durationLimit));
    const cursor = clamp(project.history.cursor, 0, entries.length);
    const nextSequence = Math.max(
      project.history.nextSequence,
      entries.reduce(
        (maxSequence, entry) => Math.max(maxSequence, entry.sequence),
        0,
      ) + 1,
    );

    this.audioController.seek(playheadMs);
    this.audioController.setPlaybackRate(project.playbackRate);
    this.loopRange = undefined;
    if (typeof project.loopSectionId === "number") {
      const loopSection = findSongSectionById(
        this.store.getState().session.sectionAnalysis,
        project.loopSectionId,
      );
      if (loopSection) {
        this.loopRange = {
          sectionId: loopSection.id,
          startMs: loopSection.startMs,
          endMs: loopSection.endMs,
        };
      }
    }
    this.previewRange = undefined;
    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          playheadMs,
          isPlaying: false,
          unsavedChanges: true,
        },
        ui: {
          ...state.ui,
          mode: project.mode,
          snapMode: project.snapMode,
          snapToleranceMs: Math.max(0, Math.round(project.snapToleranceMs)),
          baselineOverlayEnabled: project.baselineOverlayEnabled,
          validationEnabled: project.validationEnabled,
          playbackRate: project.playbackRate,
          timeline: {
            visibleStartMs: Math.max(
              0,
              Math.round(project.timeline.visibleStartMs),
            ),
            visibleDurationMs: Math.max(
              1200,
              Math.round(project.timeline.visibleDurationMs),
            ),
          },
          selectedObjectId: project.selectedObjectId,
          selectedSectionId: project.selectedSectionId,
          loopSectionId: project.loopSectionId,
          lockedSectionIds: Array.isArray(project.lockedSectionIds)
            ? project.lockedSectionIds
                .filter((value): value is number => Number.isFinite(value))
                .map((value) => Math.round(value))
                .sort((left, right) => left - right)
            : [],
          modal: undefined,
        },
        history: {
          ...state.history,
          entries,
          cursor,
          nextSequence,
        },
        candidates: {
          ...candidates,
          championCandidateIndex: restoredChampionIndex,
          championHistory: restoredHistory,
          notes: restoredNotes,
        },
      }),
    );
    this.revalidateNow();
  }

  private withDerivedState(state: EditorRootState): EditorRootState {
    const baselineMap = state.session.baselineMap;
    const workingMap = state.session.workingMap;
    const selectedSection = findSongSectionById(
      state.session.sectionAnalysis,
      state.ui.selectedSectionId,
    );
    const selectedObject =
      workingMap && state.ui.selectedObjectId
        ? workingMap.objects.find(
            (object) => object.editorId === state.ui.selectedObjectId,
          )
        : undefined;
    const comparisonSummary =
      baselineMap && workingMap
        ? summarizeChanges(baselineMap, workingMap)
        : createInitialEditorState().session.comparisonSummary;
    const comparisonByObjectId =
      baselineMap && workingMap
        ? buildComparisonMap(baselineMap, workingMap)
        : {};
    const changedObjectCount =
      comparisonSummary.moved +
      comparisonSummary.retimed +
      comparisonSummary.movedAndRetimed +
      comparisonSummary.added +
      comparisonSummary.removed;
    const totalDuration = Math.max(
      state.session.audioDurationMs,
      state.session.sectionAnalysis?.audio.durationMs ?? 0,
      workingMap ? mapDurationMs(workingMap) : 0,
    );

    return {
      ...state,
      session: {
        ...state.session,
        baselineMap,
        workingMap,
        selectedObject,
        selectedSection,
        comparisonSummary,
        comparisonByObjectId,
        changedObjectCount,
        audioDurationMs: totalDuration,
        statusText: {
          mode: state.ui.mode,
          selectedObjectLabel: selectedObject
            ? `Object ${selectedObject.id}`
            : "No object",
          playheadLabel: formatTimeMs(state.session.playheadMs),
          zoomLabel: `${Math.round(
            totalDuration > 0
              ? totalDuration / state.ui.timeline.visibleDurationMs
              : 1,
          )}x`,
          snapLabel: formatSnapLabel(state.ui.snapMode, state.ui.snapToleranceMs),
          unsavedLabel: state.session.unsavedChanges
            ? "Unsaved Changes"
            : "Saved",
          issueLabel: `${state.session.liveValidation.summary.total} issues`,
          autosaveLabel: state.session.lastAutosaveMessage,
          audioLabel:
            state.session.loadStatus === "ready"
              ? "Audio ready"
              : state.session.loadStatus === "error"
                ? "Audio failed"
                : "Audio loading",
        },
      },
    };
  }

  private findWorkingObject(editorId?: string): EditorHitObject | undefined {
    const objects = this.store.getState().session.workingMap?.objects ?? [];
    return objects.find((object) => object.editorId === editorId);
  }

  private findBaselineObject(editorId?: string): EditorHitObject | undefined {
    const objects = this.store.getState().session.baselineMap?.objects ?? [];
    return objects.find((object) => object.editorId === editorId);
  }

  private totalDurationMs(): number {
    const state = this.store.getState();
    return Math.max(
      state.session.audioDurationMs,
      state.session.analysis?.audioDurationMs ?? 0,
      state.session.sectionAnalysis?.audio.durationMs ?? 0,
      state.session.workingMap ? mapDurationMs(state.session.workingMap) : 0,
    );
  }

  private snapTime(targetTimeMs: number, objectId?: string): number {
    const state = this.store.getState();
    const tolerance = state.ui.snapToleranceMs || DEFAULT_SNAP_TOLERANCE_MS;
    if (state.ui.snapMode === "off") {
      return targetTimeMs;
    }

    const analysis = state.session.analysis;
    if (!analysis) {
      return targetTimeMs;
    }

    const beatCandidate = nearestMarker(analysis.beats, targetTimeMs);
    const onsetCandidate = nearestMarker(analysis.onsets, targetTimeMs);

    const candidates =
      state.ui.snapMode === "beat"
        ? [beatCandidate]
        : state.ui.snapMode === "onset"
          ? [onsetCandidate]
          : [beatCandidate, onsetCandidate]
              .filter((candidate): candidate is { timeMs: number; strength: number } => Boolean(candidate))
              .sort((left, right) => {
                if (left.strength !== right.strength) {
                  return right.strength - left.strength;
                }

                return Math.abs(left.timeMs - targetTimeMs) - Math.abs(right.timeMs - targetTimeMs);
              });

    const closest = candidates
      .filter((candidate): candidate is { timeMs: number; strength: number } => Boolean(candidate))
      .sort(
        (left, right) =>
          Math.abs(left.timeMs - targetTimeMs) - Math.abs(right.timeMs - targetTimeMs),
      )[0];

    if (!closest) {
      return targetTimeMs;
    }

    if (Math.abs(closest.timeMs - targetTimeMs) > tolerance) {
      return targetTimeMs;
    }

    const duplicateOwner = this.store
      .getState()
      .session.workingMap?.objects.find(
        (object) =>
          object.editorId !== objectId && object.time === Math.round(closest.timeMs),
      );

    if (duplicateOwner) {
      return targetTimeMs;
    }

    return Math.round(closest.timeMs);
  }

  private handleLoadFailure(error: unknown, title: string): void {
    const message =
      error instanceof Error ? error.message : "Unknown map loading failure.";

    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        session: {
          ...state.session,
          loadStatus: "error",
          errorMessage: message,
        },
        ui: {
          ...state.ui,
          modal: {
            kind: "message",
            title,
            message,
          },
        },
      }),
    );
  }

  private loadCandidateBrowser(report: EvolutionReport): void {
    const workspaceKey = buildCandidateWorkspaceKey({
      title: report.song.title,
      artist: report.song.artist,
      difficulty: report.song.difficulty,
    });
    const persisted = loadCandidateWorkspace(workspaceKey);
    const entries = buildCandidateBrowserEntries(report);
    const persistedChampion =
      persisted?.championCandidateIndex !== undefined &&
      entries.some(
        (entry) => entry.candidateIndex === persisted?.championCandidateIndex,
      )
        ? persisted.championCandidateIndex
        : report.champion.candidateIndex;

    this.store.update((state) =>
      this.withDerivedState({
        ...state,
        candidates: {
          ...createInitialCandidateBrowserState(workspaceKey),
          entries,
          championCandidateIndex: persistedChampion,
          championHistory: persisted?.history ?? [],
          notes: persisted?.notes ?? {},
        },
      }),
    );
  }

  private persistCandidateWorkspace(): void {
    const state = this.store.getState();
    if (state.candidates.entries.length === 0) {
      return;
    }

    saveCandidateWorkspace(state.candidates.workspaceKey, {
      championCandidateIndex: state.candidates.championCandidateIndex,
      history: state.candidates.championHistory,
      notes: state.candidates.notes,
    });
  }

  private isComparisonActive(): boolean {
    const candidates = this.store.getState().candidates;
    return candidates.comparisonEnabled && candidates.comparison.state === "ready";
  }

  private async checkCandidatePromotable(
    entry: CandidateBrowserEntry,
  ): Promise<{ ok: boolean; reasons: string[] }> {
    const reasons: string[] = [];

    if (!entry.eligible) {
      reasons.push("The candidate is not eligible for promotion.");
    }

    if (entry.rejectionReasons.length > 0) {
      reasons.push(`Rejection reasons: ${entry.rejectionReasons.join(", ")}.`);
    }

    if (entry.validationStatus === "failed") {
      reasons.push("The candidate failed validation.");
    }

    for (const gate of entry.qualityGates) {
      if (gate.mandatory && !gate.passed) {
        reasons.push(`Mandatory quality gate failed: ${gate.name}.`);
      }
    }

    const map = await loadCandidateMapDocument(entry.mapPath);
    if (!map) {
      reasons.push("The candidate map could not be loaded.");
      return { ok: reasons.length === 0, reasons };
    }

    if (
      !map.title.trim() ||
      !map.artist.trim() ||
      !map.audio.trim()
    ) {
      reasons.push(
        "The candidate map is missing required metadata (title, artist, or audio).",
      );
    }

    const state = this.store.getState();
    const validation = validateEditorMap(map, {
      difficulty: state.session.source?.difficulty ?? entry.difficulty,
      audioDurationMs:
        state.session.audioDurationMs ||
        state.session.analysis?.audioDurationMs,
      beats: state.session.analysis?.beats,
      onsets: state.session.analysis?.onsets,
      energyFrames: state.session.analysis?.energyFrames,
    });
    if (hasBlockingIssues(validation)) {
      reasons.push(
        "The candidate map has critical structural issues that block promotion.",
      );
    }

    return { ok: reasons.length === 0, reasons };
  }

  private async promoteCandidate(
    entry: CandidateBrowserEntry,
    reason: string,
    manual: boolean,
  ): Promise<void> {
    const state = this.store.getState();
    const previousChampion = state.candidates.championCandidateIndex ?? null;
    const previousEntry =
      previousChampion === null
        ? undefined
        : findCandidateEntry(state.candidates.entries, previousChampion);
    const lastSequence =
      state.candidates.championHistory.length > 0
        ? state.candidates.championHistory[
            state.candidates.championHistory.length - 1
          ].sequence
        : 0;
    const historyEntry = createChampionHistoryEntry({
      sequence: lastSequence + 1,
      previousChampionIndex: previousChampion,
      previousMapPath: previousEntry?.mapPath ?? null,
      newChampionIndex: entry.candidateIndex,
      newChampionScore: entry.finalScore,
      newMapPath: entry.mapPath,
      reason,
      manual,
    });
    const history = appendChampionHistory(
      state.candidates.championHistory,
      historyEntry,
    );

    this.store.update((currentState) =>
      this.withDerivedState({
        ...currentState,
        candidates: {
          ...currentState.candidates,
          championCandidateIndex: entry.candidateIndex,
          championHistory: history,
        },
      }),
    );
    this.persistCandidateWorkspace();
  }
}

function nearestMarker(
  markers: Array<{ timeMs: number; strength: number }>,
  timeMs: number,
): { timeMs: number; strength: number } | undefined {
  let nearest: { timeMs: number; strength: number } | undefined;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const marker of markers) {
    const distanceMs = Math.abs(marker.timeMs - timeMs);
    if (distanceMs < bestDistance) {
      nearest = marker;
      bestDistance = distanceMs;
    }
  }

  return nearest;
}

function replaceWorkingObject(
  map: EditorMapDocument,
  editorId: string,
  patch: Partial<{ x: number; y: number; time: number; endTime: number }>,
): EditorMapDocument {
  const nextObjects = map.objects
    .map((object) =>
      object.editorId === editorId
        ? patchWorkingObject(object, patch)
        : object,
    )
    .sort((left, right) => {
      if (left.time !== right.time) {
        return left.time - right.time;
      }

      return left.editorId.localeCompare(right.editorId);
    });

  return {
    ...map,
    objects: nextObjects,
  };
}

function snapshotObject(object: EditorHitObject): JsonObject {
  switch (object.type) {
    case "circle":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        extraFields: object.extraFields,
      } as unknown as JsonObject;
    case "slider":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        endTime: object.endTime,
        pathType: object.pathType,
        controlPoints: object.controlPoints,
        repeats: object.repeats,
        pixelLength: object.pixelLength,
        extraFields: object.extraFields,
      } as unknown as JsonObject;
    case "spinner":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        time: object.time,
        endTime: object.endTime,
        extraFields: object.extraFields,
      } as unknown as JsonObject;
  }
}

function patchWorkingObject(
  object: EditorHitObject,
  patch: Partial<{ x: number; y: number; time: number; endTime: number }>,
): EditorHitObject {
  switch (object.type) {
    case "circle":
      return {
        ...object,
        x: typeof patch.x === "number" ? patch.x : object.x,
        y: typeof patch.y === "number" ? patch.y : object.y,
        time: typeof patch.time === "number" ? patch.time : object.time,
        extraFields: object.extraFields,
      };
    case "slider":
      return {
        ...object,
        x: typeof patch.x === "number" ? patch.x : object.x,
        y: typeof patch.y === "number" ? patch.y : object.y,
        time: typeof patch.time === "number" ? patch.time : object.time,
        endTime:
          typeof patch.endTime === "number" ? patch.endTime : object.endTime,
        extraFields: object.extraFields,
      };
    case "spinner":
      return {
        ...object,
        time: typeof patch.time === "number" ? patch.time : object.time,
        endTime:
          typeof patch.endTime === "number" ? patch.endTime : object.endTime,
        extraFields: object.extraFields,
      };
  }
}

function buildComparisonMap(
  baselineMap: EditorMapDocument,
  workingMap: EditorMapDocument,
): Record<string, ComparisonStatus> {
  const baselineById = new Map(
    baselineMap.objects.map((object) => [object.editorId, object]),
  );
  const workingById = new Map(
    workingMap.objects.map((object) => [object.editorId, object]),
  );
  const allIds = new Set([
    ...baselineById.keys(),
    ...workingById.keys(),
  ]);
  const output: Record<string, ComparisonStatus> = {};

  for (const editorId of allIds) {
    output[editorId] = compareObjectToBaseline(
      baselineById.get(editorId),
      workingById.get(editorId),
    );
  }

  return output;
}

function clampCoordinate(
  value: number,
  radius: number,
  maximum: number,
): number {
  return Math.round(clamp(value, radius, maximum - radius));
}

function sanitizeCandidateNotes(
  record: Record<string, unknown>,
): Record<string, string> {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (typeof value === "string") {
      output[key] = value;
    }
  }
  return output;
}

function snapshotToPastedObject(
  snapshot: JsonObject,
  editorId: string,
  id: number,
  time: number,
): EditorHitObject {
  const type = typeof snapshot.type === "string" ? snapshot.type : "circle";
  const extraFields = JSON.parse(JSON.stringify(snapshot.extraFields ?? {})) as JsonObject;

  if (type === "slider") {
    return {
      editorId,
      id,
      type: "slider",
      x: typeof snapshot.x === "number" ? snapshot.x : 256,
      y: typeof snapshot.y === "number" ? snapshot.y : 192,
      time,
      endTime:
        time + (typeof snapshot.endTime === "number" && snapshot.endTime > time
          ? snapshot.endTime - (typeof snapshot.time === "number" ? snapshot.time : time)
          : 200),
      pathType: (typeof snapshot.pathType === "string"
        ? snapshot.pathType
        : "bezier") as SliderPathType,
      controlPoints: Array.isArray(snapshot.controlPoints)
        ? snapshot.controlPoints.flatMap((point) =>
            typeof point === "object" &&
            point !== null &&
            typeof (point as Record<string, unknown>).x === "number" &&
            typeof (point as Record<string, unknown>).y === "number"
              ? [{ x: (point as { x: number }).x, y: (point as { y: number }).y }]
              : [],
          )
        : [],
      repeats: typeof snapshot.repeats === "number" ? snapshot.repeats : 1,
      pixelLength: typeof snapshot.pixelLength === "number" ? snapshot.pixelLength : 100,
      extraFields,
    } as EditorHitObject;
  }

  if (type === "spinner") {
    const durationMs =
      typeof snapshot.endTime === "number" && typeof snapshot.time === "number"
        ? snapshot.endTime - snapshot.time
        : 1200;
    return {
      editorId,
      id,
      type: "spinner",
      time,
      endTime: time + Math.max(300, Math.round(durationMs)),
      extraFields,
    } as EditorHitObject;
  }

  return {
    editorId,
    id,
    type: "circle",
    x: typeof snapshot.x === "number" ? snapshot.x : 256,
    y: typeof snapshot.y === "number" ? snapshot.y : 192,
    time,
    extraFields,
  } as EditorHitObject;
}

function toDifficultyName(value: string | undefined): "easy" | "normal" | "hard" | undefined {
  if (value === "easy" || value === "normal" || value === "hard") {
    return value;
  }

  return undefined;
}

function formatSnapLabel(mode: EditorSnapMode, toleranceMs: number): string {
  if (mode === "off") {
    return "Snap: Off";
  }

  if (mode === "beat") {
    return `Snap: Beat (${toleranceMs}ms)`;
  }

  if (mode === "onset") {
    return `Snap: Onset (${toleranceMs}ms)`;
  }

  return `Snap: Strongest (${toleranceMs}ms)`;
}
