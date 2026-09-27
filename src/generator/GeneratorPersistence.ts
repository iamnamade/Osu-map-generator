import type {
  AudioMetadataSuggestion,
  GeneratorState,
  WizardStep,
  WorkspaceMetadata,
} from "./GeneratorModels";
import { createEmptyMetadataDraft, cloneWorkspaceMetadata } from "./GeneratorModels";
import { isWizardStep, validateMetadataDraft } from "./GeneratorValidation";

const STORAGE_KEY = "pulse-practice-generator-state";
const STORAGE_VERSION = 1;

export interface PersistedGeneratorState {
  version: 1;
  currentStep: WizardStep;
  workspaceId?: string;
  jobId?: string;
  metadataDraft: WorkspaceMetadata;
  advancedSettingsOpen: boolean;
  logsExpanded: boolean;
  technicalDetailsExpanded: boolean;
  detectedMetadata?: AudioMetadataSuggestion;
}

export function loadPersistedGeneratorState():
  | PersistedGeneratorState
  | undefined {
  if (!canUseStorage()) {
    return undefined;
  }

  const rawValue = window.localStorage.getItem(STORAGE_KEY);
  if (!rawValue) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!isPersistedGeneratorState(parsed)) {
      return undefined;
    }

    const restoredMetadataDraft = parseMetadataDraft(parsed.metadataDraft);
    if (!restoredMetadataDraft) {
      return undefined;
    }

    return {
      ...parsed,
      metadataDraft: cloneWorkspaceMetadata(restoredMetadataDraft),
      detectedMetadata: parsed.detectedMetadata
        ? { ...parsed.detectedMetadata }
        : undefined,
    };
  } catch {
    return undefined;
  }
}

export function savePersistedGeneratorState(state: GeneratorState): void {
  if (!canUseStorage()) {
    return;
  }

  const payload: PersistedGeneratorState = {
    version: STORAGE_VERSION,
    currentStep: state.currentStep,
    workspaceId: state.workspace?.workspace.workspaceId,
    jobId: state.job?.jobId,
    metadataDraft: cloneWorkspaceMetadata(state.metadataDraft),
    advancedSettingsOpen: state.advancedSettingsOpen,
    logsExpanded: state.logsExpanded,
    technicalDetailsExpanded: state.technicalDetailsExpanded,
    detectedMetadata: state.detectedMetadata
      ? { ...state.detectedMetadata }
      : undefined,
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function clearPersistedGeneratorState(): void {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.removeItem(STORAGE_KEY);
}

export function buildPersistenceFallback(): PersistedGeneratorState {
  return {
    version: STORAGE_VERSION,
    currentStep: "upload",
    metadataDraft: createEmptyMetadataDraft(),
    advancedSettingsOpen: false,
    logsExpanded: false,
    technicalDetailsExpanded: false,
  };
}

function isPersistedGeneratorState(
  value: unknown,
): value is PersistedGeneratorState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Record<string, unknown>;
  if (record.version !== STORAGE_VERSION || !isWizardStep(record.currentStep)) {
    return false;
  }

  const metadataDraft = parseMetadataDraft(record.metadataDraft);
  if (!metadataDraft) {
    return false;
  }

  const metadataErrors = validateMetadataDraft(metadataDraft);
  if (
    metadataDraft.title.trim().length > 0 &&
    metadataErrors.fieldErrors.title
  ) {
    return false;
  }

  if (
    metadataDraft.artist.trim().length > 0 &&
    metadataErrors.fieldErrors.artist
  ) {
    return false;
  }

  return (
    (record.workspaceId === undefined || typeof record.workspaceId === "string") &&
    (record.jobId === undefined || typeof record.jobId === "string") &&
    typeof record.advancedSettingsOpen === "boolean" &&
    typeof record.logsExpanded === "boolean" &&
    typeof record.technicalDetailsExpanded === "boolean"
  );
}

function parseMetadataDraft(value: unknown): WorkspaceMetadata | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }

  const defaults = createEmptyMetadataDraft();
  const record = value as Record<string, unknown>;
  const selectedDifficulties = Array.isArray(record.selectedDifficulties)
    ? record.selectedDifficulties.filter(isDifficultyName)
    : defaults.selectedDifficulties;
  const difficultySettings = parseDifficultySettingsRecord(
    record.difficultySettings,
    defaults,
  );

  return {
    title: typeof record.title === "string" ? record.title : defaults.title,
    titleUnicode:
      typeof record.titleUnicode === "string" ? record.titleUnicode : "",
    artist: typeof record.artist === "string" ? record.artist : defaults.artist,
    artistUnicode:
      typeof record.artistUnicode === "string" ? record.artistUnicode : "",
    creator:
      typeof record.creator === "string" && record.creator.trim().length > 0
        ? record.creator
        : defaults.creator,
    source: typeof record.source === "string" ? record.source : defaults.source,
    tags: typeof record.tags === "string" ? record.tags : defaults.tags,
    backgroundFilename:
      typeof record.backgroundFilename === "string"
        ? record.backgroundFilename
        : undefined,
    selectedDifficulties,
    difficultySettings,
  };
}

