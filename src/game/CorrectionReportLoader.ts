import type {
  BeforeAfterSummary,
  CorrectionAction,
  CorrectionActionType,
  CorrectionReport,
  CorrectionSummary,
  ProcessingStage,
  ScoreChanges,
  ValidationIssueCategory,
} from "./types";

type CorrectionReportLoadResult =
  | { status: "ok"; report: CorrectionReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

const VALID_ACTION_TYPES = new Set<CorrectionActionType>([
  "move_object",
  "adjust_time",
  "remove_object",
  "insert_object",
]);
const VALID_STAGES = new Set<ProcessingStage>([
  "structural_safety",
  "timing_corrections",
  "movement_corrections",
  "stacking_corrections",
  "density_corrections",
  "repetition_corrections",
  "difficulty_corrections",
  "local_optimization",
]);
const VALID_CATEGORIES = new Set<ValidationIssueCategory>([
  "structural",
  "timing",
  "rhythm",
  "movement",
  "readability",
  "spatialBalance",
  "repetition",
  "densityConsistency",
  "difficultyConsistency",
]);

export async function loadCorrectionReport(
  url: string,
): Promise<CorrectionReportLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Improvement report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Improvement report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Improvement report has not been generated yet.",
    };
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Improvement report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: validateCorrectionReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Improvement report at ${url} is malformed: ${error.message}`
          : `Improvement report at ${url} is malformed.`,
    };
  }
}

function validateCorrectionReport(rawData: unknown): CorrectionReport {
  const value = expectRecord(rawData, "correction report");

  return {
    version: expectNumber(value.version, "correction report.version"),
    sourceMap: expectString(value.sourceMap, "correction report.sourceMap"),
    outputMap: expectString(value.outputMap, "correction report.outputMap"),
    difficulty: expectString(value.difficulty, "correction report.difficulty"),
    seed: expectNumber(value.seed, "correction report.seed"),
    accepted: expectBoolean(value.accepted, "correction report.accepted"),
    before: validateBeforeAfterSummary(value.before, "correction report.before"),
    after: validateBeforeAfterSummary(value.after, "correction report.after"),
    scoreChanges: validateScoreChanges(value.scoreChanges),
    summary: validateCorrectionSummary(value.summary),
    actions: expectArray(value.actions, "correction report.actions").map(
      validateCorrectionAction,
    ),
    rejectionReason: expectOptionalString(
      value.rejectionReason,
      "correction report.rejectionReason",
    ),
  };
}

function validateBeforeAfterSummary(
  rawValue: unknown,
  label: string,
): BeforeAfterSummary {
  const value = expectRecord(rawValue, label);

  return {
    overallScore: expectNumber(value.overallScore, `${label}.overallScore`),
    playable: expectBoolean(value.playable, `${label}.playable`),
    critical: expectNumber(value.critical, `${label}.critical`),
    errors: expectNumber(value.errors, `${label}.errors`),
    warnings: expectNumber(value.warnings, `${label}.warnings`),
  };
}

function validateScoreChanges(rawValue: unknown): ScoreChanges {
  const value = expectRecord(rawValue, "correction report.scoreChanges");

  return {
    overall: expectNumber(value.overall, "correction report.scoreChanges.overall"),
    structural: expectNumber(
      value.structural,
      "correction report.scoreChanges.structural",
    ),
    timing: expectNumber(value.timing, "correction report.scoreChanges.timing"),
    rhythm: expectNumber(value.rhythm, "correction report.scoreChanges.rhythm"),
    movement: expectNumber(
      value.movement,
      "correction report.scoreChanges.movement",
    ),
    readability: expectNumber(
      value.readability,
      "correction report.scoreChanges.readability",
    ),
    spatialBalance: expectNumber(
      value.spatialBalance,
      "correction report.scoreChanges.spatialBalance",
    ),
    repetition: expectNumber(
      value.repetition,
      "correction report.scoreChanges.repetition",
    ),
    densityConsistency: expectNumber(
      value.densityConsistency,
      "correction report.scoreChanges.densityConsistency",
    ),
    difficultyConsistency: expectNumber(
      value.difficultyConsistency,
      "correction report.scoreChanges.difficultyConsistency",
    ),
  };
}

function validateCorrectionSummary(rawValue: unknown): CorrectionSummary {
  const value = expectRecord(rawValue, "correction report.summary");

  return {
    plannedActions: expectNumber(
      value.plannedActions,
      "correction report.summary.plannedActions",
    ),
    acceptedActions: expectNumber(
      value.acceptedActions,
      "correction report.summary.acceptedActions",
    ),
    revertedActions: expectNumber(
      value.revertedActions,
      "correction report.summary.revertedActions",
    ),
    movedObjects: expectNumber(
      value.movedObjects,
      "correction report.summary.movedObjects",
    ),
    timingAdjustments: expectNumber(
      value.timingAdjustments,
      "correction report.summary.timingAdjustments",
    ),
    removedObjects: expectNumber(
      value.removedObjects,
      "correction report.summary.removedObjects",
    ),
    insertedObjects: expectNumber(
      value.insertedObjects,
      "correction report.summary.insertedObjects",
    ),
  };
}

function validateCorrectionAction(rawValue: unknown, index: number): CorrectionAction {
  const value = expectRecord(rawValue, `correction report.actions[${index}]`);
  const actionType = expectString(
    value.actionType,
    `correction report.actions[${index}].actionType`,
  );
  const stage = expectString(
    value.stage,
    `correction report.actions[${index}].stage`,
  );

  if (!VALID_ACTION_TYPES.has(actionType as CorrectionActionType)) {
    throw new Error(
      `correction report.actions[${index}].actionType is not supported.`,
    );
  }

  if (!VALID_STAGES.has(stage as ProcessingStage)) {
    throw new Error(`correction report.actions[${index}].stage is not supported.`);
  }

  const expectedCategories = expectArray(
    value.expectedCategories,
    `correction report.actions[${index}].expectedCategories`,
  ).map((item, categoryIndex) => {
    const category = expectString(
      item,
      `correction report.actions[${index}].expectedCategories[${categoryIndex}]`,
    );

    if (!VALID_CATEGORIES.has(category as ValidationIssueCategory)) {
      throw new Error(
        `correction report.actions[${index}].expectedCategories[${categoryIndex}] is not supported.`,
      );
    }

    return category as ValidationIssueCategory;
  });

  return {
    actionId: expectString(
      value.actionId,
      `correction report.actions[${index}].actionId`,
    ),
    stage: stage as ProcessingStage,
    actionType: actionType as CorrectionActionType,
    reasonCode: expectString(
      value.reasonCode,
      `correction report.actions[${index}].reasonCode`,
    ),
    objectIds: expectNumberArray(
      value.objectIds,
      `correction report.actions[${index}].objectIds`,
    ),
    before: expectPrimitiveRecord(
      value.before,
      `correction report.actions[${index}].before`,
    ),
    after: expectPrimitiveRecord(
      value.after,
      `correction report.actions[${index}].after`,
    ),
    confidence: expectNumber(
      value.confidence,
      `correction report.actions[${index}].confidence`,
    ),
    expectedCategories,
    expectedScoreImpact: expectNumber(
      value.expectedScoreImpact,
      `correction report.actions[${index}].expectedScoreImpact`,
    ),
    actualScoreImpact: expectNumber(
      value.actualScoreImpact,
      `correction report.actions[${index}].actualScoreImpact`,
    ),
    accepted: expectBoolean(
      value.accepted,
      `correction report.actions[${index}].accepted`,
    ),
    rejectionReason: expectOptionalString(
      value.rejectionReason,
      `correction report.actions[${index}].rejectionReason`,
    ),
  };
}

function expectRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object.`);
  }

  return value;
}

function expectPrimitiveRecord(
  value: unknown,
  label: string,
): Record<string, string | number | boolean | null> {
  const record = expectRecord(value, label);
  const output: Record<string, string | number | boolean | null> = {};

  for (const [key, item] of Object.entries(record)) {
    if (
      item === null ||
      typeof item === "string" ||
      typeof item === "number" ||
      typeof item === "boolean"
    ) {
      output[key] = item;
      continue;
    }

    throw new Error(`${label}.${key} must be a primitive value or null.`);
  }

  return output;
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

function expectOptionalString(
  value: unknown,
  label: string,
): string | undefined {
  if (value === undefined) {
    return undefined;
  }

  return expectString(value, label);
}

function expectNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number.`);
  }

  return value;
}

function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }

  return value;
}

function expectNumberArray(value: unknown, label: string): number[] {
  return expectArray(value, label).map((item, index) =>
    expectNumber(item, `${label}[${index}]`),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export type { CorrectionReportLoadResult };
