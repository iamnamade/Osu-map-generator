import { isJsonObject } from "./JsonTypes";

export type PhraseRelationshipType =
  | "repetition"
  | "variation"
  | "continuation"
  | "escalation"
  | "reduction"
  | "contrast"
  | "call-and-response"
  | "transition";

export type PhraseStrategyName =
  | "establish"
  | "intensify"
  | "release"
  | "contrast"
  | "recover"
  | "transition"
  | "neutral";

export interface Phrase {
  id: number;
  startMs: number;
  endMs: number;
  durationMs: number;
  sectionId: number | null;
  label: string;
  confidence: number;
  averageEnergy: number;
  energySlope: number;
  onsetDensity: number;
  beatDensity: number;
  averageOnsetStrength: number;
  rhythmComplexity: number;
  spectralFlux: number;
  emphasisRatio: number;
  quietRatio: number;
  highEnergyRatio: number;
  subdivisionRatio: number;
  motifId: number | null;
  strategy: PhraseStrategyName;
  targetDensity: number;
  targetDifficulty: number;
  minGapMs: number;
  targetGapMs: number;
  entryDirectionDeg: number | null;
  exitDirectionDeg: number | null;
  sectionRepetitionGroup: number | null;
}

export interface PhraseRelationship {
  id: number;
  fromPhraseId: number;
  toPhraseId: number;
  relationshipType: PhraseRelationshipType;
  similarity: number;
  confidence: number;
  featureDeltas: Record<string, number>;
}

export interface PhraseMotif {
  id: number;
  phraseIds: number[];
  rhythmSignature: number[];
  densityProfile: number[];
  occurrenceCount: number;
  label: string;
}

export interface PhraseTrajectoryPoint {
  timeMs: number;
  density: number;
  difficulty: number;
}

export interface PhraseReport {
  version: number;
  audio: {
    path: string;
    durationMs: number;
  };
  configuration: Record<string, unknown>;
  inputSignature: string;
  phrases: Phrase[];
  relationships: PhraseRelationship[];
  motifs: PhraseMotif[];
  trajectory: PhraseTrajectoryPoint[];
  summary: Record<string, unknown>;
}

export function parsePhraseReport(rawData: unknown): PhraseReport {
  const root = expectRecord(rawData, "phrase report");
  const audio = expectRecord(root.audio, "phrase report audio");
  return {
    version: expectNumber(root.version, "phrase report version"),
    audio: {
      path: expectString(audio.path, "phrase report audio.path"),
      durationMs: expectNumber(
        audio.durationMs,
        "phrase report audio.durationMs",
      ),
    },
    configuration: expectLooseRecord(
      root.configuration,
      "phrase report configuration",
    ),
    inputSignature: expectString(
      root.inputSignature,
      "phrase report inputSignature",
    ),
    phrases: expectArray(root.phrases, "phrase report phrases").map(
      validatePhrase,
    ),
    relationships: expectArray(
      root.relationships,
      "phrase report relationships",
    ).map(validatePhraseRelationship),
    motifs: expectArray(root.motifs, "phrase report motifs").map(
      validatePhraseMotif,
    ),
    trajectory: expectArray(root.trajectory, "phrase report trajectory").map(
      validateTrajectoryPoint,
    ),
    summary: expectLooseRecord(root.summary, "phrase report summary"),
  };
}

export function findPhraseByTime(
  phrases: Phrase[],
  timeMs: number,
): Phrase | undefined {
  return phrases.find((phrase) => {
    if (timeMs < phrase.startMs) {
      return false;
    }
    return timeMs < phrase.endMs;
  });
}

export function getStrategyColor(strategy: PhraseStrategyName): string {
  const colors: Record<PhraseStrategyName, string> = {
    establish: "#5de0a6",
    intensify: "#ff7a6e",
    release: "#8ab4ff",
    contrast: "#f6c15e",
    recover: "#6fcf97",
    transition: "#c58fff",
    neutral: "#8da0be",
  };
  return colors[strategy] ?? "#8da0be";
}

export function getRelationshipColor(
  relationshipType: PhraseRelationshipType,
): string {
  const colors: Record<PhraseRelationshipType, string> = {
    repetition: "#5de0a6",
    variation: "#a5e88b",
    continuation: "#6fb6ff",
    escalation: "#ff7a6e",
    reduction: "#8ab4ff",
    contrast: "#f6c15e",
    "call-and-response": "#c58fff",
    transition: "#f0a0d0",
  };
  return colors[relationshipType] ?? "#8da0be";
}

