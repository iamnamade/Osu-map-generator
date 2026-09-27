import Phaser from "phaser";

import { escapeHtml, formatTimeMs } from "../shared/format";
import {
  getProjectMapById,
  resolveRequestedProjectMap,
} from "../shared/mapCatalog";
import { EditorController } from "./EditorController";
import { EditorKeyboard } from "./EditorKeyboard";
import type { EditorRootState } from "./EditorState";
import { EditorStore } from "./EditorStore";
import { CandidateBrowserPanel } from "./panels/CandidateBrowserPanel";
import { DifficultyPanel } from "./panels/DifficultyPanel";
import { EvolutionPanel } from "./panels/EvolutionPanel";
import { ExportPanel } from "./panels/ExportPanel";
import { HistoryPanel } from "./panels/HistoryPanel";
import { HybridPanel } from "./panels/HybridPanel";
import { InspectorPanel } from "./panels/InspectorPanel";
import { MapLibraryPanel } from "./panels/MapLibraryPanel";
import { SettingsPanel } from "./panels/SettingsPanel";
import { ValidationPanel } from "./panels/ValidationPanel";
import { EditorScene } from "./playfield/EditorScene";
import { TimelineController } from "./timeline/TimelineController";
import "./styles/editor.css";

export class EditorApp {
  private readonly store = new EditorStore();
  private readonly controller = new EditorController(this.store);
  private readonly keyboard = new EditorKeyboard(this.controller);
  private readonly scene = new EditorScene();
  private phaserGame?: Phaser.Game;
  private timeline?: TimelineController;
  private libraryPanel?: MapLibraryPanel;
  private inspectorPanel?: InspectorPanel;
  private validationPanel?: ValidationPanel;
  private difficultyPanel?: DifficultyPanel;
  private evolutionPanel?: EvolutionPanel;
  private candidatesPanel?: CandidateBrowserPanel;
  private hybridPanel?: HybridPanel;
  private historyPanel?: HistoryPanel;
  private settingsPanel?: SettingsPanel;
  private exportPanel?: ExportPanel;
  private unsubscribe?: () => void;
  private readonly initialMapEntry =
    resolveRequestedProjectMap(new URLSearchParams(window.location.search)) ??
    getProjectMapById("champion-normal") ??
    getProjectMapById("champion-easy");

  constructor(private readonly root: HTMLElement) {}

  async start(): Promise<void> {
    this.renderShell();
    this.controller.bootstrap();
    this.keyboard.attach();
    this.mountPhaser();
    this.mountPanels();
    this.mountTimeline();
    this.bindToolbar();
    this.unsubscribe = this.store.subscribe((state) => {
      this.renderToolbar(state);
      this.renderStatusBar(state);
      this.renderTabs(state);
      this.renderDialogs(state);
    });

    if (this.store.getState().ui.modal?.kind !== "restore-session" && this.initialMapEntry) {
      await this.controller.loadCatalogMap(this.initialMapEntry);
    }
  }

  dispose(): void {
    this.unsubscribe?.();
    this.timeline?.dispose();
    this.libraryPanel?.dispose();
    this.inspectorPanel?.dispose();
    this.validationPanel?.dispose();
    this.difficultyPanel?.dispose();
    this.evolutionPanel?.dispose();
    this.candidatesPanel?.dispose();
    this.hybridPanel?.dispose();
    this.historyPanel?.dispose();
    this.settingsPanel?.dispose();
    this.exportPanel?.dispose();
    this.controller.dispose();
    this.keyboard.detach();
    this.phaserGame?.destroy(true);
  }

