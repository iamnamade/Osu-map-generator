import { loadDifficultyReport } from "../game/DifficultyReportLoader";
import type { DifficultyReport } from "../shared/difficultyReport";
import { loadEvolutionReport } from "../game/EvolutionReportLoader";
import type { EvolutionReport } from "../shared/evolutionReport";
import type { ValidationReport } from "../game/types";
import { loadHybridAssemblyReport } from "../game/HybridAssemblyReportLoader";
import { loadPhraseAnalysis } from "../game/PhraseAnalysisLoader";
import { loadRecoveryAnalysis } from "../game/RecoveryAnalysisLoader";
import { loadSectionAnalysis } from "../game/SectionAnalysisLoader";
import { loadValidationReport } from "../game/ValidationReportLoader";
import {
  parseBeatmapDocument,
  type BeatmapDocument,
} from "../shared/beatmapSchema";
import { cloneJsonValue, isJsonObject } from "../shared/JsonTypes";
import type { ProjectMapCatalogEntry } from "../shared/mapCatalog";
import {
  importOsuBeatmapText,
  type UnsupportedObjectMode,
} from "../shared/osuInterop";
import type { PhraseReport } from "../shared/phraseData";
import type { RecoveryReport } from "../shared/recoveryData";
import type {
  HybridAssemblyReport,
  SectionAnalysis,
} from "../shared/sectionData";
import {
  createImportedSourceIdentity,
  createSourceIdentityFromCatalog,
  freezeEditorMap,
  isEditorProject,
  type EditorAnalysis,
  type EditorMapBundle,
  type EditorMapDocument,
  type EditorProjectExport,
  type EditorSourceIdentity,
} from "./models/EditorModels";

export interface EditorFileImportOptions {
  kind?: "project-json" | "editor-project" | "osu";
  unsupportedMode?: UnsupportedObjectMode;
}

export async function loadEditorBundleFromCatalog(
  entry: ProjectMapCatalogEntry,
): Promise<EditorMapBundle> {
  const beatmapResponse = await fetch(entry.path);
  if (!beatmapResponse.ok) {
    throw new Error(`Map could not be loaded from ${entry.path}.`);
  }

  const rawBeatmap = await beatmapResponse.json();
  const beatmap = parseBeatmapDocument(rawBeatmap);
  const source = createSourceIdentityFromCatalog(entry);
  const analysis = entry.analysisPath
    ? await loadEditorAnalysis(entry.analysisPath)
    : undefined;
  const sectionAnalysis = entry.sectionAnalysisPath
    ? await loadSavedSectionAnalysis(entry.sectionAnalysisPath)
    : undefined;
  const phraseAnalysis = entry.phraseAnalysisPath
    ? await loadSavedPhraseAnalysis(entry.phraseAnalysisPath)
    : undefined;
  const recoveryAnalysis = entry.recoveryAnalysisPath
    ? await loadSavedRecoveryAnalysis(entry.recoveryAnalysisPath)
    : undefined;
  const hybridAssembly = entry.hybridAssemblyPath
    ? await loadSavedHybridAssembly(entry.hybridAssemblyPath)
    : undefined;
  const report = entry.reportPath
    ? await loadSavedReport(entry.reportPath)
    : undefined;
  const difficultyReport = entry.difficultyReportPath
    ? await loadSavedDifficultyReport(entry.difficultyReportPath)
    : undefined;
  const evolutionReport = entry.evolutionReportPath
    ? await loadSavedEvolutionReport(entry.evolutionReportPath)
    : undefined;

  return createBundle({
    beatmap,
    source,
    analysis,
    sectionAnalysis,
    phraseAnalysis,
    recoveryAnalysis,
    hybridAssembly,
    pythonReport: report,
    difficultyReport,
    evolutionReport,
  });
}

