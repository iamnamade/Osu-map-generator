import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  type Beatmap,
  type BeatmapHitObject,
  type BeatmapSliderHitObject,
  type BeatmapSpinnerHitObject,
  type SliderPathType,
} from "./types";

const SUPPORTED_TYPES = new Set(["circle", "slider", "spinner"]);
const SUPPORTED_SLIDER_PATH_TYPES = new Set<SliderPathType>([
  "bezier",
  "linear",
  "catmull",
  "perfect",
]);

export async function loadBeatmap(url: string): Promise<Beatmap> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Beatmap could not be loaded from ${url}.`);
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    throw new Error(
      `Beatmap JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    );
  }

  return validateBeatmap(rawData);
}

function validateBeatmap(rawData: unknown): Beatmap {
  if (!isRecord(rawData)) {
    throw new Error("Beatmap JSON must be an object.");
  }

  const title = expectString(rawData.title, "Beatmap title");
  const artist = expectString(rawData.artist, "Beatmap artist");
  const audio = expectString(rawData.audio, "Beatmap audio path");
  const approachTime = expectPositiveNumber(rawData.approachTime, "approachTime");
  const circleRadius = expectPositiveNumber(rawData.circleRadius, "circleRadius");

  if (!Array.isArray(rawData.objects) || rawData.objects.length === 0) {
    throw new Error("Beatmap must contain at least one hit object.");
  }

  const seenIds = new Set<number>();
  const objects = rawData.objects.map((item, index) =>
    validateObject(item, index, seenIds),
  );

  objects.sort((left, right) => left.time - right.time);

  return {
    title,
    artist,
    audio,
    approachTime,
    circleRadius,
    objects,
  };
}

function validateObject(
  rawObject: unknown,
  index: number,
  seenIds: Set<number>,
): BeatmapHitObject {
  if (!isRecord(rawObject)) {
    throw new Error(`Hit object ${index + 1} must be an object.`);
  }

  const id = expectWholeNumber(rawObject.id, `Hit object ${index + 1} id`);
  const type = expectString(rawObject.type, `Hit object ${id} type`);
  const time = expectNumber(rawObject.time, `Hit object ${id} time`);

  if (seenIds.has(id)) {
    throw new Error(`Hit object ${id} is duplicated. IDs must be unique.`);
  }

  seenIds.add(id);

  if (!SUPPORTED_TYPES.has(type)) {
    throw new Error(`Hit object ${id} uses unsupported type "${type}".`);
  }

  if (time < 0) {
    throw new Error(`Hit object ${id} must have a non-negative target time.`);
  }

  if (type === "circle" || type === "slider") {
    const x = expectNumber(rawObject.x, `Hit object ${id} x`);
    const y = expectNumber(rawObject.y, `Hit object ${id} y`);

    if (x < 0 || x > PLAYFIELD_WIDTH || y < 0 || y > PLAYFIELD_HEIGHT) {
      throw new Error(
        `Hit object ${id} must stay within the ${PLAYFIELD_WIDTH}x${PLAYFIELD_HEIGHT} playfield.`,
      );
    }

    if (type === "circle") {
      return {
        id,
        type,
        x,
        y,
        time,
      };
    }

    const endTime = expectNumber(rawObject.endTime, `Hit object ${id} endTime`);
    const pathType = expectSliderPathType(
      rawObject.pathType,
      `Hit object ${id} pathType`,
    );
    const repeats = expectWholeNumber(rawObject.repeats, `Hit object ${id} repeats`);
    const pixelLength = expectPositiveNumber(
      rawObject.pixelLength,
      `Hit object ${id} pixelLength`,
    );
    const controlPoints = expectControlPoints(rawObject.controlPoints, id);

    if (endTime <= time) {
      throw new Error(`Hit object ${id} slider endTime must be greater than time.`);
    }

    const slider: BeatmapSliderHitObject = {
      id,
      type: "slider",
      x,
      y,
      time,
      endTime,
      pathType,
      controlPoints,
      repeats,
      pixelLength,
    };
    return slider;
  }

  const endTime = expectNumber(rawObject.endTime, `Hit object ${id} endTime`);

  if (endTime <= time) {
    throw new Error(`Hit object ${id} spinner endTime must be greater than time.`);
  }

  const spinner: BeatmapSpinnerHitObject = {
    id,
    type: "spinner",
    time,
    endTime,
  };
  return spinner;
}

function expectControlPoints(value: unknown, id: number): Array<{ x: number; y: number }> {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`Hit object ${id} slider controlPoints must be a non-empty array.`);
  }

  return value.map((entry, index) => {
    if (!isRecord(entry)) {
      throw new Error(
        `Hit object ${id} slider control point ${index + 1} must be an object.`,
      );
    }

    return {
      x: expectNumber(entry.x, `Hit object ${id} control point ${index + 1} x`),
      y: expectNumber(entry.y, `Hit object ${id} control point ${index + 1} y`),
    };
  });
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
