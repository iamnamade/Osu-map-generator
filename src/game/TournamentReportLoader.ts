import type {
  DiversitySummary,
  RejectedTournamentCandidate,
  TournamentCandidate,
  TournamentChampion,
  TournamentConfiguration,
  TournamentOverview,
  TournamentReport,
} from "./types";

type TournamentReportLoadResult =
  | { status: "ok"; report: TournamentReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadTournamentReport(
  url: string,
): Promise<TournamentReportLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Tournament report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Tournament report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Tournament report has not been generated yet.",
    };
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Tournament report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: validateTournamentReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Tournament report at ${url} is malformed: ${error.message}`
          : `Tournament report at ${url} is malformed.`,
    };
  }
}

function validateTournamentReport(rawData: unknown): TournamentReport {
  const value = expectRecord(rawData, "tournament report");
  const song = expectRecord(value.song, "tournament report.song");

  const report: TournamentReport = {
    version: expectPositiveInteger(value.version, "tournament report.version"),
    song: {
      title: expectString(song.title, "tournament report.song.title"),
      artist: expectString(song.artist, "tournament report.song.artist"),
      difficulty: expectString(song.difficulty, "tournament report.song.difficulty"),
      audio: expectPublicPath(song.audio, "tournament report.song.audio"),
    },
    configuration: validateConfiguration(value.configuration),
    summary: validateSummary(value.summary),
    champion: validateChampion(value.champion),
    ranking: expectArray(value.ranking, "tournament report.ranking").map(
      validateRankingEntry,
    ),
    rejectedCandidates: expectArray(
      value.rejectedCandidates,
      "tournament report.rejectedCandidates",
    ).map(validateRejectedCandidate),
    diversity: validateDiversity(value.diversity),
    scoreWeights: expectNumberRecord(
      value.scoreWeights,
      "tournament report.scoreWeights",
    ),
  };

  if (report.configuration.candidateCount > 100) {
    throw new Error(`tournament report.configuration.candidateCount exceeds 100.`);
  }

  if (report.summary.generated !== report.configuration.candidateCount) {
    throw new Error(
      `tournament report.summary.generated must match configuration.candidateCount.`,
    );
  }

  report.ranking.forEach((entry, index) => {
    if (entry.rank !== index + 1) {
      throw new Error(`tournament report.ranking must be sequential starting at 1.`);
    }

    if (index > 0 && entry.tournamentScore > report.ranking[index - 1].tournamentScore) {
      throw new Error(`tournament report.ranking must be sorted by descending score.`);
    }
  });

  if (!report.ranking.some((entry) => entry.candidateIndex === report.champion.candidateIndex)) {
    throw new Error(`tournament report.champion.candidateIndex must exist in ranking.`);
  }

  if (report.ranking[0]?.candidateIndex !== report.champion.candidateIndex) {
    throw new Error(`tournament report.champion must match the top-ranked candidate.`);
  }

  return report;
}

function validateConfiguration(rawValue: unknown): TournamentConfiguration {
  const value = expectRecord(rawValue, "tournament report.configuration");

  return {
    rootSeed: expectInteger(value.rootSeed, "tournament report.configuration.rootSeed"),
    candidateCount: expectPositiveInteger(
      value.candidateCount,
      "tournament report.configuration.candidateCount",
    ),
    timingVariation: expectBoolean(
      value.timingVariation,
      "tournament report.configuration.timingVariation",
    ),
  };
}

function validateSummary(rawValue: unknown): TournamentOverview {
  const value = expectRecord(rawValue, "tournament report.summary");

  return {
    generated: expectPositiveInteger(value.generated, "tournament report.summary.generated"),
    eligible: expectNonNegativeInteger(value.eligible, "tournament report.summary.eligible"),
    rejected: expectNonNegativeInteger(value.rejected, "tournament report.summary.rejected"),
    unique: expectNonNegativeInteger(value.unique, "tournament report.summary.unique"),
    nearDuplicateGroups: expectNonNegativeInteger(
      value.nearDuplicateGroups,
      "tournament report.summary.nearDuplicateGroups",
    ),
  };
}

function validateChampion(rawValue: unknown): TournamentChampion {
  const value = expectRecord(rawValue, "tournament report.champion");

  return {
    candidateIndex: expectPositiveInteger(
      value.candidateIndex,
      "tournament report.champion.candidateIndex",
    ),
    candidateSeed: expectPositiveInteger(
      value.candidateSeed,
      "tournament report.champion.candidateSeed",
    ),
    tournamentScore: expectScore(
      value.tournamentScore,
      "tournament report.champion.tournamentScore",
    ),
    qualityScore: expectScore(
      value.qualityScore,
      "tournament report.champion.qualityScore",
    ),
    stabilityScore: expectScore(
      value.stabilityScore,
      "tournament report.champion.stabilityScore",
    ),
    mapPath: expectPublicPath(value.mapPath, "tournament report.champion.mapPath"),
    reportPath: expectPublicPath(
      value.reportPath,
      "tournament report.champion.reportPath",
    ),
    sourceMapPath: expectRelativePath(
      value.sourceMapPath,
      "tournament report.champion.sourceMapPath",
    ),
    sourceReportPath: expectRelativePath(
      value.sourceReportPath,
      "tournament report.champion.sourceReportPath",
    ),
    summaryPath: expectRelativePath(
      value.summaryPath,
      "tournament report.champion.summaryPath",
    ),
  };
}

function validateRankingEntry(
  rawValue: unknown,
  index: number,
): TournamentCandidate {
  const value = expectRecord(rawValue, `tournament report.ranking[${index}]`);

  return {
    rank: expectPositiveInteger(value.rank, `tournament report.ranking[${index}].rank`),
    candidateIndex: expectPositiveInteger(
      value.candidateIndex,
      `tournament report.ranking[${index}].candidateIndex`,
    ),
    candidateSeed: expectPositiveInteger(
      value.candidateSeed,
      `tournament report.ranking[${index}].candidateSeed`,
    ),
    tournamentScore: expectScore(
      value.tournamentScore,
      `tournament report.ranking[${index}].tournamentScore`,
    ),
    qualityScore: expectScore(
      value.qualityScore,
      `tournament report.ranking[${index}].qualityScore`,
    ),
    stabilityScore: expectScore(
      value.stabilityScore,
      `tournament report.ranking[${index}].stabilityScore`,
    ),
    errors: expectNonNegativeInteger(
      value.errors,
      `tournament report.ranking[${index}].errors`,
    ),
    warnings: expectNonNegativeInteger(
      value.warnings,
      `tournament report.ranking[${index}].warnings`,
    ),
    destructiveCorrections: expectNonNegativeInteger(
      value.destructiveCorrections,
      `tournament report.ranking[${index}].destructiveCorrections`,
    ),
    difficultyConsistencyScore: expectScore(
      value.difficultyConsistencyScore,
      `tournament report.ranking[${index}].difficultyConsistencyScore`,
    ),
    summaryPath: expectRelativePath(
      value.summaryPath,
      `tournament report.ranking[${index}].summaryPath`,
    ),
    mapPath: expectRelativePath(
      value.mapPath,
      `tournament report.ranking[${index}].mapPath`,
    ),
    reportPath: expectRelativePath(
      value.reportPath,
      `tournament report.ranking[${index}].reportPath`,
    ),
  };
}

function validateRejectedCandidate(
  rawValue: unknown,
  index: number,
): RejectedTournamentCandidate {
  const value = expectRecord(
    rawValue,
    `tournament report.rejectedCandidates[${index}]`,
  );

  return {
    candidateIndex: expectPositiveInteger(
      value.candidateIndex,
      `tournament report.rejectedCandidates[${index}].candidateIndex`,
    ),
    candidateSeed: expectPositiveInteger(
      value.candidateSeed,
      `tournament report.rejectedCandidates[${index}].candidateSeed`,
    ),
    qualityScore: expectScore(
      value.qualityScore,
      `tournament report.rejectedCandidates[${index}].qualityScore`,
    ),
    stabilityScore: expectScore(
      value.stabilityScore,
      `tournament report.rejectedCandidates[${index}].stabilityScore`,
    ),
    rejectionReasons: expectStringArray(
      value.rejectionReasons,
      `tournament report.rejectedCandidates[${index}].rejectionReasons`,
    ),
    summaryPath: expectRelativePath(
      value.summaryPath,
      `tournament report.rejectedCandidates[${index}].summaryPath`,
    ),
  };
}

function validateDiversity(rawValue: unknown): DiversitySummary {
  const value = expectRecord(rawValue, "tournament report.diversity");

  return {
    candidateCount: expectPositiveInteger(
      value.candidateCount,
      "tournament report.diversity.candidateCount",
    ),
    eligibleCount: expectNonNegativeInteger(
      value.eligibleCount,
      "tournament report.diversity.eligibleCount",
    ),
    uniqueCandidateCount: expectNonNegativeInteger(
      value.uniqueCandidateCount,
      "tournament report.diversity.uniqueCandidateCount",
    ),
    nearDuplicateGroups: expectArray(
      value.nearDuplicateGroups,
      "tournament report.diversity.nearDuplicateGroups",
    ).map((group, groupIndex) =>
      expectNumberArray(
        group,
        `tournament report.diversity.nearDuplicateGroups[${groupIndex}]`,
      ),
    ),
    averagePairwiseDiversity: expectScore(
      value.averagePairwiseDiversity,
      "tournament report.diversity.averagePairwiseDiversity",
    ),
    minimumPairwiseDiversity: expectScore(
      value.minimumPairwiseDiversity,
      "tournament report.diversity.minimumPairwiseDiversity",
    ),
    maximumPairwiseDiversity: expectScore(
      value.maximumPairwiseDiversity,
      "tournament report.diversity.maximumPairwiseDiversity",
    ),
    mostUniqueCandidate: expectOptionalInteger(
      value.mostUniqueCandidate,
      "tournament report.diversity.mostUniqueCandidate",
    ),
    mostDuplicatedCandidate: expectOptionalInteger(
      value.mostDuplicatedCandidate,
      "tournament report.diversity.mostDuplicatedCandidate",
    ),
    pairCount: expectNonNegativeInteger(
      value.pairCount,
      "tournament report.diversity.pairCount",
    ),
  };
}

function expectRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (typeof value !== "object" || value === null) {
    throw new Error(`${label} must be an object.`);
  }

  return value as Record<string, unknown>;
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

function expectRelativePath(value: unknown, label: string): string {
  const path = expectString(value, label);

  if (path.startsWith("/") || path.startsWith("\\")) {
    throw new Error(`${label} must be a relative project path.`);
  }

  return path;
}

function expectPublicPath(value: unknown, label: string): string {
  const path = expectString(value, label);

  if (!path.startsWith("/")) {
    throw new Error(`${label} must be a public path starting with "/".`);
  }

  return path;
}

function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }

  return value;
}

function expectNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number.`);
  }

  return value;
}

