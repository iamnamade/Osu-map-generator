import { escapeHtml } from "../../shared/format";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class HistoryPanel {
  private unsubscribe?: () => void;

  constructor(private readonly container: HTMLElement, store: EditorStore) {
    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  dispose(): void {
    this.unsubscribe?.();
  }

  private render(state: EditorRootState): void {
    const entries = state.history.entries.slice().reverse();

    this.container.innerHTML = `
      <div class="history-summary">
        <span>History Limit</span>
        <strong>${state.history.limit}</strong>
        <span>Undo Cursor</span>
        <strong>${state.history.cursor} / ${state.history.entries.length}</strong>
      </div>
      <ul class="history-list">
        ${
          entries.length > 0
            ? entries
                .map((entry) => {
                  const current = entry.sequence <= state.history.cursor ? " is-current" : "";
                  return `
                    <li class="history-item${current}">
                      <strong>#${entry.sequence}</strong>
                      <span>${escapeHtml(entry.summary)}</span>
                      <small>${escapeHtml(entry.action)}</small>
                    </li>
                  `;
                })
                .join("")
            : `<li class="panel-empty-copy">No committed edits yet.</li>`
        }
      </ul>
    `;
  }
}
