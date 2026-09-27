import type { JobResultSummary, JobStatus } from "../GeneratorModels";
import { buildPreviewVersionLabel, capitalize, formatBytes } from "../GeneratorModels";
import { escapeHtml, formatClockTimeMs } from "../../shared/format";

export function renderMapsetSummary(
  summary: JobResultSummary,
  finalStatus: JobStatus | null | undefined,
): string {
  const difficultyLabels = summary.difficulties
    .map((difficulty) => buildPreviewVersionLabel(difficulty))
    .join(", ");
  const generationModes = Array.from(
    new Set(summary.difficulties.map((difficulty) => capitalize(difficulty.finalMapKind))),
  ).join(" / ");

  return `
    <section class="panel-subsection results-summary-panel">
      <div class="panel-subsection-head">
        <div>
          <p class="section-eyebrow">Mapset Summary</p>
          <h3>${escapeHtml(summary.title)}</h3>
          <p>${escapeHtml(summary.artist)} / ${summary.audioDurationMs ? formatClockTimeMs(summary.audioDurationMs) : "Duration unavailable"}</p>
        </div>
        <span class="sidebar-status-badge sidebar-status-badge--${finalStatus === "completed" ? "success" : finalStatus === "failed" ? "danger" : "warning"}">
          ${escapeHtml(capitalize(finalStatus ?? "completed"))}
        </span>
      </div>

      <div class="results-stat-grid">
        <article class="results-stat-card">
          <span>Selected Difficulties</span>
          <strong>${escapeHtml(difficultyLabels || "None")}</strong>
        </article>
        <article class="results-stat-card">
          <span>Generation Mode</span>
          <strong>${escapeHtml(generationModes || "Generated")}</strong>
        </article>
        <article class="results-stat-card">
          <span>Section Count</span>
          <strong>${summary.sectionCount ?? "-"}</strong>
        </article>
        <article class="results-stat-card">
          <span>Package Size</span>
          <strong>${formatBytes(summary.packageSizeBytes)}</strong>
        </article>
      </div>
    </section>
  `;
}
