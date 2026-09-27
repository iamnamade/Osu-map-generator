import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  hasHitObjectPosition,
  type ValidationIssueCategory,
  type ValidationSeverity,
} from "../game/types";
import type {
  EditorAnalysisMarker,
  EditorHitObject,
  EditorMapDocument,
  EditorSliderHitObject,
  PositionedEditorHitObject,
} from "./models/EditorModels";
import type {
  EditorLiveValidation,
  EditorObjectMetrics,
  EditorValidationIssue,
} from "./models/EditorValidationModels";

const GAP_WARNING_MS: Record<string, number> = {
  easy: 220,
  normal: 150,
  hard: 100,
};
const SPEED_WARNING: Record<string, number> = {
  easy: 320,
  normal: 420,
  hard: 560,
};
const SPEED_ERROR: Record<string, number> = {
  easy: 420,
  normal: 560,
  hard: 720,
};

export function validateEditorMap(
  map: EditorMapDocument,
  options: {
    difficulty?: string;
    audioDurationMs?: number;
    beats?: EditorAnalysisMarker[];
    onsets?: EditorAnalysisMarker[];
    energyFrames?: Array<{ timeMs: number; value: number }>;
  } = {},
): EditorLiveValidation {
  const issues: EditorValidationIssue[] = [];
  const issuesByObjectId: Record<string, EditorValidationIssue[]> = {};
  const metricsByObjectId: Record<string, EditorObjectMetrics> = {};
  const difficulty = options.difficulty ?? "normal";
  const sortedObjects = map.objects.slice().sort((left, right) => left.time - right.time);
  const seenTimes = new Map<number, string>();
  const minGapWarning = GAP_WARNING_MS[difficulty] ?? GAP_WARNING_MS.normal;
  const speedWarning = SPEED_WARNING[difficulty] ?? SPEED_WARNING.normal;
  const speedError = SPEED_ERROR[difficulty] ?? SPEED_ERROR.normal;
  const legalMin = Math.round(map.circleRadius);
  const legalMaxX = PLAYFIELD_WIDTH - legalMin;
  const legalMaxY = PLAYFIELD_HEIGHT - legalMin;

  sortedObjects.forEach((object, index) => {
    const previous = sortedObjects[index - 1];
    const next = sortedObjects[index + 1];
    const metrics: EditorObjectMetrics = {};
    metricsByObjectId[object.editorId] = metrics;

    const hasPosition = hasHitObjectPosition(object);

    if (object.type === "spinner") {
      applySpinnerValidation(
        issues,
        issuesByObjectId,
        object,
        previous,
        next,
        map,
      );
      return;
    }

    if (
      (hasPosition && (!Number.isFinite(object.x) || !Number.isFinite(object.y))) ||
      !Number.isFinite(object.time)
    ) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "critical",
        category: "structural",
        code: "non_finite_value",
        message: `Object ${object.id} contains a non-finite coordinate or time value.`,
      });
    }

    if (object.time < 0) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "critical",
        category: "structural",
        code: "negative_time",
        timeMs: object.time,
        message: `Object ${object.id} cannot be placed before 0ms.`,
      });
    }

    const existingTimeOwner = seenTimes.get(object.time);
    if (existingTimeOwner) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "critical",
        category: "structural",
        code: "duplicate_timestamp",
        timeMs: object.time,
        message: `Object ${object.id} duplicates another object's timestamp at ${object.time}ms.`,
      });
    } else {
      seenTimes.set(object.time, object.editorId);
    }

    if (
      hasPosition &&
      (object.x < legalMin || object.x > legalMaxX || object.y < legalMin || object.y > legalMaxY)
    ) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "error",
        category: "structural",
        code: "out_of_bounds",
        message: `Object ${object.id} falls outside the safe playfield bounds for the current circle radius.`,
      });
    }

    if (options.audioDurationMs && object.time > options.audioDurationMs) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "error",
        category: "structural",
        code: "after_audio_end",
        timeMs: object.time,
        allowedValue: options.audioDurationMs,
        message: `Object ${object.id} is placed after the audio duration.`,
      });
    }

    if (previous) {
      const gapMs = object.time - previous.time;
      metrics.previousGapMs = gapMs;

      if (hasHitObjectPosition(previous) && hasPosition) {
        const distancePx = distance(previous.x, previous.y, object.x, object.y);
        const cursorSpeed = gapMs > 0 ? (distancePx / gapMs) * 1000 : Infinity;
        metrics.previousDistancePx = distancePx;
        metrics.previousCursorSpeed = cursorSpeed;

        if (gapMs < minGapWarning) {
          pushIssue(issues, issuesByObjectId, {
            objectId: object.editorId,
            severity: gapMs < minGapWarning * 0.7 ? "error" : "warning",
            category: "timing",
            code: "minimum_gap",
            timeMs: object.time,
            measuredValue: gapMs,
            allowedValue: minGapWarning,
            message: `Object ${object.id} is too close to the previous object.`,
          });
        }

        if (cursorSpeed > speedWarning) {
          pushIssue(issues, issuesByObjectId, {
            objectId: object.editorId,
            severity: cursorSpeed > speedError ? "error" : "warning",
            category: "movement",
            code: "cursor_speed",
            timeMs: object.time,
            measuredValue: cursorSpeed,
            allowedValue: speedWarning,
            message: `Object ${object.id} produces ${cursorSpeed.toFixed(0)} px/s from the previous object.`,
          });
        }

        if (distancePx < map.circleRadius * 0.4) {
          pushIssue(issues, issuesByObjectId, {
            objectId: object.editorId,
            severity: distancePx === 0 ? "error" : "warning",
            category: "movement",
            code: "stacking",
            timeMs: object.time,
            measuredValue: distancePx,
            allowedValue: map.circleRadius * 0.4,
            message:
              distancePx === 0
                ? `Object ${object.id} exactly stacks on the previous object.`
                : `Object ${object.id} is near-stacked with the previous object.`,
          });
        }

        if (distancePx > PLAYFIELD_WIDTH * 0.55) {
          pushIssue(issues, issuesByObjectId, {
            objectId: object.editorId,
            severity: "warning",
            category: "movement",
            code: "large_jump",
            timeMs: object.time,
            measuredValue: distancePx,
            message: `Object ${object.id} creates a large jump from the previous object.`,
          });
        }
      }
    }

    if (next) {
      const gapMs = next.time - object.time;
      metrics.nextGapMs = gapMs;

      if (hasPosition && hasHitObjectPosition(next)) {
        const distancePx = distance(object.x, object.y, next.x, next.y);
        const cursorSpeed = gapMs > 0 ? (distancePx / gapMs) * 1000 : Infinity;
        metrics.nextDistancePx = distancePx;
        metrics.nextCursorSpeed = cursorSpeed;
      }
    }

    if (
      hasPosition &&
      (object.x < legalMin + 12 ||
        object.x > legalMaxX - 12 ||
        object.y < legalMin + 12 ||
        object.y > legalMaxY - 12)
    ) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "info",
        category: "movement",
        code: "edge_proximity",
        timeMs: object.time,
        message: `Object ${object.id} sits close to the safe playfield edge.`,
      });
    }

    if (
      previous &&
      next &&
      hasHitObjectPosition(previous) &&
      hasPosition &&
      hasHitObjectPosition(next) &&
      distance(previous.x, previous.y, next.x, next.y) < map.circleRadius * 0.7
    ) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "info",
        category: "readability",
        code: "rapid_return",
        timeMs: object.time,
        message: `Object ${object.id} creates a rapid coordinate return between its neighbors.`,
      });
    }

    if (
      previous &&
      hasHitObjectPosition(previous) &&
      hasPosition &&
      distance(previous.x, previous.y, object.x, object.y) < 4 &&
      object.time - previous.time < minGapWarning * 1.1
    ) {
      pushIssue(issues, issuesByObjectId, {
        objectId: object.editorId,
        severity: "info",
        category: "readability",
        code: "near_identical_position",
        timeMs: object.time,
        message: `Object ${object.id} repeats a near-identical position shortly after the previous note.`,
      });
    }

    applyAnchorMetrics(
      issues,
      issuesByObjectId,
      metrics,
      object.editorId,
      object.id,
      object.time,
      options.beats ?? [],
      options.onsets ?? [],
    );

    if (options.energyFrames && options.energyFrames.length > 0) {
      metrics.localEnergy = sampleEnergy(options.energyFrames, object.time);
      if ((metrics.localEnergy ?? 0) < 0.18) {
        pushIssue(issues, issuesByObjectId, {
          objectId: object.editorId,
          severity: "info",
          category: "timing",
          code: "quiet_region",
          timeMs: object.time,
          measuredValue: metrics.localEnergy,
          message: `Object ${object.id} is placed in a relatively quiet energy region.`,
        });
      }
    }
  });

  // Phase 23: radius-aware physical overlap detection (disc-disc, disc vs
  // slider body, slider vs slider). Runs after the per-object checks because
  // it needs the full sorted object list.
  applyCollisionValidation(issues, issuesByObjectId, sortedObjects, map.circleRadius);

  const summary = summarizeIssues(issues);
  return {
    issues,
    issuesByObjectId,
    summary,
    metricsByObjectId,
  };
}

