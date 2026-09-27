import { isJsonObject } from "./JsonTypes";

export interface DifficultyReportMapInfo {
  path: string;
  title: string;
  artist: string;
  difficulty: string;
  objectCount: number;
  durationMs: number;
  approachTimeMs: number;
  circleRadius: number;
}

export interface DifficultyReportTarget {
  name: string;
  starRange: { min: number; max: number };
  starCenter: number;
  densityTarget: number;
  jumpTarget: number;
  speedTarget: number;
  readingTarget: number;
  tolerance: number;
}

export interface RawMetricsSummary {
  objectCount: number;
  circleCount: number;
  sliderCount: number;
  spinnerCount: number;
  activeDurationMs: number;
  objectsPerSecond: number;
  circleDensity: number;
  sliderDensity: number;
  spinnerFrequencyPerMinute: number;
  averageGapMs: number;
  minimumGapMs: number;
  maximumGapMs: number;
  gapStandardDeviationMs: number;
  averageJumpDistance: number;
  maximumJumpDistance: number;
  jumpDistanceStandardDeviation: number;
  averageCursorVelocityPps: number;
  maximumCursorVelocityPps: number;
  averageCursorAccelerationPps2: number;
  angleComplexity: number;
  directionChangeCount: number;
  longestStreamLength: number;
  longestBurstLength: number;
  averageSliderLengthMs: number;
  averageSliderVelocityPps: number;
  averageSliderRepeats: number;
  sliderComplexity: number;
  averageReactionTimeMs: number;
  minimumReactionTimeMs: number;
  recoveryWindowCount: number;
  patternVariation: number;
  staminaDemand: number;
  rhythmComplexity: number;
}

export interface ReadingMetricsSummary {
  spacingComplexity: number;
  stackingCount: number;
  overlapCount: number;
  visualClutter: number;
  approachTimingRatio: number;
  directionAmbiguity: number;
  patternRecognitionDemand: number;
  score: number;
}

export interface RhythmMetricsSummary {
  syncopationRatio: number;
  subdivisionVariety: number;
  rhythmSwitchCount: number;
  timingConsistency: number;
  tempoChangeCount: number;
  offbeatRatio: number;
  tripletCount: number;
  burstCount: number;
  score: number;
}

export interface AimMetricsSummary {
  distanceDemand: number;
  speedDemand: number;
  precisionDemand: number;
  angleDemand: number;
  sharpTurnCount: number;
  flowQuality: number;
  microAdjustmentCount: number;
  largeJumpCount: number;
  score: number;
}

export interface StaminaMetricsSummary {
  continuousActivityMs: number;
  highDensityDurationMs: number;
  streamDurationMs: number;
  restFrequency: number;
  sliderWorkload: number;
  score: number;
}

export interface PatternDifficultySummary {
  pattern: string;
  startMs: number;
  endMs: number;
  objectCount: number;
  score: number;
}

export interface DifficultyCurvePointSummary {
  timeMs: number;
  difficultyScore: number;
  density: number;
  speed: number;
  flow: number;
  reading: number;
  rhythm: number;
}

export interface SectionDifficultySummary {
  sectionId: number | null;
  label: string;
  startMs: number;
  endMs: number;
  difficultyScore: number;
  density: number;
  speed: number;
  reading: number;
  rhythm: number;
}

export interface ObjectDifficultySummary {
  objectId: number;
  objectType: string;
  timeMs: number;
  score: number;
  contribution: number;
}

export interface StarRatingSummary {
  overall: number;
  aim: number;
  speed: number;
  reading: number;
  rhythm: number;
  stamina: number;
  technical: number;
  breakdown: Record<string, unknown>;
}

export interface GameplayAnalyticsSummary {
  estimatedMissProbability: number;
  estimatedComboStability: number;
  estimatedPlayerStress: number;
  recoveryWindowCount: number;
  averageRecoveryWindowMs: number;
  hardestPassageMs: number;
  simulatedPlaycount: number;
}

export interface DifficultyVerificationIssue {
  code: string;
  severity: string;
  message: string;
  measuredValue?: number;
  allowedValue?: number;
}

