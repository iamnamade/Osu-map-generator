import { describe, expect, it } from "vitest";
import type { EvolutionReport } from "../../src/shared/evolutionReport";
import {
  buildCandidateBrowserEntries,
  createInitialCandidateFilters,
  createInitialCandidateSort,
  filterCandidateEntries,
  findCandidateEntry,
  formatCandidatePercent,
  formatCandidateScore,
  sortCandidateEntries,
  type CandidateBrowserEntry,
} from "../../src/editor/candidates/candidateModels";
import {
  buildSectionComparison,
  buildVisualDiff,
  computeSectionDensity,
  computeSectionMovement,
  matchCandidateObjects,
} from "../../src/editor/candidates/candidateCompare";
import {
  appendChampionHistory,
  buildCandidateWorkspaceKey,
  candidateNoteKey,
  createChampionHistoryEntry,
  parseChampionHistory,
  serializeChampionHistory,
} from "../../src/editor/candidates/championHistory";
import type { EditorMapDocument } from "../../src/editor/models/EditorModels";
import { parseEvolutionReport } from "../../src/shared/evolutionReport";
import type { SongSection } from "../../src/shared/sectionData";

function makeCircle(
  id: number,
  time: number,
  x: number,
  y: number,
): EditorMapDocument["objects"][number] {
  return {
    editorId: `obj-${String(id).padStart(6, "0")}`,
    id,
    type: "circle",
    x,
    y,
    time,
    extraFields: {},
  };
}

function makeSpinner(id: number, time: number, endTime: number): EditorMapDocument["objects"][number] {
  return {
    editorId: `obj-${String(id).padStart(6, "0")}`,
    id,
    type: "spinner",
    time,
    endTime,
    extraFields: {},
  };
}

function makeMap(objects: EditorMapDocument["objects"][number][]): EditorMapDocument {
  return {
    title: "Test Song",
    artist: "Unknown Artist",
    audio: "/audio/test-song.mp3",
    approachTime: 950,
    circleRadius: 40,
    objects,
    extraFields: {},
  };
}

function makeSection(id: number, startMs: number, endMs: number): SongSection {
  return {
    id,
    startMs,
    endMs,
    durationMs: endMs - startMs,
    label: `section-${id}`,
    confidence: 0.9,
    averageEnergy: 0.5,
    energyTrend: "flat",
    beatDensity: 1,
    onsetDensity: 1,
    rhythmComplexity: 0.5,
    repetitionGroup: null,
    energyClass: "medium",
  };
}