function applyAnchorMetrics(
  issues: EditorValidationIssue[],
  issuesByObjectId: Record<string, EditorValidationIssue[]>,
  metrics: EditorObjectMetrics,
  editorId: string,
  objectId: number,
  timeMs: number,
  beats: EditorAnalysisMarker[],
  onsets: EditorAnalysisMarker[],
): void {
  const nearestBeat = nearestMarker(beats, timeMs);
  const nearestOnset = nearestMarker(onsets, timeMs);

  if (nearestBeat) {
    metrics.nearestBeatTimeMs = nearestBeat.timeMs;
    metrics.nearestBeatDeltaMs = Math.abs(nearestBeat.timeMs - timeMs);
    metrics.nearestBeatStrength = nearestBeat.strength;
  }

  if (nearestOnset) {
    metrics.nearestOnsetTimeMs = nearestOnset.timeMs;
    metrics.nearestOnsetDeltaMs = Math.abs(nearestOnset.timeMs - timeMs);
    metrics.nearestOnsetStrength = nearestOnset.strength;
  }

  const strongest = [nearestBeat, nearestOnset]
    .filter((item): item is EditorAnalysisMarker => Boolean(item))
    .sort((left, right) => right.strength - left.strength)[0];

  metrics.selectedAnchor = strongest
    ? strongest === nearestBeat
      ? "beat"
      : "onset"
    : "none";

  const bestDelta =
    Math.min(
      metrics.nearestBeatDeltaMs ?? Number.POSITIVE_INFINITY,
      metrics.nearestOnsetDeltaMs ?? Number.POSITIVE_INFINITY,
    ) || 0;
  metrics.timingConfidence =
    bestDelta <= 22 ? "high" : bestDelta <= 55 ? "medium" : "low";

  if (bestDelta > 90) {
    pushIssue(issues, issuesByObjectId, {
      objectId: editorId,
      severity: "warning",
      category: "timing",
      code: "weak_anchor",
      timeMs,
      measuredValue: bestDelta,
      allowedValue: 90,
      message: `Object ${objectId} is not aligned to a strong nearby beat or onset.`,
    });
  } else if (bestDelta > 45) {
    pushIssue(issues, issuesByObjectId, {
      objectId: editorId,
      severity: "info",
      category: "timing",
      code: "loose_anchor",
      timeMs,
      measuredValue: bestDelta,
      allowedValue: 45,
      message: `Object ${objectId} is only loosely aligned to the nearest beat or onset.`,
    });
  }
}

