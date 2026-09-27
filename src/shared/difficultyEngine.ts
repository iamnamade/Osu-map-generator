import {
  getHitObjectEndTime,
  getHitObjectStartTime,
  hasHitObjectPosition,
  type Beatmap,
  type BeatmapHitObject,
  type BeatmapSliderHitObject,
  type PositionedBeatmapHitObject,
} from "../game/types";
import type {
  AimMetricsSummary,
  DifficultyCurvePointSummary,
  GameplayAnalyticsSummary,
  ObjectDifficultySummary,
  PatternDifficultySummary,
  RawMetricsSummary,
  ReadingMetricsSummary,
  RhythmMetricsSummary,
  SectionDifficultySummary,
  StaminaMetricsSummary,
  StarRatingSummary,
} from "./difficultyReport";
import { clamp } from "./format";
import type { SongSection } from "./sectionData";

export interface LiveDifficultyInput {
  beatmap: Beatmap;
  sections?: SongSection[];
  targetName?: string;
}

export interface LiveDifficultyTarget {
  name: string;
  min: number;
  max: number;
}

export interface LiveDifficultyAnalysis {
  target: LiveDifficultyTarget;
  metrics: RawMetricsSummary;
  reading: ReadingMetricsSummary;
  rhythm: RhythmMetricsSummary;
  aim: AimMetricsSummary;
  stamina: StaminaMetricsSummary;
  patterns: PatternDifficultySummary[];
  sections: SectionDifficultySummary[];
  curve: DifficultyCurvePointSummary[];
  objectDifficulty: ObjectDifficultySummary[];
  starRating: StarRatingSummary;
  gameplay: GameplayAnalyticsSummary;
  recommendedPlayerLevel: string;
  consistencyScore: number;
  peakDifficulty: number;
  averageDifficulty: number;
  confidenceScore: number;
}

const TARGETS: Record<string, { min: number; max: number }> = {
  easy: { min: 1.0, max: 2.6 },
  normal: { min: 2.2, max: 3.9 },
  hard: { min: 3.6, max: 5.4 },
  insane: { min: 5.2, max: 6.8 },
  expert: { min: 6.6, max: 8.4 },
  custom: { min: 0.8, max: 8.0 },
};

export function analyzeDifficultyLive(
  input: LiveDifficultyInput,
): LiveDifficultyAnalysis {
  const beatmap = input.beatmap;
  const targetName = resolveTargetName(input.targetName);
  const target = TARGETS[targetName] ?? TARGETS.normal;

  const metrics = computeRawMetrics(beatmap);
  const reading = computeReading(beatmap, metrics);
  const rhythm = computeRhythm(beatmap);
  const aim = computeAim(beatmap);
  const stamina = computeStamina(beatmap, metrics);
  const patterns = scorePatterns(beatmap, metrics);
  const technical = computeTechnicalScore(metrics, patterns);
  const starRating = computeStars(metrics, aim, reading, rhythm, stamina, technical);

  const sections = computeSections(beatmap, input.sections, reading, rhythm, aim);
  const sectionScores = sections.map((section) => section.difficultyScore);
  const curve = buildCurve(beatmap, reading, rhythm);
  const objectDifficulty = computeObjectDifficulty(beatmap, aim, reading, rhythm);
  const gameplay = computeGameplay(beatmap, metrics, aim, reading, rhythm, stamina);

  const peakDifficulty = curve.length > 0
    ? Math.max(...curve.map((point) => point.difficultyScore))
    : 0;
  const averageDifficulty = curve.length > 0
    ? curve.reduce((sum, point) => sum + point.difficultyScore, 0) / curve.length
    : 0;
  const consistencyScore = consistency(sectionScores);
  const confidenceScore = confidence(sectionScores);

  return {
    target: { name: targetName, min: target.min, max: target.max },
    metrics,
    reading,
    rhythm,
    aim,
    stamina,
    patterns,
    sections,
    curve,
    objectDifficulty,
    starRating,
    gameplay,
    recommendedPlayerLevel: recommendedLevel(starRating.overall),
    consistencyScore,
    peakDifficulty,
    averageDifficulty,
    confidenceScore,
  };
}

function resolveTargetName(name: string | undefined): string {
  return name && name in TARGETS ? name : "normal";
}

