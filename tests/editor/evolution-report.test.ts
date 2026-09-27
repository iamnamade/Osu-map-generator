import { describe, expect, it } from "vitest";
import { parseEvolutionReport } from "../../src/shared/evolutionReport";

interface RawRankingEntry {
  rank: number;
  candidateIndex: number;
  candidateSeed: number;
  stars: number;
  scores: Record<string, number>;
  mapPath: string;
  reportPath: string;
  summaryPath: string;
  eligible: boolean;
  rejectionReasons: string[];
}

function makeRankingEntry(overrides: Partial<RawRankingEntry> = {}): RawRankingEntry {
  return {
    rank: 1,
    candidateIndex: 2,
    candidateSeed: 99,
    stars: 3.2,
    scores: {
      overall: 91.2,
      quality: 88.0,
      difficulty: 90.0,
      flow: 75.0,
      rhythm: 70.0,
      movement: 85.0,
      pattern: 78.0,
      slider: 82.0,
      spinner: 95.0,
      reading: 72.0,
      playability: 76.0,
      consistency: 88.0,
      confidence: 84.0,
      replay: 67.1,
    },
    mapPath: "public/candidates/test-song/normal/candidate-002/improved-map.json",
    reportPath: "public/candidates/test-song/normal/candidate-002/improved-report.json",
    summaryPath: "public/candidates/test-song/normal/candidate-002/candidate-summary.json",
    eligible: true,
    rejectionReasons: [],
    ...overrides,
  };
}

function makeEvolutionRaw(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
      maxPasses: 2,
      archivePolicy: "all",
      timingVariation: false,
    },
    summary: {
      generated: 3,
      eligible: 3,
      rejected: 0,
      passesUsed: 1,
      earlyStopped: false,
    },
    champion: {
      candidateIndex: 2,
      candidateSeed: 99,
      overallScore: 91.2,
      qualityScore: 88.0,
      stars: 3.2,
      mapPath: "/maps/champions/test-song-normal.json",
      reportPath: "/reports/champions/test-song-normal-report.json",
      sourceMapPath: "public/candidates/test-song/normal/candidate-002/improved-map.json",
      sourceReportPath: "public/candidates/test-song/normal/candidate-002/improved-report.json",
      summaryPath: "public/candidates/test-song/normal/candidate-002/candidate-summary.json",
      promotionReason: "Candidate 002 won by 4.1 points overall.",
    },
    ranking: [makeRankingEntry(), makeRankingEntry({ rank: 2, candidateIndex: 1 })],
    rejectedCandidates: [],
    comparison: [
      {
        dimension: "replay",
        championValue: 67.1,
        runnerValue: 60.2,
        delta: 6.9,
        note: "Champion leads by 6.9 points on Replay.",
      },
    ],
    comparisonReasons: ["Champion gained 6.9 points on Replay."],
    heatmaps: [{ dimension: "movement", label: "Movement", values: [0.5, 0.6] }],
    replay: {
      fullComboChance: 0.0396,
      expectedAccuracy: 0.6671,
      expectedMisses: 2.84,
      highestStressSectionMs: 9613,
      hardestPattern: "zigzag",
      mostDifficultTransitionMs: 13607,
      replayScore: 64.1,
      playerProfile: "advanced",
      expectedComboPct: 0.3077,
      cursorEfficiency: 0.8898,
      readingScore: 66.2,
      fatigueAverage: 0.0061,
      fatiguePeak: 0.0135,
      comboBreaks: 4,
      missClusters: 4,
      weakestSection: "outro-like",
      strongestSection: "intro-like",
    },
    improvementHistory: [
      { passNumber: 1, candidateIndex: 2, overallBefore: 88.0, overallAfter: 91.2, accepted: true },
    ],
    diagnostics: {
      scoreDistribution: { "60-69": 0, "70-79": 0, "80-89": 1, "90-100": 1 },
      averageImprovement: 3.2,
      promotionReason: "Candidate 002 won by 4.1 points overall.",
      confidence: 82.8,
    },
    scoreWeights: {
      quality: 0.16,
      difficulty: 0.08,
      playability: 0.1,
      consistency: 0.07,
      confidence: 0.05,
      reading: 0.07,
      rhythm: 0.08,
      flow: 0.07,
      movement: 0.07,
      pattern: 0.05,
      slider: 0.05,
      spinner: 0.05,
      replay: 0.1,
    },
    replayReportPath: "public/evolution/test-song-normal-evolution-replay.json",
    ...overrides,
  };
}

describe("evolution report contract (Python -> TypeScript)", () => {
  it("parses the Phase 15 replay fields from the report", () => {
    const report = parseEvolutionReport(makeEvolutionRaw());
    expect(report.version).toBe(1);
    expect(report.replay.replayScore).toBe(64.1);
    expect(report.replay.playerProfile).toBe("advanced");
    expect(report.replay.weakestSection).toBe("outro-like");
    expect(report.replayReportPath).toBe(
      "public/evolution/test-song-normal-evolution-replay.json",
    );
    expect(report.ranking[0].scores.replay).toBe(67.1);
    expect(report.scoreWeights.replay).toBe(0.1);
  });

  it("still parses legacy reports without the Phase 15 fields", () => {
    const raw = makeEvolutionRaw();
    delete raw.replayReportPath;
    delete (raw.replay as Record<string, unknown>).replayScore;
    delete (raw.replay as Record<string, unknown>).playerProfile;
    delete (raw.replay as Record<string, unknown>).expectedComboPct;
    delete (raw.replay as Record<string, unknown>).weakestSection;
    delete (raw.ranking[0].scores as Record<string, number>).replay;
    delete (raw.ranking[1].scores as Record<string, number>).replay;

    const report = parseEvolutionReport(raw);
    expect(report.replay.replayScore).toBe(0);
    expect(report.replay.playerProfile).toBe("");
    expect(report.replay.weakestSection).toBe("");
    expect(report.replayReportPath).toBe("");
    expect(report.ranking[0].scores.replay).toBe(0);
  });

  it("rejects malformed reports", () => {
    expect(() => parseEvolutionReport({})).toThrow();
    expect(() => parseEvolutionReport(makeEvolutionRaw({ replay: "nope" }))).toThrow();
  });
});