function sampleEnergy(
  frames: Array<{ timeMs: number; value: number }>,
  timeMs: number,
): number {
  let bestFrame = frames[0];
  let bestDistance = Math.abs(bestFrame.timeMs - timeMs);

  for (const frame of frames) {
    const distanceMs = Math.abs(frame.timeMs - timeMs);
    if (distanceMs < bestDistance) {
      bestFrame = frame;
      bestDistance = distanceMs;
    }
  }

  return bestFrame.value;
}

function nearestMarker(
  markers: EditorAnalysisMarker[],
  timeMs: number,
): EditorAnalysisMarker | undefined {
  let nearest: EditorAnalysisMarker | undefined;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const marker of markers) {
    const distanceMs = Math.abs(marker.timeMs - timeMs);
    if (distanceMs < bestDistance) {
      nearest = marker;
      bestDistance = distanceMs;
    }
  }

  return nearest;
}

function summarizeIssues(issues: EditorValidationIssue[]) {
  const summary = {
    critical: 0,
    errors: 0,
    warnings: 0,
    info: 0,
    total: issues.length,
  };

  for (const issue of issues) {
    if (issue.severity === "critical") {
      summary.critical += 1;
      continue;
    }

    if (issue.severity === "error") {
      summary.errors += 1;
      continue;
    }

    if (issue.severity === "warning") {
      summary.warnings += 1;
      continue;
    }

    summary.info += 1;
  }

  return summary;
}

