import { describe, expect, it } from "vitest";

import {
  fatigueAtTime,
  getTriggerColor,
  parseRecoveryReport,
  type RecoveryReport,
} from "../../src/shared/recoveryData";

function makeRecoveryReport(): RecoveryReport {
  return {
    version: 1,
    difficulty: "hard",
    audioDurationMs: 30000,
    objectCount: 120,
    spinnerCount: 2,
    avgSpinnerDurationMs: 1500,
    guidelines: { minDurationMs: 600, postClearanceMs: 350 },
    fatigue: {
      timestamps: [1000, 1150, 1300, 5000, 9000],
      fatigueScores: [0.1, 0.4, 0.8, 0.2, 0.3],
      peakFatigueTime: 1300,
      peakFatigue: 0.8,
    },
    recoveryWindows: [
      {
        startTime: 1300,
        endTime: 5000,
        staminaReductionFactor: 0.6,
        reason: "post_intense_phrase",
        phraseId: 1,
      },
    ],
    harmony: {
      roles: {
        intensify: { circle: 40, slider: 10, spinner: 0, total: 50 },
        recover: { circle: 20, slider: 5, spinner: 2, total: 27 },
      },
      violations: [
        {
          role: "intensify",
          message: "intensify phrases contain 3 spinners (6% of 50 objects, cap 6%).",
        },
      ],
    },
    objectTypeCounts: { circle: 90, slider: 28, spinner: 2 },
  };
}

describe("recovery data parsing", () => {
  it("parses a complete recovery report", () => {
    const report = parseRecoveryReport(makeRecoveryReport());
    expect(report.spinnerCount).toBe(2);
    expect(report.fatigue.peakFatigue).toBe(0.8);
    expect(report.recoveryWindows).toHaveLength(1);
    expect(report.recoveryWindows[0]?.reason).toBe("post_intense_phrase");
    expect(report.harmony.roles.intensify?.spinner).toBe(0);
    expect(report.harmony.violations).toHaveLength(1);
    expect(report.objectTypeCounts.spinner).toBe(2);
    expect(report.guidelines.postClearanceMs).toBe(350);
  });

  it("round-trips through raw JSON", () => {
    const raw = JSON.parse(JSON.stringify(makeRecoveryReport()));
    const report = parseRecoveryReport(raw);
    expect(report.fatigue.timestamps).toHaveLength(5);
    expect(report.recoveryWindows[0]?.staminaReductionFactor).toBe(0.6);
    expect(report.difficulty).toBe("hard");
  });
});

describe("fatigue lookup", () => {
  it("averages fatigue in a window around a timestamp", () => {
    const report = parseRecoveryReport(makeRecoveryReport());
    // Around 1150 (window 400ms) covers 1000 + 1150 + 1300.
    const value = fatigueAtTime(report.fatigue, 1150);
    expect(value).toBeCloseTo((0.1 + 0.4 + 0.8) / 3, 5);
  });

  it("falls back to the nearest sample outside the window", () => {
    const report = parseRecoveryReport(makeRecoveryReport());
    const value = fatigueAtTime(report.fatigue, 9000);
    expect(value).toBe(0.3);
  });

  it("returns 0 for an empty profile", () => {
    const empty = {
      timestamps: [],
      fatigueScores: [],
      peakFatigueTime: 0,
      peakFatigue: 0,
    };
    expect(fatigueAtTime(empty, 1000)).toBe(0);
  });
});

describe("recovery backward compatibility", () => {
  it("tolerates a missing objectTypeCounts", () => {
    const raw = JSON.parse(JSON.stringify(makeRecoveryReport())) as Record<
      string,
      unknown
    >;
    delete raw.objectTypeCounts;
    const report = parseRecoveryReport(raw);
    expect(report.objectTypeCounts.circle).toBe(0);
  });

  it("tolerates an empty recoveryWindows list", () => {
    const raw = JSON.parse(JSON.stringify(makeRecoveryReport())) as Record<
      string,
      unknown
    >;
    raw.recoveryWindows = [];
    const report = parseRecoveryReport(raw);
    expect(report.recoveryWindows).toHaveLength(0);
  });

  it("tolerates an empty harmony roles map", () => {
    const raw = JSON.parse(JSON.stringify(makeRecoveryReport())) as Record<
      string,
      unknown
    >;
    raw.harmony = { roles: {}, violations: [] };
    const report = parseRecoveryReport(raw);
    expect(report.harmony.roles).toEqual({});
  });
});

describe("recovery visualization helpers", () => {
  it("maps trigger types to colors", () => {
    expect(getTriggerColor("sustain")).toBe("#5de0a6");
    expect(getTriggerColor("fade_out")).toBe("#8ab4ff");
    expect(getTriggerColor("riser")).toBe("#f6c15e");
    expect(getTriggerColor("unknown" as never)).toBe("#8da0be");
  });
});
