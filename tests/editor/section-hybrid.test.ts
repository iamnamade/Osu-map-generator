import { afterEach, describe, expect, it, vi } from "vitest";

import { loadHybridAssemblyReport } from "../../src/game/HybridAssemblyReportLoader";
import { loadSectionAnalysis } from "../../src/game/SectionAnalysisLoader";
import { EditorController } from "../../src/editor/EditorController";
import { createInitialEditorState, EditorStore } from "../../src/editor/EditorStore";
import {
  buildHybridSourceSequence,
  countHybridCandidateSwitches,
  findSectionByTime,
  getSectionTimelineBounds,
  parseHybridAssemblyReport,
  parseSectionAnalysis,
} from "../../src/shared/sectionData";

const originalFetch = globalThis.fetch;
const originalWindow = (globalThis as Record<string, unknown>).window;

afterEach(() => {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
  } else {
    delete (globalThis as { fetch?: unknown }).fetch;
  }

  if (originalWindow) {
    (globalThis as Record<string, unknown>).window = originalWindow;
  } else {
    delete (globalThis as { window?: unknown }).window;
  }
});

describe("phase 7 section and hybrid runtime validation", () => {
  it("parses section analysis and resolves section lookup by playhead", () => {
    const analysis = parseSectionAnalysis(makeSectionAnalysisRaw());
    const secondSection = findSectionByTime(analysis.sections, 6200);
    const secondBounds = getSectionTimelineBounds(analysis.sections[1]!);

    expect(analysis.sections).toHaveLength(2);
    expect(secondSection?.id).toBe(2);
    expect(secondBounds).toEqual({
      startMs: 6000,
      endMs: 12000,
      durationMs: 6000,
    });
  });

  it("parses hybrid assembly reports and renders source sequence data", () => {
    const report = parseHybridAssemblyReport(makeHybridAssemblyRaw());

    expect(report.promotion.promoted).toBe(true);
    expect(buildHybridSourceSequence(report.sections)).toBe("C3 -> C5");
    expect(countHybridCandidateSwitches(report.sections)).toBe(1);
  });

  it("returns missing and malformed loader fallbacks without crashing", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("", {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ bad: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ) as typeof fetch;

    const missingSections = await loadSectionAnalysis("/sections/test-song-sections.json");
    const malformedHybrid = await loadHybridAssemblyReport(
      "/hybrids/test-song-normal-assembly.json",
    );

    expect(missingSections).toEqual({
      status: "missing",
      message: "Section analysis has not been generated yet.",
    });
    expect(malformedHybrid.status).toBe("error");
  });
});

describe("phase 7 editor section interactions", () => {
  it("tracks section selection, preview range, loop range, and lock metadata", async () => {
    const store = new EditorStore();
    const controller = new EditorController(store);
    const audioStub = {
      seek: vi.fn(),
      play: vi.fn().mockResolvedValue(undefined),
      pause: vi.fn(),
      isPlaying: vi.fn(() => false),
      stop: vi.fn(),
      restart: vi.fn(),
      load: vi.fn(),
      setPlaybackRate: vi.fn(),
      dispose: vi.fn(),
    };
    (controller as unknown as { audioController: typeof audioStub }).audioController =
      audioStub;
    (globalThis as Record<string, unknown>).window = {
      setTimeout,
      clearTimeout,
    };

    const initial = createInitialEditorState();
    store.setState(
      (controller as unknown as {
        withDerivedState: (state: ReturnType<typeof createInitialEditorState>) => ReturnType<typeof createInitialEditorState>;
      }).withDerivedState({
        ...initial,
        session: {
          ...initial.session,
          sectionAnalysis: parseSectionAnalysis(makeSectionAnalysisRaw()),
          hybridAssembly: parseHybridAssemblyReport(makeHybridAssemblyRaw()),
        },
      }),
    );

    controller.selectSection(2, { seek: true, openHybridTab: true });
    expect(store.getState().ui.selectedSectionId).toBe(2);
    expect(store.getState().ui.activeRightTab).toBe("hybrid");
    expect(audioStub.seek).toHaveBeenCalledWith(6000);

    controller.playSection(1);
    expect(audioStub.play).toHaveBeenCalledTimes(1);
    expect(
      (controller as unknown as {
        previewRange?: { startMs: number; endMs: number };
      }).previewRange,
    ).toEqual({
      sectionId: 1,
      startMs: 0,
      endMs: 6000,
    });

    controller.toggleSectionLoop(2);
    expect(store.getState().ui.loopSectionId).toBe(2);
    expect(
      (controller as unknown as {
        loopRange?: { startMs: number; endMs: number };
      }).loopRange,
    ).toEqual({
      sectionId: 2,
      startMs: 6000,
      endMs: 12000,
    });

    controller.toggleSectionLock(2);
    expect(store.getState().ui.lockedSectionIds).toEqual([2]);

    controller.zoomToSection(2);
    expect(store.getState().ui.timeline.visibleStartMs).toBeLessThanOrEqual(6000);
    expect(store.getState().ui.timeline.visibleDurationMs).toBeGreaterThanOrEqual(6000);

    controller.dispose();
  });
});