function pushIssue(
  issues: EditorValidationIssue[],
  issuesByObjectId: Record<string, EditorValidationIssue[]>,
  issue: {
    objectId?: string;
    severity: ValidationSeverity;
    category: ValidationIssueCategory;
    code: string;
    message: string;
    timeMs?: number;
    measuredValue?: number;
    allowedValue?: number;
  },
): void {
  const nextIssue: EditorValidationIssue = {
    id: `${issue.code}:${issue.objectId ?? "map"}:${issue.timeMs ?? 0}:${issues.length}`,
    objectId: issue.objectId,
    severity: issue.severity,
    category: issue.category,
    code: issue.code,
    message: issue.message,
    timeMs: issue.timeMs,
    measuredValue: issue.measuredValue,
    allowedValue: issue.allowedValue,
  };
  issues.push(nextIssue);

  if (!issue.objectId) {
    return;
  }

  const existing = issuesByObjectId[issue.objectId];
  if (existing) {
    existing.push(nextIssue);
    return;
  }

  issuesByObjectId[issue.objectId] = [nextIssue];
}

function applySpinnerValidation(
  issues: EditorValidationIssue[],
  issuesByObjectId: Record<string, EditorValidationIssue[]>,
  spinner: Extract<EditorMapDocument["objects"][number], { type: "spinner" }>,
  previous: EditorMapDocument["objects"][number] | undefined,
  next: EditorMapDocument["objects"][number] | undefined,
  map: EditorMapDocument,
): void {
  const durationMs = spinner.endTime - spinner.time;

  if (spinner.endTime <= spinner.time) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "critical",
      category: "structural",
      code: "spinner_end_before_start",
      timeMs: spinner.time,
      message: `Spinner ${spinner.id} endTime must be greater than its start time.`,
    });
  }

  if (durationMs < 450) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "warning",
      category: "structural",
      code: "spinner_too_short",
      timeMs: spinner.time,
      measuredValue: durationMs,
      allowedValue: 450,
      message: `Spinner ${spinner.id} is shorter than 450ms and is hard to read as a spinner.`,
    });
  }

  if (durationMs > 6000) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "warning",
      category: "structural",
      code: "spinner_too_long",
      timeMs: spinner.time,
      measuredValue: durationMs,
      allowedValue: 6000,
      message: `Spinner ${spinner.id} is very long for a single spin section.`,
    });
  }

  if (previous) {
    const previousEnd = "endTime" in previous ? previous.endTime : previous.time;
    if (spinner.time < previousEnd) {
      pushIssue(issues, issuesByObjectId, {
        objectId: spinner.editorId,
        severity: "critical",
        category: "structural",
        code: "spinner_overlaps_previous",
        timeMs: spinner.time,
        message: `Spinner ${spinner.id} starts before the previous object ends.`,
      });
    } else if (spinner.time - previousEnd < 80) {
      pushIssue(issues, issuesByObjectId, {
        objectId: spinner.editorId,
        severity: "warning",
        category: "timing",
        code: "spinner_entry_tight",
        timeMs: spinner.time,
        measuredValue: spinner.time - previousEnd,
        allowedValue: 80,
        message: `Spinner ${spinner.id} leaves little reaction time after the previous object.`,
      });
    }
  }

  if (next && next.time < spinner.endTime) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "critical",
      category: "structural",
      code: "spinner_overlaps_next",
      timeMs: next.time,
      message: `Spinner ${spinner.id} ends after the next object starts.`,
    });
  } else if (next && next.time - spinner.endTime < 120) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "warning",
      category: "timing",
      code: "spinner_recovery_tight",
      timeMs: spinner.endTime,
      measuredValue: next.time - spinner.endTime,
      allowedValue: 120,
      message: `Spinner ${spinner.id} leaves little recovery time before the next object.`,
    });
  }

  if (map.circleRadius > 40 && durationMs > 3200) {
    pushIssue(issues, issuesByObjectId, {
      objectId: spinner.editorId,
      severity: "info",
      category: "difficultyConsistency",
      code: "spinner_difficulty_inconsistent",
      timeMs: spinner.time,
      measuredValue: durationMs,
      allowedValue: 3200,
      message: `Spinner ${spinner.id} is long for an easy difficulty map.`,
    });
  }
}