function computeRawMetrics(beatmap: Beatmap): RawMetricsSummary {
  const objects = beatmap.objects;
  if (objects.length === 0) {
    return emptyRawMetrics();
  }
  const activeDurationMs = Math.max(
    1,
    getHitObjectStartTime(objects[objects.length - 1]) - getHitObjectStartTime(objects[0]),
  );
  const activeSeconds = activeDurationMs / 1000;
  const circleCount = objects.filter((item) => item.type === "circle").length;
  const sliderCount = objects.filter((item) => item.type === "slider").length;
  const spinnerCount = objects.filter((item) => item.type === "spinner").length;

  const gaps: number[] = [];
  for (let index = 1; index < objects.length; index += 1) {
    const gap = getHitObjectStartTime(objects[index]) - getHitObjectStartTime(objects[index - 1]);
    if (gap > 0) {
      gaps.push(gap);
    }
  }

  const positioned = objects.filter(hasHitObjectPosition);
  const jumpDistances: number[] = [];
  const velocities: number[] = [];
  const accelerations: number[] = [];
  for (let index = 1; index < positioned.length; index += 1) {
    const left = positioned[index - 1];
    const right = positioned[index];
    const distance = Math.hypot(right.x - left.x, right.y - left.y);
    jumpDistances.push(distance);
    const deltaMs = getHitObjectStartTime(right) - getHitObjectStartTime(left);
    if (deltaMs > 0) {
      velocities.push(distance / (deltaMs / 1000));
    }
  }
  for (let index = 1; index < velocities.length; index += 1) {
    accelerations.push(velocities[index] - velocities[index - 1]);
  }

  const turnAngles: number[] = [];
  let directionChangeCount = 0;
  for (let index = 1; index < positioned.length - 1; index += 1) {
    const angle = turnAngleDeg(positioned[index - 1], positioned[index], positioned[index + 1]);
    if (angle !== null) {
      turnAngles.push(angle);
      if (angle >= 110) {
        directionChangeCount += 1;
      }
    }
  }

  const streamFlags = gaps.map((gap) => gap <= 190);
  const burstFlags = gaps.map((gap) => gap <= 300);
  const longestStreamLength = longestRun(streamFlags) + 1;
  const longestBurstLength = longestRun(burstFlags) + 1;

  const sliderDurations: number[] = [];
  const sliderVelocities: number[] = [];
  const sliderRepeats: number[] = [];
  for (const item of objects) {
    if (item.type !== "slider") {
      continue;
    }
    const slider = item as BeatmapSliderHitObject;
    const durationMs = Math.max(0, getHitObjectEndTime(slider) - getHitObjectStartTime(slider));
    sliderDurations.push(durationMs);
    sliderRepeats.push(slider.repeats);
    if (durationMs > 0) {
      sliderVelocities.push(slider.pixelLength / (durationMs / 1000));
    }
  }

  const reactionTimes = gaps;
  const recoveryWindowCount = gaps.filter((gap) => gap >= 1200).length;

  return {
    objectCount: objects.length,
    circleCount,
    sliderCount,
    spinnerCount,
    activeDurationMs,
    objectsPerSecond: activeSeconds > 0 ? objects.length / activeSeconds : 0,
    circleDensity: activeSeconds > 0 ? circleCount / activeSeconds : 0,
    sliderDensity: activeSeconds > 0 ? sliderCount / activeSeconds : 0,
    spinnerFrequencyPerMinute: activeDurationMs > 0
      ? spinnerCount / (activeDurationMs / 60000)
      : 0,
    averageGapMs: mean(gaps),
    minimumGapMs: gaps.length > 0 ? Math.min(...gaps) : 0,
    maximumGapMs: gaps.length > 0 ? Math.max(...gaps) : 0,
    gapStandardDeviationMs: standardDeviation(gaps),
    averageJumpDistance: mean(jumpDistances),
    maximumJumpDistance: jumpDistances.length > 0 ? Math.max(...jumpDistances) : 0,
    jumpDistanceStandardDeviation: standardDeviation(jumpDistances),
    averageCursorVelocityPps: mean(velocities),
    maximumCursorVelocityPps: velocities.length > 0 ? Math.max(...velocities) : 0,
    averageCursorAccelerationPps2: mean(accelerations),
    angleComplexity: mean(turnAngles),
    directionChangeCount,
    longestStreamLength,
    longestBurstLength,
    averageSliderLengthMs: mean(sliderDurations),
    averageSliderVelocityPps: mean(sliderVelocities),
    averageSliderRepeats: mean(sliderRepeats),
    sliderComplexity: sliderComplexity(sliderVelocities, sliderRepeats, sliderCount),
    averageReactionTimeMs: mean(reactionTimes),
    minimumReactionTimeMs: reactionTimes.length > 0 ? Math.min(...reactionTimes) : 0,
    recoveryWindowCount,
    patternVariation: patternVariation(positioned),
    staminaDemand: staminaDemandProxy(objects),
    rhythmComplexity: rhythmComplexityProxy(gaps),
  };
}

function computeReading(beatmap: Beatmap, metrics: RawMetricsSummary): ReadingMetricsSummary {
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const circleRadius = beatmap.circleRadius;
  const approachTime = beatmap.approachTime;
  const overlapThreshold = circleRadius * 1.7;
  const stackingThreshold = circleRadius * 0.35;

  let stackingCount = 0;
  let overlapCount = 0;
  const pairs = positionedPairs(beatmap);
  for (const pair of pairs) {
    if (pair.distance <= stackingThreshold) {
      stackingCount += 1;
    }
    if (pair.distance <= overlapThreshold && pair.timeGapMs <= approachTime * 0.8) {
      overlapCount += 1;
    }
  }

  const times = positioned.map((item) => getHitObjectStartTime(item));
  const clutterCounts: number[] = [];
  for (let index = 0; index < times.length; index += 1) {
    const start = times[index] - approachTime;
    const end = times[index];
    let count = 0;
    for (let other = 0; other < times.length; other += 1) {
      if (other !== index && times[other] >= start && times[other] <= end) {
        count += 1;
      }
    }
    clutterCounts.push(count);
  }
  const visualClutter = mean(clutterCounts);
  const approachTimingRatio = approachTime > 0
    ? metrics.averageReactionTimeMs / approachTime
    : 0;

  const turnAngles = turnAnglesFor(positioned);
  const ambiguous = turnAngles.filter((angle) => angle >= 45 && angle <= 135).length;
  const directionAmbiguity = turnAngles.length > 0 ? ambiguous / turnAngles.length : 0;

  const distances = pairs.map((pair) => pair.distance);
  const spacingComplexity = coefficientOfVariation(distances);
  const score = pairs.length > 0
    ? clamp(
        norm(spacingComplexity, 0.9) * 0.22
        + norm(visualClutter, 4) * 0.22
        + norm(Math.max(0, 1 - approachTimingRatio * 1.2), 1) * 0.18
        + directionAmbiguity * 0.18
        + norm(overlapCount / pairs.length, 0.25) * 0.12
        + norm(stackingCount / pairs.length, 0.2) * 0.08,
        0,
        1,
      )
    : 0;

  return {
    spacingComplexity: clamp(spacingComplexity, 0, 1.5),
    stackingCount,
    overlapCount,
    visualClutter: round3(visualClutter),
    approachTimingRatio: round3(approachTimingRatio),
    directionAmbiguity: round3(directionAmbiguity),
    patternRecognitionDemand: round3(metrics.patternVariation),
    score,
  };
}

