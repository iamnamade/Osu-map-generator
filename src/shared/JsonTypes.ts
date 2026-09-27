export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return Number.isFinite(value as number) || typeof value !== "number";
  }

  if (Array.isArray(value)) {
    return value.every((item) => isJsonValue(item));
  }

  if (!isJsonObject(value)) {
    return false;
  }

  return Object.values(value).every((item) => isJsonValue(item));
}

export function cloneJsonValue<T extends JsonValue>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function sanitizeJsonObject(
  value: Record<string, unknown>,
  excludedKeys: ReadonlySet<string>,
): JsonObject {
  const output: JsonObject = {};

  for (const [key, item] of Object.entries(value)) {
    if (excludedKeys.has(key) || !isJsonValue(item)) {
      continue;
    }

    output[key] = cloneJsonValue(item);
  }

  return output;
}
