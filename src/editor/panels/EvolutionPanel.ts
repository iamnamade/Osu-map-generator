import type { EditorController } from "../EditorController";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";
import type { EvolutionReport } from "../../shared/evolutionReport";
import { escapeHtml, formatTimeMs } from "../../shared/format";

export class EvolutionPanel {
  private unsubscribe?: () => void;

  constructor(
    private readonly container: HTMLElement,
    store: EditorStore,
    private readonly controller: EditorController,
  ) {
    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  dispose(): void {
    this.unsubscribe?.();
  }

  private render(state: EditorRootState): void {
    const report = state.session.evolutionReport;

    if (!report) {
      this.container.innerHTML = `
        <section class="panel-subheading">
          <h3>Candidate Evolution</h3>
        </section>
        <p class="panel-empty-copy">
          No evolution report is attached to this map. Evolution reports are
          produced when the generator runs candidate evolution for a difficulty.
        </p>
      `;
      return;
    }

    this.container.innerHTML = `
      <section class="evolution-hero">
        <div class="evolution-hero-title">
          <span>Champion ${String(report.champion.candidateIndex).padStart(3, "0")}</span>
          <strong>${report.champion.overallScore.toFixed(1)}</strong>
          <p>Overall score &middot; ${report.champion.stars.toFixed(2)} stars</p>
        </div>
        <div class="evolution-hero-meta">
          <span class="difficulty-badge">Quality ${report.champion.qualityScore.toFixed(1)}</span>
          <span class="difficulty-badge">Seed ${report.champion.candidateSeed}</span>
          <span class="difficulty-badge">${report.summary.passesUsed} pass${report.summary.passesUsed === 1 ? "" : "es"}</span>
          <span class="difficulty-badge${report.summary.earlyStopped ? " is-ok" : ""}">${report.summary.earlyStopped ? "Early stopped" : "Full passes"}</span>
        </div>
        <p class="evolution-promotion">${escapeHtml(report.champion.promotionReason)}</p>
        <div class="evolution-actions">
          <button type="button" class="editor-primary-button" data-evolution-open-champion>Open Champion in Editor</button>
          <button type="button" class="editor-ghost-button" data-evolution-open-candidate="${report.champion.candidateIndex}">Open Source Candidate</button>
        </div>
      </section>

      <section class="panel-subheading">
        <h3>Leaderboard</h3>
      </section>
      ${renderLeaderboard(report)}

      <section class="panel-subheading">
        <h3>Champion vs Runner-up</h3>
      </section>
      ${renderComparison(report)}
      ${renderComparisonReasons(report)}

      <section class="panel-subheading">
        <h3>Comparison Heatmaps</h3>
      </section>
      ${renderHeatmaps(report)}

      <section class="panel-subheading">
        <h3>Replay Simulation</h3>
      </section>
      ${renderReplay(report)}

      <section class="panel-subheading">
        <h3>Improvement History</h3>
      </section>
      ${renderImprovementHistory(report)}

      <section class="panel-subheading">
        <h3>Evolution Configuration</h3>
      </section>
      ${renderConfiguration(report)}
    `;

    this.bindActions(report, state.session.source?.evolutionReportPath);
  }

  private bindActions(
    report: EvolutionReport,
    evolutionReportPath: string | undefined,
  ): void {
    const championButton = this.container.querySelector<HTMLButtonElement>(
      "[data-evolution-open-champion]",
    );
    championButton?.addEventListener("click", () => {
      void this.controller.openEvolutionCandidate({
        path: toBrowserPath(report.champion.mapPath),
        label: `Champion Candidate ${String(report.champion.candidateIndex).padStart(3, "0")}`,
        kind: "champion",
        difficulty: report.song.difficulty,
        evolutionReportPath,
      });
    });

    this.container
      .querySelectorAll<HTMLButtonElement>("[data-evolution-open-candidate]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const index = Number(button.dataset.evolutionOpenCandidate);
          const entry = report.ranking.find(
            (item) => item.candidateIndex === index,
          );
          if (!entry) {
            return;
          }
          void this.controller.openEvolutionCandidate({
            path: toBrowserPath(entry.mapPath),
            label: `Candidate ${String(entry.candidateIndex).padStart(3, "0")} (rank ${entry.rank})`,
            kind: entry.rank === 1 ? "champion" : "improved",
            difficulty: report.song.difficulty,
            evolutionReportPath,
          });
        });
      });
  }
}