function makeReport(): EvolutionReport {
  return {
    version: 1,
    song: {
      title: "Test Song",
      artist: "Unknown Artist",
      difficulty: "normal",
      audio: "/audio/test-song.mp3",
    },
    configuration: {
      rootSeed: 42,
      candidateCount: 3,
      maxPasses: 1,
      archivePolicy: "all",
      timingVariation: false,
    },
    summary: { generated: 3, eligible: 3, rejected: 0, passesUsed: 1, earlyStopped: false },
    champion: {
      candidateIndex: 2,
      candidateSeed: 99,
      overallScore: 91.2,
      qualityScore: 88,
      stars: 3.2,
      mapPath: "/maps/champions/test-song-normal.json",
      reportPath: "/reports/champions/test-song-normal-report.json",
      sourceMapPath: "public/candidates/test-song/normal/candidate-002/improved-map.json",
      sourceReportPath: "public/candidates/test-song/normal/candidate-002/improved-report.json",
      summaryPath: "public/candidates/test-song/normal/candidate-002/candidate-summary.json",
      promotionReason: "Candidate 002 won.",
    },
    ranking: [
      {
        rank: 1,
        candidateIndex: 2,
        candidateSeed: 99,
        stars: 3.2,
        scores: {
          overall: 91.2,
          quality: 88,
          difficulty: 90,
          flow: 75,
          rhythm: 70,
          movement: 85,
          pattern: 78,
          slider: 82,
          spinner: 95,
          reading: 72,
          playability: 76,
          consistency: 88,
          confidence: 84,
          replay: 67.1,
        },
        final: {
          weightedScore: 90.4,
          rhythm: 70,
          playability: 76,
          pattern: 78,
          target: 90,
          reading: 72,
          replay: 67.1,
          consistency: 88,
          validity: 80,
          flow: 75,
          section: 98.5,
          fatigue: 99.1,
          rebalance: 52.4,
        },
        qualityGates: [
          { code: "VALID_STRUCTURE", name: "Valid beatmap structure", mandatory: true, passed: true, detail: "ok", penalty: 0 },
          { code: "READABILITY", name: "No readability problems", mandatory: false, passed: true, detail: "ok", penalty: 0 },
        ],
        validationStatus: "passed",
        improvementsMade: ["replay-simulated"],
        targetDeviation: 0.12,
        diversityPenalty: 0.4,
        mapPath: "public/candidates/test-song/normal/candidate-002/improved-map.json",
        reportPath: "public/candidates/test-song/normal/candidate-002/improved-report.json",
        summaryPath: "public/candidates/test-song/normal/candidate-002/candidate-summary.json",
        eligible: true,
        rejectionReasons: [],
      },
      {
        rank: 2,
        candidateIndex: 1,
        candidateSeed: 55,
        stars: 2.9,
        scores: {
          overall: 85.1,
          quality: 82,
          difficulty: 84,
          flow: 60,
          rhythm: 66,
          movement: 80,
          pattern: 70,
          slider: 80,
          spinner: 90,
          reading: 64,
          playability: 74,
          consistency: 80,
          confidence: 78,
          replay: 61,
        },
        final: {
          weightedScore: 84.0,
          rhythm: 66,
          playability: 74,
          pattern: 70,
          target: 84,
          reading: 64,
          replay: 61,
          consistency: 80,
          validity: 75,
          flow: 60,
          section: 96.0,
          fatigue: 97.5,
          rebalance: 50.0,
        },
        qualityGates: [
          { code: "VALID_STRUCTURE", name: "Valid beatmap structure", mandatory: true, passed: true, detail: "ok", penalty: 0 },
        ],
        validationStatus: "passed",
        improvementsMade: [],
        mapPath: "public/candidates/test-song/normal/candidate-001/improved-map.json",
        reportPath: "public/candidates/test-song/normal/candidate-001/improved-report.json",
        summaryPath: "public/candidates/test-song/normal/candidate-001/candidate-summary.json",
        eligible: true,
        rejectionReasons: [],
      },
      {
        rank: 3,
        candidateIndex: 3,
        candidateSeed: 123,
        stars: 3.5,
        scores: {
          overall: 70.0,
          quality: 70,
          difficulty: 95,
          flow: 20,
          rhythm: 60,
          movement: 90,
          pattern: 60,
          slider: 85,
          spinner: 85,
          reading: 40,
          playability: 60,
          consistency: 70,
          confidence: 70,
          replay: 55,
        },
        mapPath: "public/candidates/test-song/normal/candidate-003/improved-map.json",
        reportPath: "public/candidates/test-song/normal/candidate-003/improved-report.json",
        summaryPath: "public/candidates/test-song/normal/candidate-003/candidate-summary.json",
        eligible: false,
        rejectionReasons: ["Flow too low"],
        validationStatus: "failed",
      },
    ],
    rejectedCandidates: [],
    comparison: [],
    comparisonReasons: [],
    heatmaps: [],
    replay: {
      fullComboChance: 0.4,
      expectedAccuracy: 0.85,
      expectedMisses: 1.2,
      highestStressSectionMs: 8000,
      hardestPattern: "linear",
      mostDifficultTransitionMs: 9000,
      replayScore: 67.1,
      playerProfile: "advanced",
      expectedComboPct: 0.8,
      cursorEfficiency: 0.9,
      readingScore: 70,
      fatigueAverage: 0.05,
      fatiguePeak: 0.1,
      comboBreaks: 2,
      missClusters: 1,
      weakestSection: "outro-like",
      strongestSection: "intro-like",
    },
    improvementHistory: [],
    diagnostics: {
      scoreDistribution: {},
      averageImprovement: 2,
      promotionReason: "Candidate 002 won.",
      confidence: 80,
    },
    scoreWeights: {},
    replayReportPath: "public/evolution/test-song-normal-evolution-replay.json",
  };
}

