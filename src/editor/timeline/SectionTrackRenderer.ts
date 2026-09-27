import type { EditorRootState } from "../EditorState";
import type { TimelineFrame } from "./WaveformRenderer";
import { timeToCanvasX } from "./WaveformRenderer";

export interface TimelineSectionMarker {
  sectionId: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

const SECTION_COLORS = [
  ["rgba(93, 129, 233, 0.38)", "rgba(172, 195, 255, 0.92)"],
  ["rgba(56, 160, 131, 0.34)", "rgba(160, 237, 214, 0.92)"],
  ["rgba(199, 128, 58, 0.34)", "rgba(255, 213, 168, 0.92)"],
  ["rgba(138, 99, 217, 0.34)", "rgba(226, 205, 255, 0.92)"],
];

export function renderSectionTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): TimelineSectionMarker[] {
  const sections = state.session.sectionAnalysis?.sections ?? [];
  const hybridSections = state.session.hybridAssembly?.sections ?? [];
  const hybridBySectionId = new Map(
    hybridSections.map((section) => [section.sectionId, section]),
  );
  const markers: TimelineSectionMarker[] = [];
  if (sections.length === 0) {
    return markers;
  }

  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();

  for (let index = 0; index < sections.length; index += 1) {
    const section = sections[index]!;
    if (section.endMs < frame.visibleStartMs || section.startMs > frame.visibleEndMs) {
      continue;
    }

    const left = timeToCanvasX(
      Math.max(section.startMs, frame.visibleStartMs),
      frame,
    );
    const right = timeToCanvasX(
      Math.min(section.endMs, frame.visibleEndMs),
      frame,
    );
    const width = Math.max(2, right - left);
    const [fillColor, strokeColor] = SECTION_COLORS[index % SECTION_COLORS.length]!;
    const isSelected = state.ui.selectedSectionId === section.id;
    const isLooped = state.ui.loopSectionId === section.id;
    const isLocked = state.ui.lockedSectionIds.includes(section.id);
    const hybridSection = hybridBySectionId.get(section.id);

    context.fillStyle = fillColor;
    context.strokeStyle = isSelected ? "#f2f5ff" : strokeColor;
    context.lineWidth = isSelected ? 2 : 1;
    context.fillRect(left, frame.y + 2, width, frame.height - 4);
    context.strokeRect(left, frame.y + 2, width, frame.height - 4);

    if (isLooped) {
      context.strokeStyle = "#f6c15e";
      context.setLineDash([4, 4]);
      context.strokeRect(left + 1.5, frame.y + 3.5, Math.max(1, width - 3), frame.height - 7);
      context.setLineDash([]);
    }

    context.fillStyle = "#ecf3ff";
    context.font = "11px Bahnschrift, 'Segoe UI', sans-serif";
    context.textAlign = "left";
    context.textBaseline = "top";

    const pieces = [
      `S${section.id}`,
      section.label,
      hybridSection ? `C${hybridSection.sourceCandidate}` : "",
      hybridSection?.transitionStatusAfter
        ? hybridSection.transitionStatusAfter.slice(0, 4).toUpperCase()
        : "",
      isLocked ? "L" : "",
    ].filter(Boolean);
    const label = pieces.join(" ");
    if (width > 46) {
      context.fillText(label, left + 6, frame.y + 8, Math.max(0, width - 12));
      context.fillStyle = "rgba(236, 243, 255, 0.74)";
      context.fillText(
        `${Math.round(section.confidence * 100)}%`,
        left + 6,
        frame.y + 22,
        Math.max(0, width - 12),
      );
    } else {
      context.fillText(`S${section.id}`, left + 4, frame.y + 12, Math.max(0, width - 8));
    }

    markers.push({
      sectionId: section.id,
      x: left,
      y: frame.y,
      width,
      height: frame.height,
    });
  }

  context.restore();
  return markers;
}
