import {
  getHitObjectEndTime,
  getHitObjectPosition,
  type BeatmapCircleHitObject,
  type BeatmapHitObject,
  type BeatmapSliderHitObject,
  type BeatmapSpinnerHitObject,
  type HitObjectPoint,
  type ValidationReport,
} from "../../game/types";
import {
  isJsonObject,
  type JsonObject,
  type JsonValue,
} from "../../shared/JsonTypes";
import type { ProjectMapCatalogEntry, ProjectMapKind } from "../../shared/mapCatalog";
import type { ChampionHistoryEntry } from "../candidates/championHistory";
import type { DifficultyReport } from "../../shared/difficultyReport";
import type { EvolutionReport } from "../../shared/evolutionReport";
import type { PhraseReport } from "../../shared/phraseData";
import type { RecoveryReport } from "../../shared/recoveryData";
import type {
  HybridAssemblyReport,
  SectionAnalysis,
  SongSection,
} from "../../shared/sectionData";

export type EditorMode = "select" | "add-circle";
export type EditorSnapMode = "off" | "beat" | "onset" | "strongest-anchor";
export type EditorPlaybackRate = 0.5 | 0.75 | 1;
export type EditorLoadStatus =
  | "idle"
  | "loading-map"
  | "loading-audio"
  | "loading-analysis"
  | "decoding-waveform"
  | "ready"
  | "error";
export type EditorSourceType =
  | ProjectMapKind
  | "imported"
  | "editor-project";
export type ComparisonStatus =
  | "unchanged"
  | "moved"
  | "retimed"
  | "moved-and-retimed"
  | "added"
  | "removed";

export type EditorCircleHitObject = BeatmapCircleHitObject & {
  editorId: string;
  extraFields: JsonObject;
};
export type EditorSliderHitObject = BeatmapSliderHitObject & {
  editorId: string;
  extraFields: JsonObject;
};
export type EditorSpinnerHitObject = BeatmapSpinnerHitObject & {
  editorId: string;
  extraFields: JsonObject;
};
export type EditorHitObject =
  | EditorCircleHitObject
  | EditorSliderHitObject
  | EditorSpinnerHitObject;
export type PositionedEditorHitObject =
  | EditorCircleHitObject
  | EditorSliderHitObject;

export interface EditorMapDocument {
  title: string;
  artist: string;
  audio: string;
  approachTime: number;
  circleRadius: number;
  objects: EditorHitObject[];
  extraFields: JsonObject;
}

export interface EditorSourceIdentity {
  id: string;
  label: string;
  path?: string;
  kind: EditorSourceType;
  difficulty?: string;
  description?: string;
  reportPath?: string;
  correctionReportPath?: string;
  tournamentReportPath?: string;
  analysisPath?: string;
  sectionAnalysisPath?: string;
  phraseAnalysisPath?: string;
  recoveryAnalysisPath?: string;
  hybridAssemblyPath?: string;
  hybridTransitionLogPath?: string;
  importReportPath?: string;
  difficultyReportPath?: string;
  evolutionReportPath?: string;
  importedFilename?: string;
}

export interface EditorMapBundle {
  baselineMap: EditorMapDocument;
  workingMap: EditorMapDocument;
  source: EditorSourceIdentity;
  analysis?: EditorAnalysis;
  pythonReport?: ValidationReport;
  sectionAnalysis?: SectionAnalysis;
  phraseAnalysis?: PhraseReport;
  recoveryAnalysis?: RecoveryReport;
  hybridAssembly?: HybridAssemblyReport;
  difficultyReport?: DifficultyReport;
  evolutionReport?: EvolutionReport;
  restoredProject?: EditorProjectExport;
}

export interface EditorAnalysisMarker {
  timeMs: number;
  strength: number;
}

export interface EditorEnergyFrame {
  timeMs: number;
  value: number;
}

export interface EditorTimeRegion {
  startMs: number;
  endMs: number;
}

