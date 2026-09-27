import { isJsonObject, type JsonObject } from "../shared/JsonTypes";
import {
  parseEditorMapDocument,
  serializeEditorMapDocumentForProject,
} from "./EditorMapLoader";
import { type SliderPathType } from "../game/types";
import type { EditorHistoryEntry } from "./models/EditorActions";
import {
  EditorMapDocument,
  EditorHitObject,
  EditorSerializedHistory,
  EditorSerializedHistoryEntry,
  cloneEditorMap,
} from "./models/EditorModels";

export function applyHistoryEntry(
  map: EditorMapDocument,
  entry: EditorHistoryEntry,
): EditorMapDocument {
  switch (entry.action) {
    case "move_object":
    case "retime_object":
    case "move_and_retime_object":
      return patchObject(map, entry.objectId, entry.after);
    case "add_object":
      return insertObjectSnapshot(map, entry.objectSnapshot, entry.objectIndex);
    case "delete_object":
      return removeObjectByEditorId(map, entry.objectId);
    case "reset_object":
      if (!entry.after) {
        return removeObjectByEditorId(map, entry.objectId);
      }
      if (findObjectIndex(map, entry.objectId) === -1) {
        return insertObjectSnapshot(map, entry.after, entry.objectIndex);
      }
      return patchObject(map, entry.objectId, entry.after);
    case "reset_map":
      return cloneMap(entry.afterMap);
    case "batch_metadata_edit":
      return patchMetadata(map, entry.after);
  }
}

export function undoHistoryEntry(
  map: EditorMapDocument,
  entry: EditorHistoryEntry,
): EditorMapDocument {
  switch (entry.action) {
    case "move_object":
    case "retime_object":
    case "move_and_retime_object":
      return patchObject(map, entry.objectId, entry.before);
    case "add_object":
      return removeObjectByEditorId(map, entry.objectId);
    case "delete_object":
      return insertObjectSnapshot(map, entry.objectSnapshot, entry.objectIndex);
    case "reset_object":
      if (!entry.before) {
        return removeObjectByEditorId(map, entry.objectId);
      }
      if (findObjectIndex(map, entry.objectId) === -1) {
        return insertObjectSnapshot(map, entry.before, entry.objectIndex);
      }
      return patchObject(map, entry.objectId, entry.before);
    case "reset_map":
      return cloneMap(entry.beforeMap);
    case "batch_metadata_edit":
      return patchMetadata(map, entry.before);
  }
}

export function pushHistoryEntry(
  entries: EditorHistoryEntry[],
  cursor: number,
  nextEntry: EditorHistoryEntry,
  limit: number,
): { entries: EditorHistoryEntry[]; cursor: number } {
  const truncated = entries.slice(0, cursor);
  truncated.push(nextEntry);

  if (truncated.length > limit) {
    const overflow = truncated.length - limit;
    return {
      entries: truncated.slice(overflow),
      cursor: limit,
    };
  }

  return {
    entries: truncated,
    cursor: truncated.length,
  };
}

export function serializeHistory(
  entries: EditorHistoryEntry[],
  cursor: number,
  nextSequence: number,
): EditorSerializedHistory {
  return {
    entries: entries.map((entry) => {
      switch (entry.action) {
        case "move_object":
        case "retime_object":
        case "move_and_retime_object":
          return {
            sequence: entry.sequence,
            action: entry.action,
            objectId: entry.objectId,
            before: entry.before,
            after: entry.after,
            timeMs: entry.timeMs,
            summary: entry.summary,
          };
        case "add_object":
        case "delete_object":
          return {
            sequence: entry.sequence,
            action: entry.action,
            objectId: entry.objectId,
            before: entry.action === "delete_object" ? entry.objectSnapshot : undefined,
            after: entry.action === "add_object" ? entry.objectSnapshot : undefined,
            objectSnapshot: entry.objectSnapshot,
            objectIndex: entry.objectIndex,
            timeMs: entry.timeMs,
            summary: entry.summary,
          };
        case "reset_object":
          return {
            sequence: entry.sequence,
            action: entry.action,
            objectId: entry.objectId,
            before: entry.before,
            after: entry.after,
            objectIndex: entry.objectIndex,
            timeMs: entry.timeMs,
            summary: entry.summary,
          };
        case "batch_metadata_edit":
          return {
            sequence: entry.sequence,
            action: entry.action,
            before: entry.before,
            after: entry.after,
            timeMs: entry.timeMs,
            summary: entry.summary,
          };
        case "reset_map":
          return {
            sequence: entry.sequence,
            action: entry.action,
            beforeMap: serializeEditorMapDocumentForProject(entry.beforeMap),
            afterMap: serializeEditorMapDocumentForProject(entry.afterMap),
            timeMs: entry.timeMs,
            summary: entry.summary,
          };
      }
    }),
    cursor,
    nextSequence,
  };
}