export interface DifficultyDiagnosticsSummary {
  difficultyHistogram: Record<string, number>;
  objectContribution: ObjectDifficultySummary[];
  hardestPatterns: PatternDifficultySummary[];
  hardestSection: SectionDifficultySummary | null;
  difficultyVariance: number;
  starCalculationSummary: Record<string, unknown>;
}

export interface DifficultyReport {
  version: number;
  map: DifficultyReportMapInfo;
  target: DifficultyReportTarget;
  metrics: RawMetricsSummary;
  reading: ReadingMetricsSummary;
  rhythm: RhythmMetricsSummary;
  aim: AimMetricsSummary;
  stamina: StaminaMetricsSummary;
  patterns: PatternDifficultySummary[];
  sections: SectionDifficultySummary[];
  heatmap: Array<{ startMs: number; endMs: number; difficultyScore: number }>;
  curve: DifficultyCurvePointSummary[];
  objectDifficulty: ObjectDifficultySummary[];
  starRating: StarRatingSummary;
  gameplay: GameplayAnalyticsSummary;
  verification: DifficultyVerificationIssue[];
  diagnostics: DifficultyDiagnosticsSummary;
  recommendedPlayerLevel: string;
  consistencyScore: number;
  peakDifficulty: number;
  averageDifficulty: number;
  confidenceScore: number;
  signature: string;
}