export interface EditorAnalysis {
  audioDurationMs: number;
  bpm?: number;
  offsetMs?: number;
  beats: EditorAnalysisMarker[];
  onsets: EditorAnalysisMarker[];
  energyFrames: EditorEnergyFrame[];
  quietRegions: EditorTimeRegion[];
  highEnergyRegions: EditorTimeRegion[];
}

export interface EditorWaveformPeaks {
  sampleCount: number;
  peaks: number[];
}

export interface EditorTimelineState {
  visibleStartMs: number;
  visibleDurationMs: number;
}

export interface EditorMapSummary {
  objectCount: number;
  durationMs: number;
}

export interface EditorComparisonSummary {
  unchanged: number;
  moved: number;
  retimed: number;
  movedAndRetimed: number;
  added: number;
  removed: number;
}

export interface EditorProjectExport {
  editorProject: {
    name: "pulse-practice-editor";
    version: 1;
    source: EditorSourceIdentity;
  };
  baselineMap: Record<string, unknown>;
  workingMap: Record<string, unknown>;
  history: EditorSerializedHistory;
  timeline: EditorTimelineState;
  selectedObjectId?: string;
  selectedSectionId?: number;
  playheadMs: number;
  mode: EditorMode;
  snapMode: EditorSnapMode;
  snapToleranceMs: number;
  baselineOverlayEnabled: boolean;
  validationEnabled: boolean;
  playbackRate: EditorPlaybackRate;
  loopSectionId?: number;
  lockedSectionIds?: number[];
  championCandidateIndex?: number;
  championHistory?: ChampionHistoryEntry[];
  candidateNotes?: Record<string, string>;
}

export interface EditorSerializedHistoryEntry {
  sequence: number;
  action: string;
  objectId?: string;
  before?: JsonObject;
  after?: JsonObject;
  objectSnapshot?: JsonObject;
  objectIndex?: number;
  beforeMap?: Record<string, unknown>;
  afterMap?: Record<string, unknown>;
  timeMs?: number;
  summary: string;
}

export interface EditorSerializedHistory {
  entries: EditorSerializedHistoryEntry[];
  cursor: number;
  nextSequence: number;
}

export interface EditorAutosavePayload extends EditorProjectExport {
  autosave: {
    version: 1;
    savedRevision: number;
  };
}

export interface EditorStatusText {
  mode: EditorMode;
  selectedObjectLabel: string;
  playheadLabel: string;
  zoomLabel: string;
  snapLabel: string;
  unsavedLabel: string;
  issueLabel: string;
  autosaveLabel: string;
  audioLabel: string;
}

export function createImportedSourceIdentity(
  filename: string,
  description = "Imported from a local JSON file. Changes stay in the browser until exported.",
): EditorSourceIdentity {
  return {
    id: `import:${filename}`,
    label: filename,
    kind: "imported",
    importedFilename: filename,
    description,
  };
}

export function createSourceIdentityFromCatalog(
  entry: ProjectMapCatalogEntry,
): EditorSourceIdentity {
  return {
    id: entry.id,
    label: entry.label,
    path: entry.path,
    kind: entry.kind,
    difficulty: entry.difficulty,
    description: entry.description,
    reportPath: entry.reportPath,
    correctionReportPath: entry.correctionReportPath,
    tournamentReportPath: entry.tournamentReportPath,
    analysisPath: entry.analysisPath,
    sectionAnalysisPath: entry.sectionAnalysisPath,
    phraseAnalysisPath: entry.phraseAnalysisPath,
    recoveryAnalysisPath: entry.recoveryAnalysisPath,
    hybridAssemblyPath: entry.hybridAssemblyPath,
    hybridTransitionLogPath: entry.hybridTransitionLogPath,
    importReportPath: entry.importReportPath,
    difficultyReportPath: entry.difficultyReportPath,
    evolutionReportPath: entry.evolutionReportPath,
  };
}

export function cloneEditorMap(map: EditorMapDocument): EditorMapDocument {
  return {
    title: map.title,
    artist: map.artist,
    audio: map.audio,
    approachTime: map.approachTime,
    circleRadius: map.circleRadius,
    extraFields: JSON.parse(JSON.stringify(map.extraFields)) as JsonObject,
    objects: map.objects.map(cloneEditorHitObject),
  };
}