export function deserializeHistory(
  history: EditorSerializedHistory,
): EditorHistoryEntry[] {
  return history.entries.flatMap((entry) => deserializeHistoryEntry(entry));
}

function patchObject(
  map: EditorMapDocument,
  objectId: string,
  patch: JsonObject,
): EditorMapDocument {
  const nextMap = cloneMap(map);
  const objectIndex = findObjectIndex(nextMap, objectId);

  if (objectIndex === -1) {
    return nextMap;
  }

  const target = nextMap.objects[objectIndex];
  nextMap.objects[objectIndex] = patchEditorObject(target, patch);
  sortObjects(nextMap.objects);
  return nextMap;
}

function patchMetadata(
  map: EditorMapDocument,
  patch: JsonObject,
): EditorMapDocument {
  const nextMap = cloneMap(map);
  nextMap.title = typeof patch.title === "string" ? patch.title : nextMap.title;
  nextMap.artist = typeof patch.artist === "string" ? patch.artist : nextMap.artist;
  nextMap.audio = typeof patch.audio === "string" ? patch.audio : nextMap.audio;
  nextMap.approachTime =
    typeof patch.approachTime === "number" ? patch.approachTime : nextMap.approachTime;
  nextMap.circleRadius =
    typeof patch.circleRadius === "number" ? patch.circleRadius : nextMap.circleRadius;
  return nextMap;
}

function insertObjectSnapshot(
  map: EditorMapDocument,
  snapshot: JsonObject,
  objectIndex: number,
): EditorMapDocument {
  const nextMap = cloneMap(map);
  const nextObject = snapshotToObject(snapshot);
  const safeIndex = Math.max(0, Math.min(objectIndex, nextMap.objects.length));
  nextMap.objects.splice(safeIndex, 0, nextObject);
  sortObjects(nextMap.objects);
  return nextMap;
}

function removeObjectByEditorId(
  map: EditorMapDocument,
  objectId: string,
): EditorMapDocument {
  const nextMap = cloneMap(map);
  nextMap.objects = nextMap.objects.filter((object) => object.editorId !== objectId);
  return nextMap;
}

function sortObjects(objects: EditorHitObject[]): void {
  objects.sort((left, right) => {
    if (left.time !== right.time) {
      return left.time - right.time;
    }

    return left.id - right.id;
  });
}

function snapshotToObject(snapshot: JsonObject): EditorHitObject {
  const type = typeof snapshot.type === "string" ? snapshot.type : "circle";
  const common = {
    editorId: String(snapshot.editorId ?? ""),
    id: Number(snapshot.id ?? 0),
    time: Number(snapshot.time ?? 0),
    extraFields:
      (typeof snapshot.extraFields === "object" &&
      snapshot.extraFields &&
      !Array.isArray(snapshot.extraFields)
        ? snapshot.extraFields
        : {}) as JsonObject,
  };

  if (type === "slider") {
    return {
      ...common,
      type: "slider",
      x: Number(snapshot.x ?? 0),
      y: Number(snapshot.y ?? 0),
      endTime: Number(snapshot.endTime ?? common.time),
      pathType: (typeof snapshot.pathType === "string"
        ? snapshot.pathType
        : "bezier") as SliderPathType,
      controlPoints: Array.isArray(snapshot.controlPoints)
        ? snapshot.controlPoints.flatMap((point) =>
            isJsonObject(point) && typeof point.x === "number" && typeof point.y === "number"
              ? [{ x: point.x, y: point.y }]
              : [],
          )
        : [],
      repeats: Number(snapshot.repeats ?? 1),
      pixelLength: Number(snapshot.pixelLength ?? 0),
    };
  }

  if (type === "spinner") {
    return {
      ...common,
      type: "spinner",
      endTime: Number(snapshot.endTime ?? common.time),
    };
  }

  return {
    ...common,
    type: "circle",
    x: Number(snapshot.x ?? 0),
    y: Number(snapshot.y ?? 0),
  };
}

