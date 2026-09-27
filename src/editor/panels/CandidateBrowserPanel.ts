import { escapeHtml, formatTimeMs } from "../../shared/format";
import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";
import type {
  CandidateBrowserEntry,
  CandidateDetailBundle,
  CandidateFilters,
  CandidateRebalanceDetail,
  CandidateReplayDetail,
  CandidateSectionComparison,
  CandidateSortKey,
} from "../candidates/candidateModels";

import {
  filterCandidateEntries,
  findCandidateEntry,
  formatCandidatePercent,
  formatCandidateScore,
  sortCandidateEntries,
} from "../candidates/candidateModels";

export class CandidateBrowserPanel {
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
    const candidates = state.candidates;

    if (candidates.entries.length === 0) {
      this.container.innerHTML = `
        <section class="panel-subheading">
          <h3>Candidate Browser</h3>
        </section>
        <p class="panel-empty-copy">
          No evolution candidates are available for the current map. Open a
          champion or evolution candidate so the browser can load its ranking.
        </p>
      `;
      return;
    }

    if (candidates.comparisonEnabled) {
      this.renderComparison(state);
      return;
    }

    const selected = findCandidateEntry(
      candidates.entries,
      candidates.selectedCandidateIndex,
    );
    if (selected) {
      this.renderDetail(state, selected);
      return;
    }

