import { getHitObjectEndTime, getHitObjectPosition } from "../../game/types";
import type { SongSection } from "../../shared/sectionData";
import type { EditorHitObject, EditorMapDocument } from "../models/EditorModels";
import type {
  CandidateRebalanceDetail,
  CandidateReplayDetail,
  CandidateSectionComparison,
  CandidateSectionMetric,
  CandidateVisualDiff,
  CandidateVisualDiffItem,
  SectionMetricWinner,
} from "./candidateModels";

export const CANDIDATE_TIMING_TOLERANCE_MS = 60;
export const CANDIDATE_RETIME_EPSILON_MS = 15;
export const CANDIDATE_POSITION_EPSILON = 0.5;

interface MatchedObjectPair {
  a?: EditorHitObject;
  b?: EditorHitObject;
}

export function matchCandidateObjects(
  mapA: EditorMapDocument,
  mapB: EditorMapDocument,
  toleranceMs = CANDIDATE_TIMING_TOLERANCE_MS,
): MatchedObjectPair[] {
  const objectsA = mapA.objects.slice().sort((left, right) => left.time - right.time);
  const objectsB = mapB.objects.slice().sort((left, right) => left.time - right.time);
  const output: MatchedObjectPair[] = [];
  let indexA = 0;
  let indexB = 0;

  while (indexA < objectsA.length || indexB < objectsB.length) {
    const objectA = objectsA[indexA];
    const objectB = objectsB[indexB];

    if (objectA && objectB) {
      const delta = objectA.time - objectB.time;
      if (Math.abs(delta) <= toleranceMs) {
        output.push({ a: objectA, b: objectB });
        indexA += 1;
        indexB += 1;
        continue;
      }

      if (delta < 0) {
        output.push({ a: objectA });
        indexA += 1;
        continue;
      }

      output.push({ b: objectB });
      indexB += 1;
      continue;
    }

    if (objectA) {
      output.push({ a: objectA });
      indexA += 1;
      continue;
    }

    if (objectB) {
      output.push({ b: objectB });
      indexB += 1;
      continue;
    }
  }

  return output;
}

export function buildVisualDiff(
  mapA: EditorMapDocument,
  mapB: EditorMapDocument,
): CandidateVisualDiff {
  const pairs = matchCandidateObjects(mapA, mapB);
  const items: CandidateVisualDiffItem[] = [];
  const summary = {
    shared: 0,
    aOnly: 0,
    bOnly: 0,
    moved: 0,
    retimed: 0,
    movedRetimed: 0,
  };

  for (const pair of pairs) {
    const objectA = pair.a;
    const objectB = pair.b;

    if (objectA && objectB) {
      const positionA = getHitObjectPosition(objectA);
      const positionB = getHitObjectPosition(objectB);
      const moved = positionsDiffer(positionA, positionB);
      const retimed =
        Math.abs(objectA.time - objectB.time) > CANDIDATE_RETIME_EPSILON_MS;

      if (moved && retimed) {
        summary.movedRetimed += 1;
        items.push({
          kind: "moved-retimed",
          timeMs: (objectA.time + objectB.time) / 2,
          aX: positionA?.x,
          aY: positionA?.y,
          aTime: objectA.time,
          bX: positionB?.x,
          bY: positionB?.y,
          bTime: objectB.time,
        });
        continue;
      }

      if (moved) {
        summary.moved += 1;
        items.push({
          kind: "moved",
          timeMs: objectA.time,
          aX: positionA?.x,
          aY: positionA?.y,
          aTime: objectA.time,
          bX: positionB?.x,
          bY: positionB?.y,
          bTime: objectB.time,
        });
        continue;
      }

      if (retimed) {
        summary.retimed += 1;
        items.push({
          kind: "retimed",
          timeMs: objectB.time,
          aX: positionA?.x,
          aY: positionA?.y,
          aTime: objectA.time,
          bX: positionB?.x,
          bY: positionB?.y,
          bTime: objectB.time,
        });
        continue;
      }

      summary.shared += 1;
      items.push({
        kind: "shared",
        timeMs: objectA.time,
        aX: positionA?.x,
        aY: positionA?.y,
        aTime: objectA.time,
        bX: positionB?.x,
        bY: positionB?.y,
        bTime: objectB.time,
      });
      continue;
    }

    if (objectA) {
      summary.aOnly += 1;
      const position = getHitObjectPosition(objectA);
      items.push({
        kind: "a-only",
        timeMs: objectA.time,
        aX: position?.x,
        aY: position?.y,
        aTime: objectA.time,
      });
      continue;
    }

    if (objectB) {
      summary.bOnly += 1;
      const position = getHitObjectPosition(objectB);
      items.push({
        kind: "b-only",
        timeMs: objectB.time,
        bX: position?.x,
        bY: position?.y,
        bTime: objectB.time,
      });
    }
  }

  return { items, summary };
}

