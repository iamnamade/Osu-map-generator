import { describe, expect, it, vi } from "vitest";

import { GeneratorApiError } from "../../src/generator/GeneratorApiClient";
import { GeneratorApp } from "../../src/generator/GeneratorApp";
import {
  createEmptyMetadataDraft,
  createInitialGeneratorState,
  type AudioUploadResponse,
  type WorkspaceResponse,
} from "../../src/generator/GeneratorModels";

describe("generator app upload flow", () => {
  it("advances to metadata and applies detected suggestions after upload", async () => {
    const app = createGeneratorApp();
    const internals = app as unknown as GeneratorAppInternals;
    const response = makeAudioUploadResponse({
      detectedMetadata: {
        title: "Detected Song",
        artist: "Detected Artist",
        durationMs: 180000,
        sampleRate: 44100,
        codec: "mp3",
      },
    });

    internals.store.setState({
      ...createInitialGeneratorState(),
      bootState: "ready",
      currentStep: "upload",
      workspace: makeWorkspaceResponse(),
      metadataDraft: createEmptyMetadataDraft(),
      healthStatus: "ready",
      healthMessage: "Local API ready.",
    });
    internals.api = {
      uploadAudio: vi.fn().mockResolvedValue(response),
    } as unknown as GeneratorAppInternals["api"];

    await internals.uploadAudio(
      new File(["test"], "song.mp3", { type: "audio/mpeg" }),
    );

    const state = internals.store.getState();
    expect(state.currentStep).toBe("metadata");
    expect(state.detectedMetadata?.title).toBe("Detected Song");
    expect(state.metadataDraft.title).toBe("Detected Song");
    expect(state.metadataDraft.artist).toBe("Detected Artist");
    expect(state.audioUpload.status).toBe("uploaded");
  });

  it("stores readable api errors instead of generic upload/save failures", async () => {
    const app = createGeneratorApp();
    const internals = app as unknown as GeneratorAppInternals;
    const metadataDraft = createEmptyMetadataDraft();
    metadataDraft.title = "Ready Song";
    metadataDraft.artist = "Unit Test";
    metadataDraft.selectedDifficulties = ["easy"];

    internals.store.setState({
      ...createInitialGeneratorState(),
      bootState: "ready",
      currentStep: "metadata",
      workspace: makeWorkspaceResponse(),
      metadataDraft,
      healthStatus: "ready",
      healthMessage: "Local API ready.",
    });
    internals.api = {
      updateMetadata: vi
        .fn()
        .mockRejectedValue(
          new GeneratorApiError("Song title is required before generation.", 422),
        ),
    } as unknown as GeneratorAppInternals["api"];

    const saved = await internals.saveConfiguration();

    expect(saved).toBe(false);
    expect(internals.store.getState().errorMessage).toBe(
      "Song title is required before generation.",
    );
  });
});

function createGeneratorApp(): GeneratorApp {
  return new GeneratorApp(new FakeRootElement() as unknown as HTMLElement);
}

function makeWorkspaceResponse(): WorkspaceResponse {
  return {
    workspace: {
      schemaVersion: 1,
      workspaceId: "workspace-1",
      createdAt: "2026-07-17T00:00:00Z",
      updatedAt: "2026-07-17T00:00:00Z",
      audio: undefined,
      background: undefined,
      metadata: createEmptyMetadataDraft(),
      configurationSignature: null,
      lastRunSignature: null,
      jobStatus: null,
      availableArtifacts: [],
      lastResult: null,
    },
    artifacts: [],
    readyForGeneration: false,
  };
}

function makeAudioUploadResponse(params: {
  detectedMetadata: AudioUploadResponse["detectedMetadata"];
}): AudioUploadResponse {
  return {
    ...makeWorkspaceResponse(),
    workspace: {
      ...makeWorkspaceResponse().workspace,
      audio: {
        originalFilename: "song.mp3",
        normalizedFilename: "source-audio.mp3",
        relativePath: "source/source-audio.mp3",
        sizeBytes: 128,
        contentType: "audio/mpeg",
        sha256: "abc123",
        detectedMetadata: params.detectedMetadata,
      },
    },
    detectedMetadata: params.detectedMetadata,
  };
}

class FakeRootElement {
  innerHTML = "";

  addEventListener(): void {}

  querySelector(): null {
    return null;
  }
}

interface GeneratorAppInternals {
  api: {
    uploadAudio: (workspaceId: string, file: File) => Promise<AudioUploadResponse>;
    updateMetadata: (workspaceId: string, payload: unknown) => Promise<WorkspaceResponse>;
  };
  store: {
    getState: () => ReturnType<typeof createInitialGeneratorState>;
    setState: (state: ReturnType<typeof createInitialGeneratorState>) => void;
  };
  uploadAudio: (file: File) => Promise<void>;
  saveConfiguration: () => Promise<boolean>;
}
