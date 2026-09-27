import { describe, expect, it } from "vitest";
import { parseDifficultyReport } from "../../src/shared/difficultyReport";
import { analyzeDifficultyLive } from "../../src/shared/difficultyEngine";
import type { Beatmap } from "../../src/game/types";
import testSongEasyReport from "../../public/difficulty/test-song-easy-difficulty.json";
import testSongNormalReport from "../../public/difficulty/test-song-normal-difficulty.json";
import testSongHardReport from "../../public/difficulty/test-song-hard-difficulty.json";

describe("difficulty report contract (Python -> TypeScript)", () => {
  it("parses the generated easy report produced by the Python engine", () => {
    const report = parseDifficultyReport(testSongEasyReport);
    expect(report.version).toBe(1);
    expect(report.map.objectCount).toBeGreaterThan(0);
    expect(report.starRating.overall).toBeGreaterThan(0);
    expect(report.target.name).toBe("easy");
    expect(report.sections.length).toBeGreaterThan(0);
    expect(report.curve.length).toBeGreaterThan(0);
    expect(report.signature.trim().length).toBeGreaterThan(0);
  });

  it("parses the generated normal and hard reports", () => {
    const normal = parseDifficultyReport(testSongNormalReport);
    const hard = parseDifficultyReport(testSongHardReport);
    expect(normal.target.name).toBe("normal");
    expect(hard.target.name).toBe("hard");
    expect(normal.metrics.objectCount).toBeGreaterThan(0);
    expect(hard.metrics.objectCount).toBeGreaterThan(0);
    expect(hard.starRating.overall).toBeGreaterThan(0);
  });

  it("exposes per-axis stars and diagnostic sections", () => {
    const report = parseDifficultyReport(testSongEasyReport);
    expect(report.starRating.aim).toBeGreaterThanOrEqual(0);
    expect(report.starRating.speed).toBeGreaterThanOrEqual(0);
    expect(report.starRating.reading).toBeGreaterThanOrEqual(0);
    expect(report.starRating.rhythm).toBeGreaterThanOrEqual(0);
    expect(report.starRating.stamina).toBeGreaterThanOrEqual(0);
    expect(report.starRating.technical).toBeGreaterThanOrEqual(0);
    expect(report.diagnostics.difficultyHistogram).toBeDefined();
    expect(report.gameplay.simulatedPlaycount).toBeGreaterThan(0);
  });
});

describe("live difficulty engine", () => {
  const beatmap: Beatmap = {
    title: "Test",
    artist: "Artist",
    audio: "song.mp3",
    approachTime: 800,
    circleRadius: 48,
    objects: [
      { id: 1, type: "circle", x: 100, y: 100, time: 1000 },
      { id: 2, type: "circle", x: 300, y: 100, time: 1250 },
      { id: 3, type: "circle", x: 100, y: 300, time: 1500 },
      { id: 4, type: "circle", x: 300, y: 300, time: 1750 },
      { id: 5, type: "circle", x: 100, y: 100, time: 2000 },
    ],
  };

  it("produces a deterministic analysis for identical input", () => {
    const first = analyzeDifficultyLive({ beatmap });
    const second = analyzeDifficultyLive({ beatmap });
    expect(first.starRating.overall).toBe(second.starRating.overall);
    expect(first.peakDifficulty).toBe(second.peakDifficulty);
    expect(first.curve).toEqual(second.curve);
  });

  it("exposes the resolved target range for the badge", () => {
    const analysis = analyzeDifficultyLive({
      beatmap,
      targetName: "hard",
    });
    expect(analysis.target).toEqual({ name: "hard", min: 3.6, max: 5.4 });
  });

  it("falls back to normal target for unknown names", () => {
    const analysis = analyzeDifficultyLive({
      beatmap,
      targetName: "not-a-preset",
    });
    expect(analysis.target.name).toBe("normal");
  });

  it("computes section and gameplay estimates", () => {
    const analysis = analyzeDifficultyLive({
      beatmap,
      sections: [
        { id: 1, label: "Intro", startMs: 1000, endMs: 2000, durationMs: 1000 },
      ],
    });
    expect(analysis.sections.length).toBeGreaterThanOrEqual(1);
    expect(analysis.gameplay.estimatedMissProbability).toBeGreaterThanOrEqual(0);
    expect(analysis.gameplay.estimatedComboStability).toBeGreaterThanOrEqual(0);
    expect(analysis.objectDifficulty.length).toBe(5);
  });
});