function expectInteger(value: unknown, label: string): number {
  const numeric = expectNumber(value, label);

  if (!Number.isInteger(numeric)) {
    throw new Error(`${label} must be an integer.`);
  }

  return numeric;
}

function expectPositiveInteger(value: unknown, label: string): number {
  const numeric = expectInteger(value, label);

  if (numeric <= 0) {
    throw new Error(`${label} must be greater than zero.`);
  }

  return numeric;
}

function expectNonNegativeInteger(value: unknown, label: string): number {
  const numeric = expectInteger(value, label);

  if (numeric < 0) {
    throw new Error(`${label} must not be negative.`);
  }

  return numeric;
}

function expectOptionalInteger(
  value: unknown,
  label: string,
): number | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }

  return expectInteger(value, label);
}

function expectScore(value: unknown, label: string): number {
  const numeric = expectNumber(value, label);

  if (numeric < 0 || numeric > 100) {
    throw new Error(`${label} must stay between 0 and 100.`);
  }

  return numeric;
}

function expectStringArray(value: unknown, label: string): string[] {
  return expectArray(value, label).map((item, index) =>
    expectString(item, `${label}[${index}]`),
  );
}

function expectNumberArray(value: unknown, label: string): number[] {
  return expectArray(value, label).map((item, index) =>
    expectPositiveInteger(item, `${label}[${index}]`),
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

export type { TournamentReportLoadResult };
