import type { ValidationSeverity } from "../../game/types";
import { computeDensityCurve } from "../candidates/candidateCompare";
import type { EditorRootState } from "../EditorState";
import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export interface TimelineObjectMarker {
  objectId: string;
  x: number;
  y: number;
  radius: number;
}

export interface TimelineIssueMarker {
  issueId: string;
  x: number;
  y: number;
  radius: number;
}

export function renderObjectTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): {
  objectMarkers: TimelineObjectMarker[];
  issueMarkers: TimelineIssueMarker[];
} {
  const workingMap = state.session.workingMap;
  const baselineMap = state.session.baselineMap;
  const selectedObjectId = state.ui.selectedObjectId;
  const objectMarkers: TimelineObjectMarker[] = [];
  const issueMarkers: TimelineIssueMarker[] = [];

  if (!workingMap) {
    return { objectMarkers, issueMarkers };
  }

  const baselineById = new Map(
    (baselineMap?.objects ?? []).map((object) => [object.editorId, object]),
  );

  for (const object of workingMap.objects) {
    const endTime = "endTime" in object ? object.endTime : object.time;
    if (endTime < frame.visibleStartMs || object.time > frame.visibleEndMs) {
      continue;
    }

    const x = timeToCanvasX(object.time, frame);
    const y = frame.y + frame.height / 2;
    const baseline = baselineById.get(object.editorId);
    const baselineEnd = baseline && "endTime" in baseline ? baseline.endTime : baseline?.time;
    const changed =
      baseline &&
      (baseline.x !== object.x ||
        baseline.y !== object.y ||
        baseline.time !== object.time ||
        baselineEnd !== endTime);

    if (object.type === "spinner") {
      const endX = timeToCanvasX(endTime, frame);
      const width = Math.max(8, endX - x);
      const barHeight = object.editorId === selectedObjectId ? 16 : 12;
      context.fillStyle =
        object.editorId === selectedObjectId
          ? "#8b5cf6"
          : changed
            ? "#4b7ce2"
            : "#9be8ff";
      context.globalAlpha = 0.85;
      context.fillRect(x, y - barHeight / 2, width, barHeight);
      context.globalAlpha = 1;
      context.strokeStyle = object.editorId === selectedObjectId ? "#f4ebff" : "#2c4a63";
      context.lineWidth = 1;
      context.strokeRect(x, y - barHeight / 2, width, barHeight);

      context.fillStyle = "#04121c";
      context.font = "12px Bahnschrift, 'Segoe UI', sans-serif";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText("S", x + 8, y);

      objectMarkers.push({
        objectId: object.editorId,
        x: x + Math.max(0, width / 2),
        y,
        radius: 12,
      });
      continue;
    }

    context.fillStyle =
      object.editorId === selectedObjectId
        ? "#8b5cf6"
        : changed
          ? "#4b7ce2"
          : "#281f42";
    context.strokeStyle = object.editorId === selectedObjectId ? "#f4ebff" : "#a78bfa";
    context.lineWidth = object.editorId === selectedObjectId ? 2 : 1;
    context.beginPath();
    context.arc(x, y, object.editorId === selectedObjectId ? 11 : 9, 0, Math.PI * 2);
    context.fill();
    context.stroke();

    context.fillStyle = "#f9fbff";
    context.font = "12px Bahnschrift, 'Segoe UI', sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(String(object.id), x, y);

    objectMarkers.push({
      objectId: object.editorId,
      x,
      y,
      radius: 12,
    });

    if (state.ui.baselineOverlayEnabled && baseline && baseline.time !== object.time) {
      const baselineX = timeToCanvasX(baseline.time, frame);
      context.strokeStyle = "rgba(167, 139, 250, 0.6)";
      context.beginPath();
      context.arc(baselineX, y, 5, 0, Math.PI * 2);
      context.stroke();
      context.beginPath();
      context.moveTo(baselineX, y - 12);
      context.lineTo(x, y - 12);
      context.stroke();
    }
  }

  renderComparisonOverlay(context, state, frame);

  for (const issue of state.session.liveValidation.issues) {
    if (
      !issue.objectId ||
      typeof issue.timeMs !== "number" ||
      issue.timeMs < frame.visibleStartMs ||
      issue.timeMs > frame.visibleEndMs
    ) {
      continue;
    }

    const x = timeToCanvasX(issue.timeMs, frame);
    const y = frame.y + frame.height - 14;
    const fillStyle = issueColor(issue.severity);
    context.fillStyle = fillStyle;
    context.beginPath();
    context.moveTo(x, y - 6);
    context.lineTo(x + 6, y);
    context.lineTo(x, y + 6);
    context.lineTo(x - 6, y);
    context.closePath();
    context.fill();

    issueMarkers.push({
      issueId: issue.id,
      x,
      y,
      radius: 8,
    });
  }

  return { objectMarkers, issueMarkers };
}

