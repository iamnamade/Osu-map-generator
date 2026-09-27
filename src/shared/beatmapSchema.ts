import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  getHitObjectEndTime,
  getHitObjectStartTime,
  type Beatmap,
  type BeatmapCircleHitObject,
  type BeatmapHitObject,
  type BeatmapSliderHitObject,
  type BeatmapSpinnerHitObject,
  type HitObjectPoint,
  type HitObjectType,
  type SliderPathType,
} from "../game/types";
import {
  type JsonObject,
  cloneJsonValue,
  isJsonObject,
  sanitizeJsonObject,
} from "./JsonTypes";

const SUPPORTED_TYPES = new Set<HitObjectType>(["circle", "slider", "spinner"]);
const SUPPORTED_SLIDER_PATH_TYPES = new Set<SliderPathType>([
  "bezier",
  "linear",
  "catmull",
  "perfect",
]);
const KNOWN_MAP_KEYS = new Set([
  "title",
  "artist",
  "audio",
  "approachTime",
  "circleRadius",
  "objects",
]);
const KNOWN_OBJECT_KEYS = new Set(["id", "type", "time"]);
const KNOWN_CIRCLE_KEYS = new Set([...KNOWN_OBJECT_KEYS, "x", "y"]);
const KNOWN_SLIDER_KEYS = new Set([
  ...KNOWN_CIRCLE_KEYS,
  "endTime",
  "pathType",
  "controlPoints",
  "repeats",
  "pixelLength",
]);
const KNOWN_SPINNER_KEYS = new Set([...KNOWN_OBJECT_KEYS, "endTime"]);

export type BeatmapDocumentCircleObject = BeatmapCircleHitObject & {
  extraFields: JsonObject;
};
export type BeatmapDocumentSliderObject = BeatmapSliderHitObject & {
  extraFields: JsonObject;
};
export type BeatmapDocumentSpinnerObject = BeatmapSpinnerHitObject & {
  extraFields: JsonObject;
};
export type BeatmapDocumentObject =
  | BeatmapDocumentCircleObject
  | BeatmapDocumentSliderObject
  | BeatmapDocumentSpinnerObject;

export interface BeatmapDocument extends Omit<Beatmap, "objects"> {
  objects: BeatmapDocumentObject[];
  extraFields: JsonObject;
}

export interface ParseBeatmapOptions {
  requireObjects?: boolean;
  requireUniqueTimestamps?: boolean;
}

export function parseBeatmapDocument(
  rawData: unknown,
  options: ParseBeatmapOptions = {},
): BeatmapDocument {
  const { requireObjects = true, requireUniqueTimestamps = true } = options;

  if (!isJsonObject(rawData)) {
    throw new Error("Beatmap JSON must be an object.");
  }

  const title = expectString(rawData.title, "Beatmap title");
  const artist = expectString(rawData.artist, "Beatmap artist");
  const audio = expectString(rawData.audio, "Beatmap audio path");
  const approachTime = expectPositiveNumber(rawData.approachTime, "approachTime");
  const circleRadius = expectPositiveNumber(rawData.circleRadius, "circleRadius");

  if (!Array.isArray(rawData.objects)) {
    throw new Error("Beatmap objects must be an array.");
  }

  if (requireObjects && rawData.objects.length === 0) {
    throw new Error("Beatmap must contain at least one hit object.");
  }

  const seenIds = new Set<number>();
  const seenTimes = new Set<number>();
  const objects = rawData.objects.map((item, index) =>
    validateObject(item, index, seenIds, seenTimes, requireUniqueTimestamps),
  );

  objects.sort((left, right) => {
    const startTimeDelta = getHitObjectStartTime(left) - getHitObjectStartTime(right);
    if (startTimeDelta !== 0) {
      return startTimeDelta;
    }

    const endTimeDelta = getHitObjectEndTime(left) - getHitObjectEndTime(right);
    if (endTimeDelta !== 0) {
      return endTimeDelta;
    }

    return left.id - right.id;
  });

  return {
    title,
    artist,
    audio,
    approachTime,
    circleRadius,
    objects,
    extraFields: sanitizeJsonObject(rawData, KNOWN_MAP_KEYS),
  };
}

export function serializeBeatmapDocument(
  beatmap: BeatmapDocument,
): Record<string, unknown> {
  return {
    ...cloneJsonValue(beatmap.extraFields),
    title: beatmap.title,
    artist: beatmap.artist,
    audio: beatmap.audio,
    approachTime: beatmap.approachTime,
    circleRadius: beatmap.circleRadius,
    objects: beatmap.objects.map((object) => ({
      ...cloneJsonValue(object.extraFields),
      ...serializeDocumentObject(object),
    })),
  };
}

export function toGameBeatmap(beatmap: BeatmapDocument): Beatmap {
  return {
    title: beatmap.title,
    artist: beatmap.artist,
    audio: beatmap.audio,
    approachTime: beatmap.approachTime,
    circleRadius: beatmap.circleRadius,
    objects: beatmap.objects.map(toGameObject),
  };
}