export async function loadEditorBundleFromFile(
  file: File,
  options: EditorFileImportOptions = {},
): Promise<EditorMapBundle> {
  const text = await file.text();
  const resolvedKind = resolveFileImportKind(file, options.kind);

  if (resolvedKind === "osu") {
    const { beatmap, report } = importOsuBeatmapText(text, {
      unsupported: options.unsupportedMode ?? "reject",
      filename: file.name,
    });
    const skippedSummary =
      report.skippedCount > 0
        ? `Imported from a local .osu file with ${report.skippedCount} unsupported object${
            report.skippedCount === 1 ? "" : "s"
          } skipped.`
        : "Imported from a local .osu file. Phase 8A currently supports circles only.";
    return createBundle({
      beatmap,
      source: createImportedSourceIdentity(file.name, skippedSummary),
    });
  }

  let rawData: unknown;

  try {
    rawData = JSON.parse(text) as unknown;
  } catch (error) {
    throw new Error(
      `Imported file is not valid JSON: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    );
  }

  if (resolvedKind === "editor-project") {
    if (!isEditorProject(rawData)) {
      throw new Error("Imported file is not a valid editor project export.");
    }

    return await loadEditorProject(rawData, file.name);
  }

  if (isEditorProject(rawData)) {
    if (resolvedKind === "project-json") {
      throw new Error(
        "Imported file is an editor project export. Use Import Editor Project instead of Project JSON.",
      );
    }

    return await loadEditorProject(rawData, file.name);
  }

  const beatmap = parseBeatmapDocument(rawData);
  return createBundle({
    beatmap,
    source: createImportedSourceIdentity(file.name),
  });
}

export async function loadEditorBundleFromProject(
  project: EditorProjectExport,
  filename = "recovered.editor.json",
): Promise<EditorMapBundle> {
  return await loadEditorProject(project, filename);
}

export function createBundle(params: {
  beatmap: BeatmapDocument;
  source: EditorSourceIdentity;
  analysis?: EditorAnalysis;
  sectionAnalysis?: SectionAnalysis;
  phraseAnalysis?: PhraseReport;
  recoveryAnalysis?: RecoveryReport;
  hybridAssembly?: HybridAssemblyReport;
  pythonReport?: Awaited<ReturnType<typeof loadSavedReport>>;
  difficultyReport?: Awaited<ReturnType<typeof loadSavedDifficultyReport>>;
  evolutionReport?: Awaited<ReturnType<typeof loadSavedEvolutionReport>>;
  restoredProject?: EditorProjectExport;
}): EditorMapBundle {
  const baselineMap = freezeEditorMap(convertToEditorMap(params.beatmap));
  const workingMap = cloneEditorMap(baselineMap);

  return {
    baselineMap,
    workingMap,
    source: params.source,
    analysis: params.analysis,
    sectionAnalysis: params.sectionAnalysis,
    phraseAnalysis: params.phraseAnalysis,
    recoveryAnalysis: params.recoveryAnalysis,
    hybridAssembly: params.hybridAssembly,
    pythonReport: params.pythonReport,
    difficultyReport: params.difficultyReport,
    evolutionReport: params.evolutionReport,
    restoredProject: params.restoredProject,
  };
}

export function exportEditorProjectShape(
  baselineMap: EditorMapDocument,
  workingMap: EditorMapDocument,
): {
  baselineMap: Record<string, unknown>;
  workingMap: Record<string, unknown>;
} {
  return {
    baselineMap: serializeEditorMapDocumentForProject(baselineMap),
    workingMap: serializeEditorMapDocumentForProject(workingMap),
  };
}

export function parseEditorMapDocument(rawData: unknown): EditorMapDocument {
  return convertToEditorMap(parseBeatmapDocument(rawData));
}

export function serializeEditorMapDocumentForProject(
  map: EditorMapDocument,
): Record<string, unknown> {
  return {
    ...cloneJsonValue(map.extraFields),
    title: map.title,
    artist: map.artist,
    audio: map.audio,
    approachTime: map.approachTime,
    circleRadius: map.circleRadius,
    objects: map.objects.map((object) => ({
      ...cloneJsonValue(object.extraFields),
      editorId: object.editorId,
      ...serializeEditorObject(object),
    })),
  };
}

export function cloneEditorMap(map: EditorMapDocument): EditorMapDocument {
  return {
    title: map.title,
    artist: map.artist,
    audio: map.audio,
    approachTime: map.approachTime,
    circleRadius: map.circleRadius,
    extraFields: cloneJsonValue(map.extraFields),
    objects: map.objects.map(cloneEditorObject),
  };
}

async function loadSavedReport(
  reportPath: string,
): Promise<ValidationReport | undefined> {
  try {
    const result = await loadValidationReport(reportPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedSectionAnalysis(
  analysisPath: string,
): Promise<SectionAnalysis | undefined> {
  try {
    const result = await loadSectionAnalysis(analysisPath);
    if (result.status === "ok") {
      return result.analysis;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedPhraseAnalysis(
  analysisPath: string,
): Promise<PhraseReport | undefined> {
  try {
    const result = await loadPhraseAnalysis(analysisPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedRecoveryAnalysis(
  analysisPath: string,
): Promise<RecoveryReport | undefined> {
  try {
    const result = await loadRecoveryAnalysis(analysisPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedDifficultyReport(
  reportPath: string,
): Promise<DifficultyReport | undefined> {
  try {
    const result = await loadDifficultyReport(reportPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedEvolutionReport(
  reportPath: string,
): Promise<EvolutionReport | undefined> {
  try {
    const result = await loadEvolutionReport(reportPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadSavedHybridAssembly(
  reportPath: string,
): Promise<HybridAssemblyReport | undefined> {
  try {
    const result = await loadHybridAssemblyReport(reportPath);
    if (result.status === "ok") {
      return result.report;
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function loadEditorAnalysis(path: string): Promise<EditorAnalysis | undefined> {
  let response: Response;

  try {
    response = await fetch(path);
  } catch {
    return undefined;
  }

  if (!response.ok) {
    return undefined;
  }

  const rawData = (await response.json()) as unknown;
  if (!isJsonObject(rawData)) {
    return undefined;
  }

  const audio = isJsonObject(rawData.audio) ? rawData.audio : undefined;
  const rhythm = isJsonObject(rawData.rhythm) ? rawData.rhythm : undefined;
  const energy = isJsonObject(rawData.energy) ? rawData.energy : undefined;

  const durationMs =
    typeof audio?.durationMs === "number" ? audio.durationMs : 0;
  const beats = Array.isArray(rhythm?.beats)
    ? rhythm.beats.flatMap((item) => toAnalysisMarker(item))
    : [];
  const onsets = Array.isArray(rhythm?.onsets)
    ? rhythm.onsets.flatMap((item) => toAnalysisMarker(item))
    : [];
  const energyFrames = Array.isArray(energy?.frames)
    ? energy.frames.flatMap((item) => toEnergyFrame(item))
    : [];
  const quietRegions = Array.isArray(energy?.quietRegions)
    ? energy.quietRegions.flatMap((item) => toTimeRegion(item))
    : [];
  const highEnergyRegions = Array.isArray(energy?.highEnergyRegions)
    ? energy.highEnergyRegions.flatMap((item) => toTimeRegion(item))
    : [];

  return {
    audioDurationMs: durationMs,
    bpm: typeof rhythm?.bpm === "number" ? rhythm.bpm : undefined,
    offsetMs: typeof rhythm?.offsetMs === "number" ? rhythm.offsetMs : undefined,
    beats,
    onsets,
    energyFrames,
    quietRegions,
    highEnergyRegions,
  };
}

async function loadEditorProject(
  rawData: unknown,
  filename: string,
): Promise<EditorMapBundle> {
  if (!isJsonObject(rawData)) {
    throw new Error("Editor project must be a JSON object.");
  }

  const baselineRaw = rawData.baselineMap;
  const workingRaw = rawData.workingMap;
  const projectMeta = rawData.editorProject;

  if (!projectMeta || !baselineRaw || !workingRaw) {
    throw new Error("Editor project is missing its baseline or working map.");
  }

  const sourceRecord =
    isJsonObject(projectMeta) && isJsonObject(projectMeta.source)
      ? projectMeta.source
      : undefined;
  const sourceKind = sourceRecord?.kind;

  const source: EditorSourceIdentity = {
    id: typeof sourceRecord?.id === "string" ? sourceRecord.id : `project:${filename}`,
    label:
      typeof sourceRecord?.label === "string"
        ? sourceRecord.label
        : filename,
    kind:
      sourceKind === "manual" ||
      sourceKind === "generated" ||
      sourceKind === "improved" ||
      sourceKind === "champion" ||
      sourceKind === "hybrid" ||
      sourceKind === "imported" ||
      sourceKind === "editor-project"
        ? sourceKind
        : "editor-project",
    path: typeof sourceRecord?.path === "string" ? sourceRecord.path : undefined,
    description:
      typeof sourceRecord?.description === "string"
        ? sourceRecord.description
        : "Recovered from a saved editor project. Exported maps still need human review and optional Python validation.",
    difficulty:
      typeof sourceRecord?.difficulty === "string"
        ? sourceRecord.difficulty
        : undefined,
    reportPath:
      typeof sourceRecord?.reportPath === "string"
        ? sourceRecord.reportPath
        : undefined,
    correctionReportPath:
      typeof sourceRecord?.correctionReportPath === "string"
        ? sourceRecord.correctionReportPath
        : undefined,
    tournamentReportPath:
      typeof sourceRecord?.tournamentReportPath === "string"
        ? sourceRecord.tournamentReportPath
        : undefined,
    analysisPath:
      typeof sourceRecord?.analysisPath === "string"
        ? sourceRecord.analysisPath
        : undefined,
    sectionAnalysisPath:
      typeof sourceRecord?.sectionAnalysisPath === "string"
        ? sourceRecord.sectionAnalysisPath
        : undefined,
    phraseAnalysisPath:
      typeof sourceRecord?.phraseAnalysisPath === "string"
        ? sourceRecord.phraseAnalysisPath
        : undefined,
    recoveryAnalysisPath:
      typeof sourceRecord?.recoveryAnalysisPath === "string"
        ? sourceRecord.recoveryAnalysisPath
        : undefined,
    hybridAssemblyPath:
      typeof sourceRecord?.hybridAssemblyPath === "string"
        ? sourceRecord.hybridAssemblyPath
        : undefined,
    hybridTransitionLogPath:
      typeof sourceRecord?.hybridTransitionLogPath === "string"
        ? sourceRecord.hybridTransitionLogPath
        : undefined,
    importReportPath:
      typeof sourceRecord?.importReportPath === "string"
        ? sourceRecord.importReportPath
        : undefined,
    difficultyReportPath:
      typeof sourceRecord?.difficultyReportPath === "string"
        ? sourceRecord.difficultyReportPath
        : undefined,
    evolutionReportPath:
      typeof sourceRecord?.evolutionReportPath === "string"
        ? sourceRecord.evolutionReportPath
        : undefined,
    importedFilename:
      typeof sourceRecord?.importedFilename === "string"
        ? sourceRecord.importedFilename
        : undefined,
  };
  const analysis = source.analysisPath
    ? await loadEditorAnalysis(source.analysisPath)
    : undefined;
  const sectionAnalysis = source.sectionAnalysisPath
    ? await loadSavedSectionAnalysis(source.sectionAnalysisPath)
    : undefined;
  const phraseAnalysis = source.phraseAnalysisPath
    ? await loadSavedPhraseAnalysis(source.phraseAnalysisPath)
    : undefined;
  const recoveryAnalysis = source.recoveryAnalysisPath
    ? await loadSavedRecoveryAnalysis(source.recoveryAnalysisPath)
    : undefined;
  const hybridAssembly = source.hybridAssemblyPath
    ? await loadSavedHybridAssembly(source.hybridAssemblyPath)
    : undefined;
  const pythonReport = source.reportPath
    ? await loadSavedReport(source.reportPath)
    : undefined;
  const difficultyReport = source.difficultyReportPath
    ? await loadSavedDifficultyReport(source.difficultyReportPath)
    : undefined;
  const evolutionReport = source.evolutionReportPath
    ? await loadSavedEvolutionReport(source.evolutionReportPath)
    : undefined;

  return {
    baselineMap: freezeEditorMap(parseEditorMapDocument(baselineRaw)),
    workingMap: parseEditorMapDocument(workingRaw),
    source,
    analysis,
    sectionAnalysis,
    phraseAnalysis,
    recoveryAnalysis,
    hybridAssembly,
    pythonReport,
    difficultyReport,
    evolutionReport,
    restoredProject: rawData as unknown as EditorProjectExport,
  };
}

function convertToEditorMap(beatmap: BeatmapDocument): EditorMapDocument {
  return {
    title: beatmap.title,
    artist: beatmap.artist,
    audio: beatmap.audio,
    approachTime: beatmap.approachTime,
    circleRadius: beatmap.circleRadius,
    extraFields: cloneJsonValue(beatmap.extraFields),
    objects: beatmap.objects.map((object, index) =>
      toEditorObject(
        object,
        typeof object.extraFields.editorId === "string" &&
          object.extraFields.editorId.trim().length > 0
          ? object.extraFields.editorId
          : `obj-${String(index + 1).padStart(6, "0")}`,
      ),
    ),
  };
}

function serializeEditorObject(
  object: EditorMapDocument["objects"][number],
): Record<string, unknown> {
  switch (object.type) {
    case "circle":
      return {
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
      };
    case "slider":
      return {
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        endTime: object.endTime,
        pathType: object.pathType,
        controlPoints: object.controlPoints.map((point) => ({
          x: point.x,
          y: point.y,
        })),
        repeats: object.repeats,
        pixelLength: object.pixelLength,
      };
    case "spinner":
      return {
        id: object.id,
        type: object.type,
        time: object.time,
        endTime: object.endTime,
      };
  }
}

function cloneEditorObject(
  object: EditorMapDocument["objects"][number],
): EditorMapDocument["objects"][number] {
  switch (object.type) {
    case "circle":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        extraFields: cloneJsonValue(object.extraFields),
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
        controlPoints: object.controlPoints.map((point) => ({
          x: point.x,
          y: point.y,
        })),
        repeats: object.repeats,
        pixelLength: object.pixelLength,
        extraFields: cloneJsonValue(object.extraFields),
      };
    case "spinner":
      return {
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        time: object.time,
        endTime: object.endTime,
        extraFields: cloneJsonValue(object.extraFields),
      };
  }
}

function toEditorObject(
  object: BeatmapDocument["objects"][number],
  editorId: string,
): EditorMapDocument["objects"][number] {
  const extraFields = stripProjectOnlyObjectFields(object.extraFields);

  switch (object.type) {
    case "circle":
      return {
        editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        extraFields,
      };
    case "slider":
      return {
        editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
        endTime: object.endTime,
        pathType: object.pathType,
        controlPoints: object.controlPoints.map((point) => ({
          x: point.x,
          y: point.y,
        })),
        repeats: object.repeats,
        pixelLength: object.pixelLength,
        extraFields,
      };
    case "spinner":
      return {
        editorId,
        id: object.id,
        type: object.type,
        time: object.time,
        endTime: object.endTime,
        extraFields,
      };
  }
}

function toAnalysisMarker(value: unknown): Array<{ timeMs: number; strength: number }> {
  if (!isJsonObject(value)) {
    return [];
  }

  if (typeof value.timeMs !== "number" || typeof value.strength !== "number") {
    return [];
  }

  return [{ timeMs: value.timeMs, strength: value.strength }];
}

function toEnergyFrame(value: unknown): Array<{ timeMs: number; value: number }> {
  if (!isJsonObject(value)) {
    return [];
  }

  if (typeof value.timeMs !== "number" || typeof value.value !== "number") {
    return [];
  }

  return [{ timeMs: value.timeMs, value: value.value }];
}

function toTimeRegion(value: unknown): Array<{ startMs: number; endMs: number }> {
  if (!isJsonObject(value)) {
    return [];
  }

  if (typeof value.startMs !== "number" || typeof value.endMs !== "number") {
    return [];
  }

  return [{ startMs: value.startMs, endMs: value.endMs }];
}

function stripProjectOnlyObjectFields(
  extraFields: BeatmapDocument["objects"][number]["extraFields"],
): BeatmapDocument["objects"][number]["extraFields"] {
  const cloned = cloneJsonValue(extraFields);
  delete cloned.editorId;
  return cloned;
}

function resolveFileImportKind(
  file: File,
  explicitKind: EditorFileImportOptions["kind"],
): NonNullable<EditorFileImportOptions["kind"]> | "auto-json" {
  if (explicitKind) {
    return explicitKind;
  }

  if (file.name.toLowerCase().endsWith(".osu")) {
    return "osu";
  }

  return "auto-json";
}
