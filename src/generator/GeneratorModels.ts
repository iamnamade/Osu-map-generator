import type { RuntimeProjectMapSelection } from "../shared/mapCatalog";

export type DifficultyName = "easy" | "normal" | "hard";
export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type WizardStep =
  | "upload"
  | "metadata"
  | "difficulties"
  | "generate"
  | "results";
export type TransferStatus = "idle" | "uploading" | "uploaded" | "error";

export interface AudioMetadataSuggestion {
  title?: string | null;
  artist?: string | null;
  durationMs?: number | null;
  sampleRate?: number | null;
  codec?: string | null;
  bitrateKbps?: number | null;
}

export type MappingPresetName =
  | "balanced"
  | "technical"
  | "aim"
  | "rhythm"
  | "tournament"
  | "custom";

export type DifficultyTargetMode = "auto" | "custom";
export type SeedMode = "auto" | "manual";

export interface MappingControlValues {
  circleDensity: number;
  sliderDensity: number;
  spinnerFrequency: number;
  jumpIntensity: number;
  streamIntensity: number;
  burstIntensity: number;
  rhythmComplexity: number;
  patternVariety: number;
  spacing: number;
  aggression: number;
}

export interface DifficultySettings extends MappingControlValues {
  candidateCount: number;
  rootSeed: number;
  timingVariation: boolean;
  tournamentEnabled: boolean;
  hybridAssemblyEnabled: boolean;
  mappingPreset: MappingPresetName;
  difficultyTarget: DifficultyTargetMode;
  customTargetStar?: number | null;
  customMinStar?: number | null;
  customMaxStar?: number | null;
  evolutionPasses: number;
  seedMode: SeedMode;
  replayProfile: string;
  sectionSensitivity: number;
}

export interface WorkspaceMetadata {
  title: string;
  titleUnicode?: string | null;
  artist: string;
  artistUnicode?: string | null;
  creator: string;
  source: string;
  tags: string;
  backgroundFilename?: string | null;
  selectedDifficulties: DifficultyName[];
  difficultySettings: Record<DifficultyName, DifficultySettings>;
}

export interface UploadedFileDescriptor {
  originalFilename: string;
  normalizedFilename: string;
  relativePath: string;
  sizeBytes: number;
  contentType: string;
  sha256: string;
  detectedMetadata?: AudioMetadataSuggestion | null;
}

export interface ArtifactDescriptor {
  id: string;
  workspaceId: string;
  group: string;
  kind: string;
  label: string;
  relativePath: string;
  fileName: string;
  contentType: string;
  sizeBytes: number;
  difficulty?: DifficultyName | null;
  downloadUrl: string;
}

export interface ArtifactGroup {
  group: string;
  items: ArtifactDescriptor[];
}

export interface FinalDifficultyResult {
  difficulty: DifficultyName;
  finalMapKind: string;
  objectCount?: number | null;
  score?: number | null;
  candidateWinner?: number | null;
  sectionCount?: number | null;
  promoted?: boolean | null;
  mapArtifactId?: string | null;
  osuArtifactId?: string | null;
}

export interface JobResultSummary {
  title: string;
  artist: string;
  audioDurationMs?: number | null;
  selectedDifficulties: DifficultyName[];
  packageArtifactId?: string | null;
  packageSizeBytes?: number | null;
  sectionCount?: number | null;
  difficulties: FinalDifficultyResult[];
}

export interface WorkspaceManifest {
  schemaVersion: number;
  workspaceId: string;
  createdAt: string;
  updatedAt: string;
  audio?: UploadedFileDescriptor | null;
  background?: UploadedFileDescriptor | null;
  metadata: WorkspaceMetadata;
  configurationSignature?: string | null;
  lastRunSignature?: string | null;
  jobStatus?: JobStatus | null;
  availableArtifacts: ArtifactDescriptor[];
  lastResult?: JobResultSummary | null;
}

export interface WorkspaceResponse {
  workspace: WorkspaceManifest;
  artifacts: ArtifactGroup[];
  readyForGeneration: boolean;
}

export interface AudioUploadResponse extends WorkspaceResponse {
  detectedMetadata: AudioMetadataSuggestion;
}

export type BackgroundUploadResponse = WorkspaceResponse;