describe("candidate loading", () => {
  it("builds browser entries from the evolution report ranking", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    expect(entries).toHaveLength(3);
    expect(entries[0]).toMatchObject({
      candidateIndex: 2,
      rank: 1,
      finalScore: 90.4,
      difficultyScore: 90,
      rhythmScore: 70,
      patternScore: 78,
      readingScore: 72,
      flowScore: 75,
      replayScore: 67.1,
      fatigueScore: 99.1,
      champion: true,
      validationStatus: "passed",
      eligible: true,
    });
  });

  it("falls back to dimension scores when final scores are absent", () => {
    const report = makeReport();
    const third = report.ranking[2];
    expect(third?.final).toBeUndefined();
    const entry = buildCandidateBrowserEntries(report).find(
      (item) => item.candidateIndex === 3,
    );
    expect(entry?.finalScore).toBe(70.0);
    expect(entry?.replayScore).toBe(55);
    expect(entry?.sectionScore).toBeNull();
  });

  it("derives replay and rebalance report paths from the map path", () => {
    const entry = buildCandidateBrowserEntries(makeReport())[0];
    expect(entry?.replayReportPath).toBe(
      "public/candidates/test-song/normal/candidate-002/replay-report.json",
    );
    expect(entry?.rebalanceReportPath).toBe(
      "public/candidates/test-song/normal/candidate-002/rebalance-report.json",
    );
  });

  it("marks rejected candidates and preserves rejection reasons", () => {
    const entry = buildCandidateBrowserEntries(makeReport()).find(
      (item) => item.candidateIndex === 3,
    );
    expect(entry?.eligible).toBe(false);
    expect(entry?.rejectionReasons).toEqual(["Flow too low"]);
    expect(entry?.validationStatus).toBe("failed");
  });

  it("keeps the champion flag on the report champion", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    expect(entries.find((entry) => entry.candidateIndex === 2)?.champion).toBe(true);
    expect(entries.find((entry) => entry.candidateIndex === 1)?.champion).toBe(false);
  });
});

describe("candidate selection", () => {
  it("resolves entries by candidate index", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    expect(findCandidateEntry(entries, 2)?.candidateIndex).toBe(2);
    expect(findCandidateEntry(entries, 99)).toBeUndefined();
    expect(findCandidateEntry(entries, undefined)).toBeUndefined();
  });
});

describe("candidate filtering and sorting", () => {
  it("filters by difficulty", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const filters = createInitialCandidateFilters();
    expect(filterCandidateEntries(entries, { ...filters, difficulty: "normal" })).toHaveLength(3);
    expect(filterCandidateEntries(entries, { ...filters, difficulty: "hard" })).toHaveLength(0);
  });

  it("filters by validation status", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const filters = createInitialCandidateFilters();
    expect(filterCandidateEntries(entries, { ...filters, validation: "passed" })).toHaveLength(2);
    expect(filterCandidateEntries(entries, { ...filters, validation: "failed" })).toHaveLength(1);
  });

  it("filters by score range and replay threshold", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const filters = createInitialCandidateFilters();
    // Final scores: candidate 002 = 90.4, candidate 001 = 84.0, candidate 003 = 70.0.
    expect(filterCandidateEntries(entries, { ...filters, minScore: 80 })).toHaveLength(2);
    expect(filterCandidateEntries(entries, { ...filters, minScore: 90 })).toHaveLength(1);
    expect(filterCandidateEntries(entries, { ...filters, maxScore: 85 })).toHaveLength(2);
    expect(filterCandidateEntries(entries, { ...filters, minReplayScore: 65 })).toHaveLength(1);
  });

  it("filters champion-only and by rank and section quality", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const filters = createInitialCandidateFilters();
    expect(filterCandidateEntries(entries, { ...filters, championOnly: true })).toHaveLength(1);
    expect(filterCandidateEntries(entries, { ...filters, maxRank: 2 })).toHaveLength(2);
    expect(filterCandidateEntries(entries, { ...filters, minSectionQuality: 98 })).toHaveLength(1);
  });

  it("sorts by rank, final score, replay, and difficulty", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const byRank = sortCandidateEntries(entries, createInitialCandidateSort());
    expect(byRank.map((entry) => entry.rank)).toEqual([1, 2, 3]);

    const byScore = sortCandidateEntries(entries, {
      key: "final-score",
      direction: "desc",
    });
    expect(byScore[0]?.candidateIndex).toBe(2);

    const byReplay = sortCandidateEntries(entries, {
      key: "replay",
      direction: "desc",
    });
    expect(byReplay[0]?.candidateIndex).toBe(2);

    const byDifficulty = sortCandidateEntries(entries, {
      key: "difficulty",
      direction: "desc",
    });
    expect(byDifficulty[0]?.candidateIndex).toBe(3);

    const byFlowAsc = sortCandidateEntries(entries, {
      key: "flow",
      direction: "asc",
    });
    expect(byFlowAsc[0]?.candidateIndex).toBe(3);
  });
});

