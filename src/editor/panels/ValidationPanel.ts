import { escapeHtml, formatTimeMs } from "../../shared/format";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class ValidationPanel {
  private unsubscribe?: () => void;
  private severityFilter = "all";
  private categoryFilter = "all";

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
    const summary = state.session.liveValidation.summary;
    const issues = state.session.liveValidation.issues.filter((issue) => {
      if (this.severityFilter !== "all" && issue.severity !== this.severityFilter) {
        return false;
      }

      if (this.categoryFilter !== "all" && issue.category !== this.categoryFilter) {
        return false;
      }

      return true;
    });

    this.container.innerHTML = `
      <section class="validation-summary-grid">
        <div><span>Total</span><strong>${summary.total}</strong></div>
        <div><span>Critical</span><strong>${summary.critical}</strong></div>
        <div><span>Errors</span><strong>${summary.errors}</strong></div>
        <div><span>Warnings</span><strong>${summary.warnings}</strong></div>
        <div><span>Info</span><strong>${summary.info}</strong></div>
      </section>

      <section class="saved-report-card">
        <div class="panel-subheading">
          <h3>Saved Python Report</h3>
        </div>
        ${
          state.session.pythonReport
            ? `
              <p class="saved-report-copy">
                Baseline Python Score: <strong>${state.session.pythonReport.scores.overall.toFixed(1)}</strong>
                &middot; ${escapeHtml(state.session.pythonReport.interpretation)}
              </p>
            `
            : `<p class="panel-empty-copy">No saved Python report is attached to this source map.</p>`
        }
      </section>

      <section class="panel-filters">
        <label>
          <span>Severity</span>
          <select data-filter="severity">
            <option value="all"${this.severityFilter === "all" ? " selected" : ""}>All</option>
            <option value="critical"${this.severityFilter === "critical" ? " selected" : ""}>Critical</option>
            <option value="error"${this.severityFilter === "error" ? " selected" : ""}>Error</option>
            <option value="warning"${this.severityFilter === "warning" ? " selected" : ""}>Warning</option>
            <option value="info"${this.severityFilter === "info" ? " selected" : ""}>Info</option>
          </select>
        </label>
        <label>
          <span>Category</span>
          <select data-filter="category">
            <option value="all"${this.categoryFilter === "all" ? " selected" : ""}>All</option>
            <option value="structural"${this.categoryFilter === "structural" ? " selected" : ""}>Structural</option>
            <option value="timing"${this.categoryFilter === "timing" ? " selected" : ""}>Timing</option>
            <option value="movement"${this.categoryFilter === "movement" ? " selected" : ""}>Movement</option>
            <option value="readability"${this.categoryFilter === "readability" ? " selected" : ""}>Readability</option>
          </select>
        </label>
      </section>

      <section class="panel-subheading">
        <h3>Current Live Editor Checks</h3>
      </section>
      <ul class="issue-list">
        ${
          issues.length > 0
            ? issues
                .map(
                  (issue) => `
                    <li class="issue-list-item severity-${issue.severity}" data-issue-id="${issue.id}">
                      <div>
                        <strong>${escapeHtml(issue.code)}</strong>
                        <p>${escapeHtml(issue.message)}</p>
                        <small>${escapeHtml(issue.category)}${typeof issue.timeMs === "number" ? ` · ${formatTimeMs(issue.timeMs)}` : ""}</small>
                      </div>
                    </li>
                  `,
                )
                .join("")
            : `<li class="panel-empty-copy">No issues match the current filters.</li>`
        }
      </ul>
    `;

    this.bindEvents();
  }

  private bindEvents(): void {
    this.container
      .querySelector<HTMLSelectElement>("select[data-filter='severity']")
      ?.addEventListener("change", (event) => {
        this.severityFilter = (event.currentTarget as HTMLSelectElement).value;
        this.render(this.controller.getState());
      });
    this.container
      .querySelector<HTMLSelectElement>("select[data-filter='category']")
      ?.addEventListener("change", (event) => {
        this.categoryFilter = (event.currentTarget as HTMLSelectElement).value;
        this.render(this.controller.getState());
      });
    this.container
      .querySelectorAll<HTMLElement>("[data-issue-id]")
      .forEach((item) => {
        item.addEventListener("click", () => {
          const issueId = item.dataset.issueId;
          if (issueId) {
            this.controller.jumpToIssue(issueId);
          }
        });
      });
  }
}
