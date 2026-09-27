import type {
  DifficultyName,
  GeneratorState,
  JobStateResponse,
  WizardStep,
  WorkspaceMetadata,
} from "./GeneratorModels";

export interface MetadataValidationResult {
  fieldErrors: Partial<Record<"title" | "artist" | "creator" | "source" | "tags", string>>;
  summary: string[];
}

export interface PipelineStageDescriptor {
  code: string;
  label: string;
  difficulty?: DifficultyName;
}

export type PipelineStageState =
  | "complete"
  | "active"
  | "pending"
  | "failed"
  | "cancelled";

const MAX_TITLE_LENGTH = 160;
const MAX_ARTIST_LENGTH = 160;
const MAX_SOURCE_LENGTH = 160;
const MAX_TAGS_LENGTH = 512;
const MAX_CREATOR_LENGTH = 80;

export function validateMetadataDraft(
  metadata: WorkspaceMetadata,
): MetadataValidationResult {
  const fieldErrors: MetadataValidationResult["fieldErrors"] = {};

  if (!metadata.title.trim()) {
    fieldErrors.title = "Song title is required.";
  } else if (metadata.title.length > MAX_TITLE_LENGTH) {
    fieldErrors.title = `Song title must stay within ${MAX_TITLE_LENGTH} characters.`;
  }

  if (!metadata.artist.trim()) {
    fieldErrors.artist = "Artist is required.";
  } else if (metadata.artist.length > MAX_ARTIST_LENGTH) {
    fieldErrors.artist = `Artist must stay within ${MAX_ARTIST_LENGTH} characters.`;
  }

  if (!metadata.creator.trim()) {
    fieldErrors.creator = "Creator is required.";
  } else if (metadata.creator.length > MAX_CREATOR_LENGTH) {
    fieldErrors.creator = `Creator must stay within ${MAX_CREATOR_LENGTH} characters.`;
  }

  if (metadata.source.length > MAX_SOURCE_LENGTH) {
    fieldErrors.source = `Source must stay within ${MAX_SOURCE_LENGTH} characters.`;
  }

  if (metadata.tags.length > MAX_TAGS_LENGTH) {
    fieldErrors.tags = `Tags must stay within ${MAX_TAGS_LENGTH} characters.`;
  }

  return {
    fieldErrors,
    summary: Object.values(fieldErrors),
  };
}

export function validateDifficultySelection(metadata: WorkspaceMetadata): string[] {
  const errors: string[] = [];
  if (metadata.selectedDifficulties.length === 0) {
    errors.push("Select at least one difficulty before continuing.");
  }

  for (const difficulty of metadata.selectedDifficulties) {
    const settings = metadata.difficultySettings[difficulty];
    if (!settings) {
      errors.push(`Missing settings for ${difficulty}.`);
      continue;
    }

    if (settings.candidateCount < 1 || settings.candidateCount > 64) {
      errors.push(
        `${capitalize(difficulty)} candidate count must stay between 1 and 64.`,
      );
    }

    if (settings.rootSeed < 0) {
      errors.push(`${capitalize(difficulty)} root seed must be non-negative.`);
    }

    if (settings.hybridAssemblyEnabled && !settings.tournamentEnabled) {
      errors.push(
        `${capitalize(difficulty)} hybrid assembly requires tournament mode to stay enabled.`,
      );
    }

    if (settings.evolutionPasses < 1 || settings.evolutionPasses > 5) {
      errors.push(
        `${capitalize(difficulty)} evolution passes must stay between 1 and 5.`,
      );
    }

    if (settings.difficultyTarget === "custom") {
      const target = settings.customTargetStar;
      const min = settings.customMinStar;
      const max = settings.customMaxStar;
      if (
        typeof target !== "number" ||
        typeof min !== "number" ||
        typeof max !== "number"
      ) {
        errors.push(
          `${capitalize(difficulty)} custom difficulty requires target, minimum, and maximum star values.`,
        );
      } else if (!(0.5 <= min && min <= target && target <= max && max <= 12.0)) {
        errors.push(
          `${capitalize(difficulty)} custom difficulty range is impossible: min <= target <= max with all values between 0.5 and 12.0 stars.`,
        );
      }
    }
  }

  return errors;
}

export function validateMappingWarnings(metadata: WorkspaceMetadata): string[] {
  const warnings: string[] = [];
  for (const difficulty of metadata.selectedDifficulties) {
    const settings = metadata.difficultySettings[difficulty];
    if (!settings) {
      continue;
    }
    const prefix = `${capitalize(difficulty)}:`;

    if (settings.circleDensity >= 0.75 && settings.spacing <= 0.3) {
      warnings.push(
        `${prefix} very high circle density with very low spacing produces cramped, unreadable patterns. Consider raising Spacing to 45%+ or lowering Circle Density.`,
      );
    }

    if (difficulty === "easy" && settings.jumpIntensity >= 0.75) {
      warnings.push(
        `${prefix} excessive jump intensity for Easy may exceed beginner movement limits. Consider 70% or lower.`,
      );
    }

    if (
      settings.streamIntensity >= 0.7 &&
      settings.rhythmComplexity <= 0.35
    ) {
      warnings.push(
        `${prefix} high stream intensity needs finer timing resolution. Raise Rhythm Complexity to 40%+ so streams can be subdivided musically.`,
      );
    }

    if (settings.spinnerFrequency >= 0.8) {
      warnings.push(
        `${prefix} very high spinner frequency risks spinner spam. Values above 80% may interrupt flow.`,
      );
    }

    if (settings.circleDensity >= 0.8 && settings.sliderDensity >= 0.7) {
      warnings.push(
        `${prefix} extremely high circle density combined with high slider density produces a very packed map. Consider lowering one of them.`,
      );
    }

    if (settings.jumpIntensity >= 0.8 && settings.spacing >= 0.8) {
      warnings.push(
        `${prefix} very high jump intensity with very wide spacing creates large cross-screen movements that may exceed comfortable cursor speed.`,
      );
    }
  }
  return warnings;
}