function validatePhrase(rawValue: unknown): Phrase {
  const value = expectRecord(rawValue, "phrase");
  return {
    id: expectNumber(value.id, "phrase id"),
    startMs: expectNumber(value.startMs, "phrase startMs"),
    endMs: expectNumber(value.endMs, "phrase endMs"),
    durationMs: expectNumber(value.durationMs, "phrase durationMs"),
    sectionId: expectNullableNumber(value.sectionId, "phrase sectionId"),
    label: expectString(value.label, "phrase label"),
    confidence: expectNumber(value.confidence, "phrase confidence"),
    averageEnergy: expectNumber(value.averageEnergy, "phrase averageEnergy"),
    energySlope: expectNumber(value.energySlope, "phrase energySlope"),
    onsetDensity: expectNumber(value.onsetDensity, "phrase onsetDensity"),
    beatDensity: expectNumber(value.beatDensity, "phrase beatDensity"),
    averageOnsetStrength: expectNumber(
      value.averageOnsetStrength,
      "phrase averageOnsetStrength",
    ),
    rhythmComplexity: expectNumber(
      value.rhythmComplexity,
      "phrase rhythmComplexity",
    ),
    spectralFlux: expectNumber(value.spectralFlux, "phrase spectralFlux"),
    emphasisRatio: expectNumber(value.emphasisRatio, "phrase emphasisRatio"),
    quietRatio: expectNumber(value.quietRatio, "phrase quietRatio"),
    highEnergyRatio: expectNumber(
      value.highEnergyRatio,
      "phrase highEnergyRatio",
    ),
    subdivisionRatio: expectNumber(
      value.subdivisionRatio,
      "phrase subdivisionRatio",
    ),
    motifId: expectNullableNumber(value.motifId, "phrase motifId"),
    strategy: validateStrategy(value.strategy),
    targetDensity: expectNumber(value.targetDensity, "phrase targetDensity"),
    targetDifficulty: expectNumber(
      value.targetDifficulty,
      "phrase targetDifficulty",
    ),
    minGapMs: expectNumber(value.minGapMs, "phrase minGapMs"),
    targetGapMs: expectNumber(value.targetGapMs, "phrase targetGapMs"),
    entryDirectionDeg: expectNullableNumber(
      value.entryDirectionDeg,
      "phrase entryDirectionDeg",
    ),
    exitDirectionDeg: expectNullableNumber(
      value.exitDirectionDeg,
      "phrase exitDirectionDeg",
    ),
    sectionRepetitionGroup: expectNullableNumber(
      value.sectionRepetitionGroup,
      "phrase sectionRepetitionGroup",
    ),
  };
}

function validatePhraseRelationship(
  rawValue: unknown,
): PhraseRelationship {
  const value = expectRecord(rawValue, "phrase relationship");
  return {
    id: expectNumber(value.id, "relationship id"),
    fromPhraseId: expectNumber(value.fromPhraseId, "relationship fromPhraseId"),
    toPhraseId: expectNumber(value.toPhraseId, "relationship toPhraseId"),
    relationshipType: validateRelationshipType(value.relationshipType),
    similarity: expectNumber(value.similarity, "relationship similarity"),
    confidence: expectNumber(value.confidence, "relationship confidence"),
    featureDeltas: expectNumberRecord(
      value.featureDeltas,
      "relationship featureDeltas",
    ),
  };
}

function validatePhraseMotif(rawValue: unknown): PhraseMotif {
  const value = expectRecord(rawValue, "phrase motif");
  return {
    id: expectNumber(value.id, "motif id"),
    phraseIds: expectArray(value.phraseIds, "motif phraseIds").map(
      (item, index) => expectNumber(item, `motif phraseIds[${index}]`),
    ),
    rhythmSignature: expectArray(
      value.rhythmSignature,
      "motif rhythmSignature",
    ).map((item, index) =>
      expectNumber(item, `motif rhythmSignature[${index}]`),
    ),
    densityProfile: expectArray(
      value.densityProfile,
      "motif densityProfile",
    ).map((item, index) => expectNumber(item, `motif densityProfile[${index}]`)),
    occurrenceCount: expectNumber(
      value.occurrenceCount,
      "motif occurrenceCount",
    ),
    label: expectString(value.label, "motif label"),
  };
}

function validateTrajectoryPoint(rawValue: unknown): PhraseTrajectoryPoint {
  const value = expectRecord(rawValue, "phrase trajectory point");
  return {
    timeMs: expectNumber(value.timeMs, "trajectory timeMs"),
    density: expectNumber(value.density, "trajectory density"),
    difficulty: expectNumber(value.difficulty, "trajectory difficulty"),
  };
}

function validateStrategy(value: unknown): PhraseStrategyName {
  const strategies: PhraseStrategyName[] = [
    "establish",
    "intensify",
    "release",
    "contrast",
    "recover",
    "transition",
    "neutral",
  ];
  if (typeof value === "string" && strategies.includes(value as PhraseStrategyName)) {
    return value as PhraseStrategyName;
  }
  return "neutral";
}

function validateRelationshipType(
  value: unknown,
): PhraseRelationshipType {
  const types: PhraseRelationshipType[] = [
    "repetition",
    "variation",
    "continuation",
    "escalation",
    "reduction",
    "contrast",
    "call-and-response",
    "transition",
  ];
  if (typeof value === "string" && types.includes(value as PhraseRelationshipType)) {
    return value as PhraseRelationshipType;
  }
  return "continuation";
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