export interface HealthResponse {
  status: "ok";
  version: number;
  pipelineAvailable: boolean;
}

export interface JobEvent {
  index: number;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
}

// P2.4: server-measured wall-clock duration for a finished pipeline stage.
export interface StageTiming {
  index: number;
  stage: string;
  label: string;
  difficulty?: DifficultyName | null;
  durationMs: number;
  status: "completed" | "failed" | "cancelled";
}

export interface JobStateResponse {
  jobId: string;
  workspaceId: string;
  status: JobStatus;
  currentStage?: string | null;
  currentStageLabel?: string | null;
  completedStages: number;
  totalStages: number;
  overallProgressPercent: number;
  currentDifficulty?: DifficultyName | null;
  currentCandidate?: number | null;
  candidatesCompleted?: number | null;
  candidatesTotal?: number | null;
  latestMessage: string;
  warnings: string[];
  errors: string[];
  artifactIds: string[];
  technicalDetails?: string | null;
  startedAt: string;
  updatedAt: string;
  finishedAt?: string | null;
  events: JobEvent[];
  stageTimings?: StageTiming[];
  result?: JobResultSummary | null;
}

export interface FileTransferState {
  status: TransferStatus;
  progressPercent: number;
  fileName?: string;
  fileSizeBytes?: number;
  error?: string;
}

export interface GeneratorState {
  bootState: "booting" | "ready" | "error";
  currentStep: WizardStep;
  workspace?: WorkspaceResponse;
  detectedMetadata?: AudioMetadataSuggestion;
  metadataDraft: WorkspaceMetadata;
  audioUpload: FileTransferState;
  backgroundUpload: FileTransferState;
  job?: JobStateResponse;
  jobId?: string;
  healthStatus: "checking" | "ready" | "error";
  healthMessage: string;
  busyMessage?: string;
  errorMessage?: string;
  noticeMessage?: string;
  advancedSettingsOpen: boolean;
  logsExpanded: boolean;
  technicalDetailsExpanded: boolean;
}

export interface WizardStepDescriptor {
  id: WizardStep;
  label: string;
  shortLabel: string;
}

export interface DifficultyCardDescriptor {
  difficulty: DifficultyName;
  label: string;
  description: string;
  defaultCandidateCount: number;
  processingCost: string;
}

export const WIZARD_STEPS: WizardStepDescriptor[] = [
  { id: "upload", label: "Upload", shortLabel: "1" },
  { id: "metadata", label: "Metadata", shortLabel: "2" },
  { id: "difficulties", label: "Difficulties", shortLabel: "3" },
  { id: "generate", label: "Generate", shortLabel: "4" },
  { id: "results", label: "Results", shortLabel: "5" },
];

export const DIFFICULTY_CARDS: DifficultyCardDescriptor[] = [
  {
    difficulty: "easy",
    label: "Easy",
    description:
      "Smoother jumps, wider timing gaps, and a more readable beginner-friendly pulse.",
    defaultCandidateCount: 8,
    processingCost: "Lowest processing cost",
  },
  {
    difficulty: "normal",
    label: "Normal",
    description:
      "Balanced density with stronger off-beat detail and moderate movement variety.",
    defaultCandidateCount: 10,
    processingCost: "Medium processing cost",
  },
  {
    difficulty: "hard",
    label: "Hard",
    description:
      "Faster reads, tighter rhythms, and more assertive cursor travel across the playfield.",
    defaultCandidateCount: 12,
    processingCost: "Highest processing cost",
  },
];

export function createDefaultMappingControlValues(): MappingControlValues {
  return {
    circleDensity: 0.5,
    sliderDensity: 0.5,
    spinnerFrequency: 0.5,
    jumpIntensity: 0.5,
    streamIntensity: 0.5,
    burstIntensity: 0.5,
    rhythmComplexity: 0.5,
    patternVariety: 0.5,
    spacing: 0.5,
    aggression: 0.5,
  };
}

export function createEmptyDifficultySettings(): DifficultySettings {
  return {
    ...createDefaultMappingControlValues(),
    candidateCount: 8,
    rootSeed: 42,
    timingVariation: false,
    tournamentEnabled: true,
    hybridAssemblyEnabled: true,
    mappingPreset: "balanced",
    difficultyTarget: "auto",
    customTargetStar: null,
    customMinStar: null,
    customMaxStar: null,
    evolutionPasses: 2,
    seedMode: "auto",
    replayProfile: "advanced",
    sectionSensitivity: 0.5,
  };
}