function computeRhythm(beatmap: Beatmap): RhythmMetricsSummary {
  const objects = beatmap.objects;
  const gaps: number[] = [];
  for (let index = 1; index < objects.length; index += 1) {
    const gap = getHitObjectStartTime(objects[index]) - getHitObjectStartTime(objects[index - 1]);
    if (gap > 0) {
      gaps.push(gap);
    }
  }
  if (gaps.length === 0) {
    return {
      syncopationRatio: 0,
      subdivisionVariety: 0,
      rhythmSwitchCount: 0,
      timingConsistency: 0,
      tempoChangeCount: 0,
      offbeatRatio: 0,
      tripletCount: 0,
      burstCount: 0,
      score: 0,
    };
  }

  const meanGap = mean(gaps);
  const bucketSize = Math.max(30, meanGap * 0.25);
  const subdivisionVariety = bucketCount(gaps, bucketSize) / gaps.length;
  let rhythmSwitchCount = 0;
  let tempoChangeCount = 0;
  for (let index = 1; index < gaps.length; index += 1) {
    const delta = gaps[index] - gaps[index - 1];
    if (Math.abs(delta) >= meanGap * 0.4) {
      rhythmSwitchCount += 1;
    }
    if (Math.abs(delta) >= meanGap * 0.6) {
      tempoChangeCount += 1;
    }
  }
  const timingConsistency = clamp(1 - standardDeviation(gaps) / Math.max(1, meanGap * 0.6), 0, 1);

  const dominantGap = dominantGapMs(gaps);
  const syncopated = gaps.filter((gap) => gapErrorRatio(gap, dominantGap) > 0.25).length;
  const syncopationRatio = syncopated / gaps.length;
  const offbeatRatio = syncopationRatio;

  let tripletCount = 0;
  let burstCount = 0;
  const rapidThreshold = Math.max(140, meanGap * 0.5);
  for (let index = 0; index < gaps.length - 2; index += 1) {
    const triple = gaps.slice(index, index + 3);
    if (Math.max(...triple) - Math.min(...triple) <= meanGap * 0.12
      && triple.every((gap) => gap <= rapidThreshold)) {
      tripletCount += 1;
    }
  }
  let burstRun = 0;
  for (const gap of gaps) {
    if (gap <= rapidThreshold) {
      burstRun += 1;
    } else {
      if (burstRun >= 3) {
        burstCount += 1;
      }
      burstRun = 0;
    }
  }
  if (burstRun >= 3) {
    burstCount += 1;
  }

  const score = clamp(
    syncopationRatio * 0.25
    + norm(subdivisionVariety, 0.5) * 0.2
    + norm(rhythmSwitchCount / gaps.length, 0.5) * 0.2
    + (1 - timingConsistency) * 0.15
    + norm(tripletCount / gaps.length, 0.15) * 0.1
    + norm(burstCount / gaps.length, 0.12) * 0.1,
    0,
    1,
  );

  return {
    syncopationRatio: round3(syncopationRatio),
    subdivisionVariety: round3(subdivisionVariety),
    rhythmSwitchCount,
    timingConsistency: round3(timingConsistency),
    tempoChangeCount,
    offbeatRatio: round3(offbeatRatio),
    tripletCount,
    burstCount,
    score,
  };
}

function computeAim(beatmap: Beatmap): AimMetricsSummary {
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const pairs = positionedPairs(beatmap);
  if (pairs.length === 0) {
    return {
      distanceDemand: 0,
      speedDemand: 0,
      precisionDemand: 0,
      angleDemand: 0,
      sharpTurnCount: 0,
      flowQuality: 0,
      microAdjustmentCount: 0,
      largeJumpCount: 0,
      score: 0,
    };
  }
  const distances = pairs.map((pair) => pair.distance);
  const velocities = pairs.map((pair) => pair.velocityPps);
  const playfieldDiagonal = Math.hypot(512, 384);
  const distanceDemand = norm(mean(distances), playfieldDiagonal * 0.45);
  const speedDemand = norm(mean(velocities), 860);

  const microAdjustmentCount = pairs.filter(
    (pair) => pair.distance <= 42 && pair.timeGapMs <= 320,
  ).length;
  const precisionDemand = norm(microAdjustmentCount / pairs.length, 0.22);

  const angles = turnAnglesFor(positioned);
  const sharpTurnCount = angles.filter((angle) => angle >= 110).length;
  const angleDemand = norm(mean(angles), 90);
  const smoothTurns = angles.filter((angle) => angle <= 30).length;
  const flowQuality = angles.length > 0 ? smoothTurns / angles.length : 0;
  const largeJumpCount = distances.filter((distance) => distance >= playfieldDiagonal * 0.55).length;

  const score = clamp(
    distanceDemand * 0.35
    + speedDemand * 0.3
    + precisionDemand * 0.1
    + angleDemand * 0.15
    + norm(largeJumpCount / pairs.length, 0.12) * 0.1,
    0,
    1,
  );

  return {
    distanceDemand: round3(distanceDemand),
    speedDemand: round3(speedDemand),
    precisionDemand: round3(precisionDemand),
    angleDemand: round3(angleDemand),
    sharpTurnCount,
    flowQuality: round3(flowQuality),
    microAdjustmentCount,
    largeJumpCount,
    score,
  };
}

function computeStamina(beatmap: Beatmap, metrics: RawMetricsSummary): StaminaMetricsSummary {
  const positionedTimes = beatmap.objects
    .filter(hasHitObjectPosition)
    .map((item) => getHitObjectStartTime(item));
  if (positionedTimes.length < 2) {
    return {
      continuousActivityMs: 0,
      highDensityDurationMs: 0,
      streamDurationMs: 0,
      restFrequency: 0,
      sliderWorkload: 0,
      score: 0,
    };
  }
  const gaps: number[] = [];
  for (let index = 1; index < positionedTimes.length; index += 1) {
    gaps.push(positionedTimes[index] - positionedTimes[index - 1]);
  }
  const activeDurationMs = Math.max(1, positionedTimes[positionedTimes.length - 1] - positionedTimes[0]);

  let current = 0;
  let best = 0;
  for (const gap of gaps) {
    if (gap < 900) {
      current += gap;
      best = Math.max(best, current);
    } else {
      current = 0;
    }
  }
  const continuousActivityMs = best;
  const highDensityDurationMs = gaps
    .filter((gap) => gap <= 320)
    .reduce((sum, gap) => sum + gap, 0);
  const streamDurationMs = gaps.filter((gap) => gap <= 190).reduce((sum, gap) => sum + gap, 0);
  const restCount = gaps.filter((gap) => gap >= 900).length;
  const minutes = activeDurationMs / 60000;
  const restFrequency = minutes > 0 ? restCount / minutes : 0;

  const sliderDurationMs = beatmap.objects
    .filter((item) => item.type === "slider")
    .reduce((sum, item) => sum + Math.max(0, getHitObjectEndTime(item) - getHitObjectStartTime(item)), 0);
  const sliderWorkload = clamp(sliderDurationMs / Math.max(1, activeDurationMs), 0, 1);

  const activityRatio = clamp(continuousActivityMs / Math.max(1, activeDurationMs), 0, 1);
  const highDensityRatio = clamp(highDensityDurationMs / Math.max(1, activeDurationMs), 0, 1);
  const score = clamp(
    norm(activityRatio, 0.55) * 0.4
    + norm(highDensityRatio, 0.4) * 0.3
    + norm(restFrequency / 30, 1) * 0.1
    + sliderWorkload * 0.1
    + norm(metrics.longestStreamLength / 8, 1) * 0.1,
    0,
    1,
  );

  return {
    continuousActivityMs,
    highDensityDurationMs,
    streamDurationMs,
    restFrequency: round3(restFrequency),
    sliderWorkload: round3(sliderWorkload),
    score,
  };
}

