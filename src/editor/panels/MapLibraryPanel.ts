import type { ValidationReport } from "../../game/types";
import { escapeHtml, formatTimeMs } from "../../shared/format";
import {
  getProjectMapCatalog,
  groupProjectMaps,
  initializeProjectMapCatalog,
} from "../../shared/mapCatalog";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class MapLibraryPanel {
  private unsubscribe?: () => void;

  constructor(
    private readonly container: HTMLElement,
    private readonly controller: EditorController,
    private readonly store: EditorStore,
  ) {
    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  dispose(): void {
    this.unsubscribe?.();
  }

  private render(state: EditorRootState): void {
    const groups = groupProjectMaps();
    const source = state.session.source;
    const activePath = source?.path;
    const map = state.session.workingMap;
    const pythonReport = state.session.pythonReport;
    const comparison = state.session.comparisonSummary;

    this.container.innerHTML = `
      <section class="editor-card library-card">
        <div class="panel-heading">
          <div>
            <p class="panel-eyebrow">Map Library</p>
            <h2>Available Maps</h2>
          </div>
          <button type="button" class="editor-icon-button" data-action="refresh" title="Refresh catalog and reload selected map">Reload</button>
        </div>
        <div class="library-groups">
          ${groups
            .map(
              (group) => `
                <section class="library-group">
                  <h3>${escapeHtml(group.label)}</h3>
                  <div class="library-item-list">
                    ${group.items
                      .map(
                        (entry) => `
                          <button
                            type="button"
                            class="library-item${entry.path === activePath ? " is-active" : ""}"
                            data-map-path="${entry.path}"
                          >
                            <span>${escapeHtml(entry.path.split("/").pop() ?? entry.label)}</span>
                            <small>${escapeHtml(entry.label)}</small>
                          </button>
                        `,
                      )
                      .join("")}
                  </div>
                </section>
              `,
            )
            .join("")}
        </div>
        <div class="library-actions">
          <button type="button" class="editor-secondary-button" data-action="import-project-json">Import Project JSON</button>
          <button type="button" class="editor-secondary-button" data-action="import-osu">Import Circle-only .osu</button>
          <button type="button" class="editor-secondary-button" data-action="import-editor-project">Import Editor Project</button>
          <label class="panel-empty-copy">
            <input id="editor-osu-skip-unsupported" type="checkbox" />
            Skip unsupported sliders and spinners while importing .osu
          </label>
          <input id="editor-project-json-import" type="file" accept=".json,application/json" hidden />
          <input id="editor-osu-import" type="file" accept=".osu,text/plain" hidden />
          <input id="editor-project-session-import" type="file" accept=".json,application/json" hidden />
        </div>
      </section>

      <section class="editor-card library-card">
        <div class="panel-heading">
          <div>
            <p class="panel-eyebrow">Map Info</p>
            <h2>${escapeHtml(map?.title ?? "No map loaded")}</h2>
          </div>
        </div>
        ${
          map
            ? `
              <dl class="info-grid">
                <div><dt>Artist</dt><dd>${escapeHtml(map.artist)}</dd></div>
                <div><dt>Audio</dt><dd>${escapeHtml(map.audio)}</dd></div>
                <div><dt>Difficulty</dt><dd>${escapeHtml(source?.difficulty ?? "custom")}</dd></div>
                <div><dt>Objects</dt><dd>${map.objects.length}</dd></div>
                <div><dt>Duration</dt><dd>${formatTimeMs(state.session.audioDurationMs)}</dd></div>
                <div><dt>Approach</dt><dd>${map.approachTime} ms</dd></div>
                <div><dt>Circle Size</dt><dd>${map.circleRadius}</dd></div>
                <div><dt>Source</dt><dd>${escapeHtml(source?.kind ?? "unknown")}</dd></div>
              </dl>
            `
            : `<p class="panel-empty-copy">Load a project map, an editor project, or a circle-only .osu beatmap to begin editing.</p>`
        }
      </section>

      <section class="editor-card library-card">
        <div class="panel-heading">
          <div>
            <p class="panel-eyebrow">Baseline Python Report</p>
            <h2>Saved Authoritative Score</h2>
          </div>
        </div>
        ${renderPythonReportSummary(pythonReport)}
      </section>

      <section class="editor-card library-card">
        <div class="panel-heading">
          <div>
            <p class="panel-eyebrow">Comparison</p>
            <h2>Baseline vs Working Copy</h2>
          </div>
        </div>
        <div class="summary-grid">
          <div><span>Unchanged</span><strong>${comparison.unchanged}</strong></div>
          <div><span>Moved</span><strong>${comparison.moved}</strong></div>
          <div><span>Retimed</span><strong>${comparison.retimed}</strong></div>
          <div><span>Moved+Retimed</span><strong>${comparison.movedAndRetimed}</strong></div>
          <div><span>Added</span><strong>${comparison.added}</strong></div>
          <div><span>Removed</span><strong>${comparison.removed}</strong></div>
        </div>
      </section>
    `;

    this.bindEvents();
  }

  private bindEvents(): void {
    this.container
      .querySelectorAll<HTMLButtonElement>("[data-map-path]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const entry = getProjectMapCatalog().find(
            (item) => item.path === button.dataset.mapPath,
          );
          if (!entry) {
            return;
          }

          void this.controller.loadCatalogMap(entry);
        });
      });

    this.container
      .querySelector<HTMLButtonElement>("[data-action='refresh']")
      ?.addEventListener("click", () => {
        void initializeProjectMapCatalog(true).then(() => {
          this.render(this.store.getState());

          const sourcePath = this.store.getState().session.source?.path;
          const entry = getProjectMapCatalog().find(
            (item) => item.path === sourcePath,
          );
          if (!entry) {
            return;
          }

          void this.controller.loadCatalogMap(entry);
        });
      });

    const projectJsonInput = this.container.querySelector<HTMLInputElement>(
      "#editor-project-json-import",
    );
    const osuInput = this.container.querySelector<HTMLInputElement>(
      "#editor-osu-import",
    );
    const editorProjectInput = this.container.querySelector<HTMLInputElement>(
      "#editor-project-session-import",
    );
    const skipUnsupportedInput = this.container.querySelector<HTMLInputElement>(
      "#editor-osu-skip-unsupported",
    );

    this.container
      .querySelector<HTMLButtonElement>("[data-action='import-project-json']")
      ?.addEventListener("click", () => {
        projectJsonInput?.click();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='import-osu']")
      ?.addEventListener("click", () => {
        osuInput?.click();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-action='import-editor-project']")
      ?.addEventListener("click", () => {
        editorProjectInput?.click();
      });

    projectJsonInput?.addEventListener("change", () => {
      const file = projectJsonInput.files?.[0];
      if (!file) {
        return;
      }

      void this.controller.importProjectJsonFile(file);
      projectJsonInput.value = "";
    });

    osuInput?.addEventListener("change", () => {
      const file = osuInput.files?.[0];
      if (!file) {
        return;
      }

      void this.controller.importOsuFile(
        file,
        skipUnsupportedInput?.checked ? "skip" : "reject",
      );
      osuInput.value = "";
    });

    editorProjectInput?.addEventListener("change", () => {
      const file = editorProjectInput.files?.[0];
      if (!file) {
        return;
      }

      void this.controller.importEditorProjectFile(file);
      editorProjectInput.value = "";
    });
  }
}

function renderPythonReportSummary(report?: ValidationReport): string {
  if (!report) {
    return `<p class="panel-empty-copy">No saved Python report was available for the current map source.</p>`;
  }

  return `
    <div class="report-summary">
      <div class="report-score">
        <strong>${report.scores.overall.toFixed(1)} / 100</strong>
        <span>${escapeHtml(report.interpretation)}</span>
      </div>
      <div class="summary-grid">
        <div><span>Critical</span><strong>${report.summary.critical}</strong></div>
        <div><span>Errors</span><strong>${report.summary.errors}</strong></div>
        <div><span>Warnings</span><strong>${report.summary.warnings}</strong></div>
        <div><span>Info</span><strong>${report.summary.info}</strong></div>
      </div>
    </div>
  `;
}