export function createEmptyMetadataDraft(): WorkspaceMetadata {
  return {
    title: "",
    titleUnicode: "",
    artist: "",
    artistUnicode: "",
    creator: "osu-map-ai",
    source: "",
    tags: "",
    backgroundFilename: undefined,
    selectedDifficulties: [],
    difficultySettings: {
      easy: {
        ...createEmptyDifficultySettings(),
        candidateCount: 8,
      },
      normal: {
        ...createEmptyDifficultySettings(),
        candidateCount: 10,
      },
      hard: {
        ...createEmptyDifficultySettings(),
        candidateCount: 12,
      },
    },
  };
}

export function cloneWorkspaceMetadata(metadata: WorkspaceMetadata): WorkspaceMetadata {
  return {
    title: metadata.title,
    titleUnicode: metadata.titleUnicode ?? "",
    artist: metadata.artist,
    artistUnicode: metadata.artistUnicode ?? "",
    creator: metadata.creator,
    source: metadata.source,
    tags: metadata.tags,
    backgroundFilename: metadata.backgroundFilename ?? undefined,
    selectedDifficulties: [...metadata.selectedDifficulties],
    difficultySettings: {
      easy: { ...metadata.difficultySettings.easy },
      normal: { ...metadata.difficultySettings.normal },
      hard: { ...metadata.difficultySettings.hard },
    },
  };
}

export interface MappingPresetDescriptor {
  name: MappingPresetName;
  label: string;
  description: string;
  controls: MappingControlValues;
}

export const MAPPING_PRESETS: MappingPresetDescriptor[] = [
  {
    name: "balanced",
    label: "Balanced",
    description: "Default general-purpose mapping.",
    controls: createDefaultMappingControlValues(),
  },
  {
    name: "technical",
    label: "Technical",
    description: "Higher rhythm complexity and pattern density.",
    controls: {
      circleDensity: 0.62,
      sliderDensity: 0.42,
      spinnerFrequency: 0.38,
      jumpIntensity: 0.55,
      streamIntensity: 0.7,
      burstIntensity: 0.68,
      rhythmComplexity: 0.78,
      patternVariety: 0.72,
      spacing: 0.56,
      aggression: 0.6,
    },
  },
  {
    name: "aim",
    label: "Aim",
    description: "Higher movement and jump emphasis.",
    controls: {
      circleDensity: 0.55,
      sliderDensity: 0.4,
      spinnerFrequency: 0.4,
      jumpIntensity: 0.8,
      streamIntensity: 0.45,
      burstIntensity: 0.45,
      rhythmComplexity: 0.55,
      patternVariety: 0.65,
      spacing: 0.72,
      aggression: 0.68,
    },
  },
  {
    name: "rhythm",
    label: "Rhythm",
    description: "Higher rhythm complexity with controlled movement.",
    controls: {
      circleDensity: 0.62,
      sliderDensity: 0.55,
      spinnerFrequency: 0.42,
      jumpIntensity: 0.42,
      streamIntensity: 0.58,
      burstIntensity: 0.6,
      rhythmComplexity: 0.82,
      patternVariety: 0.6,
      spacing: 0.48,
      aggression: 0.55,
    },
  },
  {
    name: "tournament",
    label: "Tournament",
    description: "Stricter readability, consistency, and replay constraints.",
    controls: {
      circleDensity: 0.55,
      sliderDensity: 0.45,
      spinnerFrequency: 0.35,
      jumpIntensity: 0.55,
      streamIntensity: 0.5,
      burstIntensity: 0.5,
      rhythmComplexity: 0.6,
      patternVariety: 0.55,
      spacing: 0.55,
      aggression: 0.5,
    },
  },
];

export interface MappingControlDescriptor {
  key: keyof MappingControlValues;
  label: string;
  lowLabel: string;
  highLabel: string;
  hint: string;
}