function scorePatterns(beatmap: Beatmap, metrics: RawMetricsSummary): PatternDifficultySummary[] {
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const results: PatternDifficultySummary[] = [];

  for (let windowSize = 3; windowSize <= 6; windowSize += 1) {
    for (let start = 0; start <= positioned.length - windowSize; start += 1) {
      const window = positioned.slice(start, start + windowSize);
      const classification = classifyWindow(window);
      if (!classification) {
        continue;
      }
      const score = scoreWindow(window, classification);
      if (score < 0.1) {
        continue;
      }
      results.push({
        pattern: classification,
        startMs: getHitObjectStartTime(window[0]),
        endMs: getHitObjectStartTime(window[window.length - 1]),
        objectCount: window.length,
        score,
      });
    }
  }

  for (let index = 1; index < positioned.length; index += 1) {
    const left = positioned[index - 1];
    const right = positioned[index];
    const distance = Math.hypot(right.x - left.x, right.y - left.y);
    const timeGap = getHitObjectStartTime(right) - getHitObjectStartTime(left);
    if (distance >= 340 && timeGap <= 900) {
      results.push({
        pattern: "cross-screen jump",
        startMs: getHitObjectStartTime(left),
        endMs: getHitObjectStartTime(right),
        objectCount: 2,
        score: pairJumpScore(distance, timeGap),
      });
    } else if (distance >= 260 && timeGap <= 700) {
      results.push({
        pattern: "wide jump",
        startMs: getHitObjectStartTime(left),
        endMs: getHitObjectStartTime(right),
        objectCount: 2,
        score: pairJumpScore(distance, timeGap),
      });
    }
  }

  let sliderChain = 0;
  let chainStart: BeatmapHitObject | undefined;
  let chainEnd: BeatmapHitObject | undefined;
  for (const item of positioned) {
    if (item.type === "slider") {
      if (sliderChain === 0) {
        chainStart = item;
      }
      sliderChain += 1;
      chainEnd = item;
    } else {
      if (sliderChain >= 3 && chainStart && chainEnd) {
        results.push({
          pattern: "slider chain",
          startMs: getHitObjectStartTime(chainStart),
          endMs: getHitObjectEndTime(chainEnd),
          objectCount: sliderChain,
          score: 0.5,
        });
      }
      sliderChain = 0;
    }
  }
  if (sliderChain >= 3 && chainStart && chainEnd) {
    results.push({
      pattern: "slider chain",
      startMs: getHitObjectStartTime(chainStart),
      endMs: getHitObjectEndTime(chainEnd),
      objectCount: sliderChain,
      score: 0.5,
    });
  }

  const times = positioned.map((item) => getHitObjectStartTime(item));
  for (let index = 0; index < times.length - 4; index += 1) {
    const span = times[index + 4] - times[index];
    if (span <= 900) {
      results.push({
        pattern: "dense cluster",
        startMs: times[index],
        endMs: times[index + 4],
        objectCount: 5,
        score: norm(metrics.objectsPerSecond, 3.5) * 0.8,
      });
    }
  }

  const deduplicated = dedupePatterns(results);
  return deduplicated.sort((a, b) => a.startMs - b.startMs || a.pattern.localeCompare(b.pattern));
}

function computeTechnicalScore(
  metrics: RawMetricsSummary,
  patterns: PatternDifficultySummary[],
): number {
  if (patterns.length === 0) {
    return clamp(metrics.angleComplexity / 180, 0, 1);
  }
  const averagePatternScore = mean(patterns.map((pattern) => pattern.score));
  const angleComponent = clamp(metrics.angleComplexity / 150, 0, 1);
  const directionComponent = clamp(
    metrics.directionChangeCount / Math.max(1, metrics.objectCount),
    0,
    0.5,
  );
  const sliderComponent = metrics.sliderComplexity;
  const patternComponent = clamp(averagePatternScore, 0, 1);
  return clamp(
    angleComponent * 0.3 + directionComponent * 0.2 + sliderComponent * 0.2 + patternComponent * 0.3,
    0,
    1,
  );
}

function computeStars(
  metrics: RawMetricsSummary,
  aim: AimMetricsSummary,
  reading: ReadingMetricsSummary,
  rhythm: RhythmMetricsSummary,
  stamina: StaminaMetricsSummary,
  technical: number,
): StarRatingSummary {
  const speedComponent = clamp(
    norm(metrics.objectsPerSecond, 3.5) * 0.4
    + norm(metrics.averageCursorVelocityPps, 900) * 0.3
    + norm(metrics.longestStreamLength / 8, 1) * 0.2
    + norm(metrics.longestBurstLength / 5, 1) * 0.1,
    0,
    1,
  );
  const aimComponent = clamp(aim.score, 0, 1);
  const readingComponent = clamp(reading.score, 0, 1);
  const rhythmComponent = clamp(rhythm.score, 0, 1);
  const staminaComponent = clamp(stamina.score, 0, 1);
  const technicalComponent = clamp(technical, 0, 1);

  const aimStars = 10 * aimComponent ** 0.9;
  const speedStars = 10 * speedComponent ** 0.85;
  const readingStars = 10 * readingComponent ** 0.95;
  const rhythmStars = 10 * rhythmComponent ** 0.9;
  const staminaStars = 10 * staminaComponent ** 0.9;
  const technicalStars = 10 * technicalComponent ** 0.9;

  const overall = clamp(
    aimStars * 0.3
    + speedStars * 0.25
    + readingStars * 0.15
    + rhythmStars * 0.12
    + staminaStars * 0.1
    + technicalStars * 0.08,
    0,
    10,
  );

  return {
    overall,
    aim: clamp(aimStars, 0, 10),
    speed: clamp(speedStars, 0, 10),
    reading: clamp(readingStars, 0, 10),
    rhythm: clamp(rhythmStars, 0, 10),
    stamina: clamp(staminaStars, 0, 10),
    technical: clamp(technicalStars, 0, 10),
    breakdown: {
      aimComponent,
      speedComponent,
      readingComponent,
      rhythmComponent,
      staminaComponent,
      technicalComponent,
      weights: { aim: 0.3, speed: 0.25, reading: 0.15, rhythm: 0.12, stamina: 0.1, technical: 0.08 },
    },
  };
}