export function computeSectionDensity(
  map: EditorMapDocument,
  startMs: number,
  endMs: number,
): number {
  const durationSec = Math.max(0.001, (endMs - startMs) / 1000);
  const count = countObjectsInRange(map.objects, startMs, endMs);
  return count / durationSec;
}

export function computeSectionMovement(
  map: EditorMapDocument,
  startMs: number,
  endMs: number,
): number {
  const objects = map.objects
    .filter((object) => object.time >= startMs && object.time <= endMs)
    .sort((left, right) => left.time - right.time);
  let totalDistance = 0;
  let segments = 0;

  for (let index = 1; index < objects.length; index += 1) {
    const previous = getHitObjectPosition(objects[index - 1]);
    const current = getHitObjectPosition(objects[index]);
    if (!previous || !current) {
      continue;
    }

    totalDistance += Math.hypot(
      current.x - previous.x,
      current.y - previous.y,
    );
    segments += 1;
  }

  return segments > 0 ? totalDistance / segments : 0;
}

export function countObjectsInRange(
  objects: EditorHitObject[],
  startMs: number,
  endMs: number,
): number {
  return objects.filter((object) => {
    const start = object.time;
    const end = getHitObjectEndTime(object);
    return start >= startMs && start <= endMs && end >= startMs;
  }).length;
}

export function buildSectionComparison(
  mapA: EditorMapDocument,
  mapB: EditorMapDocument,
  sections: SongSection[],
  detailA?: { replay: CandidateReplayDetail | null; rebalance: CandidateRebalanceDetail | null },
  detailB?: { replay: CandidateReplayDetail | null; rebalance: CandidateRebalanceDetail | null },
): CandidateSectionComparison[] {
  return sections.map((section) => {
    const replayA = findSectionReplay(detailA?.replay, section.id);
    const replayB = findSectionReplay(detailB?.replay, section.id);
    const rebalanceA = findSectionRebalance(detailA?.rebalance, section.id);
    const rebalanceB = findSectionRebalance(detailB?.rebalance, section.id);

    const metrics: CandidateSectionMetric[] = [
      {
        key: "object-count",
        label: "Object count",
        a: countObjectsInRange(mapA.objects, section.startMs, section.endMs),
        b: countObjectsInRange(mapB.objects, section.startMs, section.endMs),
        direction: "higher",
        winner: compareMetric(
          countObjectsInRange(mapA.objects, section.startMs, section.endMs),
          countObjectsInRange(mapB.objects, section.startMs, section.endMs),
          "higher",
          0,
        ),
      },
      {
        key: "density",
        label: "Density",
        a:
          rebalanceA?.density ??
          computeSectionDensity(mapA, section.startMs, section.endMs),
        b:
          rebalanceB?.density ??
          computeSectionDensity(mapB, section.startMs, section.endMs),
        direction: "higher",
        winner: compareMetric(
          rebalanceA?.density ??
            computeSectionDensity(mapA, section.startMs, section.endMs),
          rebalanceB?.density ??
            computeSectionDensity(mapB, section.startMs, section.endMs),
          "higher",
          0.05,
        ),
      },
      {
        key: "difficulty",
        label: "Difficulty",
        a: rebalanceA?.starRating ?? null,
        b: rebalanceB?.starRating ?? null,
        direction: "higher",
        winner: compareMetric(
          rebalanceA?.starRating ?? null,
          rebalanceB?.starRating ?? null,
          "higher",
          0.05,
        ),
      },
      {
        key: "rhythm",
        label: "Rhythm consistency",
        a: rebalanceA?.rhythmConsistency ?? null,
        b: rebalanceB?.rhythmConsistency ?? null,
        direction: "higher",
        winner: compareMetric(
          rebalanceA?.rhythmConsistency ?? null,
          rebalanceB?.rhythmConsistency ?? null,
          "higher",
          0.05,
        ),
      },
      {
        key: "movement",
        label: "Movement",
        a:
          rebalanceA?.cursorTravelPx ??
          computeSectionMovement(mapA, section.startMs, section.endMs),
        b:
          rebalanceB?.cursorTravelPx ??
          computeSectionMovement(mapB, section.startMs, section.endMs),
        direction: "lower",
        winner: compareMetric(
          rebalanceA?.cursorTravelPx ??
            computeSectionMovement(mapA, section.startMs, section.endMs),
          rebalanceB?.cursorTravelPx ??
            computeSectionMovement(mapB, section.startMs, section.endMs),
          "lower",
          2,
        ),
      },
      {
        key: "reading",
        label: "Reading",
        a: rebalanceA?.readingScore ?? replayA?.readingDemand ?? null,
        b: rebalanceB?.readingScore ?? replayB?.readingDemand ?? null,
        direction: "higher",
        winner: compareMetric(
          rebalanceA?.readingScore ?? replayA?.readingDemand ?? null,
          rebalanceB?.readingScore ?? replayB?.readingDemand ?? null,
          "higher",
          1,
        ),
      },
      {
        key: "replay",
        label: "Replay accuracy",
        a: replayA?.accuracy ?? null,
        b: replayB?.accuracy ?? null,
        direction: "higher",
        winner: compareMetric(
          replayA?.accuracy ?? null,
          replayB?.accuracy ?? null,
          "higher",
          0.01,
        ),
      },
      {
        key: "fatigue",
        label: "Fatigue",
        a: replayA?.fatiguePeak ?? rebalanceA?.fatigueAverage ?? null,
        b: replayB?.fatiguePeak ?? rebalanceB?.fatigueAverage ?? null,
        direction: "lower",
        winner: compareMetric(
          replayA?.fatiguePeak ?? rebalanceA?.fatigueAverage ?? null,
          replayB?.fatiguePeak ?? rebalanceB?.fatigueAverage ?? null,
          "lower",
          0.01,
        ),
      },
    ];

    return {
      sectionId: section.id,
      label: section.label,
      startMs: section.startMs,
      endMs: section.endMs,
      metrics,
      overallWinner: computeOverallWinner(metrics),
    };
  });
}

