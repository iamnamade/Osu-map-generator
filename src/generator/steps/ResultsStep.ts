import { buildEditorUrl, buildGameUrl } from "../../shared/mapCatalog";
import {
  buildDifficultyPreviewSelection,
  buildPreviewVersionLabel,
  findArtifactById,
  formatBytes,
  type GeneratorState,
} from "../GeneratorModels";
import { renderArtifactList } from "../components/ArtifactList";
import { renderMapsetSummary } from "../components/MapsetSummary";
import { escapeHtml } from "../../shared/format";

export function renderResultsStep(state: GeneratorState): string {
  const summary = state.job?.result ?? state.workspace?.workspace.lastResult;
  const workspace = state.workspace;
  if (!summary || !workspace) {
    return `
      <section class="wizard-stage-panel">
        <div class="wizard-stage-head">
          <p class="section-eyebrow">Step 5</p>
          <h2>Results Unavailable</h2>
          <p>The workspace has not produced a completed result summary yet.</p>
        </div>
      </section>
    `;
  }

  const packageArtifact = findArtifactById(
    workspace.workspace.availableArtifacts,
    summary.packageArtifactId,
  );
  const difficultyCards = summary.difficulties
    .map((difficulty) => {
      const previewSelection = buildDifficultyPreviewSelection(
        workspace,
        difficulty,
      );
      const osuArtifact = findArtifactById(
        workspace.workspace.availableArtifacts,
        difficulty.osuArtifactId,
      );

      return `
        <article class="results-difficulty-card">
          <div class="results-difficulty-head">
            <div>
              <span class="section-eyebrow">${escapeHtml(buildPreviewVersionLabel(difficulty))}</span>
              <h3>${difficulty.objectCount ?? "-"} circles</h3>
              <p>${escapeHtml(previewSelection?.description ?? "Local workspace preview and export actions.")}</p>
            </div>
            <span class="sidebar-status-badge sidebar-status-badge--${difficulty.promoted ? "success" : "muted"}">
              ${difficulty.promoted ? "Promoted" : "Recorded"}
            </span>
          </div>

          <div class="results-difficulty-metrics">
            <span>Quality ${difficulty.score?.toFixed(1) ?? "-"}</span>
            <span>Winner Candidate ${difficulty.candidateWinner ?? "-"}</span>
            <span>Sections ${difficulty.sectionCount ?? "-"}</span>
            <span>Mode ${escapeHtml(difficulty.finalMapKind)}</span>
          </div>

          <div class="results-card-actions">
            ${
              previewSelection
                ? `
                  <a
                    class="generator-secondary-button"
                    href="${escapeHtml(buildGameUrl(previewSelection))}"
                  >
                    Open In Game
                  </a>
                  <a
                    class="generator-secondary-button"
                    href="${escapeHtml(buildEditorUrl(previewSelection))}"
                  >
                    Open In Editor
                  </a>
                `
                : ""
            }
            ${
              osuArtifact
                ? `
                  <a
                    class="generator-primary-button"
                    href="${escapeHtml(osuArtifact.downloadUrl)}"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download .osu
                  </a>
                `
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");

  const finalStatus = state.job?.status ?? workspace.workspace.jobStatus ?? "completed";
  const includedDifficulties = summary.difficulties
    .map((difficulty) => buildPreviewVersionLabel(difficulty))
    .join(", ");

  return `
    <section class="wizard-stage-panel wizard-stage-panel--results">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Step 5</p>
        <h2>Generation Results</h2>
        <p>Review the completed mapset, open difficulty previews, and download the final local artifacts.</p>
      </div>

      ${renderMapsetSummary(summary, finalStatus)}

      <section class="panel-subsection">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Difficulty Outputs</p>
            <h3>Preview And Export Each Version</h3>
            <p>Use the finished maps in the existing game or editor, or download the exported .osu files directly.</p>
          </div>
        </div>
        <div class="results-difficulty-list">${difficultyCards}</div>
      </section>

      ${
        packageArtifact
          ? `
            <section class="panel-subsection results-package-card">
              <div class="panel-subsection-head">
                <div>
                  <p class="section-eyebrow">Final Package</p>
                  <h3>${escapeHtml(packageArtifact.fileName)}</h3>
                  <p>The packaged .osz archive is ready for direct download.</p>
                </div>
                <a
                  class="generator-primary-button"
                  href="${escapeHtml(packageArtifact.downloadUrl)}"
                  target="_blank"
                  rel="noreferrer"
                >
                  Download .osz
                </a>
              </div>

              <div class="results-stat-grid">
                <article class="results-stat-card">
                  <span>Package Size</span>
                  <strong>${formatBytes(packageArtifact.sizeBytes)}</strong>
                </article>
                <article class="results-stat-card">
                  <span>Included Difficulties</span>
                  <strong>${escapeHtml(includedDifficulties)}</strong>
                </article>
                <article class="results-stat-card">
                  <span>Audio Included</span>
                  <strong>${workspace.workspace.audio ? "Yes" : "No"}</strong>
                </article>
                <article class="results-stat-card">
                  <span>Background Included</span>
                  <strong>${workspace.workspace.background ? "Yes" : "No"}</strong>
                </article>
              </div>
            </section>
          `
          : ""
      }

      <div class="panel-actions panel-actions--split">
        <p class="panel-inline-note">Need a new run? Starting a new song deletes the current workspace files after confirmation.</p>
        <button
          type="button"
          class="generator-secondary-button"
          data-action="start-new-song"
        >
          Start New Song
        </button>
      </div>
    </section>

    ${renderArtifactList(workspace.artifacts)}
  `;
}