function computeSections(
  beatmap: Beatmap,
  songSections: SongSection[] | undefined,
  reading: ReadingMetricsSummary,
  rhythm: RhythmMetricsSummary,
  aim: AimMetricsSummary,
): SectionDifficultySummary[] {
  let bounds: Array<{ startMs: number; endMs: number; label: string; sectionId: number | null }>;
  if (songSections && songSections.length > 0) {
    bounds = songSections.map((section) => ({
      startMs: section.startMs,
      endMs: section.endMs,
      label: section.label,
      sectionId: section.id,
    }));
  } else {
    bounds = fallbackSections(beatmap);
  }

  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  return bounds.map((bound) => {
    const inWindow = positioned.filter(
      (item) => {
        const time = getHitObjectStartTime(item);
        return time >= bound.startMs && time < bound.endMs;
      },
    );
    const windowSeconds = Math.max(1, (bound.endMs - bound.startMs) / 1000);
    const density = inWindow.length / windowSeconds;
    let speed = 0;
    const speeds: number[] = [];
    for (let index = 1; index < inWindow.length; index += 1) {
      const left = inWindow[index - 1];
      const right = inWindow[index];
      const distance = Math.hypot(right.x - left.x, right.y - left.y);
      const deltaMs = getHitObjectStartTime(right) - getHitObjectStartTime(left);
      if (deltaMs > 0) {
        speeds.push(distance / (deltaMs / 1000));
      }
    }
    speed = mean(speeds);
    const difficultyScore = round3(
      clamp(
        norm(density, 3.5) * 0.35
        + norm(speed, 900) * 0.3
        + reading.score * 0.15
        + rhythm.score * 0.1
        + aim.score * 0.1,
        0,
        1,
      ),
    );
    return {
      sectionId: bound.sectionId,
      label: bound.label,
      startMs: bound.startMs,
      endMs: bound.endMs,
      difficultyScore,
      density: round3(density),
      speed: round3(speed),
      reading: round3(reading.score),
      rhythm: round3(rhythm.score),
    };
  });
}

function buildCurve(
  beatmap: Beatmap,
  reading: ReadingMetricsSummary,
  rhythm: RhythmMetricsSummary,
): DifficultyCurvePointSummary[] {
  const objects = beatmap.objects;
  if (objects.length === 0) {
    return [];
  }
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const firstTime = getHitObjectStartTime(objects[0]);
  const lastTime = getHitObjectEndTime(objects[objects.length - 1]);
  const windowMs = 4000;
  const stepMs = 1000;
  const points: DifficultyCurvePointSummary[] = [];

  for (let cursor = firstTime; cursor < lastTime; cursor += stepMs) {
    const start = cursor;
    const end = cursor + windowMs;
    const inWindow = positioned.filter((item) => {
      const time = getHitObjectStartTime(item);
      return time >= start && time < end;
    });
    const windowSeconds = Math.max(1, windowMs / 1000);
    const density = inWindow.length / windowSeconds;

    let speed = 0;
    const speeds: number[] = [];
    let smoothPairs = 0;
    let totalPairs = 0;
    for (let index = 1; index < inWindow.length; index += 1) {
      const left = inWindow[index - 1];
      const right = inWindow[index];
      const distance = Math.hypot(right.x - left.x, right.y - left.y);
      const timeGap = getHitObjectStartTime(right) - getHitObjectStartTime(left);
      totalPairs += 1;
      if (timeGap > 0) {
        speeds.push(distance / (timeGap / 1000));
        if (distance <= 120 && timeGap >= 250) {
          smoothPairs += 1;
        }
      }
    }
    speed = mean(speeds);
    const flow = totalPairs > 0 ? smoothPairs / totalPairs : 1;
    const readingScore = clamp(reading.score + norm(density, 3.5) * 0.2, 0, 1);
    const rhythmScore = clamp(rhythm.score + windowRhythmProxy(inWindow), 0, 1);
    const difficultyScore = clamp(
      norm(density, 3.5) * 0.4 + norm(speed, 900) * 0.3 + readingScore * 0.15 + rhythmScore * 0.15,
      0,
      1,
    );
    points.push({
      timeMs: start,
      difficultyScore: round3(difficultyScore),
      density: round3(density),
      speed: round3(speed),
      flow: round3(flow),
      reading: round3(readingScore),
      rhythm: round3(rhythmScore),
    });
  }

  // Smooth over 3 samples.
  return points.map((point, index) => {
    const neighbors = points.slice(Math.max(0, index - 1), Math.min(points.length, index + 2));
    return {
      timeMs: point.timeMs,
      difficultyScore: mean(neighbors.map((item) => item.difficultyScore)),
      density: mean(neighbors.map((item) => item.density)),
      speed: mean(neighbors.map((item) => item.speed)),
      flow: mean(neighbors.map((item) => item.flow)),
      reading: mean(neighbors.map((item) => item.reading)),
      rhythm: mean(neighbors.map((item) => item.rhythm)),
    };
  });
}

function computeObjectDifficulty(
  beatmap: Beatmap,
  aim: AimMetricsSummary,
  reading: ReadingMetricsSummary,
  rhythm: RhythmMetricsSummary,
): ObjectDifficultySummary[] {
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const results: ObjectDifficultySummary[] = [];
  for (let index = 0; index < positioned.length; index += 1) {
    const item = positioned[index];
    const previousTime = index > 0
      ? getHitObjectStartTime(positioned[index - 1])
      : getHitObjectStartTime(item);
    const nextTime = index + 1 < positioned.length
      ? getHitObjectStartTime(positioned[index + 1])
      : getHitObjectStartTime(item);
    const reaction = Math.max(0, getHitObjectStartTime(item) - previousTime);
    const gapToNext = Math.max(0, nextTime - getHitObjectStartTime(item));
    const localDensity = 1000 / Math.max(1, reaction + gapToNext);
    const score = clamp(
      (1 - clamp(reaction / 600, 0, 1)) * 0.35
      + localDensity / 8 * 0.3
      + aim.score * 0.2
      + reading.score * 0.1
      + rhythm.score * 0.05,
      0,
      1,
    );
    results.push({
      objectId: item.id,
      objectType: item.type,
      timeMs: getHitObjectStartTime(item),
      score: round3(score),
      contribution: 0,
    });
  }
  const totalScore = results.reduce((sum, item) => sum + item.score, 0);
  for (const item of results) {
    item.contribution = round3(item.score / Math.max(1e-6, totalScore));
  }
  return results.sort((a, b) => b.score - a.score || a.timeMs - b.timeMs);
}