export function freezeEditorMap<T extends EditorMapDocument>(map: T): T {
  for (const object of map.objects) {
    Object.freeze(object.extraFields);
    Object.freeze(object);
  }

  Object.freeze(map.objects);
  Object.freeze(map.extraFields);
  return Object.freeze(map);
}

export function mapDurationMs(map: EditorMapDocument): number {
  const lastObject = map.objects[map.objects.length - 1];
  return lastObject ? getHitObjectEndTime(lastObject) : 0;
}

export function findSongSectionById(
  sectionAnalysis: SectionAnalysis | undefined,
  sectionId: number | undefined,
): SongSection | undefined {
  if (!sectionAnalysis || typeof sectionId !== "number") {
    return undefined;
  }

  return sectionAnalysis.sections.find((section) => section.id === sectionId);
}

export function compareObjectToBaseline(
  baselineObject: EditorHitObject | undefined,
  workingObject: EditorHitObject | undefined,
): ComparisonStatus {
  if (!baselineObject && workingObject) {
    return "added";
  }

  if (baselineObject && !workingObject) {
    return "removed";
  }

  if (!baselineObject || !workingObject) {
    return "unchanged";
  }

  const moved = haveDifferentPositions(baselineObject, workingObject);
  const retimed = baselineObject.time !== workingObject.time;

  if (moved && retimed) {
    return "moved-and-retimed";
  }

  if (moved) {
    return "moved";
  }

  if (retimed) {
    return "retimed";
  }

  return "unchanged";
}

function cloneEditorHitObject(object: EditorHitObject): EditorHitObject {
  const extraFields = JSON.parse(JSON.stringify(object.extraFields)) as JsonObject;

  switch (object.type) {
    case "circle":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        extraFields,
      };
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
        controlPoints: object.controlPoints.map(clonePoint),
        repeats: object.repeats,
        pixelLength: object.pixelLength,
        extraFields,
      };
    case "spinner":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        time: object.time,
        endTime: object.endTime,
        extraFields,
      };
  }
}

function haveDifferentPositions(
  left: EditorHitObject,
  right: EditorHitObject,
): boolean {
  const leftPosition = getHitObjectPosition(left as BeatmapHitObject);
  const rightPosition = getHitObjectPosition(right as BeatmapHitObject);

  if (!leftPosition || !rightPosition) {
    return Boolean(leftPosition) !== Boolean(rightPosition) || left.type !== right.type;
  }

  return leftPosition.x !== rightPosition.x || leftPosition.y !== rightPosition.y;
}

function clonePoint(point: HitObjectPoint): HitObjectPoint {
  return {
    x: point.x,
    y: point.y,
  };
}

export function isEditorProject(value: unknown): value is {
  editorProject: {
    name: string;
    version: number;
  };
} {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Record<string, unknown>;
  const editorProject = record.editorProject;
  if (typeof editorProject !== "object" || editorProject === null) {
    return false;
  }

  const name = (editorProject as Record<string, unknown>).name;
  return typeof name === "string" && name === "pulse-practice-editor";
}

export function isEditorAutosavePayload(
  value: unknown,
): value is EditorAutosavePayload {
  if (!isEditorProject(value) || !isJsonObject(value)) {
    return false;
  }

  const autosave = (value as Record<string, unknown>).autosave;
  return (
    isJsonObject(autosave) &&
    autosave.version === 1 &&
    typeof autosave.savedRevision === "number" &&
    Number.isFinite(autosave.savedRevision)
  );
}

export function jsonValueOrUndefined(value: unknown): JsonValue | undefined {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return value;
  }

  if (Array.isArray(value)) {
    const items = value
      .map((item) => jsonValueOrUndefined(item))
      .filter((item): item is JsonValue => item !== undefined);
    return items;
  }

  if (typeof value === "object" && value !== null) {
    const output: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      const nextValue = jsonValueOrUndefined(item);
      if (nextValue !== undefined) {
        output[key] = nextValue;
      }
    }
    return output;
  }

  return undefined;
}