export function computeDensityCurve(
  map: EditorMapDocument,
  durationMs: number,
  windowMs = 2000,
  stepMs = 250,
): Array<{ timeMs: number; value: number }> {
  const output: Array<{ timeMs: number; value: number }> = [];
  if (durationMs <= 0) {
    return output;
  }

  for (let timeMs = 0; timeMs <= durationMs; timeMs += stepMs) {
    const start = timeMs - windowMs / 2;
    const end = timeMs + windowMs / 2;
    const count = map.objects.filter((object) => {
      const objectStart = object.time;
      const objectEnd = getHitObjectEndTime(object);
      return objectStart >= start && objectStart <= end && objectEnd >= start;
    }).length;
    const density = count / Math.max(0.001, windowMs / 1000);
    output.push({ timeMs, value: density });
  }

  return output;
}

function findSectionReplay(
  replay: CandidateReplayDetail | null | undefined,
  sectionId: number,
): CandidateReplayDetail["sections"][number] | undefined {
  return replay?.sections.find((section) => section.sectionId === sectionId);
}

function findSectionRebalance(
  rebalance: CandidateRebalanceDetail | null | undefined,
  sectionId: number,
): CandidateRebalanceDetail["sections"][number] | undefined {
  return rebalance?.sections.find((section) => section.sectionId === sectionId);
}

function compareMetric(
  a: number | null,
  b: number | null,
  direction: "higher" | "lower",
  epsilon: number,
): SectionMetricWinner {
  if (a === null || b === null) {
    return "tie";
  }

  if (Math.abs(a - b) < epsilon) {
    return "tie";
  }

  if (direction === "higher") {
    return a > b ? "a" : "b";
  }

  return a < b ? "a" : "b";
}

function computeOverallWinner(metrics: CandidateSectionMetric[]): SectionMetricWinner {
  let aWins = 0;
  let bWins = 0;
  for (const metric of metrics) {
    if (metric.winner === "a") {
      aWins += 1;
    } else if (metric.winner === "b") {
      bWins += 1;
    }
  }

  if (aWins === bWins) {
    return "tie";
  }

  return aWins > bWins ? "a" : "b";
}

function positionsDiffer(
  left: { x: number; y: number } | null | undefined,
  right: { x: number; y: number } | null | undefined,
): boolean {
  if (!left && !right) {
    return false;
  }

  if (!left || !right) {
    return true;
  }

  return (
    Math.abs(left.x - right.x) > CANDIDATE_POSITION_EPSILON ||
    Math.abs(left.y - right.y) > CANDIDATE_POSITION_EPSILON
  );
}
