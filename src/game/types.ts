export const PLAYFIELD_WIDTH = 512;
export const PLAYFIELD_HEIGHT = 384;

export type GameState = "loading" | "ready" | "playing" | "finished" | "error";
export type HitObjectType = "circle" | "slider" | "spinner";
export type SliderPathType = "bezier" | "linear" | "catmull" | "perfect";
export type Judgment = "Perfect" | "Good" | "Okay" | "Miss";

export interface HitObjectPoint {
  x: number;
  y: number;
}

export interface BeatmapHitObjectBase {
  id: number;
  type: HitObjectType;
  x?: number;
  y?: number;
  time: number;
}

export interface BeatmapCircleHitObject extends BeatmapHitObjectBase {
  type: "circle";
  x: number;
  y: number;
}

export interface BeatmapSliderHitObject extends BeatmapHitObjectBase {
  type: "slider";
  x: number;
  y: number;
  endTime: number;
  pathType: SliderPathType;
  controlPoints: HitObjectPoint[];
  repeats: number;
  pixelLength: number;
}

export interface BeatmapSpinnerHitObject extends BeatmapHitObjectBase {
  type: "spinner";
  endTime: number;
}

export type BeatmapHitObject =
  | BeatmapCircleHitObject
  | BeatmapSliderHitObject
  | BeatmapSpinnerHitObject;
export type PositionedBeatmapHitObject =
  | BeatmapCircleHitObject
  | BeatmapSliderHitObject;

export interface Beatmap {
  title: string;
  artist: string;
  audio: string;
  approachTime: number;
  circleRadius: number;
  objects: BeatmapHitObject[];
}

export function isCircleHitObject(
  hitObject: BeatmapHitObject,
): hitObject is BeatmapCircleHitObject {
  return hitObject.type === "circle";
}

export function isSliderHitObject(
  hitObject: BeatmapHitObject,
): hitObject is BeatmapSliderHitObject {
  return hitObject.type === "slider";
}

export function isSpinnerHitObject(
  hitObject: BeatmapHitObject,
): hitObject is BeatmapSpinnerHitObject {
  return hitObject.type === "spinner";
}

export function hasHitObjectPosition(
  hitObject: BeatmapHitObject,
): hitObject is PositionedBeatmapHitObject {
  return hitObject.type === "circle" || hitObject.type === "slider";
}

export function getHitObjectStartTime(hitObject: BeatmapHitObject): number {
  return hitObject.time;
}

export function getHitObjectEndTime(hitObject: BeatmapHitObject): number {
  return "endTime" in hitObject ? hitObject.endTime : hitObject.time;
}

export function getHitObjectPosition(
  hitObject: BeatmapHitObject,
): HitObjectPoint | undefined {
  if (!hasHitObjectPosition(hitObject)) {
    return undefined;
  }

  return {
    x: hitObject.x,
    y: hitObject.y,
  };
}

export type ValidationSeverity = "info" | "warning" | "error" | "critical";
export type ProcessingStage =
  | "structural_safety"
  | "timing_corrections"
  | "movement_corrections"
  | "stacking_corrections"
  | "density_corrections"
  | "repetition_corrections"
  | "difficulty_corrections"
  | "local_optimization";
export type ValidationIssueCategory =
  | "structural"
  | "timing"
  | "rhythm"
  | "movement"
  | "readability"
  | "spatialBalance"
  | "repetition"
  | "densityConsistency"
  | "difficultyConsistency";
export type EstimatedBehavior =
  | "easier-than-target"
  | "within-target"
  | "harder-than-target"
  | "inconsistent";

export interface ValidationIssue {
  code: string;
  severity: ValidationSeverity;
  message: string;
  category: ValidationIssueCategory;
  objectIds: number[];
  startTimeMs?: number;
  endTimeMs?: number;
  measuredValue?: number;
  allowedValue?: number;
  suggestion?: string;
}

export interface ScoreCategories {
  structural: number;
  timing: number;
  rhythm: number;
  movement: number;
  readability: number;
  spatialBalance: number;
  repetition: number;
  densityConsistency: number;
  difficultyConsistency: number;
  overall: number;
}

export interface ReportSummary {
  critical: number;
  errors: number;
  warnings: number;
  info: number;
}

export interface ValidationReportMapInfo {
  path: string;
  title: string;
  artist: string;
  difficulty: string;
  objectCount: number;
  durationMs: number;
}

export interface StructuralMetricsSummary {
  objectCount: number;
  validObjectCount: number;
  duplicateIdCount: number;
  duplicateTimestampCount: number;
  nonFiniteValueCount: number;
}