function distance(
  leftX: number,
  leftY: number,
  rightX: number,
  rightY: number,
): number {
  return Math.hypot(rightX - leftX, rightY - leftY);
}

// ---------------------------------------------------------------------------
// Phase 23 — Radius-aware collision detection
// ---------------------------------------------------------------------------

const COLLISION_TIME_GAP_MS = 2000;
const COLLISION_STACK_WINDOW_MS = 1500;
const COLLISION_MARGIN_PX = 2;
const PERFECT_STACK_PX = 2;

interface CollisionPoint {
  x: number;
  y: number;
}

function applyCollisionValidation(
  issues: EditorValidationIssue[],
  issuesByObjectId: Record<string, EditorValidationIssue[]>,
  sortedObjects: EditorHitObject[],
  circleRadius: number,
): void {
  const radius = circleRadius > 0 ? circleRadius : 1;

  for (let index = 0; index < sortedObjects.length; index += 1) {
    const right = sortedObjects[index];
    if (!hasHitObjectPosition(right)) {
      continue;
    }
    const rightPath = sliderOrPointPath(right);

    // Walk backwards through earlier objects (sorted ascending, so break as
    // soon as the time gap exceeds the collision window).
    for (let other = index - 1; other >= 0; other -= 1) {
      const left = sortedObjects[other];
      if (!hasHitObjectPosition(left)) {
        continue;
      }
      const gapMs = right.time - left.time;
      if (gapMs > COLLISION_TIME_GAP_MS) {
        break;
      }
      if (gapMs <= 0) {
        continue;
      }

      const leftPath = sliderOrPointPath(left);
      const kind =
        left.type === "slider" && right.type === "slider"
          ? "slider-slider"
          : left.type === "slider" || right.type === "slider"
            ? "disc-slider"
            : "disc-disc";
      const clearance = clearanceForPaths(kind, left, right, leftPath, rightPath, radius);
      if (clearance >= -COLLISION_MARGIN_PX) {
        continue;
      }

      // Intentional time-separated stacks are legal osu! notation.
      if (
        gapMs > COLLISION_STACK_WINDOW_MS &&
        kind === "disc-disc" &&
        sameCenter(leftPath, rightPath)
      ) {
        continue;
      }

      pushIssue(issues, issuesByObjectId, {
        objectId: right.editorId,
        severity: "error",
        category: "movement",
        code: "collision_overlap",
        timeMs: right.time,
        measuredValue: clearance,
        allowedValue: -(radius * 2),
        message: `Object ${right.id} physically overlaps object ${left.id} (${kind}) by ${(-clearance).toFixed(1)}px. Nudge the later object away.`,
      });
      break;
    }
  }
}

function sliderOrPointPath(object: PositionedEditorHitObject): CollisionPoint[] {
  if (object.type !== "slider") {
    return [{ x: object.x, y: object.y }];
  }
  const path = sampleSliderPath(object);
  return path.length > 0 ? path : [{ x: object.x, y: object.y }];
}