describe("visual diff calculations", () => {
  it("classifies shared, unique, moved, and retimed objects", () => {
    const mapA = makeMap([
      makeCircle(1, 1000, 100, 100),
      makeCircle(2, 2000, 200, 200),
      makeCircle(3, 3000, 300, 300),
      makeCircle(4, 4000, 100, 100),
    ]);
    const mapB = makeMap([
      makeCircle(1, 1000, 100, 100),
      makeCircle(2, 2010, 300, 300),
      makeCircle(3, 3000, 300, 300),
      makeCircle(5, 5000, 150, 150),
    ]);

    // c1 and c3 are identical in both maps; c2 moved; c4 only in A; c5 only in B.
    const diff = buildVisualDiff(mapA, mapB);
    expect(diff.summary).toEqual({
      shared: 2,
      aOnly: 1,
      bOnly: 1,
      moved: 1,
      retimed: 0,
      movedRetimed: 0,
    });

    const kinds = diff.items.map((item) => item.kind).sort();
    expect(kinds).toEqual(["a-only", "b-only", "moved", "shared", "shared"]);
  });

  it("detects retimed and moved-and-retimed objects", () => {
    const mapA = makeMap([
      makeCircle(1, 1000, 100, 100),
      makeCircle(2, 2000, 200, 200),
    ]);
    const mapB = makeMap([
      makeCircle(1, 1050, 100, 100),
      makeCircle(2, 2040, 250, 260),
    ]);

    // c1 moved within tolerance (50ms) -> retimed; c2 moved + retimed (40ms).
    const diff = buildVisualDiff(mapA, mapB);
    expect(diff.summary.retimed).toBe(1);
    expect(diff.summary.movedRetimed).toBe(1);
    expect(diff.summary.aOnly).toBe(0);
    expect(diff.summary.bOnly).toBe(0);
  });

  it("treats spinners without positions as shared when timing matches", () => {
    const mapA = makeMap([makeSpinner(1, 1000, 3000)]);
    const mapB = makeMap([makeSpinner(1, 1000, 3000)]);
    const diff = buildVisualDiff(mapA, mapB);
    expect(diff.summary.shared).toBe(1);
  });

  it("matches objects with a timing tolerance", () => {
    const mapA = makeMap([makeCircle(1, 1000, 1, 1)]);
    const mapB = makeMap([makeCircle(1, 1000, 1, 1)]);
    const pairs = matchCandidateObjects(mapA, mapB, 60);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]?.a).toBeDefined();
    expect(pairs[0]?.b).toBeDefined();

    const farMapB = makeMap([makeCircle(1, 5000, 1, 1)]);
    const pairsFar = matchCandidateObjects(mapA, farMapB, 60);
    expect(pairsFar).toHaveLength(2);
    expect(pairsFar[0]?.b).toBeUndefined();
    expect(pairsFar[1]?.a).toBeUndefined();
  });
});

