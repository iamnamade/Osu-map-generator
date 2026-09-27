import type { EditorController } from "../EditorController";
import type { TimelineIssueMarker, TimelineObjectMarker } from "./ObjectTrackRenderer";
import type { TimelineSectionMarker } from "./SectionTrackRenderer";
import type { TimelineFrame } from "./WaveformRenderer";

interface TimelineInteractionFrame {
  objectMarkers: TimelineObjectMarker[];
  issueMarkers: TimelineIssueMarker[];
  sectionMarkers: TimelineSectionMarker[];
  chartFrame: TimelineFrame;
}

export class TimelineInteractions {
  private dragMode: "none" | "playhead" | "object" = "none";
  private draggedObjectId?: string;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly controller: EditorController,
    private readonly getFrame: () => TimelineInteractionFrame | undefined,
  ) {}

  attach(): void {
    this.canvas.addEventListener("pointerdown", this.handlePointerDown);
    window.addEventListener("pointermove", this.handlePointerMove);
    window.addEventListener("pointerup", this.handlePointerUp);
    this.canvas.addEventListener("wheel", this.handleWheel, { passive: false });
  }

  detach(): void {
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    window.removeEventListener("pointermove", this.handlePointerMove);
    window.removeEventListener("pointerup", this.handlePointerUp);
    this.canvas.removeEventListener("wheel", this.handleWheel);
  }

  private readonly handlePointerDown = (event: PointerEvent) => {
    const frame = this.getFrame();
    if (!frame) {
      return;
    }

    const point = canvasPoint(this.canvas, event);
    const issue = frame.issueMarkers.find(
      (marker) => distance(point.x, point.y, marker.x, marker.y) <= marker.radius,
    );
    if (issue) {
      this.controller.jumpToIssue(issue.issueId);
      return;
    }

    const section = frame.sectionMarkers.find(
      (marker) =>
        point.x >= marker.x &&
        point.x <= marker.x + marker.width &&
        point.y >= marker.y &&
        point.y <= marker.y + marker.height,
    );
    if (section) {
      this.controller.selectSection(section.sectionId, {
        seek: true,
        openHybridTab: true,
      });
      return;
    }

    const marker = frame.objectMarkers.find(
      (candidate) => distance(point.x, point.y, candidate.x, candidate.y) <= candidate.radius,
    );
    if (marker) {
      this.dragMode = "object";
      this.draggedObjectId = marker.objectId;
      this.controller.selectObject(marker.objectId);
      return;
    }

    this.dragMode = "playhead";
    this.controller.seek(timeFromPoint(point.x, frame.chartFrame));
  };

  private readonly handlePointerMove = (event: PointerEvent) => {
    const frame = this.getFrame();
    if (!frame || this.dragMode === "none") {
      return;
    }

    const point = canvasPoint(this.canvas, event);
    const timeMs = timeFromPoint(point.x, frame.chartFrame);
    if (this.dragMode === "playhead") {
      this.controller.seek(timeMs);
      return;
    }

    if (this.draggedObjectId) {
      this.controller.retimeObject(this.draggedObjectId, timeMs, false);
    }
  };

  private readonly handlePointerUp = (event: PointerEvent) => {
    const frame = this.getFrame();
    if (!frame) {
      this.dragMode = "none";
      this.draggedObjectId = undefined;
      return;
    }

    if (this.dragMode === "object" && this.draggedObjectId) {
      const point = canvasPoint(this.canvas, event);
      const timeMs = timeFromPoint(point.x, frame.chartFrame);
      this.controller.retimeObject(this.draggedObjectId, timeMs, true);
    }

    this.dragMode = "none";
    this.draggedObjectId = undefined;
  };

  private readonly handleWheel = (event: WheelEvent) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      this.controller.zoomTimeline(event.deltaY > 0 ? 1.18 : 0.85);
      return;
    }

    this.controller.panTimeline(event.deltaY * 6);
  };
}

function canvasPoint(canvas: HTMLCanvasElement, event: PointerEvent): { x: number; y: number } {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: event.clientX - bounds.left,
    y: event.clientY - bounds.top,
  };
}

function timeFromPoint(x: number, frame: TimelineFrame): number {
  const ratio = Math.min(1, Math.max(0, (x - frame.x) / frame.width));
  return Math.round(
    frame.visibleStartMs + ratio * (frame.visibleEndMs - frame.visibleStartMs),
  );
}

function distance(leftX: number, leftY: number, rightX: number, rightY: number): number {
  return Math.hypot(rightX - leftX, rightY - leftY);
}