function clearanceForPaths(
  kind: string,
  left: PositionedEditorHitObject,
  right: PositionedEditorHitObject,
  leftPath: CollisionPoint[],
  rightPath: CollisionPoint[],
  radius: number,
): number {
  if (kind === "disc-disc") {
    return distance(left.x, left.y, right.x, right.y) - radius * 2;
  }
  if (kind === "slider-slider") {
    return polylineDistance(leftPath, rightPath) - radius * 2;
  }
  const circle = left.type === "circle" ? left : right;
  const sliderPath = left.type === "circle" ? rightPath : leftPath;
  return pointPolylineDistance(circle.x, circle.y, sliderPath) - radius * 2;
}

function pointPolylineDistance(px: number, py: number, path: CollisionPoint[]): number {
  if (path.length === 0) {
    return Number.POSITIVE_INFINITY;
  }
  if (path.length === 1) {
    return distance(px, py, path[0].x, path[0].y);
  }
  let best = Number.POSITIVE_INFINITY;
  for (let index = 1; index < path.length; index += 1) {
    best = Math.min(best, pointSegmentDistance(px, py, path[index - 1], path[index]));
  }
  return best;
}

function polylineDistance(pathA: CollisionPoint[], pathB: CollisionPoint[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (let index = 1; index < pathA.length; index += 1) {
    const a1 = pathA[index - 1];
    const a2 = pathA[index];
    for (let other = 1; other < pathB.length; other += 1) {
      const b1 = pathB[other - 1];
      const b2 = pathB[other];
      best = Math.min(best, segmentSegmentDistance(a1, a2, b1, b2));
      if (best === 0) {
        return 0;
      }
    }
  }
  return best;
}

function pointSegmentDistance(
  px: number,
  py: number,
  start: CollisionPoint,
  end: CollisionPoint,
): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared <= 0) {
    return distance(px, py, start.x, start.y);
  }
  const projection = Math.max(0, Math.min(1, ((px - start.x) * dx + (py - start.y) * dy) / lengthSquared));
  return distance(px, py, start.x + projection * dx, start.y + projection * dy);
}

function segmentSegmentDistance(
  a1: CollisionPoint,
  a2: CollisionPoint,
  b1: CollisionPoint,
  b2: CollisionPoint,
): number {
  if (segmentsIntersect(a1, a2, b1, b2)) {
    return 0;
  }
  return Math.min(
    pointSegmentDistance(b1.x, b1.y, a1, a2),
    pointSegmentDistance(b2.x, b2.y, a1, a2),
    pointSegmentDistance(a1.x, a1.y, b1, b2),
    pointSegmentDistance(a2.x, a2.y, b1, b2),
  );
}

function orientation(p: CollisionPoint, q: CollisionPoint, r: CollisionPoint): number {
  return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y);
}

function onSegment(p: CollisionPoint, q: CollisionPoint, r: CollisionPoint): boolean {
  return (
    Math.min(p.x, r.x) - 1e-9 <= q.x &&
    q.x <= Math.max(p.x, r.x) + 1e-9 &&
    Math.min(p.y, r.y) - 1e-9 <= q.y &&
    q.y <= Math.max(p.y, r.y) + 1e-9
  );
}

function segmentsIntersect(
  a1: CollisionPoint,
  a2: CollisionPoint,
  b1: CollisionPoint,
  b2: CollisionPoint,
): boolean {
  const o1 = orientation(a1, a2, b1);
  const o2 = orientation(a1, a2, b2);
  const o3 = orientation(b1, b2, a1);
  const o4 = orientation(b1, b2, a2);
  if (o1 > 0 !== o2 > 0 && o3 > 0 !== o4 > 0) {
    return true;
  }
  if (o1 === 0 && onSegment(a1, b1, a2)) {
    return true;
  }
  if (o2 === 0 && onSegment(a1, b2, a2)) {
    return true;
  }
  if (o3 === 0 && onSegment(b1, a1, b2)) {
    return true;
  }
  if (o4 === 0 && onSegment(b1, a2, b2)) {
    return true;
  }
  return false;
}

function sameCenter(leftPath: CollisionPoint[], rightPath: CollisionPoint[]): boolean {
  if (leftPath.length === 0 || rightPath.length === 0) {
    return false;
  }
  return (
    Math.abs(leftPath[0].x - rightPath[0].x) <= PERFECT_STACK_PX &&
    Math.abs(leftPath[0].y - rightPath[0].y) <= PERFECT_STACK_PX
  );
}