export function buildPipelineStagePlan(
  metadata: WorkspaceMetadata,
): PipelineStageDescriptor[] {
  const stages: PipelineStageDescriptor[] = [
    { code: "validate-audio", label: "Audio validation" },
    { code: "analyze-audio", label: "Audio analysis" },
  ];

  for (const difficulty of metadata.selectedDifficulties) {
    stages.push({
      code: `generate-${difficulty}`,
      label: `${capitalize(difficulty)} base map`,
      difficulty,
    });
    stages.push({
      code: `validate-${difficulty}`,
      label: `${capitalize(difficulty)} base validation`,
      difficulty,
    });
    stages.push({
      code: `improve-${difficulty}`,
      label: `${capitalize(difficulty)} post-processing`,
      difficulty,
    });

    if (metadata.difficultySettings[difficulty].tournamentEnabled) {
      stages.push({
        code: `evolution-${difficulty}`,
        label: `${capitalize(difficulty)} candidate evolution`,
        difficulty,
      });
    }
  }

  if (
    metadata.selectedDifficulties.some(
      (difficulty) =>
        metadata.difficultySettings[difficulty].hybridAssemblyEnabled,
    )
  ) {
    stages.push({ code: "sections", label: "Section analysis" });
    for (const difficulty of metadata.selectedDifficulties) {
      if (!metadata.difficultySettings[difficulty].hybridAssemblyEnabled) {
        continue;
      }

      stages.push({
        code: `section-eval-${difficulty}`,
        label: `${capitalize(difficulty)} section evaluation`,
        difficulty,
      });
      stages.push({
        code: `hybrid-${difficulty}`,
        label: `${capitalize(difficulty)} hybrid assembly`,
        difficulty,
      });
    }
  }

  stages.push({ code: "validate-final", label: "Final validation" });
  stages.push({ code: "export-osu", label: ".osu export" });
  stages.push({ code: "package-osz", label: ".osz packaging" });
  stages.push({ code: "verify-package", label: "Package verification" });
  return stages;
}

export function getPipelineStageState(
  stage: PipelineStageDescriptor,
  index: number,
  job: JobStateResponse | undefined,
): PipelineStageState {
  if (!job) {
    return "pending";
  }

  if (job.status === "completed") {
    return "complete";
  }

  if (index < job.completedStages) {
    return "complete";
  }

  if (job.currentStage === stage.code) {
    if (job.status === "failed") {
      return "failed";
    }

    if (job.status === "cancelled") {
      return "cancelled";
    }

    return "active";
  }

  return "pending";
}

export function deriveWizardStep(
  state: Pick<GeneratorState, "workspace" | "job">,
): WizardStep {
  const job = state.job;
  if (job) {
    if (job.status === "completed" && job.result) {
      return "results";
    }

    return "generate";
  }

  const workspace = state.workspace;
  if (!workspace?.workspace.audio) {
    return "upload";
  }

  const metadata = workspace.workspace.metadata;
  if (!metadata.title.trim() || !metadata.artist.trim()) {
    return "metadata";
  }

  if (
    metadata.selectedDifficulties.length === 0 ||
    !workspace.readyForGeneration
  ) {
    return "difficulties";
  }

  return "generate";
}

export function computeElapsedMs(job: JobStateResponse | undefined): number {
  if (!job) {
    return 0;
  }

  const startedAt = Date.parse(job.startedAt);
  const endedAt = job.finishedAt ? Date.parse(job.finishedAt) : Date.now();
  if (!Number.isFinite(startedAt) || !Number.isFinite(endedAt)) {
    return 0;
  }

  return Math.max(0, endedAt - startedAt);
}

export function applyDetectedMetadataSuggestion(
  metadata: WorkspaceMetadata,
  suggestion: {
    title?: string | null;
    artist?: string | null;
  },
): WorkspaceMetadata {
  const detectedTitle = suggestion.title?.trim();
  const detectedArtist = suggestion.artist?.trim();
  return {
    ...metadata,
    title:
      !metadata.title.trim() && detectedTitle
        ? detectedTitle
        : metadata.title,
    artist:
      !metadata.artist.trim() && detectedArtist
        ? detectedArtist
        : metadata.artist,
  };
}

export function isMappingPresetName(
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

export function clampMappingControl(value: number): number {
  const numeric = Number.isFinite(value) ? value : 0.5;
  return Math.min(1, Math.max(0, numeric));
}

export function isWizardStep(value: unknown): value is WizardStep {
  return (
    value === "upload" ||
    value === "metadata" ||
    value === "difficulties" ||
    value === "generate" ||
    value === "results"
  );
}

function capitalize(value: string): string {
  if (!value) {
    return value;
  }

  return `${value[0]?.toUpperCase() ?? ""}${value.slice(1)}`;
}
