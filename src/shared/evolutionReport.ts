import { isJsonObject } from "./JsonTypes";

export interface EvolutionSongInfo {
  title: string;
  artist: string;
  difficulty: string;
  audio: string;
}

export interface EvolutionConfiguration {
  rootSeed: number;
  candidateCount: number;
  maxPasses: number;
  archivePolicy: string;
  timingVariation: boolean;
}

export interface EvolutionSummary {
  generated: number;
  eligible: number;
  rejected: number;
  passesUsed: number;
  earlyStopped: boolean;
}

export interface EvolutionDimensionScores {
  overall: number;
  quality: number;
  difficulty: number;
  flow: number;
  rhythm: number;
  movement: number;
  pattern: number;
  slider: number;
  spinner: number;
  reading: number;
  playability: number;
  consistency: number;
  confidence: number;
  replay: number;
}

export interface EvolutionFinalScores {
  weightedScore: number;
  rhythm: number;
  playability: number;
  pattern: number;
  target: number;
  reading: number;
  replay: number;
  consistency: number;
  validity: number;
  flow: number;
  section: number;
  fatigue: number;
  rebalance: number;
}

export interface EvolutionQualityGate {
  code: string;
  name: string;
  mandatory: boolean;
  passed: boolean;
  detail: string;
  penalty: number;
}

export interface EvolutionRankingEntry {
  rank: number;
  candidateIndex: number;
  candidateSeed: number;
  stars: number;
  scores: EvolutionDimensionScores;
  mapPath: string;
  reportPath: string;
  summaryPath: string;
  eligible: boolean;
  rejectionReasons: string[];
  final?: EvolutionFinalScores;
  qualityGates?: EvolutionQualityGate[];
  validationStatus?: string;
  improvementsMade?: string[];
  targetDeviation?: number;
  diversityPenalty?: number;
}

export interface RejectedEvolutionCandidate {
  candidateIndex: number;
  candidateSeed: number;
  overallScore: number;
  rejectionReasons: string[];
  summaryPath: string;
}

export interface EvolutionChampion {
  candidateIndex: number;
  candidateSeed: number;
  overallScore: number;
  qualityScore: number;
  stars: number;
  mapPath: string;
  reportPath: string;
  sourceMapPath: string;
  sourceReportPath: string;
  summaryPath: string;
  promotionReason: string;
}

export interface EvolutionComparisonEntry {
  dimension: string;
  championValue: number;
  runnerValue: number;
  delta: number;
  note: string;
}

export interface EvolutionHeatmap {
  dimension: string;
  label: string;
  values: number[];
}

export interface ImprovementPassEntry {
  passNumber: number;
  candidateIndex: number;
  overallBefore: number;
  overallAfter: number;
  accepted: boolean;
}

export interface EvolutionDiagnostics {
  scoreDistribution: Record<string, number>;
  averageImprovement: number;
  promotionReason: string;
  confidence: number;
}

export interface EvolutionReplaySummary {
  fullComboChance: number;
  expectedAccuracy: number;
  expectedMisses: number;
  highestStressSectionMs: number;
  hardestPattern: string;
  mostDifficultTransitionMs: number;
  replayScore: number;
  playerProfile: string;
  expectedComboPct: number;
  cursorEfficiency: number;
  readingScore: number;
  fatigueAverage: number;
  fatiguePeak: number;
  comboBreaks: number;
  missClusters: number;
  weakestSection: string;
  strongestSection: string;
}

export interface EvolutionReport {
  version: number;
  song: EvolutionSongInfo;
  configuration: EvolutionConfiguration;
  summary: EvolutionSummary;
  champion: EvolutionChampion;
  ranking: EvolutionRankingEntry[];
  rejectedCandidates: RejectedEvolutionCandidate[];
  comparison: EvolutionComparisonEntry[];
  comparisonReasons: string[];
  heatmaps: EvolutionHeatmap[];
  replay: EvolutionReplaySummary;
  improvementHistory: ImprovementPassEntry[];
  diagnostics: EvolutionDiagnostics;
  scoreWeights: Record<string, number>;
  replayReportPath: string;
}