function renderComparisonOverlay(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  const comparison = state.candidates.comparison;
  const mapB = comparison.candidateB?.map;
  const mapA = comparison.candidateA?.map;
  if (
    !state.candidates.comparisonEnabled ||
    comparison.state !== "ready" ||
    !mapB
  ) {
    return;
  }

  const durationMs = Math.max(
    mapA ? mapDurationMs(mapA) : 0,
    mapDurationMs(mapB),
  );
  const curveA = mapA ? computeDensityCurve(mapA, durationMs) : [];
  const curveB = computeDensityCurve(mapB, durationMs);
  const maxDensity = Math.max(
    0.0001,
    ...curveA.map((point) => point.value),
    ...curveB.map((point) => point.value),
  );

  // Per-candidate density/strain lines (computed from real object data).
  const baselineY = frame.y + frame.height - 2;
  const strainHeight = 14;
  drawDensityLine(context, curveA, frame, baselineY, strainHeight, maxDensity, "rgba(167, 139, 250, 0.5)");
  drawDensityLine(context, curveB, frame, baselineY, strainHeight, maxDensity, "rgba(34, 211, 238, 0.6)");

  // Candidate B object markers (diamonds) over the same hit-object track.
  for (const object of mapB.objects) {
    const endTime = "endTime" in object ? object.endTime : object.time;
    if (endTime < frame.visibleStartMs || object.time > frame.visibleEndMs) {
      continue;
    }

    const x = timeToCanvasX(object.time, frame);
    const y = frame.y + frame.height / 2;
    context.strokeStyle = "rgba(34, 211, 238, 0.9)";
    context.lineWidth = 1.5;
    context.beginPath();
    context.moveTo(x, y - 8);
    context.lineTo(x + 8, y);
    context.lineTo(x, y + 8);
    context.lineTo(x - 8, y);
    context.closePath();
    context.stroke();
  }
}

function drawDensityLine(
  context: CanvasRenderingContext2D,
  curve: Array<{ timeMs: number; value: number }>,
  frame: TimelineFrame,
  baselineY: number,
  strainHeight: number,
  maxValue: number,
  color: string,
): void {
  if (curve.length === 0) {
    return;
  }

  context.strokeStyle = color;
  context.lineWidth = 1.2;
  context.beginPath();
  let started = false;
  for (const point of curve) {
    if (point.timeMs < frame.visibleStartMs || point.timeMs > frame.visibleEndMs) {
      continue;
    }

    const x =
      frame.x +
      ((point.timeMs - frame.visibleStartMs) /
        (frame.visibleEndMs - frame.visibleStartMs)) *
        frame.width;
    const y = baselineY - (point.value / maxValue) * strainHeight;
    if (!started) {
      context.moveTo(x, y);
      started = true;
    } else {
      context.lineTo(x, y);
    }
  }
  context.stroke();
}

function mapDurationMs(map: { objects: Array<{ time: number; endTime?: number }> }): number {
  const last = map.objects[map.objects.length - 1];
  return last ? (last.endTime ?? last.time) : 0;
}

function issueColor(severity: ValidationSeverity): string {
  if (severity === "critical") {
    return "#ff5e80";
  }

  if (severity === "error") {
    return "#ff875d";
  }

  if (severity === "warning") {
    return "#f6c15e";
  }

  return "#56b6ff";
}
