import { isJsonObject } from "./JsonTypes";

export interface SectionBoundary {
  rawTimeMs: number;
  finalTimeMs: number;
  confidence: number;
  reason: string;
  supportingFeatureChanges: Record<string, number>;
  snapped: boolean;
  snappedTo?: string;
  snapDistanceMs?: number;
}

export interface SongSection {
  id: number;
  startMs: number;
  endMs: number;
  durationMs: number;
  label: string;
  confidence: number;
  averageEnergy: number;
  energyTrend: string;
  beatDensity: number;
  onsetDensity: number;
  rhythmComplexity: number;
  repetitionGroup: number | null;
  energyClass: string;
}

export interface SectionAnalysis {
  version: number;
  audio: {
    path: string;
    durationMs: number;
  };
  configuration: Record<string, unknown>;
  inputSignature: string;
  sections: SongSection[];
  boundaries: SectionBoundary[];
  summary: Record<string, unknown>;
}

export interface CandidateSectionIssue {
  code: string;
  severity: string;
  message: string;
  measuredValue?: number;
  allowedValue?: number;
}

export interface CandidateSectionState {
  objectId: number | null;
  timeMs: number | null;
  x: number | null;
  y: number | null;
  directionDeg: number | null;
  cursorSpeedPps: number | null;
  gapMs: number | null;
  density: number | null;
  region: string | null;
}

export interface CandidateSectionScores {
  structural: number;
  timing: number;
  rhythm: number;
  movement: number;
  readability: number;
  spatialBalance: number;
  repetition: number;
  densityConsistency: number;
  difficultyConsistency: number;
  transitionReadiness: number;
  overall: number;
}

export interface CandidateSectionMetrics {
  objectCount: number;
  objectsPerSecond: number;
  averageObjectGapMs: number;
  minimumObjectGapMs: number;
  maximumObjectGapMs: number;
  averageJumpDistance: number;
  maximumJumpDistance: number;
  averageCursorSpeed: number;
  maximumCursorSpeed: number;
  timingConfidence: number;
  beatAlignment: number;
  onsetAlignment: number;
  spatialCoverage: number;
  centerUsage: number;
  edgeUsage: number;
  repetitionCount: number;
  stackingCount: number;
  warningCount: number;
  errorCount: number;
  localDifficultyBehavior: string;
  energyToDensityRatio: number;
  entryDirectionDeg: number | null;
  exitDirectionDeg: number | null;
}

export interface CandidateSectionEvaluation {
  sectionId: number;
  startMs: number;
  endMs: number;
  label: string;
  sourceCandidate: number;
  scores: CandidateSectionScores;
  metrics: CandidateSectionMetrics;
  issues: CandidateSectionIssue[];
  entryState: CandidateSectionState;
  exitState: CandidateSectionState;
}

export interface CandidateSectionReport {
  version: number;
  candidateIndex: number;
  difficulty: string;
  inputSignature: string;
  status: Record<string, unknown>;
  summary: Record<string, unknown>;
  sections: CandidateSectionEvaluation[];
}

export interface HybridSectionSelection {
  sectionId: number;
  startMs: number;
  endMs: number;
  label: string;
  sourceCandidate: number;
  sectionScore: number;
  selectionReason: string;
  lockState: string;
  transitionStatusBefore?: string;
  transitionStatusAfter?: string;
  issues: string[];
}

export interface HybridTransition {
  boundaryIndex: number;
  fromSectionId: number;
  toSectionId: number;
  fromCandidate: number;
  toCandidate: number;
  classification: string;
  score: number;
  metrics: Record<string, string | number | boolean | null>;
  issues: string[];
  corrections: Array<Record<string, unknown>>;
}

export interface HybridScores {
  sectionQuality: number;
  transitionQuality: number;
  styleConsistency: number;
  finalPythonQuality: number;
  overallHybridScore: number;
}

export interface HybridPromotionStatus {
  promoted: boolean;
  reason: string;
  championQuality: number | null;
  hybridPythonQuality: number;
  hybridScore: number;
}

export interface HybridAssemblyReport {
  version: number;
  difficulty: string;
  inputSignature: string;
  sections: HybridSectionSelection[];
  transitions: HybridTransition[];
  scores: HybridScores;
  sourceUsage: Record<string, number>;
  corrections: Record<string, number>;
  valid: boolean;
  playable: boolean;
  promotion: HybridPromotionStatus;
  summary: Record<string, unknown>;
}