function parseDifficultySettingsRecord(
  value: unknown,
  defaults: WorkspaceMetadata,
): WorkspaceMetadata["difficultySettings"] {
  const record =
    typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)
      : {};

  return {
    easy: parseDifficultySettings(record.easy, defaults.difficultySettings.easy),
    normal: parseDifficultySettings(
      record.normal,
      defaults.difficultySettings.normal,
    ),
    hard: parseDifficultySettings(record.hard, defaults.difficultySettings.hard),
  };
}

function parseDifficultySettings(
  value: unknown,
  fallback: WorkspaceMetadata["difficultySettings"][keyof WorkspaceMetadata["difficultySettings"]],
) {
  if (typeof value !== "object" || value === null) {
    return { ...fallback };
  }

  const record = value as Record<string, unknown>;
  return {
    candidateCount:
      typeof record.candidateCount === "number" &&
      Number.isFinite(record.candidateCount)
        ? Math.round(record.candidateCount)
        : fallback.candidateCount,
    rootSeed:
      typeof record.rootSeed === "number" && Number.isFinite(record.rootSeed)
        ? Math.round(record.rootSeed)
        : fallback.rootSeed,
    timingVariation:
      typeof record.timingVariation === "boolean"
        ? record.timingVariation
        : fallback.timingVariation,
    tournamentEnabled:
      typeof record.tournamentEnabled === "boolean"
        ? record.tournamentEnabled
        : fallback.tournamentEnabled,
    hybridAssemblyEnabled:
      typeof record.hybridAssemblyEnabled === "boolean"
        ? record.hybridAssemblyEnabled
        : fallback.hybridAssemblyEnabled,
    // Phase 19 mapping controls (safe defaults when absent).
    mappingPreset: isMappingPresetName(record.mappingPreset)
      ? record.mappingPreset
      : fallback.mappingPreset,
    difficultyTarget:
      record.difficultyTarget === "custom" ? "custom" : fallback.difficultyTarget,
    customTargetStar: parseOptionalNumber(record.customTargetStar, fallback.customTargetStar),
    customMinStar: parseOptionalNumber(record.customMinStar, fallback.customMinStar),
    customMaxStar: parseOptionalNumber(record.customMaxStar, fallback.customMaxStar),
    circleDensity: parseClampedControl(record.circleDensity, fallback.circleDensity),
    sliderDensity: parseClampedControl(record.sliderDensity, fallback.sliderDensity),
    spinnerFrequency: parseClampedControl(record.spinnerFrequency, fallback.spinnerFrequency),
    jumpIntensity: parseClampedControl(record.jumpIntensity, fallback.jumpIntensity),
    streamIntensity: parseClampedControl(record.streamIntensity, fallback.streamIntensity),
    burstIntensity: parseClampedControl(record.burstIntensity, fallback.burstIntensity),
    rhythmComplexity: parseClampedControl(record.rhythmComplexity, fallback.rhythmComplexity),
    patternVariety: parseClampedControl(record.patternVariety, fallback.patternVariety),
    spacing: parseClampedControl(record.spacing, fallback.spacing),
    aggression: parseClampedControl(record.aggression, fallback.aggression),
    evolutionPasses:
      typeof record.evolutionPasses === "number" &&
      Number.isFinite(record.evolutionPasses)
        ? Math.min(5, Math.max(1, Math.round(record.evolutionPasses)))
        : fallback.evolutionPasses,
    seedMode: record.seedMode === "manual" ? "manual" : fallback.seedMode,
    replayProfile:
      typeof record.replayProfile === "string" &&
      isReplayProfile(record.replayProfile)
        ? record.replayProfile
        : fallback.replayProfile,
    sectionSensitivity: parseClampedControl(
      record.sectionSensitivity,
      fallback.sectionSensitivity,
    ),
  };
}

function isDifficultyName(value: unknown): value is "easy" | "normal" | "hard" {
  return value === "easy" || value === "normal" || value === "hard";
}

function isMappingPresetName(
  value: unknown,
): value is "balanced" | "technical" | "aim" | "rhythm" | "tournament" | "custom" {
  return (
    value === "balanced" ||
    value === "technical" ||
    value === "aim" ||
    value === "rhythm" ||
    value === "tournament" ||
    value === "custom"
  );
}

function isReplayProfile(value: string): boolean {
  return (
    value === "beginner" ||
    value === "intermediate" ||
    value === "advanced" ||
    value === "tournament" ||
    value === "custom"
  );
}

function parseOptionalNumber(
  value: unknown,
  fallback: number | null | undefined,
): number | null | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return value;
}

function parseClampedControl(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(1, Math.max(0, value));
}

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}
