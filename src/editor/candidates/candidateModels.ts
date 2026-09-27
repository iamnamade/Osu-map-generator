import type { EvolutionReport } from "../../shared/evolutionReport";
import type { EvolutionQualityGate } from "../../shared/evolutionReport";
import type { EditorMapDocument } from "../models/EditorModels";

export type CandidateValidationFilter = "all" | "passed" | "failed";
export type CandidateDifficultyFilter = "all" | "easy" | "normal" | "hard";
export type CandidateSortKey =
  | "final-score"
  | "replay"
  | "difficulty"
  | "accuracy"
  | "flow"
  | "rank";

export interface CandidateFilters {
  difficulty: CandidateDifficultyFilter;
  minScore: number | null;
  maxScore: number | null;
  validation: CandidateValidationFilter;
  championOnly: boolean;
  minReplayScore: number | null;
  maxRank: number | null;
  minSectionQuality: number | null;
}

export interface CandidateSortState {
  key: CandidateSortKey;
  direction: "asc" | "desc";
}

export interface CandidateSectionReplay {
  sectionId: number;
  label: string;
  objectCount: number;
  accuracy: number;
  fatiguePeak: number;
  readingDemand: number;
}

export interface CandidateSectionRebalance {
  sectionId: number;
  label: string;
  objectCount: number;
  starRating: number;
  density: number;
  rhythmConsistency: number;
  cursorTravelPx: number;
  readingScore: number;
  fatigueAverage: number;
  qualityScore: number;
}

export interface CandidateReplayDetail {
  expectedAccuracy: number | null;
  expectedMisses: number | null;
  expectedComboPct: number | null;
  fatigueAverage: number | null;
  fatiguePeak: number | null;
  readingScore: number | null;
  replayScore: number | null;
  sections: CandidateSectionReplay[];
}

export interface CandidateRebalanceDetail {
  qualityGain: number | null;
  replayGain: number | null;
  qualityBefore: number | null;
  qualityAfter: number | null;
  sections: CandidateSectionRebalance[];
}

export interface CandidateDetailBundle {
  loading: boolean;
  loaded: boolean;
  replay: CandidateReplayDetail | null;
  rebalance: CandidateRebalanceDetail | null;
}

export interface CandidateBrowserEntry {
  candidateIndex: number;
  candidateSeed: number;
  rank: number;
  stars: number;
  difficulty: string;
  finalScore: number;
  difficultyScore: number;
  rhythmScore: number;
  patternScore: number;
  readingScore: number;
  flowScore: number;
  replayScore: number;
  predictedAccuracy: number | null;
  expectedMisses: number | null;
  expectedComboPct: number | null;
  fatigueScore: number;
  rebalanceGain: number | null;
  sectionScore: number | null;
  validationStatus: string;
  eligible: boolean;
  rejectionReasons: string[];
  champion: boolean;
  mapPath: string;
  reportPath: string;
  summaryPath: string;
  replayReportPath: string | null;
  rebalanceReportPath: string | null;
  improvementsMade: string[];
  qualityGates: EvolutionQualityGate[];
  targetDeviation: number | null;
  diversityPenalty: number | null;
}

export interface CandidateVisualDiffItem {
  kind: "shared" | "a-only" | "b-only" | "moved" | "retimed" | "moved-retimed";
  timeMs: number;
  aX?: number;
  aY?: number;
  aTime?: number;
  bX?: number;
  bY?: number;
  bTime?: number;
}

export interface CandidateVisualDiff {
  items: CandidateVisualDiffItem[];
  summary: {
    shared: number;
    aOnly: number;
    bOnly: number;
    moved: number;
    retimed: number;
    movedRetimed: number;
  };
}

export type SectionMetricDirection = "higher" | "lower";
export type SectionMetricWinner = "a" | "b" | "tie";

export interface CandidateSectionMetric {
  key: string;
  label: string;
  a: number | null;
  b: number | null;
  direction: SectionMetricDirection;
  winner: SectionMetricWinner;
}