export interface TimingMetricsSummary {
  averageAnchorDeltaMs: number;
  averageBeatDeltaMs: number;
  averageOnsetDeltaMs: number;
  excellentAlignmentCount: number;
  goodAlignmentCount: number;
  acceptableAlignmentCount: number;
  weakAlignmentCount: number;
  mistimedCount: number;
  earlyBiasCount: number;
  lateBiasCount: number;
  anchorUsage: Record<"beat" | "onset" | "none", number>;
}

export interface RhythmMetricsSummary {
  minGapMs: number;
  maxGapMs: number;
  averageGapMs: number;
  medianGapMs: number;
  gapStandardDeviationMs: number;
  gapPercentilesMs: Record<string, number>;
  rapidSequenceCount: number;
  longEmptySpaceCount: number;
  repeatedEqualGapRuns: number;
  commonRhythmIntervalsMs: number[];
}

export interface MovementMetricsSummary {
  minJumpDistance: number;
  maxJumpDistance: number;
  averageJumpDistance: number;
  highestCursorSpeed: number;
  averageCursorSpeed: number;
  speedViolationCount: number;
  nearLimitRunCount: number;
  exactStackingCount: number;
  nearStackingCount: number;
  overlapCount: number;
  largeIsolatedJumpCount: number;
}

export interface SpatialMetricsSummary {
  gridColumns: number;
  gridRows: number;
  regionCounts: Record<string, number>;
  playfieldCoveragePercent: number;
  centerUsagePercent: number;
  edgeUsagePercent: number;
  cornerUsagePercent: number;
  leftRightBalance: number;
  topBottomBalance: number;
  mostUsedRegion: string;
  leastUsedRegion: string;
}

export interface DensityWindowSummary {
  startMs: number;
  endMs: number;
  objectsPerSecond: number;
  objectCount: number;
  averageEventStrength: number;
  averageAudioEnergy: number;
  averageJumpDistance: number;
  averageCursorSpeed: number;
  timingConfidence: number;
  issueCount: number;
}

export interface DensityMetricsSummary {
  windows: DensityWindowSummary[];
  highDensityLowEnergyWindows: number;
  lowDensityHighEnergyWindows: number;
  abruptDensitySpikes: number;
  flatDensityDespiteEnergyChange: number;
  endingGapMs: number;
}

export interface RepetitionMetricsSummary {
  repeatedCoordinatePairs: number;
  repeatedTwoPointLoops: number;
  repeatedThreeObjectShapes: number;
  repeatedDistancePatterns: number;
  repeatedAnglePatterns: number;
  repeatedGapSequences: number;
  longestRepetitionRun: number;
}

export interface DifficultyMetricsSummary {
  estimatedBehavior: EstimatedBehavior;
  densityRatio: number;
  jumpRatio: number;
  speedRatio: number;
  timingComplexityRatio: number;
  spatialVariationRatio: number;
}

export interface ValidationReportMetrics {
  structural: StructuralMetricsSummary;
  timing: TimingMetricsSummary;
  rhythm: RhythmMetricsSummary;
  movement: MovementMetricsSummary;
  spatial: SpatialMetricsSummary;
  density: DensityMetricsSummary;
  repetition: RepetitionMetricsSummary;
  difficulty: DifficultyMetricsSummary;
}

export interface ValidationReport {
  version: number;
  map: ValidationReportMapInfo;
  valid: boolean;
  playable: boolean;
  scores: ScoreCategories;
  interpretation: string;
  summary: ReportSummary;
  metrics: ValidationReportMetrics;
  issues: ValidationIssue[];
}

export type CorrectionActionType =
  | "move_object"
  | "adjust_time"
  | "remove_object"
  | "insert_object";

export interface BeforeAfterSummary {
  overallScore: number;
  playable: boolean;
  critical: number;
  errors: number;
  warnings: number;
}

export interface ScoreChanges {
  overall: number;
  structural: number;
  timing: number;
  rhythm: number;
  movement: number;
  readability: number;
  spatialBalance: number;
  repetition: number;
  densityConsistency: number;
  difficultyConsistency: number;
}

export interface CorrectionSummary {
  plannedActions: number;
  acceptedActions: number;
  revertedActions: number;
  movedObjects: number;
  timingAdjustments: number;
  removedObjects: number;
  insertedObjects: number;
}

