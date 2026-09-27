import { describe, expect, it } from "vitest";

import {
  MAPPING_PRESETS,
  applyMappingPresetToSettings,
  buildDifficultyPreviewSelection,
  createEmptyDifficultySettings,
  createEmptyMetadataDraft,
  formatBytes,
  toPercent,
  type WorkspaceResponse,
} from "../../src/generator/GeneratorModels";

describe("generator preview mapping", () => {
  it("builds runtime preview links from workspace artifacts", () => {
    const workspace = makeWorkspaceResponse();

    const selection = buildDifficultyPreviewSelection(workspace, {
      difficulty: "easy",
      finalMapKind: "hybrid",
      mapArtifactId: "map-artifact",
      osuArtifactId: "osu-artifact",
      objectCount: 42,
      score: 91.4,
      candidateWinner: 3,
      sectionCount: 2,
      promoted: true,
    });

    expect(selection).toEqual({
      path: "/api/artifacts/map-artifact/download",
      label: "Preview Song Hybrid Easy",
      kind: "hybrid",
      difficulty: "easy",
      description:
        "Hybrid Easy with section-aware assembly and validator-backed promotion checks.",
      reportPath: "/api/artifacts/hybrid-report/download",
      correctionReportPath: "/api/artifacts/corrections/download",
      tournamentReportPath: "/api/artifacts/tournament/download",
      analysisPath: "/api/artifacts/analysis/download",
      sectionAnalysisPath: "/api/artifacts/sections/download",
      hybridAssemblyPath: "/api/artifacts/assembly/download",
      hybridTransitionLogPath: "/api/artifacts/transitions/download",
    });
  });

  it("formats bytes with readable units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.50 KB");
  });
});

describe("Phase 19 mapping settings defaults", () => {
  it("creates neutral control defaults", () => {
    const settings = createEmptyDifficultySettings();
    expect(settings.circleDensity).toBe(0.5);
    expect(settings.jumpIntensity).toBe(0.5);
    expect(settings.aggression).toBe(0.5);
    expect(settings.mappingPreset).toBe("balanced");
    expect(settings.difficultyTarget).toBe("auto");
    expect(settings.evolutionPasses).toBe(2);
    expect(settings.seedMode).toBe("auto");
    expect(settings.replayProfile).toBe("advanced");
    expect(settings.sectionSensitivity).toBe(0.5);
  });

  it("clones the new settings fields", () => {
    const draft = createEmptyMetadataDraft();
    draft.difficultySettings.hard.circleDensity = 0.8;
    draft.difficultySettings.hard.mappingPreset = "technical";
    draft.difficultySettings.hard.evolutionPasses = 4;
    draft.difficultySettings.hard.difficultyTarget = "custom";
    draft.difficultySettings.hard.customTargetStar = 5.5;

    const cloned = {
      ...draft,
      difficultySettings: {
        easy: { ...draft.difficultySettings.easy },
        normal: { ...draft.difficultySettings.normal },
        hard: { ...draft.difficultySettings.hard },
      },
    };
    expect(cloned.difficultySettings.hard.circleDensity).toBe(0.8);
    expect(cloned.difficultySettings.hard.mappingPreset).toBe("technical");
    expect(cloned.difficultySettings.hard.evolutionPasses).toBe(4);
  });
});

describe("Phase 19 mapping presets", () => {
  it("registers all preset names", () => {
    expect(MAPPING_PRESETS.map((preset) => preset.name)).toEqual([
      "balanced",
      "technical",
      "aim",
      "rhythm",
      "tournament",
    ]);
  });

  it("applies a preset's real control values", () => {
    const base = createEmptyDifficultySettings();
    const aim = applyMappingPresetToSettings(base, "aim");
    expect(aim.mappingPreset).toBe("aim");
    expect(aim.jumpIntensity).toBeGreaterThan(base.jumpIntensity);
    expect(aim.spacing).toBeGreaterThan(base.spacing);
    expect(aim.circleDensity).not.toBe(base.circleDensity);
  });

  it("keeps user values for the custom preset", () => {
    const base = createEmptyDifficultySettings();
    base.circleDensity = 0.9;
    const custom = applyMappingPresetToSettings(base, "custom");
    expect(custom.circleDensity).toBe(0.9);
  });

  it("converts control values to percentages", () => {
    expect(toPercent(0.5)).toBe(50);
    expect(toPercent(0.72)).toBe(72);
    expect(toPercent(0)).toBe(0);
  });
});

function makeWorkspaceResponse(): WorkspaceResponse {
  return {
    workspace: {
      schemaVersion: 1,
      workspaceId: "workspace",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      metadata: {
        title: "Preview Song",
        artist: "Unit Test",
        creator: "osu-map-ai",
        source: "",
        tags: "",
        selectedDifficulties: ["easy"],
        difficultySettings: {
          easy: { ...createEmptyDifficultySettings(), candidateCount: 8 },
          normal: { ...createEmptyDifficultySettings(), candidateCount: 10 },
          hard: { ...createEmptyDifficultySettings(), candidateCount: 12 },
        },
      },
      availableArtifacts: [
        artifact("map-artifact", "maps/hybrid/easy.json"),
        artifact("hybrid-report", "reports/hybrid/easy-report.json"),
        artifact("corrections", "reports/corrections/easy-corrections.json"),
        artifact("tournament", "reports/tournaments/easy-tournament.json"),
        artifact("analysis", "analysis/analysis.json"),
        artifact("sections", "sections/sections.json"),
        artifact("assembly", "hybrids/easy-assembly.json"),
        artifact("transitions", "hybrids/easy-transitions.json"),
      ],
    },
    artifacts: [],
    readyForGeneration: true,
  };
}

function artifact(id: string, relativePath: string) {
  return {
    id,
    workspaceId: "workspace",
    group: "Test",
    kind: "json",
    label: relativePath,
    relativePath,
    fileName: relativePath.split("/").at(-1) ?? relativePath,
    contentType: "application/json",
    sizeBytes: 100,
    difficulty: "easy" as const,
    downloadUrl: `/api/artifacts/${id}/download`,
  };
}
