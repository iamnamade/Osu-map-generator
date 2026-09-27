import type { EditorRootState } from "../EditorState";
import { getStrategyColor } from "../../shared/phraseData";
import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export interface TimelinePhraseMarker {
  phraseId: number;
  x: number;
  y: number;
  width: number;
  height: number;
  strategy: string;
}

export function renderPhraseTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): TimelinePhraseMarker[] {
  const phrases = state.session.phraseAnalysis?.phrases ?? [];
  const relationships = state.session.phraseAnalysis?.relationships ?? [];
  const markers: TimelinePhraseMarker[] = [];
  if (phrases.length === 0) {
    return markers;
  }

  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();

  // Density curve overlay across the phrase track.
  drawDensityCurve(context, state, frame);

  for (const phrase of phrases) {
    if (
      phrase.endMs < frame.visibleStartMs ||
      phrase.startMs > frame.visibleEndMs
    ) {
      continue;
    }
    const left = timeToCanvasX(Math.max(phrase.startMs, frame.visibleStartMs), frame);
    const right = timeToCanvasX(Math.min(phrase.endMs, frame.visibleEndMs), frame);
    const width = Math.max(2, right - left);
    const strategy = phrase.strategy;
    const color = getStrategyColor(strategy);
    const isRecover = strategy === "recover";
    const isIntensify = strategy === "intensify";

    // Phrase block with strategy-tinted fill.
    context.fillStyle = withAlpha(color, isRecover ? 0.22 : 0.3);
    context.strokeStyle = withAlpha(color, 0.85);
    context.lineWidth = isIntensify ? 1.6 : 1;
    context.fillRect(left, frame.y + 2, width, frame.height - 4);
    context.strokeRect(left, frame.y + 2, width, frame.height - 4);

    // Motif identity marker: same motif gets a solid top band.
    if (phrase.motifId !== null) {
      context.fillStyle = withAlpha(color, 0.55);
      context.fillRect(left, frame.y + 2, width, 3);
    }

    // Recovery windows get a dashed inner outline (recovery hand-off).
    if (isRecover) {
      context.strokeStyle = withAlpha(color, 0.6);
      context.setLineDash([3, 3]);
      context.strokeRect(left + 2, frame.y + 4, Math.max(1, width - 4), frame.height - 8);
      context.setLineDash([]);
    }

    // Label: phrase id, strategy, motif.
    context.fillStyle = "#dbe7f7";
    context.font = "10px Bahnschrift, 'Segoe UI', sans-serif";
    context.textAlign = "left";
    context.textBaseline = "top";
    const pieces = [
      `P${phrase.id}`,
      strategy.slice(0, 5),
      phrase.motifId !== null ? `M${phrase.motifId}` : "",
    ].filter(Boolean);
    const label = pieces.join(" ");
    if (width > 40) {
      context.fillText(label, left + 4, frame.y + 9, Math.max(0, width - 8));
      context.fillStyle = "rgba(219, 231, 247, 0.65)";
      context.fillText(
        `${Math.round(phrase.targetDensity * 10) / 10}/s`,
        left + 4,
        frame.y + 21,
        Math.max(0, width - 8),
      );
    } else {
      context.fillText(`P${phrase.id}`, left + 3, frame.y + 12, Math.max(0, width - 6));
    }

    markers.push({
      phraseId: phrase.id,
      x: left,
      y: frame.y,
      width,
      height: frame.height,
      strategy,
    });
  }

  // Relationship arcs: draw repetition/variation links between phrase centers.
  drawRelationshipLinks(context, state, frame, phrases, relationships);

  context.restore();
  return markers;
}

function drawDensityCurve(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  const trajectory = state.session.phraseAnalysis?.trajectory ?? [];
  if (trajectory.length === 0) {
    return;
  }
  const visible = trajectory.filter(
    (point) =>
      point.timeMs >= frame.visibleStartMs && point.timeMs <= frame.visibleEndMs,
  );
  if (visible.length < 2) {
    return;
  }
  const densities = visible.map((point) => point.density);
  const maxDensity = Math.max(...densities, 0.1);
  context.beginPath();
  visible.forEach((point, index) => {
    const x = timeToCanvasX(point.timeMs, frame);
    const ratio = point.density / maxDensity;
    const y = frame.y + frame.height - 3 - ratio * (frame.height - 8);
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.strokeStyle = "rgba(93, 224, 166, 0.5)";
  context.lineWidth = 1.2;
  context.stroke();
}

function drawRelationshipLinks(
  context: CanvasRenderingContext2D,
  _state: EditorRootState,
  frame: TimelineFrame,
  phrases: Array<{
    id: number;
    startMs: number;
    endMs: number;
  }>,
  relationships: Array<{
    fromPhraseId: number;
    toPhraseId: number;
    relationshipType: string;
  }>,
): void {
  if (relationships.length === 0 || phrases.length === 0) {
    return;
  }
  const byId = new Map(phrases.map((phrase) => [phrase.id, phrase]));
  const visibleRelationships = relationships.filter((relationship) => {
    const from = byId.get(relationship.fromPhraseId);
    const to = byId.get(relationship.toPhraseId);
    if (!from || !to) {
      return false;
    }
    return (
      relationship.relationshipType === "repetition" ||
      relationship.relationshipType === "call-and-response"
    );
  });
  // Limit links to avoid visual noise.
  const shown = visibleRelationships.slice(0, 12);
  for (const relationship of shown) {
    const from = byId.get(relationship.fromPhraseId);
    const to = byId.get(relationship.toPhraseId);
    if (!from || !to) {
      continue;
    }
    const fromX = timeToCanvasX((from.startMs + from.endMs) / 2, frame);
    const toX = timeToCanvasX((to.startMs + to.endMs) / 2, frame);
    if (
      fromX < frame.x - 20 ||
      toX > frame.x + frame.width + 20
    ) {
      continue;
    }
    context.strokeStyle =
      relationship.relationshipType === "repetition"
        ? "rgba(93, 224, 166, 0.4)"
        : "rgba(197, 143, 255, 0.4)";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(fromX, frame.y + frame.height - 4);
    context.quadraticCurveTo(
      (fromX + toX) / 2,
      frame.y - 6,
      toX,
      frame.y + frame.height - 4,
    );
    context.stroke();
  }
}

function withAlpha(color: string, alpha: number): string {
  return hexWithAlpha(color, alpha);
}

function hexWithAlpha(color: string, alpha: number): string {
  if (color.startsWith("#") && color.length === 7) {
    const red = parseInt(color.slice(1, 3), 16);
    const green = parseInt(color.slice(3, 5), 16);
    const blue = parseInt(color.slice(5, 7), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }
  return color;
}
