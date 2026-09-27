import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export function renderPlayhead(
  context: CanvasRenderingContext2D,
  frame: TimelineFrame,
  playheadMs: number,
  label: string,
): void {
  const x = timeToCanvasX(playheadMs, frame);
  context.strokeStyle = "#9c61ff";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(x, frame.y);
  context.lineTo(x, frame.y + frame.height);
  context.stroke();

  context.fillStyle = "#9c61ff";
  context.beginPath();
  context.roundRect(x - 20, frame.y - 22, 40, 18, 6);
  context.fill();
  context.fillStyle = "#fbf7ff";
  context.font = "11px Bahnschrift, 'Segoe UI', sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, x, frame.y - 13);
}
