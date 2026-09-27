import type { EditorController } from "./EditorController";

export class EditorKeyboard {
  private readonly onKeyDown = (event: KeyboardEvent) => {
    if (shouldIgnoreShortcut(event)) {
      return;
    }

    if (event.code === "Space") {
      event.preventDefault();
      this.controller.togglePlayPause();
      return;
    }

    if (event.key === "s" || event.key === "S") {
      event.preventDefault();
      this.controller.setMode("select");
      return;
    }

    if (event.key === "a" || event.key === "A") {
      event.preventDefault();
      this.controller.setMode("add-circle");
      return;
    }

    if (event.key === "b" || event.key === "B") {
      event.preventDefault();
      this.controller.toggleBaselineOverlay();
      return;
    }

    if (event.key === "f" || event.key === "F") {
      event.preventDefault();
      this.controller.fitTimeline();
      return;
    }

    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      this.controller.zoomTimeline(0.8);
      return;
    }

    if (event.key === "-") {
      event.preventDefault();
      this.controller.zoomTimeline(1.25);
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      this.controller.cancelActiveTool();
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      this.controller.seekToStart();
      return;
    }

    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      this.controller.deleteSelectedObject();
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      this.controller.nudgeSelection(-stepSize(event), 0);
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      this.controller.nudgeSelection(stepSize(event), 0);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      this.controller.nudgeSelection(0, -stepSize(event));
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      this.controller.nudgeSelection(0, stepSize(event));
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) {
        this.controller.redo();
        return;
      }

      this.controller.undo();
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      event.preventDefault();
      this.controller.redo();
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
      event.preventDefault();
      this.controller.copySelectedObject();
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
      event.preventDefault();
      this.controller.pasteObject();
      return;
    }
  };

  constructor(private readonly controller: EditorController) {}

  attach(): void {
    window.addEventListener("keydown", this.onKeyDown);
  }

  detach(): void {
    window.removeEventListener("keydown", this.onKeyDown);
  }
}

export function shouldIgnoreShortcut(event: KeyboardEvent): boolean {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  if (target.isContentEditable) {
    return true;
  }

  const tagName = target.tagName;
  return tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT";
}

export function stepSize(event: KeyboardEvent): number {
  return event.shiftKey ? 10 : 1;
}
