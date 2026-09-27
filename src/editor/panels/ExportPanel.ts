import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class ExportPanel {
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
    const source = state.session.source;

    this.container.innerHTML = `
      <div class="panel-subheading">
        <h3>Browser Export</h3>
      </div>
      <p class="panel-empty-copy">
        Downloads stay local to the browser. They do not overwrite files inside the project workspace.
      </p>
      <div class="export-actions">
        <button type="button" class="editor-primary-button" data-export="json">Export Project JSON</button>
        <button type="button" class="editor-secondary-button" data-export="osu">Export .osu Circle Map</button>
        <button type="button" class="editor-secondary-button" data-export="log">Export Edit Log</button>
        <button type="button" class="editor-ghost-button" data-export="project">Export Editor Project</button>
      </div>
      <div class="export-note">
        <strong>Authoritative workflow</strong>
        <p>Browser export is convenient for local iteration. Python remains authoritative for validation reports, CLI import/export, and .osz packaging.</p>
        ${
          source?.path
            ? `
              <code>python -m tools.map_generator.cli validate --map public/maps/edited/${source.path.split("/").pop()?.replace(".json", "-edited.json")} --analysis public/analysis/test-song-analysis.json --difficulty ${source.difficulty ?? "normal"} --output public/reports/edited/${source.path.split("/").pop()?.replace(".json", "-edited-report.json")}</code>
              <code>python -m tools.map_generator.cli export-osu --map public/maps/edited/${source.path.split("/").pop()?.replace(".json", "-edited.json")} --analysis public/analysis/test-song-analysis.json --output public/exports/osu/${source.path.split("/").pop()?.replace(".json", ".osu")}</code>
            `
            : ""
        }
      </div>
    `;

    this.bindEvents();
  }

  private bindEvents(): void {
    this.container
      .querySelector<HTMLButtonElement>("[data-export='json']")
      ?.addEventListener("click", () => {
        this.controller.exportCurrentMap();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-export='osu']")
      ?.addEventListener("click", () => {
        this.controller.exportCurrentOsuMap();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-export='log']")
      ?.addEventListener("click", () => {
        this.controller.exportCurrentEditLog();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-export='project']")
      ?.addEventListener("click", () => {
        this.controller.exportCurrentProject();
      });
  }
}
