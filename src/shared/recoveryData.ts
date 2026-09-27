import { isJsonObject } from "./JsonTypes";

export type SpinnerTriggerType =
  | "sustain"
  | "fade_out"
  | "transition"
  | "riser"
  | "unknown";

export interface RecoveryWindow {
  startTime: number;
  endTime: number;
  staminaReductionFactor: number;
  reason: string;
  phraseId: number | null;
}

export interface FatigueProfile {
  timestamps: number[];
  fatigueScores: number[];
  peakFatigueTime: number;
  peakFatigue: number;
}

export interface HarmonyRoleCounts {
  circle: number;
  slider: number;
  spinner: number;
  total: number;
}

export interface HarmonyReport {
  roles: Record<string, HarmonyRoleCounts>;
  violations: Array<{
    role: string;
    message: string;
  }>;
}

export interface RecoveryReport {
  version: number;
  difficulty: string;
  audioDurationMs: number;
  objectCount: number;
  spinnerCount: number;
  avgSpinnerDurationMs: number;
  guidelines: {
    minDurationMs: number;
    postClearanceMs: number;
  };
  fatigue: FatigueProfile;
  recoveryWindows: RecoveryWindow[];
  harmony: HarmonyReport;
  objectTypeCounts: {
    circle: number;
    slider: number;
    spinner: number;
  };
}

export function parseRecoveryReport(rawData: unknown): RecoveryReport {
  const root = expectRecord(rawData, "recovery report");
  const fatigue = expectRecord(root.fatigue, "recovery report fatigue");
  const guidelines = expectRecord(root.guidelines, "recovery report guidelines");
  const harmony = expectRecord(root.harmony, "recovery report harmony");
  return {
    version: expectNumber(root.version, "recovery report version"),
    difficulty: expectString(root.difficulty, "recovery report difficulty"),
    audioDurationMs: expectNumber(
      root.audioDurationMs,
      "recovery report audioDurationMs",
    ),
    objectCount: expectNumber(root.objectCount, "recovery report objectCount"),
    spinnerCount: expectNumber(root.spinnerCount, "recovery report spinnerCount"),
    avgSpinnerDurationMs: expectNumber(
      root.avgSpinnerDurationMs,
      "recovery report avgSpinnerDurationMs",
    ),
    guidelines: {
      minDurationMs: expectNumber(
        guidelines.minDurationMs,
        "recovery guidelines minDurationMs",
      ),
      postClearanceMs: expectNumber(
        guidelines.postClearanceMs,
        "recovery guidelines postClearanceMs",
      ),
    },
    fatigue: {
      timestamps: expectArray(fatigue.timestamps, "fatigue timestamps").map(
        (item, index) => expectNumber(item, `fatigue timestamps[${index}]`),
      ),
      fatigueScores: expectArray(
        fatigue.fatigueScores,
        "fatigue fatigueScores",
      ).map((item, index) =>
        expectNumber(item, `fatigue fatigueScores[${index}]`),
      ),
      peakFatigueTime: expectNumber(
        fatigue.peakFatigueTime,
        "fatigue peakFatigueTime",
      ),
      peakFatigue: expectNumber(fatigue.peakFatigue, "fatigue peakFatigue"),
    },
    recoveryWindows: expectArray(
      root.recoveryWindows,
      "recovery report recoveryWindows",
    ).map(validateRecoveryWindow),
    harmony: validateHarmony(harmony),
    objectTypeCounts: readObjectTypeCounts(root.objectTypeCounts),
  };
}

export function fatigueAtTime(
  fatigue: FatigueProfile,
  timeMs: number,
  windowMs = 400,
): number {
  if (fatigue.timestamps.length === 0) {
    return 0;
  }
  const half = windowMs / 2;
  const values: number[] = [];
  fatigue.timestamps.forEach((timestamp, index) => {
    if (Math.abs(timestamp - timeMs) <= half) {
      values.push(fatigue.fatigueScores[index]);
    }
  });
  if (values.length === 0) {
    let nearestIndex = 0;
    let nearestDelta = Infinity;
    fatigue.timestamps.forEach((timestamp, index) => {
      const delta = Math.abs(timestamp - timeMs);
      if (delta < nearestDelta) {
        nearestDelta = delta;
        nearestIndex = index;
      }
    });
    return fatigue.fatigueScores[nearestIndex];
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function getTriggerColor(triggerType: SpinnerTriggerType): string {
  const colors: Record<SpinnerTriggerType, string> = {
    sustain: "#5de0a6",
    fade_out: "#8ab4ff",
    transition: "#c58fff",
    riser: "#f6c15e",
    unknown: "#8da0be",
  };
  return colors[triggerType] ?? "#8da0be";
}

function validateRecoveryWindow(rawValue: unknown): RecoveryWindow {
  const value = expectRecord(rawValue, "recovery window");
  return {
    startTime: expectNumber(value.startTime, "recovery window startTime"),
    endTime: expectNumber(value.endTime, "recovery window endTime"),
    staminaReductionFactor: expectNumber(
      value.staminaReductionFactor,
      "recovery window staminaReductionFactor",
    ),
    reason: expectString(value.reason, "recovery window reason"),
    phraseId: expectNullableNumber(value.phraseId, "recovery window phraseId"),
  };
}

function validateHarmony(rawValue: Record<string, unknown>): HarmonyReport {
  const rolesRaw = expectRecord(rawValue.roles, "harmony roles");
  const roles: Record<string, HarmonyRoleCounts> = {};
  for (const [role, countsRaw] of Object.entries(rolesRaw)) {
    const counts = expectRecord(countsRaw, `harmony role ${role}`);
    roles[role] = {
      circle: expectNumber(counts.circle, `harmony ${role} circle`),
      slider: expectNumber(counts.slider, `harmony ${role} slider`),
      spinner: expectNumber(counts.spinner, `harmony ${role} spinner`),
      total: expectNumber(counts.total, `harmony ${role} total`),
    };
  }
  return {
    roles,
    violations: expectArray(rawValue.violations, "harmony violations").map(
      (item, index) => {
        const violation = expectRecord(item, `harmony violation ${index}`);
        return {
          role: expectString(violation.role, `violation ${index} role`),
          message: expectString(violation.message, `violation ${index} message`),
        };
      },
    ),
  };
}

function expectRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (!isJsonObject(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value;
}

function readLooseRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (value === undefined || value === null) {
    return {};
  }
  return expectRecord(value, label);
}

function readObjectTypeCounts(value: unknown): RecoveryReport["objectTypeCounts"] {
  const record = readLooseRecord(value, "objectTypeCounts");
  return {
    circle: optionalNumber(record.circle, 0),
    slider: optionalNumber(record.slider, 0),
    spinner: optionalNumber(record.spinner, 0),
  };
}

function optionalNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function expectArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value;
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

function expectNullableNumber(
  value: unknown,
  label: string,
): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  return expectNumber(value, label);
}
