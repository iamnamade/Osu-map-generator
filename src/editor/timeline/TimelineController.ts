import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";
import { TimelineInteractions } from "./TimelineInteractions";
import { TimelineRenderer, type TimelineRenderResult } from "./TimelineRenderer";

export class TimelineController {
  private readonly renderer = new TimelineRenderer();
  private readonly interactions: TimelineInteractions;
  private latestFrame?: TimelineRenderResult;
  private unsubscribe?: () => void;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly controller: EditorController,
    store: EditorStore,
    ) {
      this.interactions = new TimelineInteractions(
        canvas,
        controller,
        () => this.latestFrame,
      );

    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  attach(): void {
    this.interactions.attach();
    window.addEventListener("resize", this.handleResize);
  }

  dispose(): void {
    this.interactions.detach();
    window.removeEventListener("resize", this.handleResize);
    this.unsubscribe?.();
  }

  private readonly handleResize = () => {
    this.render(this.controller.getState());
  };

  private render(state: EditorRootState): void {
    this.latestFrame = this.renderer.render(this.canvas, state);
  }
}
