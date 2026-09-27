import type { EditorRootState } from "../EditorState";
import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export function renderBeatTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  const beats = state.session.analysis?.beats ?? [];
  renderMarkers(context, beats, frame, "#42d4ff", "#7de3ff");
}

export function renderOnsetTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  const onsets = state.session.analysis?.onsets ?? [];
  renderMarkers(context, onsets, frame, "#ffb547", "#ffd492");
}

function renderMarkers(
  context: CanvasRenderingContext2D,
  markers: Array<{ timeMs: number; strength: number }>,
  frame: TimelineFrame,
  baseColor: string,
  strongColor: string,
): void {
  for (const marker of markers) {
    if (marker.timeMs < frame.visibleStartMs || marker.timeMs > frame.visibleEndMs) {
      continue;
    }

    const x = timeToCanvasX(marker.timeMs, frame);
    const height = 10 + marker.strength * (frame.height - 10);
    context.strokeStyle = marker.strength >= 0.75 ? strongColor : baseColor;
    context.lineWidth = marker.strength >= 0.75 ? 2 : 1;
    context.beginPath();
    context.moveTo(x, frame.y + frame.height - height);
    context.lineTo(x, frame.y + frame.height);
    context.stroke();
  }
}