export function parseDifficultyReport(rawData: unknown): DifficultyReport {
  const root = expectRecord(rawData, "difficulty report");
  const map = expectRecord(root.map, "difficulty report map");
  const target = expectRecord(root.target, "difficulty report target");
  const starRange = expectRecord(target.starRange, "difficulty report target.starRange");
  const metrics = expectRecord(root.metrics, "difficulty report metrics");
  const reading = expectRecord(root.reading, "difficulty report reading");
  const rhythm = expectRecord(root.rhythm, "difficulty report rhythm");
  const aim = expectRecord(root.aim, "difficulty report aim");
  const stamina = expectRecord(root.stamina, "difficulty report stamina");
  const starRating = expectRecord(root.starRating, "difficulty report starRating");
  const gameplay = expectRecord(root.gameplay, "difficulty report gameplay");
  const diagnostics = expectRecord(root.diagnostics, "difficulty report diagnostics");

  return {
    version: expectNumber(root.version, "difficulty report version"),
    map: {
      path: expectString(map.path, "difficulty report map.path"),
      title: expectString(map.title, "difficulty report map.title"),
      artist: expectString(map.artist, "difficulty report map.artist"),
      difficulty: expectString(map.difficulty, "difficulty report map.difficulty"),
      objectCount: expectNumber(map.objectCount, "difficulty report map.objectCount"),
      durationMs: expectNumber(map.durationMs, "difficulty report map.durationMs"),
      approachTimeMs: expectNumber(
        map.approachTimeMs,
        "difficulty report map.approachTimeMs",
      ),
      circleRadius: expectNumber(
        map.circleRadius,
        "difficulty report map.circleRadius",
      ),
    },
    target: {
      name: expectString(target.name, "difficulty report target.name"),
      starRange: {
        min: expectNumber(starRange.min, "difficulty report target.starRange.min"),
        max: expectNumber(starRange.max, "difficulty report target.starRange.max"),
      },
      starCenter: expectNumber(
        target.starCenter,
        "difficulty report target.starCenter",
      ),
      densityTarget: expectNumber(
        target.densityTarget,
        "difficulty report target.densityTarget",
      ),
      jumpTarget: expectNumber(target.jumpTarget, "difficulty report target.jumpTarget"),
      speedTarget: expectNumber(target.speedTarget, "difficulty report target.speedTarget"),
      readingTarget: expectNumber(
        target.readingTarget,
        "difficulty report target.readingTarget",
      ),
      tolerance: expectNumber(target.tolerance, "difficulty report target.tolerance"),
    },
    metrics: {
      objectCount: expectNumber(metrics.objectCount, "difficulty report metrics.objectCount"),
      circleCount: expectNumber(metrics.circleCount, "difficulty report metrics.circleCount"),
      sliderCount: expectNumber(metrics.sliderCount, "difficulty report metrics.sliderCount"),
      spinnerCount: expectNumber(
        metrics.spinnerCount,
        "difficulty report metrics.spinnerCount",
      ),
      activeDurationMs: expectNumber(
        metrics.activeDurationMs,
        "difficulty report metrics.activeDurationMs",
      ),
      objectsPerSecond: expectNumber(
        metrics.objectsPerSecond,
        "difficulty report metrics.objectsPerSecond",
      ),
      circleDensity: expectNumber(
        metrics.circleDensity,
        "difficulty report metrics.circleDensity",
      ),
      sliderDensity: expectNumber(
        metrics.sliderDensity,
        "difficulty report metrics.sliderDensity",
      ),
      spinnerFrequencyPerMinute: expectNumber(
        metrics.spinnerFrequencyPerMinute,
        "difficulty report metrics.spinnerFrequencyPerMinute",
      ),
      averageGapMs: expectNumber(metrics.averageGapMs, "difficulty report metrics.averageGapMs"),
      minimumGapMs: expectNumber(metrics.minimumGapMs, "difficulty report metrics.minimumGapMs"),
      maximumGapMs: expectNumber(metrics.maximumGapMs, "difficulty report metrics.maximumGapMs"),
      gapStandardDeviationMs: expectNumber(
        metrics.gapStandardDeviationMs,
        "difficulty report metrics.gapStandardDeviationMs",
      ),
      averageJumpDistance: expectNumber(
        metrics.averageJumpDistance,
        "difficulty report metrics.averageJumpDistance",
      ),
      maximumJumpDistance: expectNumber(
        metrics.maximumJumpDistance,
        "difficulty report metrics.maximumJumpDistance",
      ),
      jumpDistanceStandardDeviation: expectNumber(
        metrics.jumpDistanceStandardDeviation,
        "difficulty report metrics.jumpDistanceStandardDeviation",
      ),
      averageCursorVelocityPps: expectNumber(
        metrics.averageCursorVelocityPps,
        "difficulty report metrics.averageCursorVelocityPps",
      ),
      maximumCursorVelocityPps: expectNumber(
        metrics.maximumCursorVelocityPps,
        "difficulty report metrics.maximumCursorVelocityPps",
      ),
      averageCursorAccelerationPps2: expectNumber(
        metrics.averageCursorAccelerationPps2,
        "difficulty report metrics.averageCursorAccelerationPps2",
      ),
      angleComplexity: expectNumber(
        metrics.angleComplexity,
        "difficulty report metrics.angleComplexity",
      ),
      directionChangeCount: expectNumber(
        metrics.directionChangeCount,
        "difficulty report metrics.directionChangeCount",
      ),
      longestStreamLength: expectNumber(
        metrics.longestStreamLength,
        "difficulty report metrics.longestStreamLength",
      ),
      longestBurstLength: expectNumber(
        metrics.longestBurstLength,
        "difficulty report metrics.longestBurstLength",
      ),
      averageSliderLengthMs: expectNumber(
        metrics.averageSliderLengthMs,
        "difficulty report metrics.averageSliderLengthMs",
      ),
      averageSliderVelocityPps: expectNumber(
        metrics.averageSliderVelocityPps,
        "difficulty report metrics.averageSliderVelocityPps",
      ),
      averageSliderRepeats: expectNumber(
        metrics.averageSliderRepeats,
        "difficulty report metrics.averageSliderRepeats",
      ),
      sliderComplexity: expectNumber(
        metrics.sliderComplexity,
        "difficulty report metrics.sliderComplexity",
      ),
      averageReactionTimeMs: expectNumber(
        metrics.averageReactionTimeMs,
        "difficulty report metrics.averageReactionTimeMs",
      ),
      minimumReactionTimeMs: expectNumber(
        metrics.minimumReactionTimeMs,
        "difficulty report metrics.minimumReactionTimeMs",
      ),
      recoveryWindowCount: expectNumber(
        metrics.recoveryWindowCount,
        "difficulty report metrics.recoveryWindowCount",
      ),
      patternVariation: expectNumber(
        metrics.patternVariation,
        "difficulty report metrics.patternVariation",
      ),
      staminaDemand: expectNumber(
        metrics.staminaDemand,
        "difficulty report metrics.staminaDemand",
      ),
      rhythmComplexity: expectNumber(
        metrics.rhythmComplexity,
        "difficulty report metrics.rhythmComplexity",
      ),
    },
    reading: {
      spacingComplexity: expectNumber(
        reading.spacingComplexity,
        "difficulty report reading.spacingComplexity",
      ),
      stackingCount: expectNumber(
        reading.stackingCount,
        "difficulty report reading.stackingCount",
      ),
      overlapCount: expectNumber(
        reading.overlapCount,
        "difficulty report reading.overlapCount",
      ),
      visualClutter: expectNumber(
        reading.visualClutter,
        "difficulty report reading.visualClutter",
      ),
      approachTimingRatio: expectNumber(
        reading.approachTimingRatio,
        "difficulty report reading.approachTimingRatio",
      ),
      directionAmbiguity: expectNumber(
        reading.directionAmbiguity,
        "difficulty report reading.directionAmbiguity",
      ),
      patternRecognitionDemand: expectNumber(
        reading.patternRecognitionDemand,
        "difficulty report reading.patternRecognitionDemand",
      ),
      score: expectNumber(reading.score, "difficulty report reading.score"),
    },
    rhythm: {
      syncopationRatio: expectNumber(
        rhythm.syncopationRatio,
        "difficulty report rhythm.syncopationRatio",
      ),
      subdivisionVariety: expectNumber(
        rhythm.subdivisionVariety,
        "difficulty report rhythm.subdivisionVariety",
      ),
      rhythmSwitchCount: expectNumber(
        rhythm.rhythmSwitchCount,
        "difficulty report rhythm.rhythmSwitchCount",
      ),
      timingConsistency: expectNumber(
        rhythm.timingConsistency,
        "difficulty report rhythm.timingConsistency",
      ),
      tempoChangeCount: expectNumber(
        rhythm.tempoChangeCount,
        "difficulty report rhythm.tempoChangeCount",
      ),
      offbeatRatio: expectNumber(
        rhythm.offbeatRatio,
        "difficulty report rhythm.offbeatRatio",
      ),
      tripletCount: expectNumber(
        rhythm.tripletCount,
        "difficulty report rhythm.tripletCount",
      ),
      burstCount: expectNumber(rhythm.burstCount, "difficulty report rhythm.burstCount"),
      score: expectNumber(rhythm.score, "difficulty report rhythm.score"),
    },
    aim: {
      distanceDemand: expectNumber(
        aim.distanceDemand,
        "difficulty report aim.distanceDemand",
      ),
      speedDemand: expectNumber(aim.speedDemand, "difficulty report aim.speedDemand"),
      precisionDemand: expectNumber(
        aim.precisionDemand,
        "difficulty report aim.precisionDemand",
      ),
      angleDemand: expectNumber(aim.angleDemand, "difficulty report aim.angleDemand"),
      sharpTurnCount: expectNumber(
        aim.sharpTurnCount,
        "difficulty report aim.sharpTurnCount",
      ),
      flowQuality: expectNumber(aim.flowQuality, "difficulty report aim.flowQuality"),
      microAdjustmentCount: expectNumber(
        aim.microAdjustmentCount,
        "difficulty report aim.microAdjustmentCount",
      ),
      largeJumpCount: expectNumber(
        aim.largeJumpCount,
        "difficulty report aim.largeJumpCount",
      ),
      score: expectNumber(aim.score, "difficulty report aim.score"),
    },
    stamina: {
      continuousActivityMs: expectNumber(
        stamina.continuousActivityMs,
        "difficulty report stamina.continuousActivityMs",
      ),
      highDensityDurationMs: expectNumber(
        stamina.highDensityDurationMs,
        "difficulty report stamina.highDensityDurationMs",
      ),
      streamDurationMs: expectNumber(
        stamina.streamDurationMs,
        "difficulty report stamina.streamDurationMs",
      ),
      restFrequency: expectNumber(
        stamina.restFrequency,
        "difficulty report stamina.restFrequency",
      ),
      sliderWorkload: expectNumber(
        stamina.sliderWorkload,
        "difficulty report stamina.sliderWorkload",
      ),
      score: expectNumber(stamina.score, "difficulty report stamina.score"),
    },
    patterns: expectArray(root.patterns, "difficulty report patterns").map((item, index) =>
      validatePattern(item, index),
    ),
    sections: expectArray(root.sections, "difficulty report sections").map((item, index) =>
      validateSection(item, index),
    ),
    heatmap: expectArray(root.heatmap, "difficulty report heatmap").map((item, index) => {
      const value = expectRecord(item, `difficulty report heatmap[${index}]`);
      return {
        startMs: expectNumber(value.startMs, `difficulty report heatmap[${index}].startMs`),
        endMs: expectNumber(value.endMs, `difficulty report heatmap[${index}].endMs`),
        difficultyScore: expectNumber(
          value.difficultyScore,
          `difficulty report heatmap[${index}].difficultyScore`,
        ),
      };
    }),
    curve: expectArray(root.curve, "difficulty report curve").map((item, index) => {
      const value = expectRecord(item, `difficulty report curve[${index}]`);
      return {
        timeMs: expectNumber(value.timeMs, `difficulty report curve[${index}].timeMs`),
        difficultyScore: expectNumber(
          value.difficultyScore,
          `difficulty report curve[${index}].difficultyScore`,
        ),
        density: expectNumber(value.density, `difficulty report curve[${index}].density`),
        speed: expectNumber(value.speed, `difficulty report curve[${index}].speed`),
        flow: expectNumber(value.flow, `difficulty report curve[${index}].flow`),
        reading: expectNumber(value.reading, `difficulty report curve[${index}].reading`),
        rhythm: expectNumber(value.rhythm, `difficulty report curve[${index}].rhythm`),
      };
    }),
    objectDifficulty: expectArray(
      root.objectDifficulty,
      "difficulty report objectDifficulty",
    ).map((item, index) => validateObjectDifficulty(item, index)),
    starRating: {
      overall: expectNumber(starRating.overall, "difficulty report starRating.overall"),
      aim: expectNumber(starRating.aim, "difficulty report starRating.aim"),
      speed: expectNumber(starRating.speed, "difficulty report starRating.speed"),
      reading: expectNumber(starRating.reading, "difficulty report starRating.reading"),
      rhythm: expectNumber(starRating.rhythm, "difficulty report starRating.rhythm"),
      stamina: expectNumber(starRating.stamina, "difficulty report starRating.stamina"),
      technical: expectNumber(
        starRating.technical,
        "difficulty report starRating.technical",
      ),
      breakdown: expectLooseRecord(
        starRating.breakdown,
        "difficulty report starRating.breakdown",
      ),
    },
    gameplay: {
      estimatedMissProbability: expectNumber(
        gameplay.estimatedMissProbability,
        "difficulty report gameplay.estimatedMissProbability",
      ),
      estimatedComboStability: expectNumber(
        gameplay.estimatedComboStability,
        "difficulty report gameplay.estimatedComboStability",
      ),
      estimatedPlayerStress: expectNumber(
        gameplay.estimatedPlayerStress,
        "difficulty report gameplay.estimatedPlayerStress",
      ),
      recoveryWindowCount: expectNumber(
        gameplay.recoveryWindowCount,
        "difficulty report gameplay.recoveryWindowCount",
      ),
      averageRecoveryWindowMs: expectNumber(
        gameplay.averageRecoveryWindowMs,
        "difficulty report gameplay.averageRecoveryWindowMs",
      ),
      hardestPassageMs: expectNumber(
        gameplay.hardestPassageMs,
        "difficulty report gameplay.hardestPassageMs",
      ),
      simulatedPlaycount: expectNumber(
        gameplay.simulatedPlaycount,
        "difficulty report gameplay.simulatedPlaycount",
      ),
    },
    verification: expectArray(
      root.verification,
      "difficulty report verification",
    ).map((item, index) => {
      const value = expectRecord(item, `difficulty report verification[${index}]`);
      return {
        code: expectString(value.code, `difficulty report verification[${index}].code`),
        severity: expectString(
          value.severity,
          `difficulty report verification[${index}].severity`,
        ),
        message: expectString(
          value.message,
          `difficulty report verification[${index}].message`,
        ),
        measuredValue: expectOptionalNumber(
          value.measuredValue,
          `difficulty report verification[${index}].measuredValue`,
        ),
        allowedValue: expectOptionalNumber(
          value.allowedValue,
          `difficulty report verification[${index}].allowedValue`,
        ),
      };
    }),
    diagnostics: {
      difficultyHistogram: expectNumberRecord(
        diagnostics.difficultyHistogram,
        "difficulty report diagnostics.difficultyHistogram",
      ),
      objectContribution: expectArray(
        diagnostics.objectContribution,
        "difficulty report diagnostics.objectContribution",
      ).map((item, index) => validateObjectDifficulty(item, index)),
      hardestPatterns: expectArray(
        diagnostics.hardestPatterns,
        "difficulty report diagnostics.hardestPatterns",
      ).map((item, index) => validatePattern(item, index)),
      hardestSection:
        diagnostics.hardestSection === null || diagnostics.hardestSection === undefined
          ? null
          : validateSection(diagnostics.hardestSection, "diagnostics.hardestSection"),
      difficultyVariance: expectNumber(
        diagnostics.difficultyVariance,
        "difficulty report diagnostics.difficultyVariance",
      ),
      starCalculationSummary: expectLooseRecord(
        diagnostics.starCalculationSummary,
        "difficulty report diagnostics.starCalculationSummary",
      ),
    },
    recommendedPlayerLevel: expectString(
      root.recommendedPlayerLevel,
      "difficulty report recommendedPlayerLevel",
    ),
    consistencyScore: expectNumber(
      root.consistencyScore,
      "difficulty report consistencyScore",
    ),
    peakDifficulty: expectNumber(root.peakDifficulty, "difficulty report peakDifficulty"),
    averageDifficulty: expectNumber(
      root.averageDifficulty,
      "difficulty report averageDifficulty",
    ),
    confidenceScore: expectNumber(
      root.confidenceScore,
      "difficulty report confidenceScore",
    ),
    signature: expectString(root.signature, "difficulty report signature"),
  };
}

