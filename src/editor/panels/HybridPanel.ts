import { escapeHtml, formatTimeMs } from "../../shared/format";
import {
  buildHybridSourceSequence,
  countHybridCandidateSwitches,
} from "../../shared/sectionData";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class HybridPanel {
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
    const sectionAnalysis = state.session.sectionAnalysis;
    const hybridAssembly = state.session.hybridAssembly;
    const selectedSection = state.session.selectedSection;
    const lockedSectionIds = new Set(state.ui.lockedSectionIds);

    if (!sectionAnalysis) {
      this.container.innerHTML = `
        <section class="panel-subheading">
          <h3>Section Track</h3>
        </section>
        <p class="panel-empty-copy">Section analysis is not available for the current map source.</p>
      `;
      return;
    }

    const selectedHybridSection = hybridAssembly?.sections.find(
      (section) => section.sectionId === selectedSection?.id,
    );
    const previousTransition = selectedSection
      ? hybridAssembly?.transitions.find(
          (transition) => transition.toSectionId === selectedSection.id,
        )
      : undefined;
    const nextTransition = selectedSection
      ? hybridAssembly?.transitions.find(
          (transition) => transition.fromSectionId === selectedSection.id,
        )
      : undefined;

    this.container.innerHTML = `
      ${
        hybridAssembly
          ? `
            <section class="validation-summary-grid">
              <div><span>Champion</span><strong>${formatScore(hybridAssembly.promotion.championQuality)}</strong></div>
              <div><span>Hybrid</span><strong>${hybridAssembly.scores.overallHybridScore.toFixed(1)}</strong></div>
              <div><span>Python</span><strong>${hybridAssembly.scores.finalPythonQuality.toFixed(1)}</strong></div>
              <div><span>Sections</span><strong>${hybridAssembly.sections.length}</strong></div>
              <div><span>Sources Used</span><strong>${Object.keys(hybridAssembly.sourceUsage).length}</strong></div>
              <div><span>Switches</span><strong>${countHybridCandidateSwitches(hybridAssembly.sections)}</strong></div>
              <div><span>Corrections</span><strong>${hybridAssembly.corrections.accepted ?? 0}</strong></div>
              <div><span>Unsafe Left</span><strong>${hybridAssembly.corrections.unsafeTransitionsRemaining ?? 0}</strong></div>
            </section>

            <section class="saved-report-card">
              <div class="panel-subheading">
                <h3>Promotion Status</h3>
              </div>
              <p class="saved-report-copy">
                <strong>${hybridAssembly.promotion.promoted ? "Promoted" : "Not Promoted"}</strong>
                &middot; ${escapeHtml(hybridAssembly.promotion.reason)}
              </p>
              <p class="saved-report-copy">${escapeHtml(buildHybridSourceSequence(hybridAssembly.sections))}</p>
            </section>
          `
          : `
            <section class="saved-report-card">
              <div class="panel-subheading">
                <h3>Hybrid Comparison</h3>
              </div>
              <p class="panel-empty-copy">Hybrid assembly data is not available for this difficulty yet.</p>
            </section>
          `
      }

      <section class="saved-report-card">
        <div class="panel-subheading">
          <h3>Selected Section</h3>
        </div>
        ${
          selectedSection
            ? `
              <div class="summary-grid">
                <div><span>Label</span><strong>${escapeHtml(selectedSection.label)}</strong></div>
                <div><span>Range</span><strong>${formatTimeMs(selectedSection.startMs)} - ${formatTimeMs(selectedSection.endMs)}</strong></div>
                <div><span>Confidence</span><strong>${selectedSection.confidence.toFixed(2)}</strong></div>
                <div><span>Local Lock</span><strong>${lockedSectionIds.has(selectedSection.id) ? "Locked" : "Unlocked"}</strong></div>
                <div><span>Energy</span><strong>${selectedSection.averageEnergy.toFixed(2)}</strong></div>
                <div><span>Beat Density</span><strong>${selectedSection.beatDensity.toFixed(2)}</strong></div>
                <div><span>Onset Density</span><strong>${selectedSection.onsetDensity.toFixed(2)}</strong></div>
                <div><span>Rhythm Complexity</span><strong>${selectedSection.rhythmComplexity.toFixed(2)}</strong></div>
                <div><span>Source Candidate</span><strong>${selectedHybridSection ? `C${selectedHybridSection.sourceCandidate}` : "n/a"}</strong></div>
                <div><span>Section Score</span><strong>${selectedHybridSection ? selectedHybridSection.sectionScore.toFixed(1) : "n/a"}</strong></div>
                <div><span>Prev Transition</span><strong>${previousTransition ? `${previousTransition.classification} (${previousTransition.score.toFixed(1)})` : "Start"}</strong></div>
                <div><span>Next Transition</span><strong>${nextTransition ? `${nextTransition.classification} (${nextTransition.score.toFixed(1)})` : "End"}</strong></div>
              </div>

              <div class="export-actions">
                <button type="button" class="editor-secondary-button" data-section-action="seek">Seek</button>
                <button type="button" class="editor-secondary-button" data-section-action="play">Play</button>
                <button type="button" class="editor-secondary-button" data-section-action="loop">${state.ui.loopSectionId === selectedSection.id ? "Stop Loop" : "Loop"}</button>
                <button type="button" class="editor-secondary-button" data-section-action="zoom">Zoom</button>
                <button type="button" class="editor-secondary-button" data-section-action="lock">${lockedSectionIds.has(selectedSection.id) ? "Unlock" : "Lock"}</button>
              </div>

              ${
                selectedHybridSection
                  ? `
                    <div class="export-note">
                      <p><strong>Selection reason</strong></p>
                      <p>${escapeHtml(selectedHybridSection.selectionReason)}</p>
                    </div>
                  `
                  : ""
              }

              <ul class="issue-list">
                ${
                  selectedHybridSection && selectedHybridSection.issues.length > 0
                    ? selectedHybridSection.issues
                        .map(
                          (issue) => `
                            <li class="issue-list-item">
                              <div>
                                <strong>${escapeHtml(issue)}</strong>
                                <small>Section-local hybrid issue</small>
                              </div>
                            </li>
                          `,
                        )
                        .join("")
                    : `<li class="panel-empty-copy">No hybrid section issues were recorded for the current selection.</li>`
                }
              </ul>
            `
            : `
              <p class="panel-empty-copy">Select a section from the timeline to inspect its metrics, hybrid source, and transition status.</p>
            `
        }
      </section>
    `;

    this.bindEvents(selectedSection?.id);
  }

  private bindEvents(sectionId?: number): void {
    this.container
      .querySelector<HTMLButtonElement>("[data-section-action='seek']")
      ?.addEventListener("click", () => {
        this.controller.seekToSectionStart(sectionId);
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-section-action='play']")
      ?.addEventListener("click", () => {
        this.controller.playSection(sectionId);
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-section-action='loop']")
      ?.addEventListener("click", () => {
        this.controller.toggleSectionLoop(sectionId);
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-section-action='zoom']")
      ?.addEventListener("click", () => {
        this.controller.zoomToSection(sectionId);
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-section-action='lock']")
      ?.addEventListener("click", () => {
        this.controller.toggleSectionLock(sectionId);
      });
  }
}

function formatScore(value: number | null): string {
  return typeof value === "number" ? value.toFixed(1) : "n/a";
}
