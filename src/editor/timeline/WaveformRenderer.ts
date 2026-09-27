import type { EditorRootState } from "../EditorState";

export function renderWaveformTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();

  const peaks = state.session.waveform?.peaks;
  if (peaks && peaks.length > 1) {
    context.strokeStyle = "#7c4dff";
    context.lineWidth = 1.2;
    context.beginPath();

    for (let index = 0; index < peaks.length; index += 1) {
      const x = frame.x + (index / (peaks.length - 1)) * frame.width;
      const amplitude = peaks[index];
      const top = frame.y + frame.height / 2 - amplitude * (frame.height / 2 - 4);
      const bottom = frame.y + frame.height / 2 + amplitude * (frame.height / 2 - 4);
      context.moveTo(x, top);
      context.lineTo(x, bottom);
    }

    context.stroke();
    context.restore();
    return;
  }

  const energyFrames = state.session.analysis?.energyFrames ?? [];
  if (energyFrames.length > 0) {
    context.fillStyle = "rgba(124, 77, 255, 0.22)";
    context.strokeStyle = "rgba(162, 133, 255, 0.95)";
    context.lineWidth = 1.2;
    context.beginPath();

    let started = false;
    for (const marker of energyFrames) {
      if (marker.timeMs < frame.visibleStartMs || marker.timeMs > frame.visibleEndMs) {
        continue;
      }

      const x = timeToCanvasX(marker.timeMs, frame);
      const y = frame.y + frame.height - marker.value * (frame.height - 6);
      if (!started) {
        context.moveTo(x, frame.y + frame.height);
        context.lineTo(x, y);
        started = true;
      } else {
        context.lineTo(x, y);
      }
    }

    context.lineTo(frame.x + frame.width, frame.y + frame.height);
    context.closePath();
    context.fill();
    context.stroke();
  }

  context.restore();
}

export interface TimelineFrame {
  x: number;
  y: number;
  width: number;
  height: number;
  visibleStartMs: number;
  visibleEndMs: number;
}

export function timeToCanvasX(timeMs: number, frame: TimelineFrame): number {
  return (
    frame.x +
    ((timeMs - frame.visibleStartMs) / (frame.visibleEndMs - frame.visibleStartMs)) *
      frame.width
  );
}