function computeGameplay(
  beatmap: Beatmap,
  metrics: RawMetricsSummary,
  aim: AimMetricsSummary,
  reading: ReadingMetricsSummary,
  rhythm: RhythmMetricsSummary,
  stamina: StaminaMetricsSummary,
): GameplayAnalyticsSummary {
  const positionedTimes = beatmap.objects
    .filter(hasHitObjectPosition)
    .map((item) => getHitObjectStartTime(item));
  if (positionedTimes.length === 0) {
    return {
      estimatedMissProbability: 0,
      estimatedComboStability: 1,
      estimatedPlayerStress: 0,
      recoveryWindowCount: 0,
      averageRecoveryWindowMs: 0,
      hardestPassageMs: 0,
      simulatedPlaycount: 200,
    };
  }
  const gaps: number[] = [];
  for (let index = 1; index < positionedTimes.length; index += 1) {
    gaps.push(positionedTimes[index] - positionedTimes[index - 1]);
  }
  const approachTime = beatmap.approachTime;
  let fatigue = 0;
  const missValues: number[] = [];
  for (let index = 0; index < positionedTimes.length; index += 1) {
    const reaction = index < gaps.length ? gaps[index] : approachTime;
    const reactionRatio = reaction / Math.max(1, approachTime);
    const reactionDemand = clamp(1 - reactionRatio * 1.1, 0, 1);
    const velocityDemand = norm(metrics.averageCursorVelocityPps, 900);
    const isRest = reaction >= 1000;
    fatigue = Math.max(0, fatigue - (isRest ? 0.25 : 0));
    if (!isRest && reaction <= 260) {
      fatigue += 0.04;
    }
    const miss = clamp(
      (reactionDemand * 0.35
        + velocityDemand * 0.2
        + reading.score * 0.2
        + aim.score * 0.15
        + clamp(fatigue, 0, 1) * 0.1)
        * 0.35,
      0.02,
      0.85,
    );
    missValues.push(miss);
  }
  const missProbability = mean(missValues);
  const cleanRuns = (1 - missProbability) ** positionedTimes.length;
  const playerStress = clamp(
    (aim.score * 0.3 + reading.score * 0.2 + rhythm.score * 0.15 + stamina.score * 0.2) / 0.85,
    0,
    1,
  );
  const recoveryWindows = gaps.filter((gap) => gap >= 1000);
  let hardestPassageMs = 0;
  let bestMiss = -1;
  for (let index = 0; index < missValues.length; index += 1) {
    if (missValues[index] > bestMiss) {
      bestMiss = missValues[index];
      hardestPassageMs = positionedTimes[index];
    }
  }
  return {
    estimatedMissProbability: round3(clamp(missProbability, 0, 1)),
    estimatedComboStability: round3(clamp(cleanRuns, 0, 1)),
    estimatedPlayerStress: round3(clamp(playerStress, 0, 1)),
    recoveryWindowCount: recoveryWindows.length,
    averageRecoveryWindowMs: mean(recoveryWindows),
    hardestPassageMs,
    simulatedPlaycount: 200,
  };
}

function consistency(sectionScores: number[]): number {
  if (sectionScores.length === 0) {
    return 0;
  }
  const average = mean(sectionScores);
  if (average <= 0) {
    return 0;
  }
  return clamp(1 - (standardDeviation(sectionScores) / average) * 1.5, 0, 1);
}

function confidence(sectionScores: number[]): number {
  if (sectionScores.length === 0) {
    return 0.5;
  }
  return clamp(0.5 + mean(sectionScores) * 0.4, 0, 1);
}

function recommendedLevel(stars: number): string {
  if (stars < 1.6) {
    return "Beginner";
  }
  if (stars < 2.6) {
    return "Novice";
  }
  if (stars < 3.6) {
    return "Intermediate";
  }
  if (stars < 4.8) {
    return "Advanced";
  }
  if (stars < 6) {
    return "Expert";
  }
  return "Master";
}

interface PairDiagnostic {
  distance: number;
  timeGapMs: number;
  velocityPps: number;
}

function positionedPairs(beatmap: Beatmap): PairDiagnostic[] {
  const positioned = beatmap.objects.filter(hasHitObjectPosition);
  const results: PairDiagnostic[] = [];
  for (let index = 1; index < positioned.length; index += 1) {
    const left = positioned[index - 1];
    const right = positioned[index];
    const distance = Math.hypot(right.x - left.x, right.y - left.y);
    const timeGapMs = Math.max(1, getHitObjectStartTime(right) - getHitObjectStartTime(left));
    results.push({
      distance,
      timeGapMs,
      velocityPps: distance / (timeGapMs / 1000),
    });
  }
  return results;
}

function turnAngleDeg(
  left: BeatmapHitObject,
  middle: BeatmapHitObject,
  right: BeatmapHitObject,
): number | null {
  if (!hasHitObjectPosition(left) || !hasHitObjectPosition(middle) || !hasHitObjectPosition(right)) {
    return null;
  }
  const vectorA = [middle.x - left.x, middle.y - left.y];
  const vectorB = [right.x - middle.x, right.y - middle.y];
  const magnitudeA = Math.hypot(vectorA[0], vectorA[1]);
  const magnitudeB = Math.hypot(vectorB[0], vectorB[1]);
  if (magnitudeA <= 0 || magnitudeB <= 0) {
    return null;
  }
  const dot = vectorA[0] * vectorB[0] + vectorA[1] * vectorB[1];
  const cosine = clamp(dot / (magnitudeA * magnitudeB), -1, 1);
  return (Math.acos(cosine) * 180) / Math.PI;
}

function turnAnglesFor(positioned: BeatmapHitObject[]): number[] {
  const angles: number[] = [];
  for (let index = 1; index < positioned.length - 1; index += 1) {
    const angle = turnAngleDeg(positioned[index - 1], positioned[index], positioned[index + 1]);
    if (angle !== null) {
      angles.push(angle);
    }
  }
  return angles;
}