export function parseSectionAnalysis(rawData: unknown): SectionAnalysis {
  const root = expectRecord(rawData, "section analysis");
  const audio = expectRecord(root.audio, "section analysis audio");
  const sections = expectArray(root.sections, "section analysis sections").map(
    validateSongSection,
  );
  const boundaries = expectArray(
    root.boundaries,
    "section analysis boundaries",
  ).map(validateSectionBoundary);
  return {
    version: expectNumber(root.version, "section analysis version"),
    audio: {
      path: expectString(audio.path, "section analysis audio.path"),
      durationMs: expectNumber(audio.durationMs, "section analysis audio.durationMs"),
    },
    configuration: expectLooseRecord(root.configuration, "section analysis configuration"),
    inputSignature: expectString(root.inputSignature, "section analysis inputSignature"),
    sections,
    boundaries,
    summary: expectLooseRecord(root.summary, "section analysis summary"),
  };
}

export function parseCandidateSectionReport(
  rawData: unknown,
): CandidateSectionReport {
  const root = expectRecord(rawData, "candidate section report");
  return {
    version: expectNumber(root.version, "candidate section report version"),
    candidateIndex: expectNumber(
      root.candidateIndex,
      "candidate section report candidateIndex",
    ),
    difficulty: expectString(
      root.difficulty,
      "candidate section report difficulty",
    ),
    inputSignature: expectString(
      root.inputSignature,
      "candidate section report inputSignature",
    ),
    status: expectLooseRecord(root.status, "candidate section report status"),
    summary: expectLooseRecord(root.summary, "candidate section report summary"),
    sections: expectArray(
      root.sections,
      "candidate section report sections",
    ).map(validateCandidateSectionEvaluation),
  };
}

export function parseHybridAssemblyReport(
  rawData: unknown,
): HybridAssemblyReport {
  const root = expectRecord(rawData, "hybrid assembly report");
  const scores = expectRecord(root.scores, "hybrid assembly scores");
  const promotion = expectRecord(root.promotion, "hybrid promotion");
  return {
    version: expectNumber(root.version, "hybrid assembly version"),
    difficulty: expectString(root.difficulty, "hybrid assembly difficulty"),
    inputSignature: expectString(
      root.inputSignature,
      "hybrid assembly inputSignature",
    ),
    sections: expectArray(root.sections, "hybrid assembly sections").map(
      validateHybridSectionSelection,
    ),
    transitions: expectArray(
      root.transitions,
      "hybrid assembly transitions",
    ).map(validateHybridTransition),
    scores: {
      sectionQuality: expectNumber(
        scores.sectionQuality,
        "hybrid scores.sectionQuality",
      ),
      transitionQuality: expectNumber(
        scores.transitionQuality,
        "hybrid scores.transitionQuality",
      ),
      styleConsistency: expectNumber(
        scores.styleConsistency,
        "hybrid scores.styleConsistency",
      ),
      finalPythonQuality: expectNumber(
        scores.finalPythonQuality,
        "hybrid scores.finalPythonQuality",
      ),
      overallHybridScore: expectNumber(
        scores.overallHybridScore,
        "hybrid scores.overallHybridScore",
      ),
    },
    sourceUsage: expectNumberRecord(
      root.sourceUsage,
      "hybrid sourceUsage",
    ),
    corrections: expectNumberRecord(
      root.corrections,
      "hybrid corrections",
    ),
    valid: expectBoolean(root.valid, "hybrid valid"),
    playable: expectBoolean(root.playable, "hybrid playable"),
    promotion: {
      promoted: expectBoolean(promotion.promoted, "hybrid promotion.promoted"),
      reason: expectString(promotion.reason, "hybrid promotion.reason"),
      championQuality: expectNullableNumber(
        promotion.championQuality,
        "hybrid promotion.championQuality",
      ),
      hybridPythonQuality: expectNumber(
        promotion.hybridPythonQuality,
        "hybrid promotion.hybridPythonQuality",
      ),
      hybridScore: expectNumber(
        promotion.hybridScore,
        "hybrid promotion.hybridScore",
      ),
    },
    summary: expectLooseRecord(root.summary, "hybrid summary"),
  };
}