describe("section comparison", () => {
  it("computes per-section metrics and overall winners", () => {
    const mapA = makeMap([
      makeCircle(1, 100, 100, 100),
      makeCircle(2, 600, 200, 200),
      makeCircle(3, 1100, 300, 300),
    ]);
    const mapB = makeMap([
      makeCircle(1, 100, 100, 100),
      makeCircle(2, 900, 150, 150),
    ]);
    const sections = [makeSection(1, 0, 1600)];

    const rows = buildSectionComparison(mapA, mapB, sections);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.metrics.find((metric) => metric.key === "object-count")?.a).toBe(3);
    expect(rows[0]?.metrics.find((metric) => metric.key === "object-count")?.b).toBe(2);
    expect(rows[0]?.metrics.find((metric) => metric.key === "object-count")?.winner).toBe("a");
    expect(rows[0]?.overallWinner).toBe("a");
  });

  it("computes density and movement from object data", () => {
    const map = makeMap([
      makeCircle(1, 0, 0, 0),
      makeCircle(2, 1000, 100, 0),
      makeCircle(3, 2000, 200, 0),
    ]);
    expect(computeSectionDensity(map, 0, 2000)).toBeCloseTo(1.5, 5);
    expect(computeSectionMovement(map, 0, 2000)).toBeCloseTo(100, 5);
  });

  it("merges replay and rebalance report metrics when available", () => {
    const mapA = makeMap([makeCircle(1, 100, 10, 10)]);
    const mapB = makeMap([makeCircle(1, 100, 10, 10)]);
    const sections = [makeSection(1, 0, 1000)];
    const detailA = {
      replay: {
        expectedAccuracy: 0.9,
        expectedMisses: 0.2,
        expectedComboPct: 0.9,
        fatigueAverage: 0.1,
        fatiguePeak: 0.1,
        readingScore: 80,
        replayScore: 90,
        sections: [{ sectionId: 1, label: "section-1", objectCount: 1, accuracy: 0.95, fatiguePeak: 0.05, readingDemand: 0.3 }],
      },
      rebalance: {
        qualityGain: 2,
        replayGain: 1,
        qualityBefore: 70,
        qualityAfter: 72,
        sections: [{ sectionId: 1, label: "section-1", objectCount: 1, starRating: 2.5, density: 1, rhythmConsistency: 0.8, cursorTravelPx: 120, readingScore: 70, fatigueAverage: 0.05, qualityScore: 80 }],
      },
    };
    const detailB = {
      replay: {
        expectedAccuracy: 0.8,
        expectedMisses: 0.5,
        expectedComboPct: 0.7,
        fatigueAverage: 0.2,
        fatiguePeak: 0.2,
        readingScore: 60,
        replayScore: 70,
        sections: [{ sectionId: 1, label: "section-1", objectCount: 1, accuracy: 0.7, fatiguePeak: 0.2, readingDemand: 0.5 }],
      },
      rebalance: {
        qualityGain: 0,
        replayGain: 0,
        qualityBefore: 70,
        qualityAfter: 70,
        sections: [{ sectionId: 1, label: "section-1", objectCount: 1, starRating: 3.5, density: 1.5, rhythmConsistency: 0.5, cursorTravelPx: 300, readingScore: 40, fatigueAverage: 0.2, qualityScore: 60 }],
      },
    };

    const rows = buildSectionComparison(mapA, mapB, sections, detailA, detailB);
    const row = rows[0];
    expect(row?.metrics.find((metric) => metric.key === "replay")?.a).toBe(0.95);
    expect(row?.metrics.find((metric) => metric.key === "replay")?.winner).toBe("a");
    expect(row?.metrics.find((metric) => metric.key === "fatigue")?.winner).toBe("a");
    expect(row?.metrics.find((metric) => metric.key === "movement")?.winner).toBe("a");
    expect(row?.overallWinner).toBe("a");
  });
});