function validateObject(
  rawObject: unknown,
  index: number,
  seenIds: Set<number>,
  seenTimes: Set<number>,
  requireUniqueTimestamps: boolean,
): BeatmapDocumentObject {
  if (!isJsonObject(rawObject)) {
    throw new Error(`Hit object ${index + 1} must be an object.`);
  }

  const id = expectWholeNumber(rawObject.id, `Hit object ${index + 1} id`);
  const type = expectHitObjectType(rawObject.type, `Hit object ${id} type`);
  const time = expectWholeNumber(rawObject.time, `Hit object ${id} time`);

  if (seenIds.has(id)) {
    throw new Error(`Hit object ${id} is duplicated. IDs must be unique.`);
  }

  if (requireUniqueTimestamps && seenTimes.has(time)) {
    throw new Error(
      `Hit object ${id} is duplicated at ${time}ms. Timestamps must be unique.`,
    );
  }

  seenIds.add(id);
  seenTimes.add(time);

  if (time < 0) {
    throw new Error(`Hit object ${id} must have a non-negative target time.`);
  }

  switch (type) {
    case "circle":
      return validateCircleObject(rawObject, id, time);
    case "slider":
      return validateSliderObject(rawObject, id, time);
    case "spinner":
      return validateSpinnerObject(rawObject, id, time);
  }
}

function validateCircleObject(
  rawObject: JsonObject,
  id: number,
  time: number,
): BeatmapDocumentCircleObject {
  const position = expectPlayfieldPoint(rawObject, `Hit object ${id}`);

  return {
    id,
    type: "circle",
    x: position.x,
    y: position.y,
    time,
    extraFields: sanitizeJsonObject(rawObject, KNOWN_CIRCLE_KEYS),
  };
}

function validateSliderObject(
  rawObject: JsonObject,
  id: number,
  time: number,
): BeatmapDocumentSliderObject {
  const position = expectPlayfieldPoint(rawObject, `Hit object ${id}`);
  const endTime = expectWholeNumber(rawObject.endTime, `Hit object ${id} endTime`);
  const pathType = expectSliderPathType(rawObject.pathType, `Hit object ${id} pathType`);
  const controlPoints = expectControlPoints(rawObject.controlPoints, id);
  const repeats = expectWholeNumber(rawObject.repeats, `Hit object ${id} repeats`);
  const pixelLength = expectPositiveNumber(
    rawObject.pixelLength,
    `Hit object ${id} pixelLength`,
  );

  if (endTime <= time) {
    throw new Error(`Hit object ${id} slider endTime must be greater than time.`);
  }

  if (repeats < 1) {
    throw new Error(`Hit object ${id} slider repeats must be at least 1.`);
  }

  return {
    id,
    type: "slider",
    x: position.x,
    y: position.y,
    time,
    endTime,
    pathType,
    controlPoints,
    repeats,
    pixelLength,
    extraFields: sanitizeJsonObject(rawObject, KNOWN_SLIDER_KEYS),
  };
}

function validateSpinnerObject(
  rawObject: JsonObject,
  id: number,
  time: number,
): BeatmapDocumentSpinnerObject {
  const endTime = expectWholeNumber(rawObject.endTime, `Hit object ${id} endTime`);

  if (endTime <= time) {
    throw new Error(`Hit object ${id} spinner endTime must be greater than time.`);
  }

  return {
    id,
    type: "spinner",
    time,
    endTime,
    extraFields: sanitizeJsonObject(rawObject, KNOWN_SPINNER_KEYS),
  };
}

function serializeDocumentObject(object: BeatmapDocumentObject): Record<string, unknown> {
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

function toGameObject(object: BeatmapDocumentObject): BeatmapHitObject {
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

function expectPlayfieldPoint(
  rawObject: JsonObject,
  label: string,
): HitObjectPoint {
  const x = expectWholeNumber(rawObject.x, `${label} x`);
  const y = expectWholeNumber(rawObject.y, `${label} y`);

  if (x < 0 || x > PLAYFIELD_WIDTH || y < 0 || y > PLAYFIELD_HEIGHT) {
    throw new Error(
      `${label} must stay within the ${PLAYFIELD_WIDTH}x${PLAYFIELD_HEIGHT} playfield.`,
    );
  }

  return { x, y };
}

function expectControlPoints(value: unknown, id: number): HitObjectPoint[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`Hit object ${id} slider controlPoints must be a non-empty array.`);
  }

  return value.map((entry, index) => {
    if (!isJsonObject(entry)) {
      throw new Error(
        `Hit object ${id} slider control point ${index + 1} must be an object.`,
      );
    }

    return {
      x: expectWholeNumber(
        entry.x,
        `Hit object ${id} slider control point ${index + 1} x`,
      ),
      y: expectWholeNumber(
        entry.y,
        `Hit object ${id} slider control point ${index + 1} y`,
      ),
    };
  });
}

function expectHitObjectType(value: unknown, label: string): HitObjectType {
  const parsedValue = expectString(value, label);

  if (!SUPPORTED_TYPES.has(parsedValue as HitObjectType)) {
    throw new Error(`Unsupported hit object type "${parsedValue}".`);
  }

  return parsedValue as HitObjectType;
}

function expectSliderPathType(value: unknown, label: string): SliderPathType {
  const parsedValue = expectString(value, label);

  if (!SUPPORTED_SLIDER_PATH_TYPES.has(parsedValue as SliderPathType)) {
    throw new Error(
      `${label} must be one of ${Array.from(SUPPORTED_SLIDER_PATH_TYPES).join(", ")}.`,
    );
  }

  return parsedValue as SliderPathType;
}

function expectString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} must be a non-empty string.`);
  }

  return value;
}

function expectNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number.`);
  }

  return value;
}

function expectPositiveNumber(value: unknown, label: string): number {
  const parsedValue = expectNumber(value, label);

  if (parsedValue <= 0) {
    throw new Error(`${label} must be greater than zero.`);
  }

  return parsedValue;
}

function expectWholeNumber(value: unknown, label: string): number {
  const parsedValue = expectNumber(value, label);

  if (!Number.isInteger(parsedValue)) {
    throw new Error(`${label} must be an integer.`);
  }

  return parsedValue;
}