  private renderShell(): void {
    this.root.innerHTML = `
      <div class="editor-shell">
        <header class="editor-toolbar">
          <div class="toolbar-group">
            <a class="toolbar-back" href="/index.html">Back to Game</a>
            <div class="toolbar-map-meta">
              <strong id="editor-map-title">Loading...</strong>
              <span id="editor-map-subtitle">Beatmap Editor</span>
            </div>
          </div>

          <div class="toolbar-group">
            <button type="button" class="toolbar-button" data-toolbar="play">Play</button>
            <button type="button" class="toolbar-button" data-toolbar="pause">Pause</button>
            <button type="button" class="toolbar-button" data-toolbar="stop">Stop</button>
            <button type="button" class="toolbar-button" data-toolbar="restart">Restart</button>
          </div>

          <div class="toolbar-group toolbar-time-group">
            <strong id="editor-playhead-time">00:00.000</strong>
            <span id="editor-duration-time">00:00.000</span>
          </div>

          <div class="toolbar-group">
            <button type="button" class="toolbar-button" data-toolbar="undo">Undo</button>
            <button type="button" class="toolbar-button" data-toolbar="redo">Redo</button>
            <button type="button" class="toolbar-button" data-toolbar="select">Select</button>
            <button type="button" class="toolbar-button" data-toolbar="add-circle">Add Circle</button>
            <button type="button" class="toolbar-button" data-toolbar="delete">Delete</button>
          </div>

          <div class="toolbar-group">
            <label class="toolbar-select-wrap">
              <span>Snap</span>
              <select id="editor-snap-mode">
                <option value="off">Off</option>
                <option value="beat">Beat</option>
                <option value="onset">Onset</option>
                <option value="strongest-anchor">Strongest</option>
              </select>
            </label>
            <button type="button" class="toolbar-button" data-toolbar="baseline">Baseline</button>
            <button type="button" class="toolbar-button" data-toolbar="validation">Validate</button>
            <button type="button" class="toolbar-button" data-toolbar="shortcuts">Shortcuts</button>
            <div class="toolbar-export">
              <button type="button" class="toolbar-button toolbar-button--primary" data-toolbar="export">Export</button>
              <div id="editor-export-menu" class="toolbar-export-menu" hidden>
                <button type="button" data-export-menu="json">Export Project JSON</button>
                <button type="button" data-export-menu="osu">Export .osu Circle Map</button>
                <button type="button" data-export-menu="log">Export Edit Log</button>
                <button type="button" data-export-menu="project">Export Editor Project</button>
              </div>
            </div>
          </div>
        </header>

        <div class="editor-main">
          <aside class="editor-sidebar-left">
            <div id="editor-library-panel"></div>
          </aside>

          <main class="editor-center">
            <section class="editor-card playfield-card">
              <div class="panel-heading">
                <div>
                  <p class="panel-eyebrow">Playfield</p>
                  <h2>512 × 384 Logical Space</h2>
                </div>
                <span class="panel-badge" id="editor-baseline-badge">Baseline: On</span>
              </div>
              <div id="editor-playfield-host" class="editor-playfield-host"></div>
            </section>

            <section class="editor-card timeline-card">
              <div class="timeline-toolbar">
                <div class="timeline-tabs">
                  <button type="button" class="timeline-tab is-active">Timeline</button>
                  <button type="button" class="timeline-tab" disabled>Legend</button>
                </div>
                <div class="timeline-controls">
                  <span>Zoom</span>
                  <button type="button" class="toolbar-button" data-timeline="zoom-in">+</button>
                  <button type="button" class="toolbar-button" data-timeline="zoom-out">−</button>
                  <button type="button" class="toolbar-button" data-timeline="fit">Fit</button>
                </div>
              </div>
              <canvas id="editor-timeline-canvas" class="editor-timeline-canvas"></canvas>
            </section>
          </main>

          <aside class="editor-sidebar-right">
            <section class="editor-card right-panel-card">
              <div class="right-panel-tabs">
                <button type="button" data-tab="inspector" class="is-active">Inspector</button>
                <button type="button" data-tab="validation">Validation</button>
                <button type="button" data-tab="difficulty">Difficulty</button>
                <button type="button" data-tab="evolution">Evolution</button>
                <button type="button" data-tab="candidates">Candidates</button>
                <button type="button" data-tab="hybrid">Hybrid</button>
                <button type="button" data-tab="history">History</button>
                <button type="button" data-tab="export">Export</button>
                <button type="button" data-tab="settings">Settings</button>
              </div>
              <div id="editor-inspector-panel" class="right-panel-view"></div>
              <div id="editor-validation-panel" class="right-panel-view" hidden></div>
              <div id="editor-difficulty-panel" class="right-panel-view" hidden></div>
              <div id="editor-evolution-panel" class="right-panel-view" hidden></div>
              <div id="editor-candidates-panel" class="right-panel-view" hidden></div>
              <div id="editor-hybrid-panel" class="right-panel-view" hidden></div>
              <div id="editor-history-panel" class="right-panel-view" hidden></div>
              <div id="editor-export-panel" class="right-panel-view" hidden></div>
              <div id="editor-settings-panel" class="right-panel-view" hidden></div>
            </section>
          </aside>
        </div>

        <footer class="editor-status-bar">
          <span id="editor-status-mode">Select mode</span>
          <span id="editor-status-object">No object</span>
          <span id="editor-status-time">00:00.000</span>
          <span id="editor-status-snap">Snap: Beat</span>
          <span id="editor-status-issues">0 issues</span>
          <span id="editor-status-unsaved">Saved</span>
          <span id="editor-status-autosave">Autosave idle</span>
          <span id="editor-status-audio">Audio not loaded</span>
        </footer>

        <div id="editor-modal-root"></div>
      </div>
    `;
  }

