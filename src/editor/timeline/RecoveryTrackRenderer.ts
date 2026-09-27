import type { EditorRootState } from "../EditorState";
import { fatigueAtTime } from "../../shared/recoveryData";
import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export interface TimelineRecoveryMarker {
  kind: "spinner" | "recovery-window";
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

export function renderRecoveryTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): TimelineRecoveryMarker[] {
  const recovery = state.session.recoveryAnalysis;
  const markers: TimelineRecoveryMarker[] = [];
  if (!recovery) {
    return markers;
  }

  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();

  // Fatigue curve across the full track.
  drawFatigueCurve(context, state, frame, recovery);

  // Recovery window bands (calm-down pacing after intense phrases).
  for (const window of recovery.recoveryWindows) {
    if (
      window.endTime < frame.visibleStartMs ||
      window.startTime > frame.visibleEndMs
    ) {
      continue;
    }
    const left = timeToCanvasX(Math.max(window.startTime, frame.visibleStartMs), frame);
    const right = timeToCanvasX(Math.min(window.endTime, frame.visibleEndMs), frame);
    const width = Math.max(2, right - left);

    context.fillStyle = "rgba(111, 207, 151, 0.16)";
    context.strokeStyle = "rgba(111, 207, 151, 0.7)";
    context.lineWidth = 1;
    context.setLineDash([4, 3]);
    context.fillRect(left, frame.y + 2, width, frame.height - 4);
    context.strokeRect(left, frame.y + 2, width, frame.height - 4);
    context.setLineDash([]);

    // Stamina reduction label.
    context.fillStyle = "#bfe8d0";
    context.font = "10px Bahnschrift, 'Segoe UI', sans-serif";
    context.textAlign = "left";
    context.textBaseline = "top";
    const reductionPct = Math.round(window.staminaReductionFactor * 100);
    const label = `recover ${reductionPct}%`;
    if (width > 60) {
      context.fillText(label, left + 4, frame.y + 7, Math.max(0, width - 8));
    }

    markers.push({
      kind: "recovery-window",
      x: left,
      y: frame.y,
      width,
      height: frame.height,
      label,
    });
  }

  // Spinner object markers (diamonds) on the same track.
  const objects = state.session.workingMap?.objects ?? [];
  for (const object of objects) {
    if (object.type !== "spinner") {
      continue;
    }
    const endTime = object.endTime;
    if (endTime < frame.visibleStartMs || object.time > frame.visibleEndMs) {
      continue;
    }
    const startX = timeToCanvasX(object.time, frame);
    const endX = timeToCanvasX(endTime, frame);
    const midX = (startX + endX) / 2;
    const y = frame.y + frame.height / 2;
    const halfWidth = Math.min(14, Math.max(5, (endX - startX) / 2));

    context.strokeStyle = "#9be8ff";
    context.lineWidth = 1.4;
    context.beginPath();
    context.moveTo(midX, y - 7);
    context.lineTo(midX + halfWidth, y);
    context.lineTo(midX, y + 7);
    context.lineTo(midX - halfWidth, y);
    context.closePath();
    context.stroke();

    markers.push({
      kind: "spinner",
      x: midX,
      y,
      width: halfWidth * 2,
      height: 14,
      label: "S",
    });
  }

  context.restore();
  return markers;
}

function drawFatigueCurve(
  context: CanvasRenderingContext2D,
  _state: EditorRootState,
  frame: TimelineFrame,
  recovery: NonNullable<EditorRootState["session"]["recoveryAnalysis"]>,
): void {
  const timestamps = recovery.fatigue.timestamps;
  if (timestamps.length === 0) {
    return;
  }
  const visible = timestamps.filter(
    (timeMs) => timeMs >= frame.visibleStartMs && timeMs <= frame.visibleEndMs,
  );
  if (visible.length < 2) {
    return;
  }

  context.beginPath();
  let started = false;
  for (const timeMs of visible) {
    const x = timeToCanvasX(timeMs, frame);
    const fatigue = fatigueAtTime(recovery.fatigue, timeMs, 120);
    const y = frame.y + frame.height - 3 - fatigue * (frame.height - 8);
    if (!started) {
      context.moveTo(x, y);
      started = true;
    } else {
      context.lineTo(x, y);
    }
  }
  context.strokeStyle = "rgba(155, 232, 255, 0.55)";
  context.lineWidth = 1.2;
  context.stroke();

  // Peak marker.
  const peakX = timeToCanvasX(recovery.fatigue.peakFatigueTime, frame);
  if (peakX >= frame.x && peakX <= frame.x + frame.width) {
    context.fillStyle = "rgba(255, 122, 110, 0.85)";
    context.beginPath();
    context.arc(peakX, frame.y + frame.height - 3 - recovery.fatigue.peakFatigue * (frame.height - 8), 2.5, 0, Math.PI * 2);
    context.fill();
  }
}