export function parseEvolutionReport(rawData: unknown): EvolutionReport {
  const root = expectRecord(rawData, "evolution report");
  const song = expectRecord(root.song, "evolution report song");
  const configuration = expectRecord(
    root.configuration,
    "evolution report configuration",
  );
  const summary = expectRecord(root.summary, "evolution report summary");
  const champion = expectRecord(root.champion, "evolution report champion");
  const replay = expectRecord(root.replay, "evolution report replay");
  const diagnostics = expectRecord(
    root.diagnostics,
    "evolution report diagnostics",
  );

  return {
    version: expectNumber(root.version, "evolution report version"),
    song: {
      title: expectString(song.title, "evolution report song.title"),
      artist: expectString(song.artist, "evolution report song.artist"),
      difficulty: expectString(song.difficulty, "evolution report song.difficulty"),
      audio: expectString(song.audio, "evolution report song.audio"),
    },
    configuration: {
      rootSeed: expectNumber(
        configuration.rootSeed,
        "evolution report configuration.rootSeed",
      ),
      candidateCount: expectNumber(
        configuration.candidateCount,
        "evolution report configuration.candidateCount",
      ),
      maxPasses: expectNumber(
        configuration.maxPasses,
        "evolution report configuration.maxPasses",
      ),
      archivePolicy: expectString(
        configuration.archivePolicy,
        "evolution report configuration.archivePolicy",
      ),
      timingVariation: expectBoolean(
        configuration.timingVariation,
        "evolution report configuration.timingVariation",
      ),
    },
    summary: {
      generated: expectNumber(summary.generated, "evolution report summary.generated"),
      eligible: expectNumber(summary.eligible, "evolution report summary.eligible"),
      rejected: expectNumber(summary.rejected, "evolution report summary.rejected"),
      passesUsed: expectNumber(summary.passesUsed, "evolution report summary.passesUsed"),
      earlyStopped: expectBoolean(
        summary.earlyStopped,
        "evolution report summary.earlyStopped",
      ),
    },
    champion: {
      candidateIndex: expectNumber(
        champion.candidateIndex,
        "evolution report champion.candidateIndex",
      ),
      candidateSeed: expectNumber(
        champion.candidateSeed,
        "evolution report champion.candidateSeed",
      ),
      overallScore: expectNumber(
        champion.overallScore,
        "evolution report champion.overallScore",
      ),
      qualityScore: expectNumber(
        champion.qualityScore,
        "evolution report champion.qualityScore",
      ),
      stars: expectNumber(champion.stars, "evolution report champion.stars"),
      mapPath: expectString(champion.mapPath, "evolution report champion.mapPath"),
      reportPath: expectString(
        champion.reportPath,
        "evolution report champion.reportPath",
      ),
      sourceMapPath: expectString(
        champion.sourceMapPath,
        "evolution report champion.sourceMapPath",
      ),
      sourceReportPath: expectString(
        champion.sourceReportPath,
        "evolution report champion.sourceReportPath",
      ),
      summaryPath: expectString(
        champion.summaryPath,
        "evolution report champion.summaryPath",
      ),
      promotionReason: expectString(
        champion.promotionReason,
        "evolution report champion.promotionReason",
      ),
    },
    ranking: expectArray(root.ranking, "evolution report ranking").map(
      (item, index) => parseRankingEntry(item, index),
    ),
    rejectedCandidates: expectArray(
      root.rejectedCandidates,
      "evolution report rejectedCandidates",
    ).map((item, index) => parseRejectedCandidate(item, index)),
    comparison: expectArray(root.comparison, "evolution report comparison").map(
      (item, index) => {
        const value = expectRecord(
          item,
          `evolution report comparison[${index}]`,
        );
        return {
          dimension: expectString(
            value.dimension,
            `evolution report comparison[${index}].dimension`,
          ),
          championValue: expectNumber(
            value.championValue,
            `evolution report comparison[${index}].championValue`,
          ),
          runnerValue: expectNumber(
            value.runnerValue,
            `evolution report comparison[${index}].runnerValue`,
          ),
          delta: expectNumber(
            value.delta,
            `evolution report comparison[${index}].delta`,
          ),
          note: expectString(
            value.note,
            `evolution report comparison[${index}].note`,
          ),
        };
      },
    ),
    comparisonReasons: expectStringArray(
      root.comparisonReasons,
      "evolution report comparisonReasons",
    ),
    heatmaps: expectArray(root.heatmaps, "evolution report heatmaps").map(
      (item, index) => {
        const value = expectRecord(item, `evolution report heatmaps[${index}]`);
        return {
          dimension: expectString(
            value.dimension,
            `evolution report heatmaps[${index}].dimension`,
          ),
          label: expectString(
            value.label,
            `evolution report heatmaps[${index}].label`,
          ),
          values: expectNumberArray(
            value.values,
            `evolution report heatmaps[${index}].values`,
          ),
        };
      },
    ),
    replay: {
      fullComboChance: expectNumber(
        replay.fullComboChance,
        "evolution report replay.fullComboChance",
      ),
      expectedAccuracy: expectNumber(
        replay.expectedAccuracy,
        "evolution report replay.expectedAccuracy",
      ),
      expectedMisses: expectNumber(
        replay.expectedMisses,
        "evolution report replay.expectedMisses",
      ),
      highestStressSectionMs: expectNumber(
        replay.highestStressSectionMs,
        "evolution report replay.highestStressSectionMs",
      ),
      hardestPattern: expectString(
        replay.hardestPattern,
        "evolution report replay.hardestPattern",
      ),
      mostDifficultTransitionMs: expectNumber(
        replay.mostDifficultTransitionMs,
        "evolution report replay.mostDifficultTransitionMs",
      ),
      replayScore: optionalNumber(
        replay.replayScore,
        "evolution report replay.replayScore",
      ),
      playerProfile: optionalString(replay.playerProfile),
      expectedComboPct: optionalNumber(
        replay.expectedComboPct,
        "evolution report replay.expectedComboPct",
      ),
      cursorEfficiency: optionalNumber(
        replay.cursorEfficiency,
        "evolution report replay.cursorEfficiency",
      ),
      readingScore: optionalNumber(
        replay.readingScore,
        "evolution report replay.readingScore",
      ),
      fatigueAverage: optionalNumber(
        replay.fatigueAverage,
        "evolution report replay.fatigueAverage",
      ),
      fatiguePeak: optionalNumber(
        replay.fatiguePeak,
        "evolution report replay.fatiguePeak",
      ),
      comboBreaks: optionalNumber(
        replay.comboBreaks,
        "evolution report replay.comboBreaks",
      ),
      missClusters: optionalNumber(
        replay.missClusters,
        "evolution report replay.missClusters",
      ),
      weakestSection: optionalString(replay.weakestSection),
      strongestSection: optionalString(replay.strongestSection),
    },
    improvementHistory: expectArray(
      root.improvementHistory,
      "evolution report improvementHistory",
    ).map((item, index) => {
      const value = expectRecord(
        item,
        `evolution report improvementHistory[${index}]`,
      );
      return {
        passNumber: expectNumber(
          value.passNumber,
          `evolution report improvementHistory[${index}].passNumber`,
        ),
        candidateIndex: expectNumber(
          value.candidateIndex,
          `evolution report improvementHistory[${index}].candidateIndex`,
        ),
        overallBefore: expectNumber(
          value.overallBefore,
          `evolution report improvementHistory[${index}].overallBefore`,
        ),
        overallAfter: expectNumber(
          value.overallAfter,
          `evolution report improvementHistory[${index}].overallAfter`,
        ),
        accepted: expectBoolean(
          value.accepted,
          `evolution report improvementHistory[${index}].accepted`,
        ),
      };
    }),
    diagnostics: {
      scoreDistribution: expectNumberRecord(
        diagnostics.scoreDistribution,
        "evolution report diagnostics.scoreDistribution",
      ),
      averageImprovement: expectNumber(
        diagnostics.averageImprovement,
        "evolution report diagnostics.averageImprovement",
      ),
      promotionReason: expectString(
        diagnostics.promotionReason,
        "evolution report diagnostics.promotionReason",
      ),
      confidence: expectNumber(
        diagnostics.confidence,
        "evolution report diagnostics.confidence",
      ),
    },
    scoreWeights: expectNumberRecord(
      root.scoreWeights,
      "evolution report scoreWeights",
    ),
    replayReportPath: optionalString(root.replayReportPath),
  };
}