function renderLeaderboard(report: EvolutionReport): string {
  const entries = report.ranking.slice(0, 10);
  if (entries.length === 0) {
    return `<p class="panel-empty-copy">No ranked candidates.</p>`;
  }

  const best = entries[0]?.scores.overall ?? 1;
  return `
    <ul class="evolution-leaderboard">
      ${entries
        .map(
          (entry) => `
            <li class="evolution-leaderboard-item${
              entry.rank === 1 ? " is-champion" : ""
            }">
              <span class="evolution-rank">#${entry.rank}</span>
              <div class="evolution-candidate-copy">
                <strong>Candidate ${String(entry.candidateIndex).padStart(3, "0")}</strong>
                <span>${entry.stars.toFixed(2)} stars &middot; seed ${entry.candidateSeed}</span>
              </div>
              <div class="evolution-candidate-track">
                <div class="evolution-candidate-fill" style="width: ${Math.round(
                  (entry.scores.overall / best) * 100,
                )}%"></div>
              </div>
              <strong class="evolution-candidate-score">${entry.scores.overall.toFixed(1)}</strong>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderComparisonReasons(report: EvolutionReport): string {
  if (report.comparisonReasons.length === 0) {
    return "";
  }

  return `
    <div class="evolution-reasons">
      ${report.comparisonReasons
        .map((reason) => `<p>${escapeHtml(reason)}</p>`)
        .join("")}
    </div>
  `;
}