export interface CandidateSectionComparison {
  sectionId: number;
  label: string;
  startMs: number;
  endMs: number;
  metrics: CandidateSectionMetric[];
  overallWinner: SectionMetricWinner;
}

export interface CandidateComparisonBundle {
  state: "idle" | "loading" | "ready" | "error";
  error?: string;
  candidateA?: { index: number; map: EditorMapDocument };
  candidateB?: { index: number; map: EditorMapDocument };
  visualDiff?: CandidateVisualDiff;
  sectionComparison?: CandidateSectionComparison[];
}

export interface CandidateBrowserState {
  entries: CandidateBrowserEntry[];
  details: Record<number, CandidateDetailBundle>;
  filters: CandidateFilters;
  sort: CandidateSortState;
  selectedCandidateIndex?: number;
  comparisonEnabled: boolean;
  compareCandidateIndex?: number;
  diffModeEnabled: boolean;
  comparison: CandidateComparisonBundle;
  championCandidateIndex?: number;
  championHistory: Array<{
    sequence: number;
    previousChampionIndex: number | null;
    previousMapPath: string | null;
    newChampionIndex: number;
    newChampionScore: number;
    newMapPath: string;
    timestamp: string;
    reason: string;
    manual: boolean;
  }>;
  notes: Record<string, string>;
  pendingPromotionIndex?: number;
  workspaceKey: string;
}

export function createInitialCandidateFilters(): CandidateFilters {
  return {
    difficulty: "all",
    minScore: null,
    maxScore: null,
    validation: "all",
    championOnly: false,
    minReplayScore: null,
    maxRank: null,
    minSectionQuality: null,
  };
}

export function createInitialCandidateSort(): CandidateSortState {
  return {
    key: "rank",
    direction: "asc",
  };
}

export function createInitialCandidateBrowserState(
  workspaceKey = "",
): CandidateBrowserState {
  return {
    entries: [],
    details: {},
    filters: createInitialCandidateFilters(),
    sort: createInitialCandidateSort(),
    comparisonEnabled: false,
    diffModeEnabled: false,
    comparison: { state: "idle" },
    championHistory: [],
    notes: {},
    workspaceKey,
  };
}

export function buildCandidateBrowserEntries(
  report: EvolutionReport,
): CandidateBrowserEntry[] {
  const championIndex = report.champion.candidateIndex;
  const championMapPath = report.champion.mapPath;

  return report.ranking
    .slice()
    .sort((left, right) => left.rank - right.rank)
    .map((entry) => {
      const final = entry.final;
      const reportPaths = deriveCandidateReportPaths(entry.mapPath);
      return {
        candidateIndex: entry.candidateIndex,
        candidateSeed: entry.candidateSeed,
        rank: entry.rank,
        stars: entry.stars,
        difficulty: report.song.difficulty,
        finalScore: final?.weightedScore ?? entry.scores.overall,
        difficultyScore: final?.target ?? entry.scores.difficulty,
        rhythmScore: final?.rhythm ?? entry.scores.rhythm,
        patternScore: final?.pattern ?? entry.scores.pattern,
        readingScore: final?.reading ?? entry.scores.reading,
        flowScore: final?.flow ?? entry.scores.flow,
        replayScore: final?.replay ?? entry.scores.replay,
        predictedAccuracy: null,
        expectedMisses: null,
        expectedComboPct: null,
        fatigueScore: final?.fatigue ?? 0,
        rebalanceGain: null,
        sectionScore: final?.section ?? null,
        validationStatus: entry.validationStatus ?? "passed",
        eligible: entry.eligible,
        rejectionReasons: entry.rejectionReasons,
        champion:
          entry.candidateIndex === championIndex ||
          entry.mapPath === championMapPath,
        mapPath: entry.mapPath,
        reportPath: entry.reportPath,
        summaryPath: entry.summaryPath,
        replayReportPath: reportPaths.replayReportPath,
        rebalanceReportPath: reportPaths.rebalanceReportPath,
        improvementsMade: entry.improvementsMade ?? [],
        qualityGates: entry.qualityGates ?? [],
        targetDeviation: entry.targetDeviation ?? null,
        diversityPenalty: entry.diversityPenalty ?? null,
      };
    });
}