function classifyWindow(window: PositionedBeatmapHitObject[]): string | null {
  const distances: number[] = [];
  const gaps: number[] = [];
  for (let index = 0; index < window.length - 1; index += 1) {
    const left = window[index]!;
    const right = window[index + 1]!;
    distances.push(Math.hypot(right.x - left.x, right.y - left.y));
    gaps.push(getHitObjectStartTime(right) - getHitObjectStartTime(left));
  }
  if (distances.length === 0) {
    return null;
  }
  const allRapid = gaps.every((gap) => gap <= 190);
  const mostlyRapid = mean(gaps) <= 230;
  const allLarge = distances.every((distance) => distance >= 280);
  const averageDistance = mean(distances);

  if (allRapid && window.length >= 5) {
    return "stream";
  }
  if (mostlyRapid && window.length <= 4 && averageDistance >= 60) {
    return "burst";
  }
  if (allLarge) {
    return "cross-screen jump";
  }
  if (averageDistance >= 260 && gaps.every((gap) => gap <= 700)) {
    return "wide jump";
  }
  if (window.length === 3 && isTriangle(window)) {
    return "triangle";
  }
  if (window.length === 4 && isRectangle(window)) {
    return "rectangle";
  }
  const turnCount = sharpTurnCount(window);
  if (turnCount >= 2) {
    return "technical pattern";
  }
  return null;
}

function isTriangle(window: PositionedBeatmapHitObject[]): boolean {
  const first = window[0]!;
  const second = window[1]!;
  const third = window[2]!;
  const a = Math.hypot(second.x - first.x, second.y - first.y);
  const b = Math.hypot(third.x - second.x, third.y - second.y);
  const c = Math.hypot(third.x - first.x, third.y - first.y);
  const lengths = [a, b, c].sort((x, y) => x - y);
  if (lengths[0] <= 10) {
    return false;
  }
  const ratio = lengths[2] / Math.max(1, lengths[0]);
  return ratio >= 1 && ratio <= 2.2;
}

function isRectangle(window: PositionedBeatmapHitObject[]): boolean {
  const first = window[0]!;
  const second = window[1]!;
  const third = window[2]!;
  const fourth = window[3]!;
  const top = Math.hypot(second.x - first.x, second.y - first.y);
  const right = Math.hypot(third.x - second.x, third.y - second.y);
  const bottom = Math.hypot(fourth.x - third.x, fourth.y - third.y);
  const left = Math.hypot(first.x - fourth.x, first.y - fourth.y);
  if (Math.min(top, right, bottom, left) <= 10) {
    return false;
  }
  const horizontalRatio = Math.max(top, bottom) / Math.max(1, Math.min(top, bottom));
  const verticalRatio = Math.max(right, left) / Math.max(1, Math.min(right, left));
  return horizontalRatio <= 1.8 && verticalRatio <= 1.8;
}

function sharpTurnCount(window: PositionedBeatmapHitObject[]): number {
  let count = 0;
  for (let index = 1; index < window.length - 1; index += 1) {
    const angle = turnAngleDeg(window[index - 1], window[index], window[index + 1]);
    if (angle !== null && angle >= 90) {
      count += 1;
    }
  }
  return count;
}

function scoreWindow(window: PositionedBeatmapHitObject[], classification: string): number {
  const distances: number[] = [];
  const gaps: number[] = [];
  for (let index = 0; index < window.length - 1; index += 1) {
    const left = window[index]!;
    const right = window[index + 1]!;
    distances.push(Math.hypot(right.x - left.x, right.y - left.y));
    gaps.push(Math.max(1, getHitObjectStartTime(right) - getHitObjectStartTime(left)));
  }
  const velocities = distances.map((distance, index) => distance / (gaps[index] / 1000));
  const speedFactor = norm(mean(velocities), 900);
  const distanceFactor = norm(mean(distances), 260);
  const densityFactor = norm(
    window.length / Math.max(1, getHitObjectStartTime(window[window.length - 1]) - getHitObjectStartTime(window[0])) * 1000,
    6,
  );
  const turnFactor = norm(sharpTurnCount(window) / Math.max(1, window.length - 1), 0.7);

  switch (classification) {
    case "stream":
      return clamp(densityFactor * 0.5 + speedFactor * 0.5, 0, 1);
    case "burst":
      return clamp(densityFactor * 0.4 + speedFactor * 0.4 + distanceFactor * 0.2, 0, 1);
    case "cross-screen jump":
    case "wide jump":
      return clamp(distanceFactor * 0.6 + speedFactor * 0.4, 0, 1);
    case "triangle":
    case "rectangle":
      return clamp(distanceFactor * 0.4 + speedFactor * 0.3 + turnFactor * 0.3, 0, 1);
    case "technical pattern":
      return clamp(turnFactor * 0.6 + speedFactor * 0.4, 0, 1);
    default:
      return 0;
  }
}

function pairJumpScore(distance: number, timeGap: number): number {
  const velocity = distance / Math.max(1, timeGap / 1000);
  return clamp(norm(distance, 420) * 0.5 + norm(velocity, 1100) * 0.5, 0, 1);
}

function dedupePatterns(patterns: PatternDifficultySummary[]): PatternDifficultySummary[] {
  const byKey = new Map<string, PatternDifficultySummary>();
  for (const pattern of patterns) {
    const key = `${pattern.pattern}:${pattern.startMs}`;
    const existing = byKey.get(key);
    if (!existing || pattern.objectCount > existing.objectCount) {
      byKey.set(key, pattern);
    }
  }
  return Array.from(byKey.values());
}

function fallbackSections(
  beatmap: Beatmap,
): Array<{ startMs: number; endMs: number; label: string; sectionId: number | null }> {
  const objects = beatmap.objects;
  if (objects.length === 0) {
    return [];
  }
  const start = getHitObjectStartTime(objects[0]);
  const end = getHitObjectEndTime(objects[objects.length - 1]);
  const span = Math.max(4000, end - start);
  const count = Math.max(2, Math.round(span / 8000));
  const step = span / count;
  const sections: Array<{ startMs: number; endMs: number; label: string; sectionId: number | null }> = [];
  for (let index = 0; index < count; index += 1) {
    sections.push({
      startMs: start + Math.round(index * step),
      endMs: start + Math.round((index + 1) * step),
      label: `Section ${index + 1}`,
      sectionId: index + 1,
    });
  }
  return sections;
}

