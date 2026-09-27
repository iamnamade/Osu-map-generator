import { escapeHtml } from "../../shared/format";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class SettingsPanel {
  private unsubscribe?: () => void;

  constructor(
    private readonly container: HTMLElement,
    private readonly controller: EditorController,
    store: EditorStore,
  ) {
    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  dispose(): void {
    this.unsubscribe?.();
  }

  private render(state: EditorRootState): void {
    const map = state.session.workingMap;
    if (!map) {
      this.container.innerHTML = `
        <div class="panel-empty-state">
          <strong>No map loaded</strong>
          <p>Load a map before editing metadata or editor settings.</p>
        </div>
      `;
      return;
    }

    this.container.innerHTML = `
      <div class="settings-grid">
        <label>
          <span>Title</span>
          <input type="text" data-meta="title" value="${escapeHtml(map.title)}" />
        </label>
        <label>
          <span>Artist</span>
          <input type="text" data-meta="artist" value="${escapeHtml(map.artist)}" />
        </label>
        <label class="wide-field">
          <span>Audio Path</span>
          <input type="text" data-meta="audio" value="${escapeHtml(map.audio)}" />
        </label>
        <label>
          <span>Approach Time (ms)</span>
          <input type="number" data-meta="approachTime" value="${map.approachTime}" />
        </label>
        <label>
          <span>Circle Radius</span>
          <input type="number" data-meta="circleRadius" value="${map.circleRadius}" />
        </label>
        <label>
          <span>Playback Rate</span>
          <select data-setting="playbackRate">
            <option value="0.5"${state.ui.playbackRate === 0.5 ? " selected" : ""}>0.5×</option>
            <option value="0.75"${state.ui.playbackRate === 0.75 ? " selected" : ""}>0.75×</option>
            <option value="1"${state.ui.playbackRate === 1 ? " selected" : ""}>1×</option>
          </select>
        </label>
        <label>
          <span>Snap Tolerance (ms)</span>
          <input type="number" data-setting="snapTolerance" value="${state.ui.snapToleranceMs}" />
        </label>
      </div>
      <div class="settings-toggles">
        <label><input type="checkbox" data-setting="baseline" ${state.ui.baselineOverlayEnabled ? "checked" : ""} /> Baseline overlay</label>
        <label><input type="checkbox" data-setting="validation" ${state.ui.validationEnabled ? "checked" : ""} /> Live validation</label>
      </div>
    `;

    this.bindEvents();
  }

  private bindEvents(): void {
    this.container.querySelectorAll<HTMLInputElement>("[data-meta]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.meta as "title" | "artist" | "audio" | "approachTime" | "circleRadius";
        const value = key === "title" || key === "artist" || key === "audio" ? input.value : Number(input.value);
        if (typeof value === "number" && !Number.isFinite(value)) {
          return;
        }

        this.controller.updateMetadata({ [key]: value } as never);
      });
    });

    this.container
      .querySelector<HTMLSelectElement>("select[data-setting='playbackRate']")
      ?.addEventListener("change", (event) => {
        this.controller.setPlaybackRate(
          Number((event.currentTarget as HTMLSelectElement).value) as 0.5 | 0.75 | 1,
        );
      });
    this.container
      .querySelector<HTMLInputElement>("input[data-setting='snapTolerance']")
      ?.addEventListener("change", (event) => {
        this.controller.setSnapToleranceMs(
          Number((event.currentTarget as HTMLInputElement).value),
        );
      });
    this.container
      .querySelector<HTMLInputElement>("input[data-setting='baseline']")
      ?.addEventListener("change", () => {
        this.controller.toggleBaselineOverlay();
      });
    this.container
      .querySelector<HTMLInputElement>("input[data-setting='validation']")
      ?.addEventListener("change", () => {
        this.controller.toggleValidation();
      });
  }
}