describe("champion promotion and history", () => {
  it("records previous and new champion in history entries", () => {
    const entry = createChampionHistoryEntry({
      sequence: 1,
      previousChampionIndex: 6,
      previousMapPath: "public/candidates/test-song/normal/candidate-006/improved-map.json",
      newChampionIndex: 2,
      newChampionScore: 90.4,
      newMapPath: "public/candidates/test-song/normal/candidate-002/improved-map.json",
      reason: "Manual promotion from the Candidate Browser.",
      manual: true,
      timestamp: "2026-08-14T12:00:00.000Z",
    });
    expect(entry.previousChampionIndex).toBe(6);
    expect(entry.newChampionIndex).toBe(2);
    expect(entry.newMapPath).toContain("candidate-002");
    expect(entry.manual).toBe(true);
  });

  it("appends history with a deterministic sequence and enforces a limit", () => {
    const first = createChampionHistoryEntry({
      sequence: 1,
      previousChampionIndex: null,
      previousMapPath: null,
      newChampionIndex: 6,
      newChampionScore: 71.6,
      newMapPath: "a.json",
      reason: "Engine promotion.",
      manual: false,
      timestamp: "2026-08-14T12:00:00.000Z",
    });
    const second = createChampionHistoryEntry({
      sequence: 2,
      previousChampionIndex: 6,
      previousMapPath: "a.json",
      newChampionIndex: 2,
      newChampionScore: 90.4,
      newMapPath: "b.json",
      reason: "Manual promotion.",
      manual: true,
      timestamp: "2026-08-14T12:05:00.000Z",
    });

    const history = appendChampionHistory(
      appendChampionHistory([], first, 50),
      second,
      50,
    );
    expect(history).toHaveLength(2);
    expect(history[1]?.previousChampionIndex).toBe(6);

    const third = createChampionHistoryEntry({
      sequence: 3,
      previousChampionIndex: 2,
      previousMapPath: "b.json",
      newChampionIndex: 1,
      newChampionScore: 85.1,
      newMapPath: "c.json",
      reason: "Manual promotion.",
      manual: true,
      timestamp: "2026-08-14T12:10:00.000Z",
    });
    const limited = appendChampionHistory(history, third, 2);
    expect(limited).toHaveLength(2);
    expect(limited[0]?.sequence).toBe(2);
    expect(limited[1]?.sequence).toBe(3);
  });

  it("serializes and parses history defensively", () => {
    const raw = [
      {
        sequence: 1,
        previousChampionIndex: null,
        previousMapPath: null,
        newChampionIndex: 6,
        newChampionScore: 71.6,
        newMapPath: "a.json",
        timestamp: "2026-08-14T12:00:00.000Z",
        reason: "Engine promotion.",
        manual: false,
      },
      { junk: true },
      "not-an-entry",
    ];
    const parsed = parseChampionHistory(raw);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.newChampionIndex).toBe(6);

    const serialized = serializeChampionHistory(parsed);
    expect(serialized).toEqual(parsed);
    expect(parseChampionHistory(undefined)).toEqual([]);
  });

  it("builds deterministic workspace keys and note keys", () => {
    const key = buildCandidateWorkspaceKey({
      title: "Test Song",
      artist: "Unknown Artist",
      difficulty: "normal",
    });
    expect(key).toBe(buildCandidateWorkspaceKey({
      title: "Test Song",
      artist: "Unknown Artist",
      difficulty: "normal",
    }));
    expect(key.startsWith("pulse-editor.candidates.")).toBe(true);
    expect(candidateNoteKey(key, 6)).toBe(`${key}:candidate-006`);
  });
});

describe("candidate notes", () => {
  it("keeps notes isolated from scoring logic", () => {
    const entries = buildCandidateBrowserEntries(makeReport());
    const filters = createInitialCandidateFilters();
    const notes: Record<string, string> = {};

    const before = filterCandidateEntries(entries, filters).map((entry) => entry.finalScore);
    notes["anything"] = "Better chorus pattern";
    const after = filterCandidateEntries(entries, filters).map((entry) => entry.finalScore);
    expect(after).toEqual(before);
  });

  it("formats metrics consistently", () => {
    expect(formatCandidateScore(90.45)).toBe("90.5");
    expect(formatCandidateScore(null)).toBe("—");
    expect(formatCandidatePercent(0.8474)).toBe("84.7%");
    expect(formatCandidatePercent(null)).toBe("—");
  });
});

describe("read-only comparison behavior", () => {
  it("does not mutate either candidate when building comparisons", () => {
    const mapA = makeMap([
      makeCircle(1, 1000, 100, 100),
      makeCircle(2, 2000, 200, 200),
    ]);
    const mapB = makeMap([
      makeCircle(1, 1010, 100, 100),
      makeCircle(3, 3000, 300, 300),
    ]);
    const sections = [makeSection(1, 0, 4000)];
    const frozenA = deepFreeze(structuredClone(mapA)) as unknown as EditorMapDocument;
    const frozenB = deepFreeze(structuredClone(mapB)) as unknown as EditorMapDocument;
    const frozenSections = deepFreeze(sections.map((section) => ({ ...section })));

    expect(() => {
      buildVisualDiff(frozenA, frozenB);
      buildSectionComparison(frozenA, frozenB, frozenSections);
      matchCandidateObjects(frozenA, frozenB);
    }).not.toThrow();

    expect(mapA).toEqual(makeMap([
      makeCircle(1, 1000, 100, 100),
      makeCircle(2, 2000, 200, 200),
    ]));
    expect(mapB).toEqual(makeMap([
      makeCircle(1, 1010, 100, 100),
      makeCircle(3, 3000, 300, 300),
    ]));
  });
});