    this.renderBrowser(state);
  }

  private renderBrowser(state: EditorRootState): void {
    const candidates = state.candidates;
    const visible = sortCandidateEntries(
      filterCandidateEntries(candidates.entries, candidates.filters),
      candidates.sort,
    );
    const championIndex = candidates.championCandidateIndex;

    this.container.innerHTML = `
      <section class="panel-subheading">
        <h3>Candidate Browser</h3>
        <span class="candidate-count-badge">${candidates.entries.length} candidates</span>
      </section>

      <section class="candidate-filter-card">
        ${renderFilters(candidates.filters, candidates.sort)}
      </section>

      <div class="candidate-list">
        ${visible
          .map(
            (entry) => `
              <article class="candidate-card${entry.champion ? " is-champion" : ""}">
                <button type="button" class="candidate-card-main" data-candidate-select="${entry.candidateIndex}">
                  <div class="candidate-card-head">
                    <span class="candidate-rank">#${entry.rank}</span>
                    <strong>Candidate ${String(entry.candidateIndex).padStart(3, "0")}</strong>
                    <span class="candidate-badge candidate-badge--stars">${entry.stars.toFixed(2)}★</span>
                    ${entry.champion ? `<span class="candidate-badge candidate-badge--champion">Champion</span>` : ""}
                  </div>
                  <div class="candidate-card-meta">
                    <span>${escapeHtml(entry.difficulty)}</span>
                    <span>seed ${entry.candidateSeed}</span>
                    <span class="${validationBadgeClass(entry)}">${escapeHtml(entry.validationStatus)}</span>
                  </div>
                  <div class="candidate-card-scores">
                    <div><span>Final</span><strong>${formatCandidateScore(entry.finalScore)}</strong></div>
                    <div><span>Replay</span><strong>${formatCandidateScore(entry.replayScore)}</strong></div>
                    <div><span>Acc</span><strong>${formatCandidatePercent(entry.predictedAccuracy)}</strong></div>
                    <div><span>Misses</span><strong>${formatCandidateScore(entry.expectedMisses)}</strong></div>
                    <div><span>Rhythm</span><strong>${formatCandidateScore(entry.rhythmScore)}</strong></div>
                    <div><span>Pattern</span><strong>${formatCandidateScore(entry.patternScore)}</strong></div>
                    <div><span>Reading</span><strong>${formatCandidateScore(entry.readingScore)}</strong></div>
                    <div><span>Flow</span><strong>${formatCandidateScore(entry.flowScore)}</strong></div>
                  </div>
                </button>
                <div class="candidate-card-actions">
                  <button type="button" class="editor-ghost-button" data-candidate-open="${entry.candidateIndex}">Open</button>
                  <button type="button" class="editor-ghost-button" data-candidate-compare="${entry.candidateIndex}">Compare…</button>
                  <button type="button" class="editor-primary-button" data-candidate-promote="${entry.candidateIndex}" ${entry.candidateIndex === championIndex ? "disabled" : ""}>Promote</button>
                </div>
              </article>
            `,
          )
          .join("")}
      </div>

      ${renderChampionHistory(state)}
    `;

    this.bindBrowserEvents();
  }

  private renderDetail(state: EditorRootState, entry: CandidateBrowserEntry): void {
    const candidates = state.candidates;
    const detail = candidates.details[entry.candidateIndex];
    const noteKey = `${candidates.workspaceKey}:candidate-${String(entry.candidateIndex).padStart(3, "0")}`;
    const note = candidates.notes[noteKey] ?? "";
    const others = candidates.entries.filter(
      (item) => item.candidateIndex !== entry.candidateIndex,
    );
    const isChampion =
      entry.candidateIndex === candidates.championCandidateIndex;

    this.container.innerHTML = `
      <section class="panel-subheading">
        <h3>Candidate ${String(entry.candidateIndex).padStart(3, "0")}</h3>
        <button type="button" class="editor-ghost-button candidate-back-button" data-candidate-back>Back</button>
      </section>

      <section class="candidate-detail-hero${isChampion ? " is-champion" : ""}">
        <div class="candidate-card-head">
          <span class="candidate-rank">#${entry.rank}</span>
          <strong>Final ${formatCandidateScore(entry.finalScore)}</strong>
          <span class="candidate-badge candidate-badge--stars">${entry.stars.toFixed(2)}★</span>
          ${isChampion ? `<span class="candidate-badge candidate-badge--champion">Champion</span>` : ""}
        </div>
        <p class="candidate-detail-sub">
          ${escapeHtml(entry.difficulty)} &middot; seed ${entry.candidateSeed} &middot;
          <span class="${validationBadgeClass(entry)}">${escapeHtml(entry.validationStatus)}</span>
        </p>
      </section>

      <div class="candidate-detail-grid">
        <div><span>Difficulty</span><strong>${formatCandidateScore(entry.difficultyScore)}</strong></div>
        <div><span>Rhythm</span><strong>${formatCandidateScore(entry.rhythmScore)}</strong></div>
        <div><span>Pattern</span><strong>${formatCandidateScore(entry.patternScore)}</strong></div>
        <div><span>Reading</span><strong>${formatCandidateScore(entry.readingScore)}</strong></div>
        <div><span>Flow</span><strong>${formatCandidateScore(entry.flowScore)}</strong></div>
        <div><span>Replay</span><strong>${formatCandidateScore(entry.replayScore)}</strong></div>
        <div><span>Accuracy</span><strong>${formatCandidatePercent(entry.predictedAccuracy)}</strong></div>
        <div><span>Misses</span><strong>${formatCandidateScore(entry.expectedMisses)}</strong></div>
        <div><span>Combo</span><strong>${formatCandidatePercent(entry.expectedComboPct)}</strong></div>
        <div><span>Fatigue</span><strong>${formatCandidateScore(entry.fatigueScore)}</strong></div>
        <div><span>Rebalance gain</span><strong>${formatCandidateScore(entry.rebalanceGain)}</strong></div>
        <div><span>Section</span><strong>${formatCandidateScore(entry.sectionScore)}</strong></div>
      </div>

      ${renderReplayDetail(detail)}

      <section class="saved-report-card">
        <div class="panel-subheading">
          <h3>Artifacts</h3>
        </div>
        <ul class="candidate-artifact-list">
          <li><span>Beatmap</span><code>${escapeHtml(entry.mapPath)}</code></li>
          <li><span>Report</span><code>${escapeHtml(entry.reportPath)}</code></li>
          <li><span>Replay</span><code>${escapeHtml(entry.replayReportPath ?? "n/a")}</code></li>
          <li><span>Rebalance</span><code>${escapeHtml(entry.rebalanceReportPath ?? "n/a")}</code></li>
          <li><span>Summary</span><code>${escapeHtml(entry.summaryPath)}</code></li>
        </ul>
      </section>

      <section class="candidate-notes-card">
        <div class="panel-subheading">
          <h3>Notes</h3>
        </div>
        <textarea
          class="candidate-notes-input"
          rows="3"
          placeholder="Optional note (metadata only, never affects scoring)…"
          data-candidate-note-input
        >${escapeHtml(note)}</textarea>
        <button type="button" class="editor-secondary-button" data-candidate-note-save>Save note</button>
      </section>

      <section class="candidate-actions">
        <button type="button" class="editor-secondary-button" data-candidate-open="${entry.candidateIndex}">Open in Editor</button>
        <label class="candidate-compare-row">
          <span>Compare with</span>
          <select data-candidate-compare-select>
            ${others
              .map(
                (other) =>
                  `<option value="${other.candidateIndex}">Candidate ${String(other.candidateIndex).padStart(3, "0")} (#${other.rank})</option>`,
              )
              .join("")}
          </select>
          <button type="button" class="editor-primary-button" data-candidate-compare-start>Compare</button>
        </label>
        <button
          type="button"
          class="editor-primary-button"
          data-candidate-promote="${entry.candidateIndex}"
          ${isChampion ? "disabled" : ""}
        >Promote to Champion</button>
      </section>

      ${renderQualityGates(entry)}

      ${renderChampionHistory(state)}
    `;

    this.bindDetailEvents(entry);
  }

  private renderComparison(state: EditorRootState): void {
    const candidates = state.candidates;
    const comparison = candidates.comparison;
    const entryA = findCandidateEntry(
      candidates.entries,
      comparison.candidateA?.index,
    );
    const entryB = findCandidateEntry(
      candidates.entries,
      comparison.candidateB?.index,
    );

    this.container.innerHTML = `
      <section class="panel-subheading">
        <h3>Candidate Comparison</h3>
        <button type="button" class="editor-ghost-button candidate-back-button" data-candidate-exit-compare>Exit</button>
      </section>

      ${
        comparison.state === "loading"
          ? `<p class="panel-empty-copy">Loading both candidate maps and reports…</p>`
          : comparison.state === "error"
            ? `<p class="panel-empty-copy">${escapeHtml(comparison.error ?? "Comparison failed.")}</p>`
            : `
              <section class="candidate-compare-hero">
                <div class="candidate-compare-side is-a">
                  <span>Candidate A</span>
                  <strong>${entryA ? `#${entryA.rank} · ${String(entryA.candidateIndex).padStart(3, "0")}` : "—"}</strong>
                  <p>Final ${formatCandidateScore(entryA?.finalScore ?? null)} · Replay ${formatCandidateScore(entryA?.replayScore ?? null)}</p>
                </div>
                <div class="candidate-compare-vs">vs</div>
                <div class="candidate-compare-side is-b">
                  <span>Candidate B</span>
                  <strong>${entryB ? `#${entryB.rank} · ${String(entryB.candidateIndex).padStart(3, "0")}` : "—"}</strong>
                  <p>Final ${formatCandidateScore(entryB?.finalScore ?? null)} · Replay ${formatCandidateScore(entryB?.replayScore ?? null)}</p>
                </div>
              </section>

              <section class="candidate-compare-controls">
                <button type="button" class="editor-secondary-button${candidates.diffModeEnabled ? " is-active" : ""}" data-candidate-diff-toggle>
                  ${candidates.diffModeEnabled ? "Diff mode: On" : "Diff mode: Off"}
                </button>
                <span class="candidate-readonly-chip">Read-only comparison · edits disabled</span>
              </section>

              ${renderDiffLegend(comparison.visualDiff)}

              ${renderMetricComparison(entryA, entryB)}

              ${renderSectionComparison(comparison.sectionComparison)}
            `
      }
    `;

    this.bindComparisonEvents();
  }

  private bindBrowserEvents(): void {
    this.container.querySelectorAll<HTMLButtonElement>("[data-candidate-select]").forEach((button) => {
      button.addEventListener("click", () => {
        this.controller.selectCandidate(Number(button.dataset.candidateSelect));
      });
    });
    this.bindOpenButtons();
    this.bindCompareButtons();
    this.bindPromoteButtons();
    this.bindFilterEvents();
  }

  private bindDetailEvents(entry: CandidateBrowserEntry): void {
    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-back]")
      ?.addEventListener("click", () => {
        this.controller.clearCandidateSelection();
      });
    this.bindOpenButtons();
    this.bindPromoteButtons();

    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-note-save]")
      ?.addEventListener("click", () => {
        const input = this.container.querySelector<HTMLTextAreaElement>(
          "[data-candidate-note-input]",
        );
        this.controller.setCandidateNote(entry.candidateIndex, input?.value ?? "");
      });

    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-compare-start]")
      ?.addEventListener("click", () => {
        const select = this.container.querySelector<HTMLSelectElement>(
          "[data-candidate-compare-select]",
        );
        const other = select ? Number(select.value) : undefined;
        if (other !== undefined && Number.isFinite(other)) {
          void this.controller.startComparison(other);
        }
      });

    this.renderChampionHistoryEvents();
  }

  private bindComparisonEvents(): void {
    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-exit-compare]")
      ?.addEventListener("click", () => {
        this.controller.exitComparison();
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-diff-toggle]")
      ?.addEventListener("click", () => {
        this.controller.setDiffMode();
      });
  }

  private bindOpenButtons(): void {
    this.container.querySelectorAll<HTMLButtonElement>("[data-candidate-open]").forEach((button) => {
      button.addEventListener("click", () => {
        this.controller.openCandidateInEditor(Number(button.dataset.candidateOpen));
      });
    });
  }

  private bindCompareButtons(): void {
    this.container.querySelectorAll<HTMLButtonElement>("[data-candidate-compare]").forEach((button) => {
      button.addEventListener("click", () => {
        // Opens the candidate detail, where the "Compare with…" selector
        // lets the user pick the second candidate.
        this.controller.selectCandidate(Number(button.dataset.candidateCompare));
      });
    });
  }

  private bindPromoteButtons(): void {
    this.container.querySelectorAll<HTMLButtonElement>("[data-candidate-promote]").forEach((button) => {
      button.addEventListener("click", () => {
        void this.controller.requestPromoteCandidate(Number(button.dataset.candidatePromote));
      });
    });
  }

  private bindFilterEvents(): void {
    const applyNumber = (value: string): number | null => {
      const parsed = Number(value);
      return Number.isFinite(parsed) && value.trim().length > 0 ? parsed : null;
    };

    this.container
      .querySelector<HTMLSelectElement>("[data-filter-difficulty]")
      ?.addEventListener("change", (event) => {
        const value = (event.currentTarget as HTMLSelectElement).value;
        this.controller.setCandidateFilters({
          difficulty:
            value === "easy" || value === "normal" || value === "hard"
              ? value
              : "all",
        });
      });
    this.container
      .querySelector<HTMLSelectElement>("[data-filter-validation]")
      ?.addEventListener("change", (event) => {
        const value = (event.currentTarget as HTMLSelectElement).value;
        this.controller.setCandidateFilters({
          validation:
            value === "passed" || value === "failed" ? value : "all",
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-min-score]")
      ?.addEventListener("input", (event) => {
        this.controller.setCandidateFilters({
          minScore: applyNumber((event.currentTarget as HTMLInputElement).value),
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-max-score]")
      ?.addEventListener("input", (event) => {
        this.controller.setCandidateFilters({
          maxScore: applyNumber((event.currentTarget as HTMLInputElement).value),
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-min-replay]")
      ?.addEventListener("input", (event) => {
        this.controller.setCandidateFilters({
          minReplayScore: applyNumber((event.currentTarget as HTMLInputElement).value),
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-max-rank]")
      ?.addEventListener("input", (event) => {
        this.controller.setCandidateFilters({
          maxRank: applyNumber((event.currentTarget as HTMLInputElement).value),
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-min-section]")
      ?.addEventListener("input", (event) => {
        this.controller.setCandidateFilters({
          minSectionQuality: applyNumber((event.currentTarget as HTMLInputElement).value),
        });
      });
    this.container
      .querySelector<HTMLInputElement>("[data-filter-champion]")
      ?.addEventListener("change", (event) => {
        this.controller.setCandidateFilters({
          championOnly: (event.currentTarget as HTMLInputElement).checked,
        });
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-filter-reset]")
      ?.addEventListener("click", () => {
        this.controller.setCandidateFilters({
          difficulty: "all",
          minScore: null,
          maxScore: null,
          validation: "all",
          championOnly: false,
          minReplayScore: null,
          maxRank: null,
          minSectionQuality: null,
        });
      });
    this.container
      .querySelector<HTMLSelectElement>("[data-sort-key]")
      ?.addEventListener("change", (event) => {
        const value = (event.currentTarget as HTMLSelectElement).value as CandidateSortKey;
        const direction = this.controller.getState().candidates.sort.direction;
        this.controller.setCandidateSort(value, direction);
      });
    this.container
      .querySelector<HTMLButtonElement>("[data-sort-direction]")
      ?.addEventListener("click", () => {
        const sort = this.controller.getState().candidates.sort;
        this.controller.setCandidateSort(
          sort.key,
          sort.direction === "asc" ? "desc" : "asc",
        );
      });
  }

  private renderChampionHistoryEvents(): void {
    this.container
      .querySelector<HTMLButtonElement>("[data-candidate-restore-champion]")
      ?.addEventListener("click", () => {
        void this.controller.restorePreviousChampion();
      });
  }
}

function renderFilters(
  filters: CandidateFilters,
  sort: { key: CandidateSortKey; direction: "asc" | "desc" },
): string {
  const sortLabels: Record<CandidateSortKey, string> = {
    "final-score": "Final score",
    replay: "Replay score",
    difficulty: "Difficulty (stars)",
    accuracy: "Predicted accuracy",
    flow: "Flow",
    rank: "Ranking",
  };

  return `
    <div class="candidate-filters">
      <label>
        <span>Difficulty</span>
        <select data-filter-difficulty>
          <option value="all" ${filters.difficulty === "all" ? "selected" : ""}>All</option>
          <option value="easy" ${filters.difficulty === "easy" ? "selected" : ""}>Easy</option>
          <option value="normal" ${filters.difficulty === "normal" ? "selected" : ""}>Normal</option>
          <option value="hard" ${filters.difficulty === "hard" ? "selected" : ""}>Hard</option>
        </select>
      </label>
      <label>
        <span>Validation</span>
        <select data-filter-validation>
          <option value="all" ${filters.validation === "all" ? "selected" : ""}>All</option>
          <option value="passed" ${filters.validation === "passed" ? "selected" : ""}>Passed</option>
          <option value="failed" ${filters.validation === "failed" ? "selected" : ""}>Failed</option>
        </select>
      </label>
      <label>
        <span>Min final score</span>
        <input type="number" data-filter-min-score value="${filters.minScore ?? ""}" placeholder="—" />
      </label>
      <label>
        <span>Max final score</span>
        <input type="number" data-filter-max-score value="${filters.maxScore ?? ""}" placeholder="—" />
      </label>
      <label>
        <span>Min replay score</span>
        <input type="number" data-filter-min-replay value="${filters.minReplayScore ?? ""}" placeholder="—" />
      </label>
      <label>
        <span>Max rank</span>
        <input type="number" data-filter-max-rank value="${filters.maxRank ?? ""}" placeholder="—" />
      </label>
      <label>
        <span>Min section quality</span>
        <input type="number" data-filter-min-section value="${filters.minSectionQuality ?? ""}" placeholder="—" />
      </label>
      <label class="candidate-filter-check">
        <input type="checkbox" data-filter-champion ${filters.championOnly ? "checked" : ""} />
        <span>Champion only</span>
      </label>
    </div>
    <div class="candidate-sort-row">
      <label>
        <span>Sort by</span>
        <select data-sort-key>
          ${Object.entries(sortLabels)
            .map(
              ([key, label]) =>
                `<option value="${key}" ${sort.key === key ? "selected" : ""}>${label}</option>`,
            )
            .join("")}
        </select>
      </label>
      <button type="button" class="editor-ghost-button" data-sort-direction>
        ${sort.direction === "asc" ? "Ascending" : "Descending"}
      </button>
      <button type="button" class="editor-ghost-button" data-filter-reset>Reset</button>
    </div>
  `;
}

function renderReplayDetail(
  detail: CandidateDetailBundle | undefined,
): string {
  if (!detail) {
    return "";
  }

  if (detail.loading) {
    return `<p class="panel-empty-copy">Loading replay and rebalance reports…</p>`;
  }

  if (!detail.loaded) {
    return "";
  }

  const replay: CandidateReplayDetail | null = detail.replay;
  const rebalance: CandidateRebalanceDetail | null = detail.rebalance;

  return `
    <div class="candidate-detail-grid candidate-detail-grid--replay">
      <div><span>Replay report</span><strong>${formatCandidateScore(replay?.replayScore ?? null)}</strong></div>
      <div><span>Predicted accuracy</span><strong>${formatCandidatePercent(replay?.expectedAccuracy ?? null)}</strong></div>
      <div><span>Expected misses</span><strong>${formatCandidateScore(replay?.expectedMisses ?? null)}</strong></div>
      <div><span>Expected combo</span><strong>${formatCandidatePercent(replay?.expectedComboPct ?? null)}</strong></div>
      <div><span>Fatigue avg</span><strong>${formatCandidatePercent(replay?.fatigueAverage ?? null)}</strong></div>
      <div><span>Fatigue peak</span><strong>${formatCandidatePercent(replay?.fatiguePeak ?? null)}</strong></div>
      <div><span>Rebalance gain</span><strong>${formatCandidateScore(rebalance?.qualityGain ?? null)}</strong></div>
      <div><span>Replay gain</span><strong>${formatCandidateScore(rebalance?.replayGain ?? null)}</strong></div>
    </div>
  `;
}

function renderQualityGates(entry: CandidateBrowserEntry): string {
  if (entry.qualityGates.length === 0) {
    return "";
  }

  return `
    <section class="saved-report-card">
      <div class="panel-subheading">
        <h3>Quality Gates</h3>
      </div>
      <ul class="candidate-gate-list">
        ${entry.qualityGates
          .map(
            (gate) => `
              <li class="${gate.passed ? "is-passed" : "is-failed"}">
                <strong>${gate.mandatory ? "Mandatory" : "Advisory"} · ${escapeHtml(gate.name)}</strong>
                <span>${gate.passed ? "Passed" : "Failed"} · ${escapeHtml(gate.detail)}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
    </section>
  `;
}

function renderMetricComparison(
  entryA: CandidateBrowserEntry | undefined,
  entryB: CandidateBrowserEntry | undefined,
): string {
  const rows: Array<{ label: string; a: string; b: string; winner: "a" | "b" | "tie" }> = [];

  const addRow = (
    label: string,
    a: number | null,
    b: number | null,
    higherIsBetter: boolean,
  ): void => {
    rows.push({
      label,
      a: formatCandidateScore(a),
      b: formatCandidateScore(b),
      winner: scoreWinner(a, b, higherIsBetter),
    });
  };

  addRow("Final score", entryA?.finalScore ?? null, entryB?.finalScore ?? null, true);
  addRow("Replay", entryA?.replayScore ?? null, entryB?.replayScore ?? null, true);
  addRow("Difficulty", entryA?.difficultyScore ?? null, entryB?.difficultyScore ?? null, true);
  addRow("Rhythm", entryA?.rhythmScore ?? null, entryB?.rhythmScore ?? null, true);
  addRow("Pattern", entryA?.patternScore ?? null, entryB?.patternScore ?? null, true);
  addRow("Reading", entryA?.readingScore ?? null, entryB?.readingScore ?? null, true);
  addRow("Flow", entryA?.flowScore ?? null, entryB?.flowScore ?? null, true);
  addRow("Accuracy", entryA?.predictedAccuracy ?? null, entryB?.predictedAccuracy ?? null, true);
  addRow("Misses", entryA?.expectedMisses ?? null, entryB?.expectedMisses ?? null, false);
  addRow("Combo", entryA?.expectedComboPct ?? null, entryB?.expectedComboPct ?? null, true);
  addRow("Fatigue", entryA?.fatigueScore ?? null, entryB?.fatigueScore ?? null, true);

  return `
    <section class="candidate-metric-compare">
      <div class="panel-subheading">
        <h3>Metrics</h3>
      </div>
      <div class="candidate-metric-head">
        <span>Candidate A</span>
        <span>Metric</span>
        <span>Candidate B</span>
      </div>
      ${rows
        .map(
          (row) => `
            <div class="candidate-metric-row">
              <strong class="${row.winner === "a" ? "is-winner" : ""}">${row.a}</strong>
              <span>${escapeHtml(row.label)}</span>
              <strong class="${row.winner === "b" ? "is-winner" : ""}">${row.b}</strong>
            </div>
          `,
        )
        .join("")}
      <p class="candidate-readonly-chip">Highlighted cells win that metric.</p>
    </section>
  `;
}

function renderDiffLegend(
  visualDiff: { summary: Record<string, number> } | undefined,
): string {
  if (!visualDiff) {
    return "";
  }

  const summary = visualDiff.summary;
  return `
    <section class="candidate-diff-legend">
      <div class="panel-subheading">
        <h3>Visual Diff</h3>
      </div>
      <ul>
        <li><span class="diff-dot is-shared"></span>Shared ${summary.shared}</li>
        <li><span class="diff-dot is-a"></span>A only ${summary.aOnly}</li>
        <li><span class="diff-dot is-b"></span>B only ${summary.bOnly}</li>
        <li><span class="diff-dot is-moved"></span>Moved ${summary.moved}</li>
        <li><span class="diff-dot is-retimed"></span>Retimed ${summary.retimed}</li>
        <li><span class="diff-dot is-both"></span>Moved + retimed ${summary.movedRetimed}</li>
      </ul>
      <p class="candidate-readonly-chip">Playfield shows candidate A objects with candidate B overlaid. Read-only — neither candidate is modified.</p>
    </section>
  `;
}

function renderSectionComparison(
  sectionComparison: CandidateSectionComparison[] | undefined,
): string {
  if (!sectionComparison || sectionComparison.length === 0) {
    return "";
  }

  return `
    <section class="candidate-section-compare">
      <div class="panel-subheading">
        <h3>Section-by-Section</h3>
      </div>
      ${sectionComparison
        .map(
          (section) => `
            <details class="candidate-section-card">
              <summary>
                <strong>${escapeHtml(section.label)}</strong>
                <span>${formatTimeMs(section.startMs)} - ${formatTimeMs(section.endMs)}</span>
                <span class="candidate-section-winner ${
                  section.overallWinner === "a"
                    ? "is-a"
                    : section.overallWinner === "b"
                      ? "is-b"
                      : "is-tie"
                }">
                  ${section.overallWinner === "a" ? "A wins" : section.overallWinner === "b" ? "B wins" : "Tie"}
                </span>
              </summary>
              <div class="candidate-section-metrics">
                ${section.metrics
                  .map((metric) => {
                    const a = metric.a === null ? "—" : Number.isInteger(metric.a) ? String(metric.a) : metric.a.toFixed(2);
                    const b = metric.b === null ? "—" : Number.isInteger(metric.b) ? String(metric.b) : metric.b.toFixed(2);
                    return `
                      <div class="candidate-section-metric-row">
                        <strong class="${metric.winner === "a" ? "is-winner" : ""}">${a}</strong>
                        <span>${escapeHtml(metric.label)}</span>
                        <strong class="${metric.winner === "b" ? "is-winner" : ""}">${b}</strong>
                      </div>
                    `;
                  })
                  .join("")}
              </div>
            </details>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderChampionHistory(state: EditorRootState): string {
  const history = state.candidates.championHistory;
  const current = state.candidates.championCandidateIndex;
  if (history.length === 0 && current === undefined) {
    return "";
  }

  return `
    <section class="candidate-history-card">
      <div class="panel-subheading">
        <h3>Champion History</h3>
      </div>
      <p class="saved-report-copy">
        Current champion: ${current === undefined ? "none" : `Candidate ${String(current).padStart(3, "0")}`}
      </p>
      ${
        history.length > 0
          ? `
            <ul class="candidate-history-list">
              ${history
                .slice()
                .reverse()
                .map(
                  (entry) => `
                    <li class="candidate-history-item">
                      <strong>
                        C${String(entry.previousChampionIndex ?? 0).padStart(3, "0")}
                        &rarr; C${String(entry.newChampionIndex).padStart(3, "0")}
                        ${entry.manual ? "· manual" : "· automatic"}
                      </strong>
                      <span>${escapeHtml(entry.reason)}</span>
                      <small>Score ${formatCandidateScore(entry.newChampionScore)} · ${escapeHtml(formatTimestamp(entry.timestamp))}</small>
                    </li>
                  `,
                )
                .join("")}
            </ul>
          `
          : ""
      }
      <button
        type="button"
        class="editor-ghost-button"
        data-candidate-restore-champion
        ${history.length === 0 || history[history.length - 1]?.previousChampionIndex === null ? "disabled" : ""}
      >Restore previous champion</button>
    </section>
  `;
}

function scoreWinner(
  a: number | null,
  b: number | null,
  higherIsBetter: boolean,
): "a" | "b" | "tie" {
  if (a === null || b === null) {
    return "tie";
  }

  if (Math.abs(a - b) < 0.05) {
    return "tie";
  }

  if (higherIsBetter) {
    return a > b ? "a" : "b";
  }

  return a < b ? "a" : "b";
}

function validationBadgeClass(entry: CandidateBrowserEntry): string {
  if (entry.validationStatus === "passed") {
    return "candidate-badge candidate-badge--passed";
  }

  if (entry.validationStatus === "failed") {
    return "candidate-badge candidate-badge--failed";
  }

  return "candidate-badge candidate-badge--unknown";
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return date.toLocaleString();
}