function parseRankingEntry(rawValue: unknown, index: number): EvolutionRankingEntry {
  const value = expectRecord(rawValue, `evolution report ranking[${index}]`);
  return {
    rank: expectNumber(value.rank, `evolution report ranking[${index}].rank`),
    candidateIndex: expectNumber(
      value.candidateIndex,
      `evolution report ranking[${index}].candidateIndex`,
    ),
    candidateSeed: expectNumber(
      value.candidateSeed,
      `evolution report ranking[${index}].candidateSeed`,
    ),
    stars: expectNumber(value.stars, `evolution report ranking[${index}].stars`),
    scores: parseDimensionScores(value.scores, `evolution report ranking[${index}].scores`),
    mapPath: expectString(
      value.mapPath,
      `evolution report ranking[${index}].mapPath`,
    ),
    reportPath: expectString(
      value.reportPath,
      `evolution report ranking[${index}].reportPath`,
    ),
    summaryPath: expectString(
      value.summaryPath,
      `evolution report ranking[${index}].summaryPath`,
    ),
    eligible: value.eligible === undefined ? true : expectBoolean(value.eligible, `evolution report ranking[${index}].eligible`),
    rejectionReasons: expectStringArray(
      value.rejectionReasons,
      `evolution report ranking[${index}].rejectionReasons`,
    ),
    final:
      value.final === undefined
        ? undefined
        : parseFinalScores(value.final, `evolution report ranking[${index}].final`),
    qualityGates:
      value.qualityGates === undefined
        ? undefined
        : expectArray(
            value.qualityGates,
            `evolution report ranking[${index}].qualityGates`,
          ).map((item, gateIndex) =>
            parseQualityGate(
              item,
              `evolution report ranking[${index}].qualityGates[${gateIndex}]`,
            ),
          ),
    validationStatus:
      value.validationStatus === undefined
        ? undefined
        : expectString(
            value.validationStatus,
            `evolution report ranking[${index}].validationStatus`,
          ),
    improvementsMade:
      value.improvementsMade === undefined
        ? undefined
        : expectStringArray(
            value.improvementsMade,
            `evolution report ranking[${index}].improvementsMade`,
          ),
    targetDeviation: optionalUndefinedNumber(
      value.targetDeviation,
      `evolution report ranking[${index}].targetDeviation`,
    ),
    diversityPenalty: optionalUndefinedNumber(
      value.diversityPenalty,
      `evolution report ranking[${index}].diversityPenalty`,
    ),
  };
}