describe("working-copy safety", () => {
  it("never mutates the source evolution report while building entries", () => {
    const report = makeReport();
    const frozenReport = deepFreeze(structuredClone(report)) as unknown as EvolutionReport;
    expect(() => buildCandidateBrowserEntries(frozenReport)).not.toThrow();
  });

  it("parses the extended optional ranking fields and legacy reports", () => {
    const raw = {
      version: 1,
      song: { title: "T", artist: "A", difficulty: "normal", audio: "a.mp3" },
      configuration: { rootSeed: 1, candidateCount: 1, maxPasses: 1, archivePolicy: "all", timingVariation: false },
      summary: { generated: 1, eligible: 1, rejected: 0, passesUsed: 0, earlyStopped: true },
      champion: {
        candidateIndex: 1,
        candidateSeed: 5,
        overallScore: 80,
        qualityScore: 80,
        stars: 3,
        mapPath: "/maps/champions/x.json",
        reportPath: "/reports/champions/x.json",
        sourceMapPath: "public/candidates/x/improved-map.json",
        sourceReportPath: "public/candidates/x/improved-report.json",
        summaryPath: "public/candidates/x/candidate-summary.json",
        promotionReason: "won",
      },
      ranking: [
        {
          rank: 1,
          candidateIndex: 1,
          candidateSeed: 5,
          stars: 3,
          scores: { overall: 80, quality: 80, difficulty: 80, flow: 80, rhythm: 80, movement: 80, pattern: 80, slider: 80, spinner: 80, reading: 80, playability: 80, consistency: 80, confidence: 80, replay: 80 },
          final: { weightedScore: 80, rhythm: 80, playability: 80, pattern: 80, target: 80, reading: 80, replay: 80, consistency: 80, validity: 80, flow: 80, section: 80, fatigue: 80, rebalance: 50 },
          qualityGates: [{ code: "VALID_STRUCTURE", name: "Valid beatmap structure", mandatory: true, passed: true, detail: "ok", penalty: 0 }],
          validationStatus: "passed",
          improvementsMade: ["replay-simulated"],
          targetDeviation: 0.1,
          diversityPenalty: 0.2,
          mapPath: "public/candidates/x/improved-map.json",
          reportPath: "public/candidates/x/improved-report.json",
          summaryPath: "public/candidates/x/candidate-summary.json",
          eligible: true,
          rejectionReasons: [],
        },
      ],
      rejectedCandidates: [],
      comparison: [],
      comparisonReasons: [],
      heatmaps: [],
      replay: { fullComboChance: 0.5, expectedAccuracy: 0.9, expectedMisses: 0.5, highestStressSectionMs: 1000, hardestPattern: "x", mostDifficultTransitionMs: 2000, replayScore: 80, playerProfile: "advanced", expectedComboPct: 0.9, cursorEfficiency: 0.9, readingScore: 80, fatigueAverage: 0.1, fatiguePeak: 0.2, comboBreaks: 1, missClusters: 0, weakestSection: "a", strongestSection: "b" },
      improvementHistory: [],
      diagnostics: { scoreDistribution: {}, averageImprovement: 0, promotionReason: "won", confidence: 90 },
      scoreWeights: {},
      replayReportPath: "public/evolution/x.json",
    };

    const parsed = parseEvolutionReport(raw);
    expect(parsed.ranking[0]?.final?.weightedScore).toBe(80);
    expect(parsed.ranking[0]?.validationStatus).toBe("passed");
    expect(parsed.ranking[0]?.qualityGates).toHaveLength(1);
    expect(parsed.ranking[0]?.targetDeviation).toBe(0.1);
    expect(parsed.ranking[0]?.improvementsMade).toEqual(["replay-simulated"]);

    // Legacy report without the optional fields still parses.
    delete (raw.ranking[0] as Record<string, unknown>).final;
    delete (raw.ranking[0] as Record<string, unknown>).qualityGates;
    delete (raw.ranking[0] as Record<string, unknown>).validationStatus;
    delete (raw.ranking[0] as Record<string, unknown>).improvementsMade;
    delete (raw.ranking[0] as Record<string, unknown>).targetDeviation;
    const legacy = parseEvolutionReport(raw);
    expect(legacy.ranking[0]?.final).toBeUndefined();
    expect(legacy.ranking[0]?.validationStatus).toBeUndefined();
  });
});

function deepFreeze<T>(value: T): T {
  if (value === null || typeof value !== "object") {
    return value;
  }

  for (const key of Object.keys(value)) {
    deepFreeze((value as Record<string, unknown>)[key]);
  }
  return Object.freeze(value);
}
