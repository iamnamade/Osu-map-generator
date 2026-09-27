import { afterEach, describe, expect, it } from "vitest";

import { createEmptyMetadataDraft } from "../../src/generator/GeneratorModels";
import {
  buildPersistenceFallback,
  clearPersistedGeneratorState,
  loadPersistedGeneratorState,
  savePersistedGeneratorState,
} from "../../src/generator/GeneratorPersistence";

const originalWindow = (globalThis as { window?: unknown }).window;

afterEach(() => {
  if (originalWindow === undefined) {
    delete (globalThis as { window?: unknown }).window;
  } else {
    (globalThis as { window?: unknown }).window = originalWindow;
  }
});

describe("generator persistence", () => {
  it("restores incomplete drafts without requiring a difficulty selection", () => {
    const storage = installStorage();
    const metadataDraft = {
      ...createEmptyMetadataDraft(),
      title: "Halfway There",
      artist: "",
      selectedDifficulties: [],
    };

    storage.setItem(
      "pulse-practice-generator-state",
      JSON.stringify({
        version: 1,
        currentStep: "metadata",
        workspaceId: "12345678-1234-1234-1234-123456789abc",
        metadataDraft,
        advancedSettingsOpen: false,
        logsExpanded: false,
        technicalDetailsExpanded: false,
      }),
    );

    const restored = loadPersistedGeneratorState();

    expect(restored).toBeDefined();
    expect(restored?.currentStep).toBe("metadata");
    expect(restored?.metadataDraft.title).toBe("Halfway There");
    expect(restored?.metadataDraft.selectedDifficulties).toEqual([]);
  });

  it("loads safe defaults for pre-Phase 19 settings", () => {
    const storage = installStorage();
    const legacySettings = {
      easy: {
        candidateCount: 8,
        rootSeed: 42,
        timingVariation: false,
        tournamentEnabled: true,
        hybridAssemblyEnabled: true,
      },
      normal: {
        candidateCount: 10,
        rootSeed: 42,
        timingVariation: false,
        tournamentEnabled: true,
        hybridAssemblyEnabled: true,
      },
      hard: {
        candidateCount: 12,
        rootSeed: 42,
        timingVariation: false,
        tournamentEnabled: true,
        hybridAssemblyEnabled: true,
      },
    };

    storage.setItem(
      "pulse-practice-generator-state",
      JSON.stringify({
        version: 1,
        currentStep: "difficulties",
        metadataDraft: {
          title: "Legacy Song",
          artist: "Unit Test",
          creator: "osu-map-ai",
          source: "",
          tags: "",
          selectedDifficulties: ["easy"],
          difficultySettings: legacySettings,
        },
        advancedSettingsOpen: false,
        logsExpanded: false,
        technicalDetailsExpanded: false,
      }),
    );

    const restored = loadPersistedGeneratorState();

    expect(restored).toBeDefined();
    const easy = restored?.metadataDraft.difficultySettings.easy;
    expect(easy?.mappingPreset).toBe("balanced");
    expect(easy?.circleDensity).toBe(0.5);
    expect(easy?.jumpIntensity).toBe(0.5);
    expect(easy?.evolutionPasses).toBe(2);
    expect(easy?.seedMode).toBe("auto");
    expect(easy?.replayProfile).toBe("advanced");
    expect(easy?.sectionSensitivity).toBe(0.5);
    expect(easy?.candidateCount).toBe(8);
  });

  it("saves and clears persisted generator state through localStorage", () => {
    const storage = installStorage();
    const metadataDraft = {
      ...createEmptyMetadataDraft(),
      title: "Saved Draft",
      artist: "Unit Test",
    };

    savePersistedGeneratorState({
      ...buildPersistenceFallback(),
      bootState: "ready",
      currentStep: "metadata",
      metadataDraft,
      audioUpload: { status: "idle", progressPercent: 0 },
      backgroundUpload: { status: "idle", progressPercent: 0 },
      healthStatus: "ready",
      healthMessage: "ok",
      advancedSettingsOpen: true,
      logsExpanded: true,
      technicalDetailsExpanded: false,
    });

    expect(loadPersistedGeneratorState()?.metadataDraft.title).toBe("Saved Draft");

    clearPersistedGeneratorState();
    expect(storage.getItem("pulse-practice-generator-state")).toBeNull();
  });
});

function installStorage() {
  const values = new Map<string, string>();
  const localStorage = {
    getItem(key: string) {
      return values.has(key) ? values.get(key) ?? null : null;
    },
    setItem(key: string, value: string) {
      values.set(key, value);
    },
    removeItem(key: string) {
      values.delete(key);
    },
    clear() {
      values.clear();
    },
  };

  (globalThis as { window?: unknown }).window = { localStorage };
  return localStorage;
}