export function deriveCandidateReportPaths(
  mapPath: string,
): {
  replayReportPath: string | null;
  rebalanceReportPath: string | null;
} {
  const slashIndex = mapPath.lastIndexOf("/");
  if (slashIndex <= 0) {
    return { replayReportPath: null, rebalanceReportPath: null };
  }

  const directory = mapPath.slice(0, slashIndex);
  return {
    replayReportPath: `${directory}/replay-report.json`,
    rebalanceReportPath: `${directory}/rebalance-report.json`,
  };
}

export function filterCandidateEntries(
  entries: CandidateBrowserEntry[],
  filters: CandidateFilters,
): CandidateBrowserEntry[] {
  return entries.filter((entry) => {
    if (filters.difficulty !== "all" && entry.difficulty !== filters.difficulty) {
      return false;
    }

    if (
      filters.minScore !== null &&
      Number.isFinite(filters.minScore) &&
      entry.finalScore < (filters.minScore as number)
    ) {
      return false;
    }

    if (
      filters.maxScore !== null &&
      Number.isFinite(filters.maxScore) &&
      entry.finalScore > (filters.maxScore as number)
    ) {
      return false;
    }

    if (
      filters.validation === "passed" &&
      entry.validationStatus !== "passed"
    ) {
      return false;
    }

    if (filters.validation === "failed" && entry.validationStatus === "passed") {
      return false;
    }

    if (filters.championOnly && !entry.champion) {
      return false;
    }

    if (
      filters.minReplayScore !== null &&
      Number.isFinite(filters.minReplayScore) &&
      entry.replayScore < (filters.minReplayScore as number)
    ) {
      return false;
    }

    if (
      filters.maxRank !== null &&
      Number.isFinite(filters.maxRank) &&
      entry.rank > (filters.maxRank as number)
    ) {
      return false;
    }

    if (
      filters.minSectionQuality !== null &&
      Number.isFinite(filters.minSectionQuality) &&
      (entry.sectionScore === null ||
        entry.sectionScore < (filters.minSectionQuality as number))
    ) {
      return false;
    }

    return true;
  });
}

export function sortCandidateEntries(
  entries: CandidateBrowserEntry[],
  sort: CandidateSortState,
): CandidateBrowserEntry[] {
  const sorted = entries.slice();
  sorted.sort((left, right) => {
    const comparison = compareCandidateEntries(left, right, sort.key);
    return sort.direction === "asc" ? comparison : -comparison;
  });
  return sorted;
}

export function compareCandidateEntries(
  left: CandidateBrowserEntry,
  right: CandidateBrowserEntry,
  key: CandidateSortKey,
): number {
  switch (key) {
    case "final-score":
      return numericCompare(left.finalScore, right.finalScore);
    case "replay":
      return numericCompare(left.replayScore, right.replayScore);
    case "difficulty":
      return numericCompare(left.stars, right.stars);
    case "accuracy":
      return nullableCompare(left.predictedAccuracy, right.predictedAccuracy);
    case "flow":
      return numericCompare(left.flowScore, right.flowScore);
    case "rank":
      return numericCompare(left.rank, right.rank);
  }
}

export function findCandidateEntry(
  entries: CandidateBrowserEntry[],
  candidateIndex: number | undefined,
): CandidateBrowserEntry | undefined {
  return entries.find((entry) => entry.candidateIndex === candidateIndex);
}

export function formatCandidateScore(value: number | null): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(1)
    : "—";
}

export function formatCandidatePercent(value: number | null): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(1)}%`
    : "—";
}

function numericCompare(left: number, right: number): number {
  return left - right;
}

function nullableCompare(left: number | null, right: number | null): number {
  if (left === null && right === null) {
    return 0;
  }

  if (left === null) {
    return 1;
  }

  if (right === null) {
    return -1;
  }

  return left - right;
}
