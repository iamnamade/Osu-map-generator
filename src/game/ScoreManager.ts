import type {
  HudSnapshot,
  Judgment,
  JudgmentCountMap,
  JudgmentOutcome,
  ResultsSnapshot,
  ScoreSnapshot,
} from "./types";

export const TIMING_WINDOWS = {
  Perfect: 50,
  Good: 100,
  Okay: 160,
} as const;

const SCORE_VALUES: Record<Judgment, number> = {
  Perfect: 300,
  Good: 100,
  Okay: 50,
  Miss: 0,
};

const MAX_JUDGMENT_VALUE = SCORE_VALUES.Perfect;
const MAX_COMBO_STEPS = 20;
const COMBO_STEP_VALUE = 0.05;

function createEmptyCounts(): JudgmentCountMap {
  return {
    Perfect: 0,
    Good: 0,
    Okay: 0,
    Miss: 0,
  };
}

export class ScoreManager {
  private readonly totalObjects: number;
  private score = 0;
  private combo = 0;
  private maxCombo = 0;
  private resolvedObjects = 0;
  private totalJudgmentValue = 0;
  private counts = createEmptyCounts();
  private lastJudgment: Judgment | null = null;

  public constructor(totalObjects: number) {
    this.totalObjects = totalObjects;
  }

  public judge(diffMs: number): Judgment {
    const absoluteDiff = Math.abs(diffMs);

    if (absoluteDiff <= TIMING_WINDOWS.Perfect) {
      return "Perfect";
    }

    if (absoluteDiff <= TIMING_WINDOWS.Good) {
      return "Good";
    }

    if (absoluteDiff <= TIMING_WINDOWS.Okay) {
      return "Okay";
    }

    return "Miss";
  }

  public registerHit(diffMs: number): JudgmentOutcome {
    return this.applyJudgment(this.judge(diffMs), diffMs);
  }

  public registerMiss(diffMs = TIMING_WINDOWS.Okay + 1): JudgmentOutcome {
    return this.applyJudgment("Miss", diffMs);
  }

  public registerSpinnerResult(
    completed: boolean,
    bonusScore = 0,
    diffMs = TIMING_WINDOWS.Okay + 1,
  ): JudgmentOutcome {
    if (!completed) {
      return this.applyJudgment("Miss", diffMs);
    }

    return this.applyJudgmentWithBonus("Perfect", diffMs, bonusScore);
  }

  private applyJudgmentWithBonus(
    judgment: Judgment,
    diffMs: number,
    bonusScore: number,
  ): JudgmentOutcome {
    const scoreValue = SCORE_VALUES[judgment];
    const multiplier = 1 + Math.min(this.combo, MAX_COMBO_STEPS) * COMBO_STEP_VALUE;
    const scoreAwarded = Math.round(scoreValue * multiplier) + Math.max(0, Math.round(bonusScore));
    this.score += scoreAwarded;
    this.combo += 1;
    this.maxCombo = Math.max(this.maxCombo, this.combo);
    this.totalJudgmentValue += scoreValue;
    this.resolvedObjects += 1;
    this.counts[judgment] += 1;
    this.lastJudgment = judgment;

    return {
      ...this.snapshot(),
      judgment,
      diffMs,
      scoreAwarded,
      judgmentValue: scoreValue,
    };
  }

  public createHudSnapshot(
    currentJudgment: string,
    progress: number,
    elapsedMs: number,
    durationMs: number,
  ): HudSnapshot {
    const snapshot = this.snapshot();

    return {
      score: snapshot.score,
      combo: snapshot.combo,
      accuracy: snapshot.accuracy,
      progress,
      currentJudgment,
      elapsedMs,
      durationMs,
    };
  }

  public buildResults(title: string, artist: string): ResultsSnapshot {
    const snapshot = this.snapshot();

    return {
      title,
      artist,
      score: snapshot.score,
      accuracy: snapshot.accuracy,
      maxCombo: snapshot.maxCombo,
      counts: { ...snapshot.counts },
      totalObjects: snapshot.totalObjects,
    };
  }

  public snapshot(): ScoreSnapshot {
    return {
      score: this.score,
      combo: this.combo,
      maxCombo: this.maxCombo,
      accuracy: this.getAccuracy(),
      resolvedObjects: this.resolvedObjects,
      totalObjects: this.totalObjects,
      counts: { ...this.counts },
      lastJudgment: this.lastJudgment,
    };
  }

  private applyJudgment(judgment: Judgment, diffMs: number): JudgmentOutcome {
    const scoreValue = SCORE_VALUES[judgment];
    let scoreAwarded = 0;

    if (judgment === "Miss") {
      this.combo = 0;
    } else {
      const multiplier = 1 + Math.min(this.combo, MAX_COMBO_STEPS) * COMBO_STEP_VALUE;
      scoreAwarded = Math.round(scoreValue * multiplier);
      this.combo += 1;
      this.maxCombo = Math.max(this.maxCombo, this.combo);
    }

    this.score += scoreAwarded;
    this.totalJudgmentValue += scoreValue;
    this.resolvedObjects += 1;
    this.counts[judgment] += 1;
    this.lastJudgment = judgment;

    return {
      ...this.snapshot(),
      judgment,
      diffMs,
      scoreAwarded,
      judgmentValue: scoreValue,
    };
  }

  private getAccuracy(): number {
    if (this.resolvedObjects === 0) {
      return 100;
    }

    return (this.totalJudgmentValue / (this.resolvedObjects * MAX_JUDGMENT_VALUE)) * 100;
  }
}