function sampleSliderPath(object: EditorSliderHitObject): CollisionPoint[] {
  const start = { x: object.x, y: object.y };
  const points = [start, ...object.controlPoints];
  if (points.length < 2) {
    return [start];
  }
  if (object.pathType === "linear") {
    return sampleLinear(points, 12);
  }
  if (object.pathType === "perfect" && points.length >= 3) {
    const arc = samplePerfect(points[0], points[1], points[2], 24);
    if (arc) {
      return arc;
    }
  }
  // Bezier (default) with red anchors (duplicated points) splitting segments.
  const segments: CollisionPoint[][] = [];
  let current = [points[0]];
  for (let index = 1; index < points.length; index += 1) {
    if (points[index].x === points[index - 1].x && points[index].y === points[index - 1].y) {
      current.push(points[index]);
      segments.push(current);
      current = [points[index]];
    } else {
      current.push(points[index]);
    }
  }
  if (current.length > 1) {
    segments.push(current);
  }
  const sampled: CollisionPoint[] = [];
  const samplesPerSegment = Math.max(4, Math.floor(24 / Math.max(1, segments.length)));
  for (const segment of segments) {
    for (let step = 0; step < samplesPerSegment; step += 1) {
      const t = step / Math.max(1, samplesPerSegment - 1);
      sampled.push(deCasteljau(segment, t));
    }
  }
  return sampled.length > 0 ? sampled : [start];
}

function sampleLinear(points: CollisionPoint[], samples: number): CollisionPoint[] {
  const output: CollisionPoint[] = [];
  for (let step = 0; step < samples; step += 1) {
    const t = step / Math.max(1, samples - 1);
    output.push(lerp(points[0], points[points.length - 1], t));
  }
  return output;
}

function samplePerfect(
  p1: CollisionPoint,
  p2: CollisionPoint,
  p3: CollisionPoint,
  samples: number,
): CollisionPoint[] | undefined {
  const d = 2 * (p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y));
  if (Math.abs(d) < 0.001) {
    return undefined;
  }
  const ux =
    ((p1.x * p1.x + p1.y * p1.y) * (p2.y - p3.y) +
      (p2.x * p2.x + p2.y * p2.y) * (p3.y - p1.y) +
      (p3.x * p3.x + p3.y * p3.y) * (p1.y - p2.y)) /
    d;
  const uy =
    ((p1.x * p1.x + p1.y * p1.y) * (p3.x - p2.x) +
      (p2.x * p2.x + p2.y * p2.y) * (p1.x - p3.x) +
      (p3.x * p3.x + p3.y * p3.y) * (p2.x - p1.x)) /
    d;
  const center = { x: ux, y: uy };
  const radius = distance(p1.x, p1.y, ux, uy);
  const startAngle = Math.atan2(p1.y - uy, p1.x - ux);
  const endAngle = Math.atan2(p3.y - uy, p3.x - ux);
  const cross = (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x);
  const clockwise = cross < 0;
  const output: CollisionPoint[] = [];
  for (let step = 0; step < samples; step += 1) {
    let angle = startAngle + (endAngle - startAngle) * (step / Math.max(1, samples - 1));
    if (clockwise && endAngle < startAngle) {
      angle = startAngle + (endAngle + Math.PI * 2 - startAngle) * (step / Math.max(1, samples - 1));
    } else if (!clockwise && endAngle > startAngle) {
      angle = startAngle + (endAngle - Math.PI * 2 - startAngle) * (step / Math.max(1, samples - 1));
    }
    output.push({ x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius });
  }
  return output;
}

function deCasteljau(points: CollisionPoint[], t: number): CollisionPoint {
  let working = points.map((point) => ({ ...point }));
  while (working.length > 1) {
    const next: CollisionPoint[] = [];
    for (let index = 0; index < working.length - 1; index += 1) {
      next.push(lerp(working[index], working[index + 1], t));
    }
    working = next;
  }
  return working[0];
}

function lerp(a: CollisionPoint, b: CollisionPoint, t: number): CollisionPoint {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}