export const MAPPING_CONTROLS: MappingControlDescriptor[] = [
  {
    key: "circleDensity",
    label: "Circle Density",
    lowLabel: "Low",
    highLabel: "High",
    hint: "How many musical events become hit circles.",
  },
  {
    key: "sliderDensity",
    label: "Slider Density",
    lowLabel: "Low",
    highLabel: "High",
    hint: "How often suitable musical events become sliders.",
  },
  {
    key: "spinnerFrequency",
    label: "Spinner Frequency",
    lowLabel: "None",
    highLabel: "Frequent",
    hint: "0% disables spinners; higher values widen musical spinner windows.",
  },
  {
    key: "jumpIntensity",
    label: "Jump Intensity",
    lowLabel: "Low",
    highLabel: "High",
    hint: "Maximum and average jump distance plus cursor speed.",
  },
  {
    key: "streamIntensity",
    label: "Stream Intensity",
    lowLabel: "Low",
    highLabel: "High",
    hint: "Longer rhythm runs with finer timing resolution.",
  },
  {
    key: "burstIntensity",
    label: "Burst Intensity",
    lowLabel: "Low",
    highLabel: "High",
    hint: "Short bursts of tightly packed objects.",
  },
  {
    key: "rhythmComplexity",
    label: "Rhythm Complexity",
    lowLabel: "Simple",
    highLabel: "Complex",
    hint: "Off-beats, subdivisions, and syncopation.",
  },
  {
    key: "patternVariety",
    label: "Pattern Variety",
    lowLabel: "Repetitive",
    highLabel: "Varied",
    hint: "How often the pattern family switches.",
  },
  {
    key: "spacing",
    label: "Spacing",
    lowLabel: "Compact",
    highLabel: "Wide",
    hint: "Object-to-object distance and pattern scale.",
  },
  {
    key: "aggression",
    label: "Mapping Aggression",
    lowLabel: "Calm",
    highLabel: "Aggressive",
    hint: "Composite pull across density, movement, and variety.",
  },
];

export const REPLAY_PROFILES: Array<{ value: string; label: string }> = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
  { value: "tournament", label: "Tournament" },
  { value: "custom", label: "Custom" },
];

export function findMappingPreset(
  name: string,
): MappingPresetDescriptor | undefined {
  return MAPPING_PRESETS.find((preset) => preset.name === name);
}

export function applyMappingPresetToSettings(
  settings: DifficultySettings,
  presetName: MappingPresetName,
): DifficultySettings {
  const preset = findMappingPreset(presetName);
  if (!preset || presetName === "custom") {
    return { ...settings, mappingPreset: presetName };
  }
  return {
    ...settings,
    ...preset.controls,
    mappingPreset: presetName,
  };
}

/**
 * P1.4: copy the shared, tier-agnostic generation settings from one difficulty
 * onto another so users do not have to re-enter the mapping controls for every
 * tier. Per-tier values that are intentionally different stay untouched:
 * ``candidateCount`` (each tier has its own processing budget) and the seed
 * (``rootSeed``/``seedMode``) so deterministic runs are not silently shared.
 */
export function applySharedGenerationSettings(
  source: DifficultySettings,
  target: DifficultySettings,
): DifficultySettings {
  return {
    ...target,
    ...source,
    candidateCount: target.candidateCount,
    rootSeed: target.rootSeed,
    seedMode: target.seedMode,
  };
}

export function toPercent(value: number): number {
  return Math.round(value * 100);
}

export function difficultyTargetLabel(mode: DifficultyTargetMode): string {
  return mode === "custom" ? "Custom" : "Auto";
}

export function createInitialFileTransferState(): FileTransferState {
  return {
    status: "idle",
    progressPercent: 0,
  };
}

export function createInitialGeneratorState(): GeneratorState {
  return {
    bootState: "booting",
    currentStep: "upload",
    metadataDraft: createEmptyMetadataDraft(),
    audioUpload: createInitialFileTransferState(),
    backgroundUpload: createInitialFileTransferState(),
    healthStatus: "checking",
    healthMessage: "Checking local API availability...",
    advancedSettingsOpen: false,
    logsExpanded: false,
    technicalDetailsExpanded: false,
  };
}

export function isTerminalJobStatus(status: JobStatus): boolean {
  return (
    status === "completed" ||
    status === "failed" ||
    status === "cancelled"
  );
}

