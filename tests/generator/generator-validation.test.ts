import { describe, expect, it } from "vitest";

import { createEmptyMetadataDraft } from "../../src/generator/GeneratorModels";
import {
  buildPipelineStagePlan,
  deriveWizardStep,
  validateDifficultySelection,
  validateMappingWarnings,
} from "../../src/generator/GeneratorValidation";

describe("generator stage planning", () => {
  it("includes evolution and hybrid stages only for enabled difficulties", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.title = "Planner";
    metadata.artist = "Unit Test";
    metadata.selectedDifficulties = ["easy", "hard"];
    metadata.difficultySettings.easy.tournamentEnabled = false;
    metadata.difficultySettings.easy.hybridAssemblyEnabled = false;
    metadata.difficultySettings.hard.tournamentEnabled = true;
    metadata.difficultySettings.hard.hybridAssemblyEnabled = true;

    const plan = buildPipelineStagePlan(metadata).map((stage) => stage.code);

    expect(plan).toContain("generate-easy");
    expect(plan).not.toContain("evolution-easy");
    expect(plan).not.toContain("section-eval-easy");
    expect(plan).toContain("evolution-hard");
    expect(plan).toContain("sections");
    expect(plan).toContain("section-eval-hard");
    expect(plan).toContain("hybrid-hard");
    expect(plan.slice(-3)).toEqual([
      "export-osu",
      "package-osz",
      "verify-package",
    ]);
  });
});

describe("Phase 19 difficulty selection validation", () => {
  it("rejects impossible custom difficulty ranges", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    const settings = metadata.difficultySettings.hard;
    settings.difficultyTarget = "custom";
    settings.customMinStar = 6.0;
    settings.customTargetStar = 5.0;
    settings.customMaxStar = 7.0;

    const errors = validateDifficultySelection(metadata);
    expect(errors.some((error) => error.includes("impossible"))).toBe(true);
  });

  it("accepts a valid custom difficulty range", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    const settings = metadata.difficultySettings.hard;
    settings.difficultyTarget = "custom";
    settings.customMinStar = 4.0;
    settings.customTargetStar = 5.0;
    settings.customMaxStar = 6.0;

    expect(validateDifficultySelection(metadata)).toEqual([]);
  });

  it("rejects evolution passes outside 1-5", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    metadata.difficultySettings.hard.evolutionPasses = 6;
    expect(validateDifficultySelection(metadata).length).toBeGreaterThan(0);
  });
});

describe("Phase 19 mapping warnings", () => {
  it("warns about high density with low spacing", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    metadata.difficultySettings.hard.circleDensity = 0.9;
    metadata.difficultySettings.hard.spacing = 0.2;
    const warnings = validateMappingWarnings(metadata);
    expect(warnings.some((warning) => warning.includes("cramped"))).toBe(true);
  });

  it("warns about excessive easy jump intensity", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["easy"];
    metadata.difficultySettings.easy.jumpIntensity = 0.9;
    const warnings = validateMappingWarnings(metadata);
    expect(warnings.some((warning) => warning.includes("Easy"))).toBe(true);
  });

  it("warns about streams without rhythm resolution", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    metadata.difficultySettings.hard.streamIntensity = 0.9;
    metadata.difficultySettings.hard.rhythmComplexity = 0.2;
    const warnings = validateMappingWarnings(metadata);
    expect(
      warnings.some((warning) => warning.includes("timing resolution")),
    ).toBe(true);
  });

  it("warns about spinner spam", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["hard"];
    metadata.difficultySettings.hard.spinnerFrequency = 0.95;
    const warnings = validateMappingWarnings(metadata);
    expect(warnings.some((warning) => warning.includes("spinner spam"))).toBe(true);
  });

  it("produces no warnings for default settings", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.selectedDifficulties = ["easy", "normal", "hard"];
    expect(validateMappingWarnings(metadata)).toEqual([]);
  });
});

describe("generator step derivation", () => {
  it("sends ready workspaces to the difficulties step until selections are saved", () => {
    const metadata = createEmptyMetadataDraft();
    metadata.title = "Step Test";
    metadata.artist = "Unit Test";

    const step = deriveWizardStep({
      workspace: {
        workspace: {
          schemaVersion: 1,
          workspaceId: "workspace",
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          audio: {
            originalFilename: "song.mp3",
            normalizedFilename: "source-audio.mp3",
            relativePath: "source/source-audio.mp3",
            sizeBytes: 1024,
            contentType: "audio/mpeg",
            sha256: "abc123",
          },
          metadata,
          availableArtifacts: [],
        },
        artifacts: [],
        readyForGeneration: false,
      },
      job: undefined,
    });

    expect(step).toBe("difficulties");
  });
});