function validatePattern(rawValue: unknown, index: number | string): PatternDifficultySummary {
  const value = expectRecord(rawValue, `difficulty report patterns[${index}]`);
  return {
    pattern: expectString(value.pattern, `difficulty report patterns[${index}].pattern`),
    startMs: expectNumber(value.startMs, `difficulty report patterns[${index}].startMs`),
    endMs: expectNumber(value.endMs, `difficulty report patterns[${index}].endMs`),
    objectCount: expectNumber(
      value.objectCount,
      `difficulty report patterns[${index}].objectCount`,
    ),
    score: expectNumber(value.score, `difficulty report patterns[${index}].score`),
  };
}

function validateSection(rawValue: unknown, index: number | string): SectionDifficultySummary {
  const value = expectRecord(rawValue, `difficulty report sections[${index}]`);
  return {
    sectionId: expectNullableNumber(
      value.sectionId,
      `difficulty report sections[${index}].sectionId`,
    ),
    label: expectString(value.label, `difficulty report sections[${index}].label`),
    startMs: expectNumber(value.startMs, `difficulty report sections[${index}].startMs`),
    endMs: expectNumber(value.endMs, `difficulty report sections[${index}].endMs`),
    difficultyScore: expectNumber(
      value.difficultyScore,
      `difficulty report sections[${index}].difficultyScore`,
    ),
    density: expectNumber(value.density, `difficulty report sections[${index}].density`),
    speed: expectNumber(value.speed, `difficulty report sections[${index}].speed`),
    reading: expectNumber(value.reading, `difficulty report sections[${index}].reading`),
    rhythm: expectNumber(value.rhythm, `difficulty report sections[${index}].rhythm`),
  };
}

function validateObjectDifficulty(
  rawValue: unknown,
  index: number | string,
): ObjectDifficultySummary {
  const value = expectRecord(rawValue, `difficulty report objectDifficulty[${index}]`);
  return {
    objectId: expectNumber(value.objectId, `difficulty report objectDifficulty[${index}].objectId`),
    objectType: expectString(
      value.objectType,
      `difficulty report objectDifficulty[${index}].objectType`,
    ),
    timeMs: expectNumber(value.timeMs, `difficulty report objectDifficulty[${index}].timeMs`),
    score: expectNumber(value.score, `difficulty report objectDifficulty[${index}].score`),
    contribution: expectNumber(
      value.contribution,
      `difficulty report objectDifficulty[${index}].contribution`,
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

function expectLooseRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (value === undefined) {
    return {};
  }
  return expectRecord(value, label);
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

function expectOptionalNumber(
  value: unknown,
  label: string,
): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  return expectNumber(value, label);
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
