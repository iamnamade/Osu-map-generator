import type { ValidationSeverity } from "../game/types";
import {
  getHitObjectEndTime,
  getHitObjectStartTime,
} from "../game/types";
import { serializeBeatmapDocument } from "../shared/beatmapSchema";
import type { JsonObject } from "../shared/JsonTypes";
import type { EditorHistoryEntry } from "./models/EditorActions";
import {
  compareObjectToBaseline,
  type EditorComparisonSummary,
  type EditorMapDocument,
  type EditorProjectExport,
  type EditorSerializedHistory,
  type EditorSourceIdentity,
} from "./models/EditorModels";
import type { EditorLiveValidation } from "./models/EditorValidationModels";

export function exportEditedMap(
  workingMap: EditorMapDocument,
  source: EditorSourceIdentity,
  editCount: number,
): { filename: string; json: string } {
  const normalized = normalizeMapForExport(workingMap, source, editCount);
  const fileSafeName = slugify(`${workingMap.title}-${source.difficulty ?? "edited"}-edited`);

  return {
    filename: `${fileSafeName}.json`,
    json: JSON.stringify(normalized, null, 2),
  };
}

export function exportEditLog(
  baselineMap: EditorMapDocument,
  workingMap: EditorMapDocument,
  source: EditorSourceIdentity,
  history: EditorSerializedHistory,
  validation: EditorLiveValidation,
): { filename: string; json: string } {
  const fileSafeName = slugify(`${workingMap.title}-${source.difficulty ?? "edited"}-edit-log`);

  return {
    filename: `${fileSafeName}.json`,
    json: JSON.stringify(
      {
        version: 1,
        source,
        baselineHash: hashMapDocument(baselineMap),
        difficulty: source.difficulty,
        actions: history.entries,
        changeSummary: summarizeChanges(baselineMap, workingMap),
        finalValidation: validation.summary,
      },
      null,
      2,
    ),
  };
}

export function exportEditorProject(
  project: EditorProjectExport,
): { filename: string; json: string } {
  const fileSafeName = slugify(
    `${project.workingMap.title}-${project.editorProject.source.difficulty ?? "edited"}`,
  );

  return {
    filename: `${fileSafeName}.editor.json`,
    json: JSON.stringify(project, null, 2),
  };
}

export function normalizeMapForExport(
  map: EditorMapDocument,
  source: EditorSourceIdentity,
  editCount: number,
): Record<string, unknown> {
  const orderedObjects = map.objects
    .slice()
    .sort((left, right) => {
      const startTimeDelta = getHitObjectStartTime(left) - getHitObjectStartTime(right);
      if (startTimeDelta !== 0) {
        return startTimeDelta;
      }

      const endTimeDelta = getHitObjectEndTime(left) - getHitObjectEndTime(right);
      if (endTimeDelta !== 0) {
        return endTimeDelta;
      }

      return left.editorId.localeCompare(right.editorId);
    })
    .map((object, index) => roundObjectForExport(object, index + 1));

  return serializeBeatmapDocument({
    ...map,
    objects: orderedObjects,
    extraFields: {
      ...map.extraFields,
      editor: {
        name: "osu-map-ai-editor",
        version: 1,
        sourceType: source.kind,
        sourceMap: source.path ?? null,
        editCount,
      },
    },
  });
}

export function hasBlockingIssues(validation: EditorLiveValidation): boolean {
  return validation.issues.some((issue) => issue.severity === "critical");
}

export function summarizeChanges(
  baselineMap: EditorMapDocument,
  workingMap: EditorMapDocument,
): EditorComparisonSummary {
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
  const summary: EditorComparisonSummary = {
    unchanged: 0,
    moved: 0,
    retimed: 0,
    movedAndRetimed: 0,
    added: 0,
    removed: 0,
  };

  for (const editorId of allIds) {
    const status = compareObjectToBaseline(
      baselineById.get(editorId),
      workingById.get(editorId),
    );

    switch (status) {
      case "added":
        summary.added += 1;
        break;
      case "removed":
        summary.removed += 1;
        break;
      case "moved":
        summary.moved += 1;
        break;
      case "retimed":
        summary.retimed += 1;
        break;
      case "moved-and-retimed":
        summary.movedAndRetimed += 1;
        break;
      case "unchanged":
        summary.unchanged += 1;
        break;
    }
  }

  return summary;
}

export function toHistorySnapshot(
  entries: EditorHistoryEntry[],
  cursor: number,
  nextSequence: number,
): EditorSerializedHistory {
  return {
    entries: entries.map((entry) => {
      if ("before" in entry || "after" in entry) {
        return {
          sequence: entry.sequence,
          action: entry.action,
          objectId: "objectId" in entry ? entry.objectId : undefined,
          before: "before" in entry ? (entry.before as JsonObject | undefined) : undefined,
          after: "after" in entry ? (entry.after as JsonObject | undefined) : undefined,
          timeMs: entry.timeMs,
          summary: entry.summary,
        };
      }

      return {
        sequence: entry.sequence,
        action: entry.action,
        objectId: "objectId" in entry ? entry.objectId : undefined,
        timeMs: entry.timeMs,
        summary: entry.summary,
      };
    }),
    cursor,
    nextSequence,
  };
}

export function validationSummaryLabel(
  count: number,
  severity: ValidationSeverity,
): string {
  return `${count} ${severity}${count === 1 ? "" : "s"}`;
}

export function downloadTextFile(
  filename: string,
  contents: string,
  mimeType = "application/json;charset=utf-8",
): void {
  const blob = new Blob([contents], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function hashMapDocument(map: EditorMapDocument): string {
  const payload = JSON.stringify(serializeBeatmapDocument(map));
  let hash = 0;

  for (let index = 0; index < payload.length; index += 1) {
    hash = (hash * 31 + payload.charCodeAt(index)) >>> 0;
  }

  return hash.toString(16).padStart(8, "0");
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
}

function roundObjectForExport(
  object: EditorMapDocument["objects"][number],
  id: number,
): EditorMapDocument["objects"][number] {
  switch (object.type) {
    case "circle":
      return {
        ...object,
        id,
        x: Math.round(object.x),
        y: Math.round(object.y),
        time: Math.round(object.time),
      };
    case "slider":
      return {
        ...object,
        id,
        x: Math.round(object.x),
        y: Math.round(object.y),
        time: Math.round(object.time),
        endTime: Math.round(object.endTime),
        pixelLength: Math.round(object.pixelLength * 1000) / 1000,
        controlPoints: object.controlPoints.map((point) => ({
          x: Math.round(point.x),
          y: Math.round(point.y),
        })),
      };
    case "spinner":
      return {
        ...object,
        id,
        time: Math.round(object.time),
        endTime: Math.round(object.endTime),
      };
  }
}