function renderComparison(report: EvolutionReport): string {
  const champion = report.ranking[0];
  const runner = report.ranking[1];
  if (!champion || !runner) {
    return `<p class="panel-empty-copy">Need at least two candidates for comparison.</p>`;
  }

  const dimensions: Array<[keyof typeof champion.scores, string]> = [
    ["quality", "Quality"],
    ["difficulty", "Difficulty"],
    ["flow", "Flow"],
    ["rhythm", "Rhythm"],
    ["movement", "Movement"],
    ["pattern", "Pattern"],
    ["slider", "Slider"],
    ["spinner", "Spinner"],
    ["reading", "Reading"],
    ["playability", "Playability"],
    ["consistency", "Consistency"],
    ["confidence", "Confidence"],
    ["replay", "Replay"],
  ];

  const maxValue = 100;
  return `
    <div class="evolution-comparison">
      <div class="evolution-comparison-head">
        <span>Champion ${String(champion.candidateIndex).padStart(3, "0")}</span>
        <span>Dimension</span>
        <span>Runner-up ${String(runner.candidateIndex).padStart(3, "0")}</span>
      </div>
      ${dimensions
        .map(([key, label]) => {
          const left = champion.scores[key];
          const right = runner.scores[key];
          const leftPercent = Math.round((left / maxValue) * 100);
          const rightPercent = Math.round((right / maxValue) * 100);
          const delta = left - right;
          return `
            <div class="evolution-comparison-row">
              <div class="evolution-comp-bar evolution-comp-bar--left">
                <div class="evolution-comp-fill" style="width: ${leftPercent}%"></div>
              </div>
              <div class="evolution-comp-label">
                <strong>${escapeHtml(label)}</strong>
                <span>${delta >= 0 ? "+" : ""}${delta.toFixed(1)}</span>
              </div>
              <div class="evolution-comp-bar evolution-comp-bar--right">
                <div class="evolution-comp-fill" style="width: ${rightPercent}%"></div>
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderHeatmaps(report: EvolutionReport): string {
  const heatmaps = report.heatmaps;
  if (heatmaps.length === 0) {
    return `<p class="panel-empty-copy">No heatmaps in this evolution report.</p>`;
  }

  return `
    <div class="evolution-heatmaps">
      ${heatmaps
        .map((heatmap) => {
          const max = Math.max(0.0001, ...heatmap.values);
          return `
            <div class="evolution-heatmap">
              <div class="evolution-heatmap-head">
                <strong>${escapeHtml(heatmap.label)}</strong>
                <span>${heatmap.values.length} candidates</span>
              </div>
              <div class="evolution-heatmap-grid">
                ${heatmap.values
                  .map(
                    (value) => `
                      <span
                        class="evolution-heatmap-cell"
                        style="opacity: ${Math.max(0.12, value / max)}"
                        title="${value.toFixed(3)}"
                      ></span>
                    `,
                  )
                  .join("")}
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderReplay(report: EvolutionReport): string {
  const replay = report.replay;
  const reportPath = report.replayReportPath;
  const weakness = replay.weakestSection || replay.hardestPattern || "";
  return `
    <div class="evolution-replay-verdict">
      <strong>${replay.replayScore.toFixed(1)}</strong>
      <span>Replay score &middot; ${escapeHtml(replay.playerProfile || "advanced")} player</span>
    </div>
    <div class="validation-summary-grid evolution-replay-grid">
      <div><span>Full combo</span><strong>${Math.round(replay.fullComboChance * 100)}%</strong></div>
      <div><span>Accuracy</span><strong>${(replay.expectedAccuracy * 100).toFixed(1)}%</strong></div>
      <div><span>Expected misses</span><strong>${replay.expectedMisses.toFixed(2)}</strong></div>
      <div><span>Expected combo</span><strong>${(replay.expectedComboPct * 100).toFixed(1)}%</strong></div>
      <div><span>Combo breaks</span><strong>${replay.comboBreaks}</strong></div>
      <div><span>Reading</span><strong>${replay.readingScore.toFixed(1)}</strong></div>
      <div><span>Cursor efficiency</span><strong>${(replay.cursorEfficiency * 100).toFixed(1)}%</strong></div>
      <div><span>Fatigue avg</span><strong>${(replay.fatigueAverage * 100).toFixed(1)}%</strong></div>
      <div><span>Fatigue peak</span><strong>${(replay.fatiguePeak * 100).toFixed(1)}%</strong></div>
      <div><span>Peak stress</span><strong>${formatTimeMs(replay.highestStressSectionMs)}</strong></div>
      <div><span>Hardest pattern</span><strong class="evolution-replay-pattern">${escapeHtml(replay.hardestPattern)}</strong></div>
      <div><span>Weak spot</span><strong>${escapeHtml(weakness)}</strong></div>
    </div>
    ${
      reportPath
        ? `<p class="saved-report-copy">Replay report JSON: <code>${escapeHtml(reportPath)}</code></p>`
        : ""
    }
  `;
}

function renderImprovementHistory(report: EvolutionReport): string {
  const history = report.improvementHistory;
  if (history.length === 0) {
    return `<p class="panel-empty-copy">No improvement passes were run.</p>`;
  }

  return `
    <ul class="issue-list">
      ${history
        .map((pass) => {
          const delta = pass.overallAfter - pass.overallBefore;
          return `
            <li class="issue-list-item${
              pass.accepted ? "" : " severity-warning"
            }">
              <div>
                <strong>
                  Pass ${pass.passNumber} &middot; Candidate ${String(
                    pass.candidateIndex,
                  ).padStart(3, "0")}
                  ${pass.accepted ? `+${delta.toFixed(1)} accepted` : "rejected"}
                </strong>
                <p>
                  ${pass.overallBefore.toFixed(1)} &rarr; ${pass.overallAfter.toFixed(1)}
                </p>
              </div>
            </li>
          `;
        })
        .join("")}
    </ul>
  `;
}

function renderConfiguration(report: EvolutionReport): string {
  const config = report.configuration;
  const summary = report.summary;
  const diagnostics = report.diagnostics;
  return `
    <div class="evolution-config">
      <div class="info-grid">
        <div>
          <span>Generated</span>
          <strong>${summary.generated} candidates</strong>
        </div>
        <div>
          <span>Eligible</span>
          <strong>${summary.eligible}</strong>
        </div>
        <div>
          <span>Rejected</span>
          <strong>${summary.rejected}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>${diagnostics.confidence.toFixed(1)}</strong>
        </div>
        <div>
          <span>Root seed</span>
          <strong>${config.rootSeed}</strong>
        </div>
        <div>
          <span>Archive</span>
          <strong>${escapeHtml(config.archivePolicy)}</strong>
        </div>
      </div>
      <p class="saved-report-copy">
        Deterministic given identical audio, seed, and settings. Champion map:
        <code>${escapeHtml(report.champion.mapPath)}</code>
      </p>
    </div>
  `;
}

function toBrowserPath(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const withoutPublic = normalized.replace(/^public\//, "");
  return withoutPublic.startsWith("/") ? withoutPublic : `/${withoutPublic}`;
}