export function findSectionByTime(
  sections: SongSection[],
  timeMs: number,
): SongSection | undefined {
  return sections.find((section) => {
    if (timeMs < section.startMs) {
      return false;
    }

    if (timeMs === section.endMs) {
      return section.id === sections[sections.length - 1]?.id;
    }

    return timeMs < section.endMs;
  });
}

export function getSectionTimelineBounds(section: SongSection): {
  startMs: number;
  endMs: number;
  durationMs: number;
} {
  return {
    startMs: section.startMs,
    endMs: section.endMs,
    durationMs: section.durationMs,
  };
}

export function buildHybridSourceSequence(
  sections: HybridSectionSelection[],
): string {
  return sections.map((section) => `C${section.sourceCandidate}`).join(" -> ");
}

export function countHybridCandidateSwitches(
  sections: HybridSectionSelection[],
): number {
  let count = 0;
  for (let index = 1; index < sections.length; index += 1) {
    if (sections[index - 1]?.sourceCandidate !== sections[index]?.sourceCandidate) {
      count += 1;
    }
  }
  return count;
}

function validateSectionBoundary(rawValue: unknown): SectionBoundary {
  const value = expectRecord(rawValue, "section boundary");
  return {
    rawTimeMs: expectNumber(value.rawTimeMs, "section boundary rawTimeMs"),
    finalTimeMs: expectNumber(value.finalTimeMs, "section boundary finalTimeMs"),
    confidence: expectNumber(value.confidence, "section boundary confidence"),
    reason: expectString(value.reason, "section boundary reason"),
    supportingFeatureChanges: expectNumberRecord(
      value.supportingFeatureChanges,
      "section boundary supportingFeatureChanges",
    ),
    snapped: expectBoolean(value.snapped, "section boundary snapped"),
    snappedTo: expectOptionalString(value.snappedTo, "section boundary snappedTo"),
    snapDistanceMs: expectOptionalNumber(
      value.snapDistanceMs,
      "section boundary snapDistanceMs",
    ),
  };
}

function validateSongSection(rawValue: unknown): SongSection {
  const value = expectRecord(rawValue, "song section");
  return {
    id: expectNumber(value.id, "song section id"),
    startMs: expectNumber(value.startMs, "song section startMs"),
    endMs: expectNumber(value.endMs, "song section endMs"),
    durationMs: expectNumber(value.durationMs, "song section durationMs"),
    label: expectString(value.label, "song section label"),
    confidence: expectNumber(value.confidence, "song section confidence"),
    averageEnergy: expectNumber(
      value.averageEnergy,
      "song section averageEnergy",
    ),
    energyTrend: expectString(value.energyTrend, "song section energyTrend"),
    beatDensity: expectNumber(value.beatDensity, "song section beatDensity"),
    onsetDensity: expectNumber(value.onsetDensity, "song section onsetDensity"),
    rhythmComplexity: expectNumber(
      value.rhythmComplexity,
      "song section rhythmComplexity",
    ),
    repetitionGroup:
      value.repetitionGroup === null
        ? null
        : value.repetitionGroup === undefined
          ? null
          : expectNumber(value.repetitionGroup, "song section repetitionGroup"),
    energyClass: expectString(value.energyClass, "song section energyClass"),
  };
}

function validateCandidateSectionEvaluation(
  rawValue: unknown,
): CandidateSectionEvaluation {
  const value = expectRecord(rawValue, "candidate section evaluation");
  return {
    sectionId: expectNumber(value.sectionId, "candidate sectionId"),
    startMs: expectNumber(value.startMs, "candidate startMs"),
    endMs: expectNumber(value.endMs, "candidate endMs"),
    label: expectString(value.label, "candidate label"),
    sourceCandidate: expectNumber(
      value.sourceCandidate,
      "candidate sourceCandidate",
    ),
    scores: validateCandidateSectionScores(value.scores),
    metrics: validateCandidateSectionMetrics(value.metrics),
    issues: expectArray(value.issues, "candidate issues").map(
      validateCandidateSectionIssue,
    ),
    entryState: validateCandidateSectionState(value.entryState),
    exitState: validateCandidateSectionState(value.exitState),
  };
}