function windowRhythmProxy(inWindow: BeatmapHitObject[]): number {
  if (inWindow.length < 2) {
    return 0;
  }
  const gaps: number[] = [];
  for (let index = 1; index < inWindow.length; index += 1) {
    gaps.push(getHitObjectStartTime(inWindow[index]) - getHitObjectStartTime(inWindow[index - 1]));
  }
  const average = mean(gaps);
  if (average <= 0) {
    return 0;
  }
  let switches = 0;
  for (let index = 1; index < gaps.length; index += 1) {
    if (Math.abs(gaps[index] - gaps[index - 1]) / average >= 0.4) {
      switches += 1;
    }
  }
  return clamp(switches / Math.max(1, gaps.length - 1), 0, 1);
}

function patternVariation(positioned: PositionedBeatmapHitObject[]): number {
  if (positioned.length < 2) {
    return 0;
  }
  const buckets = new Set<string>();
  let transitions = 0;
  for (let index = 1; index < positioned.length; index += 1) {
    const current = positioned[index]!;
    const previous = positioned[index - 1]!;
    const distance = Math.hypot(
      current.x - previous.x,
      current.y - previous.y,
    );
    const deltaMs = Math.max(1, getHitObjectStartTime(current) - getHitObjectStartTime(previous));
    const velocity = distance / (deltaMs / 1000);
    buckets.add(`${Math.floor(distance / 48)}:${Math.floor(velocity / 120)}`);
    transitions += 1;
  }
  return buckets.size / Math.max(1, transitions);
}

function staminaDemandProxy(objects: BeatmapHitObject[]): number {
  const positionedTimes = objects
    .filter(hasHitObjectPosition)
    .map((item) => getHitObjectStartTime(item));
  if (positionedTimes.length < 2) {
    return 0;
  }
  const activeDuration = Math.max(1, positionedTimes[positionedTimes.length - 1] - positionedTimes[0]);
  let longestRunMs = 0;
  let previousActive = false;
  let current = 0;
  for (let index = 0; index < positionedTimes.length - 1; index += 1) {
    const isActive = positionedTimes[index + 1] - positionedTimes[index] <= 320;
    if (isActive && !previousActive) {
      current = 0;
    }
    if (!isActive && previousActive) {
      longestRunMs = Math.max(longestRunMs, current);
    }
    if (isActive) {
      current += positionedTimes[index + 1] - positionedTimes[index];
    }
    previousActive = isActive;
  }
  if (previousActive) {
    longestRunMs = Math.max(longestRunMs, current);
  }
  return clamp((longestRunMs / activeDuration) * 2, 0, 1);
}

function rhythmComplexityProxy(gaps: number[]): number {
  if (gaps.length === 0) {
    return 0;
  }
  const meanGap = mean(gaps);
  if (meanGap <= 0) {
    return 0;
  }
  let switchCount = 0;
  for (let index = 1; index < gaps.length; index += 1) {
    if (Math.abs(gaps[index] - gaps[index - 1]) / meanGap >= 0.35) {
      switchCount += 1;
    }
  }
  const switchRatio = switchCount / Math.max(1, gaps.length - 1);
  const gapVariety = bucketCount(gaps, 100) / Math.max(1, gaps.length);
  return clamp(switchRatio * 0.7 + gapVariety * 0.3, 0, 1);
}

function sliderComplexity(
  velocities: number[],
  repeats: number[],
  count: number,
): number {
  if (count === 0) {
    return 0;
  }
  const velocityComponent = norm(mean(velocities), 900);
  const repeatComponent = clamp((mean(repeats) - 1) / 3, 0, 1);
  return clamp(velocityComponent * 0.6 + repeatComponent * 0.4, 0, 1);
}

function dominantGapMs(gaps: number[]): number {
  const buckets = new Map<number, number>();
  for (const gap of gaps) {
    const bucket = Math.floor(gap / 10);
    buckets.set(bucket, (buckets.get(bucket) ?? 0) + 1);
  }
  let dominant = 0;
  let bestCount = -1;
  for (const [bucket, count] of buckets.entries()) {
    if (count > bestCount) {
      dominant = bucket;
      bestCount = count;
    }
  }
  return dominant * 10 + 5;
}

function gapErrorRatio(gap: number, reference: number): number {
  if (reference <= 0) {
    return 1;
  }
  const nearestMultiple = Math.max(1, Math.round(gap / reference));
  const nearest = nearestMultiple * reference;
  return Math.abs(gap - nearest) / Math.max(1, reference);
}

function longestRun(values: boolean[]): number {
  let longest = 0;
  let current = 0;
  for (const isActive of values) {
    if (isActive) {
      current += 1;
      longest = Math.max(longest, current);
    } else {
      current = 0;
    }
  }
  return longest;
}

function bucketCount(values: number[], bucketSize: number): number {
  const buckets = new Set<number>();
  for (const value of values) {
    buckets.add(Math.floor(value / bucketSize));
  }
  return buckets.size;
}

function mean(values: number[]): number {
  return values.length > 0
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : 0;
}

function standardDeviation(values: number[]): number {
  if (values.length < 2) {
    return 0;
  }
  const average = mean(values);
  const variance = values.reduce((sum, value) => sum + (value - average) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

function coefficientOfVariation(values: number[]): number {
  if (values.length < 2) {
    return 0;
  }
  const average = mean(values);
  if (average === 0) {
    return 0;
  }
  return standardDeviation(values) / Math.abs(average);
}

function norm(value: number, reference: number): number {
  return clamp(reference > 0 ? value / reference : 0, 0, 1);
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function emptyRawMetrics(): RawMetricsSummary {
  return {
    objectCount: 0,
    circleCount: 0,
    sliderCount: 0,
    spinnerCount: 0,
    activeDurationMs: 1,
    objectsPerSecond: 0,
    circleDensity: 0,
    sliderDensity: 0,
    spinnerFrequencyPerMinute: 0,
    averageGapMs: 0,
    minimumGapMs: 0,
    maximumGapMs: 0,
    gapStandardDeviationMs: 0,
    averageJumpDistance: 0,
    maximumJumpDistance: 0,
    jumpDistanceStandardDeviation: 0,
    averageCursorVelocityPps: 0,
    maximumCursorVelocityPps: 0,
    averageCursorAccelerationPps2: 0,
    angleComplexity: 0,
    directionChangeCount: 0,
    longestStreamLength: 0,
    longestBurstLength: 0,
    averageSliderLengthMs: 0,
    averageSliderVelocityPps: 0,
    averageSliderRepeats: 0,
    sliderComplexity: 0,
    averageReactionTimeMs: 0,
    minimumReactionTimeMs: 0,
    recoveryWindowCount: 0,
    patternVariation: 0,
    staminaDemand: 0,
    rhythmComplexity: 0,
  };
}
