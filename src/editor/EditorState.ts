import type { ValidationReport } from "../game/types";
import type { DifficultyReport } from "../shared/difficultyReport";
import type { EvolutionReport } from "../shared/evolutionReport";
import type { PhraseReport } from "../shared/phraseData";
import type { RecoveryReport } from "../shared/recoveryData";
import type {
  HybridAssemblyReport,
  SectionAnalysis,
  SongSection,
} from "../shared/sectionData";
import type { CandidateBrowserState } from "./candidates/candidateModels";
import type { EditorHistoryEntry } from "./models/EditorActions";
import type {
  ComparisonStatus,
  EditorAnalysis,
  EditorComparisonSummary,
  EditorHitObject,
  EditorLoadStatus,
  EditorMapDocument,
  EditorPlaybackRate,
  EditorSnapMode,
  EditorSourceIdentity,
  EditorStatusText,
  EditorTimelineState,
  EditorWaveformPeaks,
} from "./models/EditorModels";
import type { EditorLiveValidation } from "./models/EditorValidationModels";

export interface EditorHistoryState {
  entries: EditorHistoryEntry[];
  cursor: number;
  nextSequence: number;
  limit: number;
}

export interface EditorUiState {
  mode: "select" | "add-circle";
  snapMode: EditorSnapMode;
  snapToleranceMs: number;
  validationEnabled: boolean;
  baselineOverlayEnabled: boolean;
  playbackRate: EditorPlaybackRate;
  timeline: EditorTimelineState;
  selectedObjectId?: string;
  selectedSectionId?: number;
  loopSectionId?: number;
  lockedSectionIds: number[];
  inspectorDraft?: {
    x?: string;
    y?: string;
    time?: string;
    title?: string;
    artist?: string;
    audio?: string;
    approachTime?: string;
    circleRadius?: string;
  };
  activeRightTab:
    | "inspector"
    | "validation"
    | "difficulty"
    | "evolution"
    | "candidates"
    | "hybrid"
    | "history"
    | "export"
    | "settings";
  shortcutHelpOpen: boolean;
  exportMenuOpen: boolean;
  modal?:
    | {
        kind: "confirm-reset-map";
        title: string;
        message: string;
      }
    | {
        kind: "restore-session";
        title: string;
        message: string;
      }
    | {
        kind: "discard-imported";
        title: string;
        message: string;
      }
    | {
        kind: "message";
        title: string;
        message: string;
      }
    | {
        kind: "confirm-promote";
        title: string;
        message: string;
      };
}

export interface EditorSessionState {
  loadStatus: EditorLoadStatus;
  errorMessage?: string;
  source?: EditorSourceIdentity;
  baselineMap?: EditorMapDocument;
  workingMap?: EditorMapDocument;
  analysis?: EditorAnalysis;
  sectionAnalysis?: SectionAnalysis;
  phraseAnalysis?: PhraseReport;
  recoveryAnalysis?: RecoveryReport;
  hybridAssembly?: HybridAssemblyReport;
  difficultyReport?: DifficultyReport;
  evolutionReport?: EvolutionReport;
  waveform?: EditorWaveformPeaks;
  pythonReport?: ValidationReport;
  liveValidation: EditorLiveValidation;
  comparisonSummary: EditorComparisonSummary;
  comparisonByObjectId: Record<string, ComparisonStatus>;
  playheadMs: number;
  audioDurationMs: number;
  isPlaying: boolean;
  unsavedChanges: boolean;
  changedRevision: number;
  changedObjectCount: number;
  autosaveStatus: "idle" | "saved" | "restored" | "error";
  lastAutosaveMessage: string;
  selectedObject?: EditorHitObject;
  selectedSection?: SongSection;
  statusText: EditorStatusText;
}

export interface EditorRootState {
  session: EditorSessionState;
  ui: EditorUiState;
  history: EditorHistoryState;
  candidates: CandidateBrowserState;
}