  private mountPhaser(): void {
    this.phaserGame = new Phaser.Game({
      type: Phaser.AUTO,
      width: 512,
      height: 384,
      parent: "editor-playfield-host",
      backgroundColor: "#07101b",
      scale: {
        parent: "editor-playfield-host",
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
        width: 512,
        height: 384,
      },
      scene: [this.scene],
    });
    this.scene.bind(this.store, this.controller);
  }

  private mountPanels(): void {
    this.libraryPanel = new MapLibraryPanel(
      this.mustFind("#editor-library-panel"),
      this.controller,
      this.store,
    );
    this.inspectorPanel = new InspectorPanel(
      this.mustFind("#editor-inspector-panel"),
      this.controller,
      this.store,
    );
    this.validationPanel = new ValidationPanel(
      this.mustFind("#editor-validation-panel"),
      this.controller,
      this.store,
    );
    this.difficultyPanel = new DifficultyPanel(
      this.mustFind("#editor-difficulty-panel"),
      this.store,
    );
    this.evolutionPanel = new EvolutionPanel(
      this.mustFind("#editor-evolution-panel"),
      this.store,
      this.controller,
    );
    this.candidatesPanel = new CandidateBrowserPanel(
      this.mustFind("#editor-candidates-panel"),
      this.controller,
      this.store,
    );
    this.hybridPanel = new HybridPanel(
      this.mustFind("#editor-hybrid-panel"),
      this.controller,
      this.store,
    );
    this.historyPanel = new HistoryPanel(
      this.mustFind("#editor-history-panel"),
      this.store,
    );
    this.exportPanel = new ExportPanel(
      this.mustFind("#editor-export-panel"),
      this.controller,
      this.store,
    );
    this.settingsPanel = new SettingsPanel(
      this.mustFind("#editor-settings-panel"),
      this.controller,
      this.store,
    );
  }

  private mountTimeline(): void {
    const canvas = this.mustFind<HTMLCanvasElement>("#editor-timeline-canvas");
    this.timeline = new TimelineController(canvas, this.controller, this.store);
    this.timeline.attach();
  }