function validateCandidateSectionScores(
  rawValue: unknown,
): CandidateSectionScores {
  const value = expectRecord(rawValue, "candidate section scores");
  return {
    structural: expectNumber(value.structural, "candidate scores.structural"),
    timing: expectNumber(value.timing, "candidate scores.timing"),
    rhythm: expectNumber(value.rhythm, "candidate scores.rhythm"),
    movement: expectNumber(value.movement, "candidate scores.movement"),
    readability: expectNumber(
      value.readability,
      "candidate scores.readability",
    ),
    spatialBalance: expectNumber(
      value.spatialBalance,
      "candidate scores.spatialBalance",
    ),
    repetition: expectNumber(value.repetition, "candidate scores.repetition"),
    densityConsistency: expectNumber(
      value.densityConsistency,
      "candidate scores.densityConsistency",
    ),
    difficultyConsistency: expectNumber(
      value.difficultyConsistency,
      "candidate scores.difficultyConsistency",
    ),
    transitionReadiness: expectNumber(
      value.transitionReadiness,
      "candidate scores.transitionReadiness",
    ),
    overall: expectNumber(value.overall, "candidate scores.overall"),
  };
}

function validateCandidateSectionMetrics(
  rawValue: unknown,
): CandidateSectionMetrics {
  const value = expectRecord(rawValue, "candidate section metrics");
  return {
    objectCount: expectNumber(value.objectCount, "candidate metrics.objectCount"),
    objectsPerSecond: expectNumber(
      value.objectsPerSecond,
      "candidate metrics.objectsPerSecond",
    ),
    averageObjectGapMs: expectNumber(
      value.averageObjectGapMs,
      "candidate metrics.averageObjectGapMs",
    ),
    minimumObjectGapMs: expectNumber(
      value.minimumObjectGapMs,
      "candidate metrics.minimumObjectGapMs",
    ),
    maximumObjectGapMs: expectNumber(
      value.maximumObjectGapMs,
      "candidate metrics.maximumObjectGapMs",
    ),
    averageJumpDistance: expectNumber(
      value.averageJumpDistance,
      "candidate metrics.averageJumpDistance",
    ),
    maximumJumpDistance: expectNumber(
      value.maximumJumpDistance,
      "candidate metrics.maximumJumpDistance",
    ),
    averageCursorSpeed: expectNumber(
      value.averageCursorSpeed,
      "candidate metrics.averageCursorSpeed",
    ),
    maximumCursorSpeed: expectNumber(
      value.maximumCursorSpeed,
      "candidate metrics.maximumCursorSpeed",
    ),
    timingConfidence: expectNumber(
      value.timingConfidence,
      "candidate metrics.timingConfidence",
    ),
    beatAlignment: expectNumber(
      value.beatAlignment,
      "candidate metrics.beatAlignment",
    ),
    onsetAlignment: expectNumber(
      value.onsetAlignment,
      "candidate metrics.onsetAlignment",
    ),
    spatialCoverage: expectNumber(
      value.spatialCoverage,
      "candidate metrics.spatialCoverage",
    ),
    centerUsage: expectNumber(
      value.centerUsage,
      "candidate metrics.centerUsage",
    ),
    edgeUsage: expectNumber(value.edgeUsage, "candidate metrics.edgeUsage"),
    repetitionCount: expectNumber(
      value.repetitionCount,
      "candidate metrics.repetitionCount",
    ),
    stackingCount: expectNumber(
      value.stackingCount,
      "candidate metrics.stackingCount",
    ),
    warningCount: expectNumber(
      value.warningCount,
      "candidate metrics.warningCount",
    ),
    errorCount: expectNumber(value.errorCount, "candidate metrics.errorCount"),
    localDifficultyBehavior: expectString(
      value.localDifficultyBehavior,
      "candidate metrics.localDifficultyBehavior",
    ),
    energyToDensityRatio: expectNumber(
      value.energyToDensityRatio,
      "candidate metrics.energyToDensityRatio",
    ),
    entryDirectionDeg: expectNullableNumber(
      value.entryDirectionDeg,
      "candidate metrics.entryDirectionDeg",
    ),
    exitDirectionDeg: expectNullableNumber(
      value.exitDirectionDeg,
      "candidate metrics.exitDirectionDeg",
    ),
  };
}