function parseFinalScores(
  rawValue: unknown,
  label: string,
): EvolutionFinalScores {
  const value = expectRecord(rawValue, label);
  return {
    weightedScore: expectNumber(value.weightedScore, `${label}.weightedScore`),
    rhythm: expectNumber(value.rhythm, `${label}.rhythm`),
    playability: expectNumber(value.playability, `${label}.playability`),
    pattern: expectNumber(value.pattern, `${label}.pattern`),
    target: expectNumber(value.target, `${label}.target`),
    reading: expectNumber(value.reading, `${label}.reading`),
    replay: expectNumber(value.replay, `${label}.replay`),
    consistency: expectNumber(value.consistency, `${label}.consistency`),
    validity: expectNumber(value.validity, `${label}.validity`),
    flow: expectNumber(value.flow, `${label}.flow`),
    section: expectNumber(value.section, `${label}.section`),
    fatigue: expectNumber(value.fatigue, `${label}.fatigue`),
    rebalance: expectNumber(value.rebalance, `${label}.rebalance`),
  };
}

function parseQualityGate(rawValue: unknown, label: string): EvolutionQualityGate {
  const value = expectRecord(rawValue, label);
  return {
    code: expectString(value.code, `${label}.code`),
    name: expectString(value.name, `${label}.name`),
    mandatory: expectBoolean(value.mandatory, `${label}.mandatory`),
    passed: expectBoolean(value.passed, `${label}.passed`),
    detail: expectString(value.detail, `${label}.detail`),
    penalty: expectNumber(value.penalty, `${label}.penalty`),
  };
}