  private bindToolbar(): void {
    this.root.querySelectorAll<HTMLButtonElement>("[data-toolbar]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.toolbar;
        switch (action) {
          case "play":
            this.controller.togglePlayPause();
            break;
          case "pause":
            this.controller.togglePlayPause();
            break;
          case "stop":
            this.controller.stopPlayback();
            break;
          case "restart":
            this.controller.restartPlayback();
            break;
          case "undo":
            this.controller.undo();
            break;
          case "redo":
            this.controller.redo();
            break;
          case "select":
            this.controller.setMode("select");
            break;
          case "add-circle":
            this.controller.setMode("add-circle");
            break;
          case "delete":
            this.controller.deleteSelectedObject();
            break;
          case "baseline":
            this.controller.toggleBaselineOverlay();
            break;
          case "validation":
            this.controller.toggleValidation();
            break;
          case "shortcuts":
            this.controller.toggleShortcutHelp();
            break;
          case "export":
            this.controller.toggleExportMenu();
            break;
        }
      });
    });

    this.root
      .querySelectorAll<HTMLButtonElement>("[data-timeline]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const action = button.dataset.timeline;
          if (action === "zoom-in") {
            this.controller.zoomTimeline(0.8);
            return;
          }

          if (action === "zoom-out") {
            this.controller.zoomTimeline(1.25);
            return;
          }

          this.controller.fitTimeline();
        });
      });

    this.root
      .querySelectorAll<HTMLButtonElement>("[data-tab]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const tab = button.dataset.tab as EditorRootState["ui"]["activeRightTab"];
          this.controller.setActiveRightTab(tab);
        });
      });

    this.mustFind<HTMLSelectElement>("#editor-snap-mode").addEventListener(
      "change",
      (event) => {
        this.controller.setSnapMode(
          (event.currentTarget as HTMLSelectElement).value as never,
        );
      },
    );

    this.mustFind("#editor-export-menu")
      .querySelectorAll<HTMLButtonElement>("[data-export-menu]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const type = button.dataset.exportMenu;
          if (type === "json") {
            this.controller.exportCurrentMap();
          } else if (type === "osu") {
            this.controller.exportCurrentOsuMap();
          } else if (type === "log") {
            this.controller.exportCurrentEditLog();
          } else {
            this.controller.exportCurrentProject();
          }
          this.controller.toggleExportMenu(false);
        });
      });
  }

  private renderToolbar(state: EditorRootState): void {
    const title = this.mustFind("#editor-map-title");
    const subtitle = this.mustFind("#editor-map-subtitle");
    const playhead = this.mustFind("#editor-playhead-time");
    const duration = this.mustFind("#editor-duration-time");
    const snap = this.mustFind<HTMLSelectElement>("#editor-snap-mode");
    const exportMenu = this.mustFind<HTMLElement>("#editor-export-menu");
    const baselineBadge = this.mustFind("#editor-baseline-badge");

    title.textContent = state.session.workingMap?.title ?? "No map loaded";
    subtitle.textContent = state.session.source
      ? `${state.session.source.label} · ${state.session.source.kind}`
      : "Beatmap Editor";
    playhead.textContent = formatTimeMs(state.session.playheadMs);
    duration.textContent = formatTimeMs(state.session.audioDurationMs);
    snap.value = state.ui.snapMode;
    baselineBadge.textContent = state.ui.baselineOverlayEnabled
      ? "Baseline: On"
      : "Baseline: Off";
    exportMenu.hidden = !state.ui.exportMenuOpen;
  }

  private renderStatusBar(state: EditorRootState): void {
    this.mustFind("#editor-status-mode").textContent =
      state.session.statusText.mode === "add-circle"
        ? "Add Circle"
        : "Select Mode";
    this.mustFind("#editor-status-object").textContent =
      state.session.statusText.selectedObjectLabel;
    this.mustFind("#editor-status-time").textContent =
      state.session.statusText.playheadLabel;
    this.mustFind("#editor-status-snap").textContent =
      state.session.statusText.snapLabel;
    this.mustFind("#editor-status-issues").textContent =
      state.session.statusText.issueLabel;
    this.mustFind("#editor-status-unsaved").textContent =
      state.session.statusText.unsavedLabel;
    this.mustFind("#editor-status-autosave").textContent =
      state.session.statusText.autosaveLabel;
    this.mustFind("#editor-status-audio").textContent =
      state.session.statusText.audioLabel;
  }

  private renderTabs(state: EditorRootState): void {
    this.root.querySelectorAll<HTMLElement>(".right-panel-view").forEach((view) => {
      view.hidden = true;
    });
    this.root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === state.ui.activeRightTab);
    });

    const selector = `#editor-${state.ui.activeRightTab}-panel`;
    const target = this.root.querySelector<HTMLElement>(selector);
    if (target) {
      target.hidden = false;
    }
  }

  private renderDialogs(state: EditorRootState): void {
    const modalRoot = this.mustFind("#editor-modal-root");
    const modal = state.ui.modal;
    const shortcutHelpOpen = state.ui.shortcutHelpOpen;

    if (!modal && !shortcutHelpOpen) {
      modalRoot.innerHTML = "";
      return;
    }

    modalRoot.innerHTML = `
      <div class="modal-backdrop">
        ${
          modal
            ? `
              <div class="modal-card">
                <h2>${escapeHtml(modal.title)}</h2>
                <p>${escapeHtml(modal.message)}</p>
                <div class="modal-actions">
                  ${
                    modal.kind === "restore-session"
                      ? `
                        <button type="button" class="editor-primary-button" data-modal="restore">Restore Session</button>
                        <button type="button" class="editor-ghost-button" data-modal="discard">Discard Session</button>
                      `
                      :                    modal.kind === "confirm-reset-map"
                      ? `
                        <button type="button" class="editor-primary-button" data-modal="confirm-reset">Reset Map</button>
                        <button type="button" class="editor-ghost-button" data-modal="close">Cancel</button>
                      `
                      : modal.kind === "confirm-promote"
                        ? `
                          <button type="button" class="editor-primary-button" data-modal="confirm-promote">Promote to Champion</button>
                          <button type="button" class="editor-ghost-button" data-modal="close">Cancel</button>
                        `
                        : `
                          <button type="button" class="editor-primary-button" data-modal="close">OK</button>
                        `
                  }
                </div>
              </div>
            `
            : ""
        }
        ${
          shortcutHelpOpen
            ? `
              <div class="modal-card shortcut-card">
                <h2>Keyboard Shortcuts</h2>
                <ul class="shortcut-list">
                  <li><strong>Space</strong><span>Play / Pause</span></li>
                  <li><strong>S</strong><span>Select mode</span></li>
                  <li><strong>A</strong><span>Add Circle mode</span></li>
                  <li><strong>Delete / Backspace</strong><span>Delete selected object</span></li>
                  <li><strong>Ctrl/Cmd + Z</strong><span>Undo</span></li>
                  <li><strong>Ctrl/Cmd + Y</strong><span>Redo</span></li>
                  <li><strong>Ctrl/Cmd + Shift + Z</strong><span>Redo</span></li>
                  <li><strong>Arrow Keys</strong><span>Move selected object by 1 px</span></li>
                  <li><strong>Shift + Arrows</strong><span>Move selected object by 10 px</span></li>
                  <li><strong>Home</strong><span>Seek to song start</span></li>
                  <li><strong>Escape</strong><span>Cancel tool / clear selection</span></li>
                  <li><strong>+</strong><span>Zoom timeline in</span></li>
                  <li><strong>-</strong><span>Zoom timeline out</span></li>
                  <li><strong>F</strong><span>Fit timeline</span></li>
                  <li><strong>B</strong><span>Toggle baseline overlay</span></li>
                </ul>
                <div class="modal-actions">
                  <button type="button" class="editor-primary-button" data-modal="close-shortcuts">Close</button>
                </div>
              </div>
            `
            : ""
        }
      </div>
    `;

    modalRoot.querySelectorAll<HTMLButtonElement>("[data-modal]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.modal;
        if (action === "restore") {
          void this.controller.restoreAutosaveIfAvailable().then(async () => {
            if (!this.store.getState().session.workingMap && this.initialMapEntry) {
              await this.controller.loadCatalogMap(this.initialMapEntry);
            }
          });
          return;
        }

        if (action === "discard") {
          this.controller.discardAutosave();
          if (this.initialMapEntry) {
            void this.controller.loadCatalogMap(this.initialMapEntry);
          }
          return;
        }

        if (action === "confirm-reset") {
          this.controller.resetMapToBaseline();
          return;
        }

        if (action === "confirm-promote") {
          void this.controller.confirmPromoteCandidate();
          return;
        }

        if (action === "close-shortcuts") {
          this.controller.toggleShortcutHelp(false);
          return;
        }

        this.controller.closeModal();
      });
    });
  }

  private mustFind<T extends Element = HTMLElement>(selector: string): T {
    const element = this.root.querySelector<T>(selector);
    if (!element) {
      throw new Error(`Missing editor element: ${selector}`);
    }

    return element;
  }
}
