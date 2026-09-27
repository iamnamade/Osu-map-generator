import type {
  DensityMetricsSummary,
  DensityWindowSummary,
  DifficultyMetricsSummary,
  ReportSummary,
  RepetitionMetricsSummary,
  RhythmMetricsSummary,
  ScoreCategories,
  SpatialMetricsSummary,
  StructuralMetricsSummary,
  TimingMetricsSummary,
  ValidationIssue,
  ValidationIssueCategory,
  ValidationReport,
  ValidationReportMapInfo,
  ValidationReportMetrics,
  ValidationSeverity,
} from "./types";

type ValidationReportLoadResult =
  | { status: "ok"; report: ValidationReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

const VALID_SEVERITIES = new Set<ValidationSeverity>([
  "info",
  "warning",
  "error",
  "critical",
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
const VALID_BEHAVIORS = new Set([
  "easier-than-target",
  "within-target",
  "harder-than-target",
  "inconsistent",
]);

export async function loadValidationReport(
  url: string,
): Promise<ValidationReportLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Quality report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Quality report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Quality report has not been generated yet.",
    };
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Quality report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: validateValidationReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Quality report at ${url} is malformed: ${error.message}`
          : `Quality report at ${url} is malformed.`,
    };
  }
}

function validateValidationReport(rawData: unknown): ValidationReport {
  if (!isRecord(rawData)) {
    throw new Error("report root must be an object.");
  }

  return {
    version: expectNumber(rawData.version, "report version"),
    map: validateMapInfo(rawData.map),
    valid: expectBoolean(rawData.valid, "report valid"),
    playable: expectBoolean(rawData.playable, "report playable"),
    scores: validateScores(rawData.scores),
    interpretation: expectString(rawData.interpretation, "report interpretation"),
    summary: validateSummary(rawData.summary),
    metrics: validateMetrics(rawData.metrics),
    issues: validateIssues(rawData.issues),
  };
}

function validateMapInfo(rawValue: unknown): ValidationReportMapInfo {
  const value = expectRecord(rawValue, "report map");

  return {
    path: expectString(value.path, "report map.path"),
    title: expectString(value.title, "report map.title"),
    artist: expectString(value.artist, "report map.artist"),
    difficulty: expectString(value.difficulty, "report map.difficulty"),
    objectCount: expectNumber(value.objectCount, "report map.objectCount"),
    durationMs: expectNumber(value.durationMs, "report map.durationMs"),
  };
}

function validateScores(rawValue: unknown): ScoreCategories {
  const value = expectRecord(rawValue, "report scores");

  return {
    structural: expectNumber(value.structural, "report scores.structural"),
    timing: expectNumber(value.timing, "report scores.timing"),
    rhythm: expectNumber(value.rhythm, "report scores.rhythm"),
    movement: expectNumber(value.movement, "report scores.movement"),
    readability: expectNumber(value.readability, "report scores.readability"),
    spatialBalance: expectNumber(
      value.spatialBalance,
      "report scores.spatialBalance",
    ),
    repetition: expectNumber(value.repetition, "report scores.repetition"),
    densityConsistency: expectNumber(
      value.densityConsistency,
      "report scores.densityConsistency",
    ),
    difficultyConsistency: expectNumber(
      value.difficultyConsistency,
      "report scores.difficultyConsistency",
    ),
    overall: expectNumber(value.overall, "report scores.overall"),
  };
}

function validateSummary(rawValue: unknown): ReportSummary {
  const value = expectRecord(rawValue, "report summary");

  return {
    critical: expectNumber(value.critical, "report summary.critical"),
    errors: expectNumber(value.errors, "report summary.errors"),
    warnings: expectNumber(value.warnings, "report summary.warnings"),
    info: expectNumber(value.info, "report summary.info"),
  };
}

function validateMetrics(rawValue: unknown): ValidationReportMetrics {
  const value = expectRecord(rawValue, "report metrics");

  return {
    structural: validateStructuralMetrics(value.structural),
    timing: validateTimingMetrics(value.timing),
    rhythm: validateRhythmMetrics(value.rhythm),
    movement: validateMovementMetrics(value.movement),
    spatial: validateSpatialMetrics(value.spatial),
    density: validateDensityMetrics(value.density),
    repetition: validateRepetitionMetrics(value.repetition),
    difficulty: validateDifficultyMetrics(value.difficulty),
  };
}

function validateStructuralMetrics(rawValue: unknown): StructuralMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.structural");

  return {
    objectCount: expectNumber(value.objectCount, "report metrics.structural.objectCount"),
    validObjectCount: expectNumber(
      value.validObjectCount,
      "report metrics.structural.validObjectCount",
    ),
    duplicateIdCount: expectNumber(
      value.duplicateIdCount,
      "report metrics.structural.duplicateIdCount",
    ),
    duplicateTimestampCount: expectNumber(
      value.duplicateTimestampCount,
      "report metrics.structural.duplicateTimestampCount",
    ),
    nonFiniteValueCount: expectNumber(
      value.nonFiniteValueCount,
      "report metrics.structural.nonFiniteValueCount",
    ),
  };
}

function validateTimingMetrics(rawValue: unknown): TimingMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.timing");
  const anchorUsage = expectRecord(value.anchorUsage, "report metrics.timing.anchorUsage");

  return {
    averageAnchorDeltaMs: expectNumber(
      value.averageAnchorDeltaMs,
      "report metrics.timing.averageAnchorDeltaMs",
    ),
    averageBeatDeltaMs: expectNumber(
      value.averageBeatDeltaMs,
      "report metrics.timing.averageBeatDeltaMs",
    ),
    averageOnsetDeltaMs: expectNumber(
      value.averageOnsetDeltaMs,
      "report metrics.timing.averageOnsetDeltaMs",
    ),
    excellentAlignmentCount: expectNumber(
      value.excellentAlignmentCount,
      "report metrics.timing.excellentAlignmentCount",
    ),
    goodAlignmentCount: expectNumber(
      value.goodAlignmentCount,
      "report metrics.timing.goodAlignmentCount",
    ),
    acceptableAlignmentCount: expectNumber(
      value.acceptableAlignmentCount,
      "report metrics.timing.acceptableAlignmentCount",
    ),
    weakAlignmentCount: expectNumber(
      value.weakAlignmentCount,
      "report metrics.timing.weakAlignmentCount",
    ),
    mistimedCount: expectNumber(
      value.mistimedCount,
      "report metrics.timing.mistimedCount",
    ),
    earlyBiasCount: expectNumber(
      value.earlyBiasCount,
      "report metrics.timing.earlyBiasCount",
    ),
    lateBiasCount: expectNumber(
      value.lateBiasCount,
      "report metrics.timing.lateBiasCount",
    ),
    anchorUsage: {
      beat: expectNumber(anchorUsage.beat, "report metrics.timing.anchorUsage.beat"),
      onset: expectNumber(
        anchorUsage.onset,
        "report metrics.timing.anchorUsage.onset",
      ),
      none: expectNumber(anchorUsage.none, "report metrics.timing.anchorUsage.none"),
    },
  };
}

function validateRhythmMetrics(rawValue: unknown): RhythmMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.rhythm");

  return {
    minGapMs: expectNumber(value.minGapMs, "report metrics.rhythm.minGapMs"),
    maxGapMs: expectNumber(value.maxGapMs, "report metrics.rhythm.maxGapMs"),
    averageGapMs: expectNumber(
      value.averageGapMs,
      "report metrics.rhythm.averageGapMs",
    ),
    medianGapMs: expectNumber(
      value.medianGapMs,
      "report metrics.rhythm.medianGapMs",
    ),
    gapStandardDeviationMs: expectNumber(
      value.gapStandardDeviationMs,
      "report metrics.rhythm.gapStandardDeviationMs",
    ),
    gapPercentilesMs: expectNumberRecord(
      value.gapPercentilesMs,
      "report metrics.rhythm.gapPercentilesMs",
    ),
    rapidSequenceCount: expectNumber(
      value.rapidSequenceCount,
      "report metrics.rhythm.rapidSequenceCount",
    ),
    longEmptySpaceCount: expectNumber(
      value.longEmptySpaceCount,
      "report metrics.rhythm.longEmptySpaceCount",
    ),
    repeatedEqualGapRuns: expectNumber(
      value.repeatedEqualGapRuns,
      "report metrics.rhythm.repeatedEqualGapRuns",
    ),
    commonRhythmIntervalsMs: expectNumberArray(
      value.commonRhythmIntervalsMs,
      "report metrics.rhythm.commonRhythmIntervalsMs",
    ),
  };
}

function validateMovementMetrics(rawValue: unknown) {
  const value = expectRecord(rawValue, "report metrics.movement");

  return {
    minJumpDistance: expectNumber(
      value.minJumpDistance,
      "report metrics.movement.minJumpDistance",
    ),
    maxJumpDistance: expectNumber(
      value.maxJumpDistance,
      "report metrics.movement.maxJumpDistance",
    ),
    averageJumpDistance: expectNumber(
      value.averageJumpDistance,
      "report metrics.movement.averageJumpDistance",
    ),
    highestCursorSpeed: expectNumber(
      value.highestCursorSpeed,
      "report metrics.movement.highestCursorSpeed",
    ),
    averageCursorSpeed: expectNumber(
      value.averageCursorSpeed,
      "report metrics.movement.averageCursorSpeed",
    ),
    speedViolationCount: expectNumber(
      value.speedViolationCount,
      "report metrics.movement.speedViolationCount",
    ),
    nearLimitRunCount: expectNumber(
      value.nearLimitRunCount,
      "report metrics.movement.nearLimitRunCount",
    ),
    exactStackingCount: expectNumber(
      value.exactStackingCount,
      "report metrics.movement.exactStackingCount",
    ),
    nearStackingCount: expectNumber(
      value.nearStackingCount,
      "report metrics.movement.nearStackingCount",
    ),
    overlapCount: expectNumber(
      value.overlapCount,
      "report metrics.movement.overlapCount",
    ),
    largeIsolatedJumpCount: expectNumber(
      value.largeIsolatedJumpCount,
      "report metrics.movement.largeIsolatedJumpCount",
    ),
  };
}

function validateSpatialMetrics(rawValue: unknown): SpatialMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.spatial");

  return {
    gridColumns: expectNumber(
      value.gridColumns,
      "report metrics.spatial.gridColumns",
    ),
    gridRows: expectNumber(value.gridRows, "report metrics.spatial.gridRows"),
    regionCounts: expectNumberRecord(
      value.regionCounts,
      "report metrics.spatial.regionCounts",
    ),
    playfieldCoveragePercent: expectNumber(
      value.playfieldCoveragePercent,
      "report metrics.spatial.playfieldCoveragePercent",
    ),
    centerUsagePercent: expectNumber(
      value.centerUsagePercent,
      "report metrics.spatial.centerUsagePercent",
    ),
    edgeUsagePercent: expectNumber(
      value.edgeUsagePercent,
      "report metrics.spatial.edgeUsagePercent",
    ),
    cornerUsagePercent: expectNumber(
      value.cornerUsagePercent,
      "report metrics.spatial.cornerUsagePercent",
    ),
    leftRightBalance: expectNumber(
      value.leftRightBalance,
      "report metrics.spatial.leftRightBalance",
    ),
    topBottomBalance: expectNumber(
      value.topBottomBalance,
      "report metrics.spatial.topBottomBalance",
    ),
    mostUsedRegion: expectString(
      value.mostUsedRegion,
      "report metrics.spatial.mostUsedRegion",
    ),
    leastUsedRegion: expectString(
      value.leastUsedRegion,
      "report metrics.spatial.leastUsedRegion",
    ),
  };
}

function validateDensityMetrics(rawValue: unknown): DensityMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.density");

  return {
    windows: expectArray(value.windows, "report metrics.density.windows").map(
      validateDensityWindow,
    ),
    highDensityLowEnergyWindows: expectNumber(
      value.highDensityLowEnergyWindows,
      "report metrics.density.highDensityLowEnergyWindows",
    ),
    lowDensityHighEnergyWindows: expectNumber(
      value.lowDensityHighEnergyWindows,
      "report metrics.density.lowDensityHighEnergyWindows",
    ),
    abruptDensitySpikes: expectNumber(
      value.abruptDensitySpikes,
      "report metrics.density.abruptDensitySpikes",
    ),
    flatDensityDespiteEnergyChange: expectNumber(
      value.flatDensityDespiteEnergyChange,
      "report metrics.density.flatDensityDespiteEnergyChange",
    ),
    endingGapMs: expectNumber(
      value.endingGapMs,
      "report metrics.density.endingGapMs",
    ),
  };
}

function validateDensityWindow(rawValue: unknown): DensityWindowSummary {
  const value = expectRecord(rawValue, "report metrics.density window");

  return {
    startMs: expectNumber(value.startMs, "report metrics.density window.startMs"),
    endMs: expectNumber(value.endMs, "report metrics.density window.endMs"),
    objectsPerSecond: expectNumber(
      value.objectsPerSecond,
      "report metrics.density window.objectsPerSecond",
    ),
    objectCount: expectNumber(
      value.objectCount,
      "report metrics.density window.objectCount",
    ),
    averageEventStrength: expectNumber(
      value.averageEventStrength,
      "report metrics.density window.averageEventStrength",
    ),
    averageAudioEnergy: expectNumber(
      value.averageAudioEnergy,
      "report metrics.density window.averageAudioEnergy",
    ),
    averageJumpDistance: expectNumber(
      value.averageJumpDistance,
      "report metrics.density window.averageJumpDistance",
    ),
    averageCursorSpeed: expectNumber(
      value.averageCursorSpeed,
      "report metrics.density window.averageCursorSpeed",
    ),
    timingConfidence: expectNumber(
      value.timingConfidence,
      "report metrics.density window.timingConfidence",
    ),
    issueCount: expectNumber(
      value.issueCount,
      "report metrics.density window.issueCount",
    ),
  };
}

function validateRepetitionMetrics(rawValue: unknown): RepetitionMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.repetition");

  return {
    repeatedCoordinatePairs: expectNumber(
      value.repeatedCoordinatePairs,
      "report metrics.repetition.repeatedCoordinatePairs",
    ),
    repeatedTwoPointLoops: expectNumber(
      value.repeatedTwoPointLoops,
      "report metrics.repetition.repeatedTwoPointLoops",
    ),
    repeatedThreeObjectShapes: expectNumber(
      value.repeatedThreeObjectShapes,
      "report metrics.repetition.repeatedThreeObjectShapes",
    ),
    repeatedDistancePatterns: expectNumber(
      value.repeatedDistancePatterns,
      "report metrics.repetition.repeatedDistancePatterns",
    ),
    repeatedAnglePatterns: expectNumber(
      value.repeatedAnglePatterns,
      "report metrics.repetition.repeatedAnglePatterns",
    ),
    repeatedGapSequences: expectNumber(
      value.repeatedGapSequences,
      "report metrics.repetition.repeatedGapSequences",
    ),
    longestRepetitionRun: expectNumber(
      value.longestRepetitionRun,
      "report metrics.repetition.longestRepetitionRun",
    ),
  };
}

function validateDifficultyMetrics(rawValue: unknown): DifficultyMetricsSummary {
  const value = expectRecord(rawValue, "report metrics.difficulty");
  const estimatedBehavior = expectString(
    value.estimatedBehavior,
    "report metrics.difficulty.estimatedBehavior",
  );

  if (!VALID_BEHAVIORS.has(estimatedBehavior)) {
    throw new Error(
      `report metrics.difficulty.estimatedBehavior must be a supported behavior label.`,
    );
  }

  return {
    estimatedBehavior: estimatedBehavior as DifficultyMetricsSummary["estimatedBehavior"],
    densityRatio: expectNumber(
      value.densityRatio,
      "report metrics.difficulty.densityRatio",
    ),
    jumpRatio: expectNumber(
      value.jumpRatio,
      "report metrics.difficulty.jumpRatio",
    ),
    speedRatio: expectNumber(
      value.speedRatio,
      "report metrics.difficulty.speedRatio",
    ),
    timingComplexityRatio: expectNumber(
      value.timingComplexityRatio,
      "report metrics.difficulty.timingComplexityRatio",
    ),
    spatialVariationRatio: expectNumber(
      value.spatialVariationRatio,
      "report metrics.difficulty.spatialVariationRatio",
    ),
  };
}

function validateIssues(rawValue: unknown): ValidationIssue[] {
  return expectArray(rawValue, "report issues").map((item, index) => {
    const value = expectRecord(item, `report issues[${index}]`);
    const severity = expectString(
      value.severity,
      `report issues[${index}].severity`,
    );
    const category = expectString(
      value.category,
      `report issues[${index}].category`,
    );

    if (!VALID_SEVERITIES.has(severity as ValidationSeverity)) {
      throw new Error(
        `report issues[${index}].severity must be one of info, warning, error, or critical.`,
      );
    }

    if (!VALID_CATEGORIES.has(category as ValidationIssueCategory)) {
      throw new Error(`report issues[${index}].category is not supported.`);
    }

    return {
      code: expectString(value.code, `report issues[${index}].code`),
      severity: severity as ValidationSeverity,
      message: expectString(value.message, `report issues[${index}].message`),
      category: category as ValidationIssueCategory,
      objectIds: expectNumberArray(
        value.objectIds,
        `report issues[${index}].objectIds`,
      ),
      startTimeMs: expectOptionalNumber(
        value.startTimeMs,
        `report issues[${index}].startTimeMs`,
      ),
      endTimeMs: expectOptionalNumber(
        value.endTimeMs,
        `report issues[${index}].endTimeMs`,
      ),
      measuredValue: expectOptionalNumber(
        value.measuredValue,
        `report issues[${index}].measuredValue`,
      ),
      allowedValue: expectOptionalNumber(
        value.allowedValue,
        `report issues[${index}].allowedValue`,
      ),
      suggestion: expectOptionalString(
        value.suggestion,
        `report issues[${index}].suggestion`,
      ),
    };
  });
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

function expectOptionalNumber(
  value: unknown,
  label: string,
): number | undefined {
  if (value === undefined) {
    return undefined;
  }

  return expectNumber(value, label);
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

function expectNumberRecord(
  value: unknown,
  label: string,
): Record<string, number> {
  const record = expectRecord(value, label);
  const output: Record<string, number> = {};

  for (const [key, item] of Object.entries(record)) {
    output[key] = expectNumber(item, `${label}.${key}`);
  }

  return output;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export type { ValidationReportLoadResult };