function validateCandidateSectionIssue(rawValue: unknown): CandidateSectionIssue {
  const value = expectRecord(rawValue, "candidate section issue");
  return {
    code: expectString(value.code, "candidate issue.code"),
    severity: expectString(value.severity, "candidate issue.severity"),
    message: expectString(value.message, "candidate issue.message"),
    measuredValue: expectOptionalNumber(
      value.measuredValue,
      "candidate issue.measuredValue",
    ),
    allowedValue: expectOptionalNumber(
      value.allowedValue,
      "candidate issue.allowedValue",
    ),
  };
}

function validateCandidateSectionState(rawValue: unknown): CandidateSectionState {
  const value = expectRecord(rawValue, "candidate section state");
  return {
    objectId: expectNullableNumber(value.objectId, "candidate state.objectId"),
    timeMs: expectNullableNumber(value.timeMs, "candidate state.timeMs"),
    x: expectNullableNumber(value.x, "candidate state.x"),
    y: expectNullableNumber(value.y, "candidate state.y"),
    directionDeg: expectNullableNumber(
      value.directionDeg,
      "candidate state.directionDeg",
    ),
    cursorSpeedPps: expectNullableNumber(
      value.cursorSpeedPps,
      "candidate state.cursorSpeedPps",
    ),
    gapMs: expectNullableNumber(value.gapMs, "candidate state.gapMs"),
    density: expectNullableNumber(value.density, "candidate state.density"),
    region:
      value.region === null
        ? null
        : expectString(value.region, "candidate state.region"),
  };
}

function validateHybridSectionSelection(
  rawValue: unknown,
): HybridSectionSelection {
  const value = expectRecord(rawValue, "hybrid section selection");
  return {
    sectionId: expectNumber(value.sectionId, "hybrid sectionId"),
    startMs: expectNumber(value.startMs, "hybrid startMs"),
    endMs: expectNumber(value.endMs, "hybrid endMs"),
    label: expectString(value.label, "hybrid label"),
    sourceCandidate: expectNumber(
      value.sourceCandidate,
      "hybrid sourceCandidate",
    ),
    sectionScore: expectNumber(value.sectionScore, "hybrid sectionScore"),
    selectionReason: expectString(
      value.selectionReason,
      "hybrid selectionReason",
    ),
    lockState: expectString(value.lockState, "hybrid lockState"),
    transitionStatusBefore: expectOptionalString(
      value.transitionStatusBefore,
      "hybrid transitionStatusBefore",
    ),
    transitionStatusAfter: expectOptionalString(
      value.transitionStatusAfter,
      "hybrid transitionStatusAfter",
    ),
    issues: expectArray(value.issues, "hybrid section issues").map((item, index) =>
      expectString(item, `hybrid section issues[${index}]`),
    ),
  };
}

function validateHybridTransition(rawValue: unknown): HybridTransition {
  const value = expectRecord(rawValue, "hybrid transition");
  return {
    boundaryIndex: expectNumber(value.boundaryIndex, "hybrid boundaryIndex"),
    fromSectionId: expectNumber(value.fromSectionId, "hybrid fromSectionId"),
    toSectionId: expectNumber(value.toSectionId, "hybrid toSectionId"),
    fromCandidate: expectNumber(value.fromCandidate, "hybrid fromCandidate"),
    toCandidate: expectNumber(value.toCandidate, "hybrid toCandidate"),
    classification: expectString(
      value.classification,
      "hybrid classification",
    ),
    score: expectNumber(value.score, "hybrid score"),
    metrics: expectLooseMetricRecord(value.metrics, "hybrid metrics"),
    issues: expectArray(value.issues, "hybrid issues").map((item, index) =>
      expectString(item, `hybrid issues[${index}]`),
    ),
    corrections: expectArray(
      value.corrections,
      "hybrid corrections",
    ).map((item, index) => expectLooseRecord(item, `hybrid corrections[${index}]`)),
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

function expectLooseMetricRecord(
  value: unknown,
  label: string,
): Record<string, string | number | boolean | null> {
  const record = expectRecord(value, label);
  const output: Record<string, string | number | boolean | null> = {};
  for (const [key, item] of Object.entries(record)) {
    if (
      item === null ||
      typeof item === "string" ||
      typeof item === "boolean" ||
      (typeof item === "number" && Number.isFinite(item))
    ) {
      output[key] = item;
      continue;
    }

    throw new Error(`${label}.${key} must be a string, number, boolean, or null.`);
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

function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }

  return value;
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