function parseRejectedCandidate(
  rawValue: unknown,
  index: number,
): RejectedEvolutionCandidate {
  const value = expectRecord(
    rawValue,
    `evolution report rejectedCandidates[${index}]`,
  );
  return {
    candidateIndex: expectNumber(
      value.candidateIndex,
      `evolution report rejectedCandidates[${index}].candidateIndex`,
    ),
    candidateSeed: expectNumber(
      value.candidateSeed,
      `evolution report rejectedCandidates[${index}].candidateSeed`,
    ),
    overallScore: expectNumber(
      value.overallScore,
      `evolution report rejectedCandidates[${index}].overallScore`,
    ),
    rejectionReasons: expectStringArray(
      value.rejectionReasons,
      `evolution report rejectedCandidates[${index}].rejectionReasons`,
    ),
    summaryPath: expectString(
      value.summaryPath,
      `evolution report rejectedCandidates[${index}].summaryPath`,
    ),
  };
}

function parseDimensionScores(
  rawValue: unknown,
  label: string,
): EvolutionDimensionScores {
  const value = expectRecord(rawValue, label);
  return {
    overall: expectNumber(value.overall, `${label}.overall`),
    quality: expectNumber(value.quality, `${label}.quality`),
    difficulty: expectNumber(value.difficulty, `${label}.difficulty`),
    flow: expectNumber(value.flow, `${label}.flow`),
    rhythm: expectNumber(value.rhythm, `${label}.rhythm`),
    movement: expectNumber(value.movement, `${label}.movement`),
    pattern: expectNumber(value.pattern, `${label}.pattern`),
    slider: expectNumber(value.slider, `${label}.slider`),
    spinner: expectNumber(value.spinner, `${label}.spinner`),
    reading: expectNumber(value.reading, `${label}.reading`),
    playability: expectNumber(value.playability, `${label}.playability`),
    consistency: expectNumber(value.consistency, `${label}.consistency`),
    confidence: expectNumber(value.confidence, `${label}.confidence`),
    replay: optionalNumber(value.replay, `${label}.replay`),
  };
}

function optionalNumber(value: unknown, label: string): number {
  return value === undefined ? 0 : expectNumber(value, label);
}

function optionalUndefinedNumber(value: unknown, label: string): number | undefined {
  return value === undefined ? undefined : expectNumber(value, label);
}

function optionalString(value: unknown): string {
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value !== "string" || value.trim().length === 0) {
    return "";
  }
  return value;
}

export function formatEvolutionStarRating(stars: number): string {
  return stars.toFixed(2);
}

export function formatEvolutionScore(score: number): string {
  return score.toFixed(1);
}

function expectRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isJsonObject(value)) {
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

function expectStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value.map((item, index) =>
    expectString(item, `${label}[${index}]`),
  );
}

function expectNumberArray(value: unknown, label: string): number[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value.map((item, index) =>
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