function deserializeHistoryEntry(
  entry: EditorSerializedHistoryEntry,
): EditorHistoryEntry[] {
  const sequence = Number.isFinite(entry.sequence) ? entry.sequence : 0;
  const summary =
    typeof entry.summary === "string" && entry.summary.length > 0
      ? entry.summary
      : entry.action;
  const timeMs = Number.isFinite(entry.timeMs) ? entry.timeMs : undefined;

  switch (entry.action) {
    case "move_object":
    case "retime_object":
    case "move_and_retime_object":
      if (
        typeof entry.objectId !== "string" ||
        !isJsonObject(entry.before) ||
        !isJsonObject(entry.after)
      ) {
        return [];
      }

      return [
        {
          action: entry.action,
          objectId: entry.objectId,
          before: entry.before,
          after: entry.after,
          sequence,
          timeMs,
          summary,
        },
      ];
    case "add_object":
    case "delete_object": {
      const snapshot =
        isJsonObject(entry.objectSnapshot)
          ? entry.objectSnapshot
          : entry.action === "add_object"
            ? entry.after
            : entry.before;

      if (typeof entry.objectId !== "string" || !isJsonObject(snapshot)) {
        return [];
      }

      return [
        {
          action: entry.action,
          objectId: entry.objectId,
          objectSnapshot: snapshot,
          objectIndex:
            typeof entry.objectIndex === "number"
              ? Math.max(0, Math.round(entry.objectIndex))
              : 0,
          sequence,
          timeMs,
          summary,
        },
      ];
    }
    case "reset_object":
      if (typeof entry.objectId !== "string") {
        return [];
      }

      return [
        {
          action: "reset_object",
          objectId: entry.objectId,
          before: isJsonObject(entry.before) ? entry.before : undefined,
          after: isJsonObject(entry.after) ? entry.after : undefined,
          objectIndex:
            typeof entry.objectIndex === "number"
              ? Math.max(0, Math.round(entry.objectIndex))
              : 0,
          sequence,
          timeMs,
          summary,
        },
      ];
    case "batch_metadata_edit":
      if (!isJsonObject(entry.before) || !isJsonObject(entry.after)) {
        return [];
      }

      return [
        {
          action: "batch_metadata_edit",
          before: entry.before,
          after: entry.after,
          sequence,
          timeMs,
          summary,
        },
      ];
    case "reset_map":
      if (!isJsonObject(entry.beforeMap) || !isJsonObject(entry.afterMap)) {
        return [];
      }

      try {
        return [
          {
            action: "reset_map",
            beforeMap: parseEditorMapDocument(entry.beforeMap),
            afterMap: parseEditorMapDocument(entry.afterMap),
            sequence,
            timeMs,
            summary,
          },
        ];
      } catch {
        return [];
      }
    default:
      return [];
  }
}

function findObjectIndex(map: EditorMapDocument, objectId: string): number {
  return map.objects.findIndex((object) => object.editorId === objectId);
}

function cloneMap(map: EditorMapDocument): EditorMapDocument {
  return cloneEditorMap(map);
}

function patchEditorObject(
  target: EditorHitObject,
  patch: JsonObject,
): EditorHitObject {
  const extraFields = JSON.parse(JSON.stringify(target.extraFields)) as JsonObject;

  switch (target.type) {
    case "circle":
      return {
        ...target,
        x: typeof patch.x === "number" ? patch.x : target.x,
        y: typeof patch.y === "number" ? patch.y : target.y,
        time: typeof patch.time === "number" ? patch.time : target.time,
        extraFields,
      };
    case "slider":
      return {
        ...target,
        x: typeof patch.x === "number" ? patch.x : target.x,
        y: typeof patch.y === "number" ? patch.y : target.y,
        time: typeof patch.time === "number" ? patch.time : target.time,
        endTime: typeof patch.endTime === "number" ? patch.endTime : target.endTime,
        extraFields,
      };
    case "spinner":
      return {
        ...target,
        time: typeof patch.time === "number" ? patch.time : target.time,
        endTime: typeof patch.endTime === "number" ? patch.endTime : target.endTime,
        extraFields,
      };
  }
}
