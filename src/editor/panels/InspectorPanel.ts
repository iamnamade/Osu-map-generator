import { escapeHtml, formatSignedNumber, formatTimeMs } from "../../shared/format";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class InspectorPanel {
  private unsubscribe?: () => void;
  private fieldErrors: Partial<Record<"x" | "y" | "time" | "endTime", string>> = {};

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
    const selected = state.session.selectedObject;
    const baseline = state.session.baselineMap?.objects.find(
      (object) => object.editorId === selected?.editorId,
    );
    const metrics = selected
      ? state.session.liveValidation.metricsByObjectId[selected.editorId]
      : undefined;
    const issues = selected
      ? state.session.liveValidation.issuesByObjectId[selected.editorId] ?? []
      : [];

    if (!selected) {
      this.container.innerHTML = `
        <div class="panel-empty-state">
          <strong>No selected object</strong>
          <p>Select a circle from the playfield or timeline to inspect and edit it.</p>
        </div>
      `;
      return;
    }

    const selectedX = typeof selected.x === "number" ? selected.x : 0;
    const selectedY = typeof selected.y === "number" ? selected.y : 0;
    const baselineX = typeof baseline?.x === "number" ? baseline.x : 0;
    const baselineY = typeof baseline?.y === "number" ? baseline.y : 0;
    const isSpinner = selected.type === "spinner";

    this.container.innerHTML = `
      <div class="inspector-grid">
        <label>
          <span>Object ID</span>
          <input type="text" value="${selected.id}" disabled />
        </label>
        <label>
          <span>Type</span>
          <input type="text" value="${escapeHtml(selected.type)}" disabled />
        </label>
        ${
          isSpinner
            ? ""
            : `
            <label>
              <span>X</span>
              <input type="number" data-field="x" value="${selectedX}" />
              ${this.fieldErrors.x ? `<small class="field-error">${escapeHtml(this.fieldErrors.x)}</small>` : ""}
            </label>
            <label>
              <span>Y</span>
              <input type="number" data-field="y" value="${selectedY}" />
              ${this.fieldErrors.y ? `<small class="field-error">${escapeHtml(this.fieldErrors.y)}</small>` : ""}
            </label>
          `
        }
        <label class="wide-field">
          <span>Time (ms)</span>
          <input type="number" data-field="time" value="${selected.time}" />
          ${this.fieldErrors.time ? `<small class="field-error">${escapeHtml(this.fieldErrors.time)}</small>` : ""}
        </label>
        ${
          isSpinner
            ? `
            <label class="wide-field">
              <span>End Time (ms)</span>
              <input type="number" data-field="endTime" value="${selected.endTime}" />
              ${this.fieldErrors.endTime ? `<small class="field-error">${escapeHtml(this.fieldErrors.endTime)}</small>` : ""}
            </label>
            <div class="inspector-readout wide-field">
              <span>Duration</span>
              <strong>${Math.max(0, selected.endTime - selected.time)} ms</strong>
            </div>
          `
            : ""
        }
        <div class="inspector-readout wide-field">
          <span>Formatted</span>
          <strong>${formatTimeMs(selected.time)}</strong>
        </div>
      </div>

      <div class="metrics-grid">
        <div><span>Baseline</span><strong>${baseline ? `${baselineX}, ${baselineY}` : "Added object"}</strong></div>
        <div><span>Position Delta</span><strong>${baseline ? `${formatSignedNumber(selectedX - baselineX)} px, ${formatSignedNumber(selectedY - baselineY)} px` : "new"}</strong></div>
        <div><span>Timing Delta</span><strong>${baseline ? `${formatSignedNumber(selected.time - baseline.time)} ms` : "new"}</strong></div>
        <div><span>Prev Gap</span><strong>${metrics?.previousGapMs ? `${Math.round(metrics.previousGapMs)} ms` : "—"}</strong></div>
        <div><span>Next Gap</span><strong>${metrics?.nextGapMs ? `${Math.round(metrics.nextGapMs)} ms` : "—"}</strong></div>
        <div><span>Prev Dist</span><strong>${metrics?.previousDistancePx ? `${Math.round(metrics.previousDistancePx)} px` : "—"}</strong></div>
        <div><span>Next Dist</span><strong>${metrics?.nextDistancePx ? `${Math.round(metrics.nextDistancePx)} px` : "—"}</strong></div>
        <div><span>Prev Speed</span><strong>${metrics?.previousCursorSpeed ? `${Math.round(metrics.previousCursorSpeed)} px/s` : "—"}</strong></div>
        <div><span>Next Speed</span><strong>${metrics?.nextCursorSpeed ? `${Math.round(metrics.nextCursorSpeed)} px/s` : "—"}</strong></div>
        <div><span>Nearest Beat</span><strong>${metrics?.nearestBeatTimeMs ? `${metrics.nearestBeatTimeMs} (Δ ${metrics.nearestBeatDeltaMs} ms)` : "—"}</strong></div>
        <div><span>Nearest Onset</span><strong>${metrics?.nearestOnsetTimeMs ? `${metrics.nearestOnsetTimeMs} (Δ ${metrics.nearestOnsetDeltaMs} ms)` : "—"}</strong></div>
        <div><span>Anchor</span><strong>${metrics?.selectedAnchor ?? "none"}</strong></div>
        <div><span>Timing Confidence</span><strong>${metrics?.timingConfidence ?? "low"}</strong></div>
        <div><span>Local Energy</span><strong>${typeof metrics?.localEnergy === "number" ? metrics.localEnergy.toFixed(2) : "—"}</strong></div>
      </div>

      <div class="panel-subheading">
        <h3>Current Issues (${issues.length})</h3>
      </div>
      <ul class="issue-list compact">
        ${
          issues.length > 0
            ? issues
                .map(
                  (issue) => `
                    <li class="issue-chip severity-${issue.severity}">
                      <strong>${escapeHtml(issue.code)}</strong>
                      <span>${escapeHtml(issue.message)}</span>
                    </li>
                  `,
                )
                .join("")
            : `<li class="panel-empty-copy">No live issues are currently attached to the selected object.</li>`
        }
      </ul>

      <div class="inspector-actions">
        <button type="button" class="editor-ghost-button" data-action="reset-position"${baseline ? "" : " disabled"}>Reset Position</button>
        <button type="button" class="editor-ghost-button" data-action="reset-timing"${baseline ? "" : " disabled"}>Reset Timing</button>
        <button type="button" class="editor-ghost-button" data-action="reset-object">Reset Object</button>
        <button type="button" class="editor-danger-button" data-action="delete-object">Delete Object</button>
        <button type="button" class="editor-secondary-button" data-action="play-from-here">Play From Here</button>
      </div>
    `;

    this.bindEvents(selectedX, selectedY);
  }

  private bindEvents(
    selectedX: number,
    selectedY: number,
  ): void {
    this.container
      .querySelectorAll<HTMLInputElement>("input[data-field]")
      .forEach((input) => {
        input.addEventListener("change", () => {
          const field = input.dataset.field as "x" | "y" | "time" | "endTime";
          const rawValue = Number(input.value);
          if (!Number.isFinite(rawValue)) {
            this.fieldErrors[field] = "Enter a finite numeric value.";
            this.render(this.controller.getState());
            return;
          }

          if (field === "x" || field === "y") {
            this.fieldErrors[field] = undefined;
            this.controller.updateSelectedPositionFromInspector(
              field === "x" ? rawValue : selectedX,
              field === "y" ? rawValue : selectedY,
            );
            return;
          }

          if (field === "endTime") {
            this.fieldErrors[field] = undefined;
            this.controller.updateSelectedEndTimeFromInspector(rawValue);
            return;
          }

          this.fieldErrors[field] = undefined;
          this.controller.updateSelectedTimeFromInspector(rawValue);
        });
      });

    this.container
      .querySelector<HTMLButtonElement>("[data-action='reset-position']")
      ?.addEventListener("click", () => {
        this.controller.resetSelectedPosition();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='reset-timing']")
      ?.addEventListener("click", () => {
        this.controller.resetSelectedTiming();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='reset-object']")
      ?.addEventListener("click", () => {
        this.controller.resetSelectedObject();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='delete-object']")
      ?.addEventListener("click", () => {
        this.controller.deleteSelectedObject();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='play-from-here']")
      ?.addEventListener("click", () => {
        this.controller.playFromSelectedObject(1600);
      });
  }
}
