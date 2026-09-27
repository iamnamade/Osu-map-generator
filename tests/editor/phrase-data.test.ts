import { describe, expect, it } from "vitest";

import {
  findPhraseByTime,
  getRelationshipColor,
  getStrategyColor,
  parsePhraseReport,
  type PhraseReport,
} from "../../src/shared/phraseData";

function makePhraseReport(): PhraseReport {
  return {
    version: 1,
    audio: { path: "audio.mp3", durationMs: 60000 },
    configuration: {},
    inputSignature: "signature",
    phrases: [
      {
        id: 1,
        startMs: 0,
        endMs: 15000,
        durationMs: 15000,
        sectionId: 1,
        label: "chorus-like",
        confidence: 0.8,
        averageEnergy: 0.7,
        energySlope: 0.001,
        onsetDensity: 3.0,
        beatDensity: 1.2,
        averageOnsetStrength: 0.6,
        rhythmComplexity: 0.6,
        spectralFlux: 0.01,
        emphasisRatio: 0.6,
        quietRatio: 0.1,
        highEnergyRatio: 0.8,
        subdivisionRatio: 2.5,
        motifId: 1,
        strategy: "establish",
        targetDensity: 2.5,
        targetDifficulty: 0.8,
        minGapMs: 100,
        targetGapMs: 400,
        entryDirectionDeg: 12,
        exitDirectionDeg: -8,
        sectionRepetitionGroup: 1,
      },
      {
        id: 2,
        startMs: 15000,
        endMs: 30000,
        durationMs: 15000,
        sectionId: 2,
        label: "verse-like",
        confidence: 0.7,
        averageEnergy: 0.3,
        energySlope: -0.002,
        onsetDensity: 1.2,
        beatDensity: 1.0,
        averageOnsetStrength: 0.5,
        rhythmComplexity: 0.3,
        spectralFlux: 0.02,
        emphasisRatio: 0.3,
        quietRatio: 0.4,
        highEnergyRatio: 0.2,
        subdivisionRatio: 1.2,
        motifId: 2,
        strategy: "recover",
        targetDensity: 0.9,
        targetDifficulty: 0.3,
        minGapMs: 250,
        targetGapMs: 1100,
        entryDirectionDeg: -5,
        exitDirectionDeg: 3,
        sectionRepetitionGroup: 2,
      },
    ],
    relationships: [
      {
        id: 1,
        fromPhraseId: 1,
        toPhraseId: 2,
        relationshipType: "continuation",
        similarity: 0.8,
        confidence: 0.7,
        featureDeltas: { averageEnergy: -0.4 },
      },
    ],
    motifs: [
      {
        id: 1,
        phraseIds: [1],
        rhythmSignature: [2.5, 1.2, 0.6],
        densityProfile: [3.0, 0.7],
        occurrenceCount: 1,
        label: "Motif 1",
      },
    ],
    trajectory: [
      { timeMs: 0, density: 2.5, difficulty: 0.8 },
      { timeMs: 15000, density: 0.9, difficulty: 0.3 },
    ],
    summary: { phraseCount: 2 },
  };
}

describe("phrase data parsing", () => {
  it("parses a complete phrase report", () => {
    const report = parsePhraseReport(makePhraseReport());
    expect(report.phrases).toHaveLength(2);
    expect(report.relationships).toHaveLength(1);
    expect(report.motifs).toHaveLength(1);
    expect(report.trajectory).toHaveLength(2);
    expect(report.phrases[0]?.strategy).toBe("establish");
    expect(report.phrases[1]?.strategy).toBe("recover");
    expect(report.phrases[0]?.motifId).toBe(1);
  });

  it("round-trips through raw JSON", () => {
    const raw = JSON.parse(JSON.stringify(makePhraseReport()));
    const report = parsePhraseReport(raw);
    expect(report.phrases[0]?.targetDensity).toBe(2.5);
    expect(report.phrases[1]?.minGapMs).toBe(250);
  });

  it("finds the phrase containing a time", () => {
    const report = parsePhraseReport(makePhraseReport());
    expect(findPhraseByTime(report.phrases, 1000)?.id).toBe(1);
    expect(findPhraseByTime(report.phrases, 20000)?.id).toBe(2);
    expect(findPhraseByTime(report.phrases, 90000)).toBeUndefined();
  });
});

describe("phrase backward compatibility", () => {
  it("defaults missing strategy to neutral", () => {
    const raw = JSON.parse(JSON.stringify(makePhraseReport()));
    delete raw.phrases[0].strategy;
    const report = parsePhraseReport(raw);
    expect(report.phrases[0]?.strategy).toBe("neutral");
  });

  it("defaults missing optional fields", () => {
    const raw = JSON.parse(JSON.stringify(makePhraseReport()));
    delete raw.phrases[0].motifId;
    delete raw.phrases[0].sectionId;
    const report = parsePhraseReport(raw);
    expect(report.phrases[0]?.motifId).toBeNull();
    expect(report.phrases[0]?.sectionId).toBeNull();
  });

  it("tolerates unknown relationship types with a fallback", () => {
    const raw = JSON.parse(JSON.stringify(makePhraseReport()));
    raw.relationships[0].relationshipType = "weird";
    const report = parsePhraseReport(raw);
    expect(report.relationships[0]?.relationshipType).toBe("continuation");
  });
});

describe("phrase visualization helpers", () => {
  it("maps strategies to colors", () => {
    expect(getStrategyColor("intensify")).toBe("#ff7a6e");
    expect(getStrategyColor("recover")).toBe("#6fcf97");
    expect(getStrategyColor("unknown" as never)).toBe("#8da0be");
  });

  it("maps relationship types to colors", () => {
    expect(getRelationshipColor("repetition")).toBe("#5de0a6");
    expect(getRelationshipColor("contrast")).toBe("#f6c15e");
  });
});