export function findArtifactById(
  artifacts: ArtifactDescriptor[],
  artifactId: string | null | undefined,
): ArtifactDescriptor | undefined {
  if (!artifactId) {
    return undefined;
  }

  return artifacts.find((item) => item.id === artifactId);
}

export function findArtifactByRelativePath(
  artifacts: ArtifactDescriptor[],
  relativePath: string,
): ArtifactDescriptor | undefined {
  return artifacts.find((item) => item.relativePath === relativePath);
}

export function buildDifficultyPreviewSelection(
  workspace: WorkspaceResponse,
  result: FinalDifficultyResult,
): RuntimeProjectMapSelection | undefined {
  const mapArtifact = findArtifactById(
    workspace.workspace.availableArtifacts,
    result.mapArtifactId,
  );
  if (!mapArtifact) {
    return undefined;
  }

  const relativeReportDirectory =
    result.finalMapKind === "hybrid"
      ? "hybrid"
      : result.finalMapKind === "champion"
        ? "champions"
        : result.finalMapKind === "improved"
          ? "improved"
          : "generated";

  const difficulty = result.difficulty;
  return {
    path: mapArtifact.downloadUrl,
    label: `${workspace.workspace.metadata.title} ${buildPreviewVersionLabel(result)}`,
    kind: toRuntimeKind(result.finalMapKind),
    difficulty,
    description: buildPreviewDescription(result),
    reportPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `reports/${relativeReportDirectory}/${difficulty}-report.json`,
    )?.downloadUrl,
    correctionReportPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `reports/corrections/${difficulty}-corrections.json`,
    )?.downloadUrl,
    tournamentReportPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `reports/tournaments/${difficulty}-tournament.json`,
    )?.downloadUrl,
    evolutionReportPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `reports/evolution/${difficulty}-evolution.json`,
    )?.downloadUrl,
    analysisPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      "analysis/analysis.json",
    )?.downloadUrl,
    sectionAnalysisPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      "sections/sections.json",
    )?.downloadUrl,
    recoveryAnalysisPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `sections/recovery-${difficulty}.json`,
    )?.downloadUrl,
    hybridAssemblyPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `hybrids/${difficulty}-assembly.json`,
    )?.downloadUrl,
    hybridTransitionLogPath: findArtifactByRelativePath(
      workspace.workspace.availableArtifacts,
      `hybrids/${difficulty}-transitions.json`,
    )?.downloadUrl,
  };
}

export function buildPreviewVersionLabel(result: FinalDifficultyResult): string {
  const difficultyLabel = capitalize(result.difficulty);
  if (result.finalMapKind === "hybrid") {
    return `Hybrid ${difficultyLabel}`;
  }
  if (result.finalMapKind === "champion") {
    return `Champion ${difficultyLabel}`;
  }
  if (result.finalMapKind === "improved") {
    return `Improved ${difficultyLabel}`;
  }
  return difficultyLabel;
}

export function buildPreviewDescription(result: FinalDifficultyResult): string {
  const versionLabel = buildPreviewVersionLabel(result);
  if (result.finalMapKind === "hybrid") {
    return `${versionLabel} with section-aware assembly and validator-backed promotion checks.`;
  }
  if (result.finalMapKind === "champion") {
    return `${versionLabel} selected by the deterministic candidate evolution engine after generating, evaluating, and ranking multiple candidates.`;
  }
  if (result.finalMapKind === "improved") {
    return `${versionLabel} after deterministic post-processing and validation corrections.`;
  }
  return `${versionLabel} generated directly from the uploaded audio analysis.`;
}

export function formatBytes(sizeBytes: number | null | undefined): string {
  if (typeof sizeBytes !== "number" || !Number.isFinite(sizeBytes) || sizeBytes < 0) {
    return "Unknown size";
  }

  const units = ["B", "KB", "MB", "GB"];
  let value = sizeBytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  const digits = unitIndex === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

export function capitalize(value: string): string {
  if (!value) {
    return value;
  }

  return `${value[0]?.toUpperCase() ?? ""}${value.slice(1)}`;
}

function toRuntimeKind(value: string): RuntimeProjectMapSelection["kind"] {
  if (
    value === "manual" ||
    value === "generated" ||
    value === "improved" ||
    value === "champion" ||
    value === "hybrid" ||
    value === "imported"
  ) {
    return value;
  }

  return "generated";
}