function makeSectionAnalysisRaw() {
  return {
    version: 1,
    audio: {
      path: "/audio/test-song.mp3",
      durationMs: 12000,
    },
    configuration: {},
    inputSignature: "section-signature",
    sections: [
      {
        id: 1,
        startMs: 0,
        endMs: 6000,
        durationMs: 6000,
        label: "intro-like",
        confidence: 0.74,
        averageEnergy: 0.26,
        energyTrend: "rising",
        beatDensity: 0.8,
        onsetDensity: 0.9,
        rhythmComplexity: 0.21,
        repetitionGroup: 1,
        energyClass: "low",
      },
      {
        id: 2,
        startMs: 6000,
        endMs: 12000,
        durationMs: 6000,
        label: "chorus-like",
        confidence: 0.81,
        averageEnergy: 0.71,
        energyTrend: "steady",
        beatDensity: 1.4,
        onsetDensity: 1.6,
        rhythmComplexity: 0.56,
        repetitionGroup: 2,
        energyClass: "high",
      },
    ],
    boundaries: [
      {
        rawTimeMs: 5900,
        finalTimeMs: 6000,
        confidence: 0.79,
        reason: "Large energy change",
        supportingFeatureChanges: { energyDelta: 0.44 },
        snapped: true,
        snappedTo: "beat",
        snapDistanceMs: 100,
      },
    ],
    summary: {},
  };
}

function makeHybridAssemblyRaw() {
  return {
    version: 1,
    difficulty: "normal",
    inputSignature: "hybrid-signature",
    sections: [
      {
        sectionId: 1,
        startMs: 0,
        endMs: 6000,
        label: "intro-like",
        sourceCandidate: 3,
        sectionScore: 91.4,
        selectionReason: "Best timing and readability for the opening section.",
        lockState: "unlocked",
        transitionStatusBefore: undefined,
        transitionStatusAfter: "safe",
        issues: [],
      },
      {
        sectionId: 2,
        startMs: 6000,
        endMs: 12000,
        label: "chorus-like",
        sourceCandidate: 5,
        sectionScore: 93.2,
        selectionReason: "Best high-energy coverage with a safe entry transition.",
        lockState: "unlocked",
        transitionStatusBefore: "safe",
        transitionStatusAfter: undefined,
        issues: ["slight-density-spike"],
      },
    ],
    transitions: [
      {
        boundaryIndex: 1,
        fromSectionId: 1,
        toSectionId: 2,
        fromCandidate: 3,
        toCandidate: 5,
        classification: "safe",
        score: 88.6,
        metrics: {
          timeGapMs: 420,
          requiredCursorSpeed: 280.4,
        },
        issues: [],
        corrections: [],
      },
    ],
    scores: {
      sectionQuality: 92.3,
      transitionQuality: 88.6,
      styleConsistency: 85.4,
      finalPythonQuality: 91.2,
      overallHybridScore: 90.9,
    },
    sourceUsage: {
      "candidate-003": 1,
      "candidate-005": 1,
    },
    corrections: {
      accepted: 1,
      reverted: 0,
      unsafeTransitionsRemaining: 0,
    },
    valid: true,
    playable: true,
    promotion: {
      promoted: true,
      reason: "Hybrid satisfied the internal promotion rules.",
      championQuality: 89.6,
      hybridPythonQuality: 91.2,
      hybridScore: 90.9,
    },
    summary: {
      sectionCount: 2,
      sourceCandidatesUsed: 2,
      candidateSwitches: 1,
    },
  };
}