export interface CorrectionAction {
  actionId: string;
  stage: ProcessingStage;
  actionType: CorrectionActionType;
  reasonCode: string;
  objectIds: number[];
  before: Record<string, string | number | boolean | null>;
  after: Record<string, string | number | boolean | null>;
  confidence: number;
  expectedCategories: ValidationIssueCategory[];
  expectedScoreImpact: number;
  actualScoreImpact: number;
  accepted: boolean;
  rejectionReason?: string;
}

export interface CorrectionReport {
  version: number;
  sourceMap: string;
  outputMap: string;
  difficulty: string;
  seed: number;
  accepted: boolean;
  before: BeforeAfterSummary;
  after: BeforeAfterSummary;
  scoreChanges: ScoreChanges;
  summary: CorrectionSummary;
  actions: CorrectionAction[];
  rejectionReason?: string;
}

export interface CandidateScores {
  originalOverall: number;
  improvedOverall: number;
  improvement: number;
  tournamentScore: number;
  qualityScore: number;
  stabilityScore: number;
}

export interface CandidateStatus {
  valid: boolean;
  playable: boolean;
  eligible: boolean;
  rejectionReasons: string[];
}

export interface DiversitySummary {
  candidateCount: number;
  eligibleCount: number;
  uniqueCandidateCount: number;
  nearDuplicateGroups: number[][];
  averagePairwiseDiversity: number;
  minimumPairwiseDiversity: number;
  maximumPairwiseDiversity: number;
  mostUniqueCandidate?: number;
  mostDuplicatedCandidate?: number;
  pairCount: number;
}

export interface StabilitySummary {
  score: number;
  label: string;
  speedMarginRatio: number;
  gapMarginRatio: number;
  nearThresholdWarnings: number;
  revertedCorrections: number;
  acceptedCorrectionMagnitude: number;
  qualitySwing: number;
  severeSectionCount: number;
}

export interface TournamentConfiguration {
  rootSeed: number;
  candidateCount: number;
  timingVariation: boolean;
}

export interface TournamentCandidate {
  rank: number;
  candidateIndex: number;
  candidateSeed: number;
  tournamentScore: number;
  qualityScore: number;
  stabilityScore: number;
  errors: number;
  warnings: number;
  destructiveCorrections: number;
  difficultyConsistencyScore: number;
  summaryPath: string;
  mapPath: string;
  reportPath: string;
}

export interface RejectedTournamentCandidate {
  candidateIndex: number;
  candidateSeed: number;
  qualityScore: number;
  stabilityScore: number;
  rejectionReasons: string[];
  summaryPath: string;
}

export interface TournamentChampion {
  candidateIndex: number;
  candidateSeed: number;
  tournamentScore: number;
  qualityScore: number;
  stabilityScore: number;
  mapPath: string;
  reportPath: string;
  sourceMapPath: string;
  sourceReportPath: string;
  summaryPath: string;
}

export interface TournamentOverview {
  generated: number;
  eligible: number;
  rejected: number;
  unique: number;
  nearDuplicateGroups: number;
}

export interface TournamentReport {
  version: number;
  song: {
    title: string;
    artist: string;
    difficulty: string;
    audio: string;
  };
  configuration: TournamentConfiguration;
  summary: TournamentOverview;
  champion: TournamentChampion;
  ranking: TournamentCandidate[];
  rejectedCandidates: RejectedTournamentCandidate[];
  diversity: DiversitySummary;
  scoreWeights: Record<string, number>;
}

export interface JudgmentCountMap {
  Perfect: number;
  Good: number;
  Okay: number;
  Miss: number;
}

export interface ScoreSnapshot {
  score: number;
  combo: number;
  maxCombo: number;
  accuracy: number;
  resolvedObjects: number;
  totalObjects: number;
  counts: JudgmentCountMap;
  lastJudgment: Judgment | null;
}

export interface JudgmentOutcome extends ScoreSnapshot {
  judgment: Judgment;
  diffMs: number;
  scoreAwarded: number;
  judgmentValue: number;
}

export interface HudSnapshot {
  score: number;
  combo: number;
  accuracy: number;
  progress: number;
  currentJudgment: string;
  elapsedMs: number;
  durationMs: number;
}

export interface ResultsSnapshot {
  title: string;
  artist: string;
  score: number;
  accuracy: number;
  maxCombo: number;
  counts: JudgmentCountMap;
  totalObjects: number;
}

export interface SceneBindings {
  beatmap: Beatmap;
  audio: HTMLAudioElement;
}

export interface GameSceneCallbacks {
  onHudUpdate: (hud: HudSnapshot) => void;
  onResults: (results: ResultsSnapshot) => void;
  onError: (message: string) => void;
  onStateChange?: (state: GameState) => void;
}
