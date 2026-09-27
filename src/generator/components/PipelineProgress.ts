import type { JobStateResponse, WorkspaceMetadata } from "../GeneratorModels";
import {
  buildPipelineStagePlan,
  computeElapsedMs,
  getPipelineStageState,
  type PipelineStageState,
} from "../GeneratorValidation";
import { formatClockTimeMs } from "../../shared/format";
import { renderPipelineStageCard } from "./PipelineStageCard";
import { escapeHtml } from "../../shared/format";

export function renderPipelineProgress(params: {
  metadata: WorkspaceMetadata;
  job?: JobStateResponse;
}): string {
  const stages = buildPipelineStagePlan(params.metadata);
  const stageStates = stages.map((stage, index) => ({
    stage,
    state: getPipelineStageState(stage, index, params.job),
    index: index + 1,
  }));
  const currentMessage =
    params.job?.latestMessage ?? "Generation has not started yet.";
  const currentStageLabel =
    params.job?.currentStageLabel ?? "Awaiting start";
  const overallProgress = params.job?.overallProgressPercent ?? 0;
  const elapsedMs = computeElapsedMs(params.job);
  const currentCandidateMarkup = renderCurrentCandidateProgress(params.job);
  const stageMarkup = stageStates
    .map(({ stage, state, index }) =>
      renderPipelineStageCard({
        stage,
        state,
        job: params.job,
        index,
      }),
    )
    .join("");

  return `
    <div class="panel-section-group generation-panel-group">
      <section class="panel-subsection generation-metrics-panel">
        <div class="generation-summary">
          <article class="generation-summary-card generation-summary-card--progress">
            <span>Overall Progress</span>
            <strong>${overallProgress}%</strong>
            <div class="upload-progress-track upload-progress-track--wide">
              <span style="width: ${overallProgress}%"></span>
            </div>
          </article>
          <article class="generation-summary-card generation-summary-card--stage">
            <span>Current Stage</span>
            <strong>${escapeHtml(currentStageLabel)}</strong>
            <p>${escapeHtml(currentMessage)}</p>
            ${currentCandidateMarkup}
          </article>
          <article class="generation-summary-card">
            <span>Elapsed Time</span>
            <strong>${formatClockTimeMs(elapsedMs)}</strong>
            <p>Real elapsed wall time from job start.</p>
          </article>
          <article class="generation-summary-card">
            <span>Stages Closed</span>
            <strong>${params.job ? params.job.completedStages : 0} of ${params.job ? params.job.totalStages : stages.length}</strong>
            <p>${params.job ? `${Math.max(0, params.job.totalStages - params.job.completedStages)} remaining` : "Waiting to start"}</p>
          </article>
        </div>

        <div class="pipeline-stage-progress-line" role="presentation">
          <div class="pipeline-stage-progress-track"></div>
          <div class="pipeline-stage-progress-nodes">
            ${stageStates
              .map(
                ({ state, index }) => `
                  <span class="pipeline-stage-progress-node pipeline-stage-progress-node--${mapStageStateToLineState(state)}">
                    ${index}
                  </span>
                `,
              )
              .join("")}
          </div>
        </div>
      </section>

      <section class="panel-subsection generation-stage-table">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Pipeline Stages</p>
            <h3>Stage Timeline</h3>
            <p>Each row reflects the real pipeline order, state, difficulty context, and candidate progress where available.</p>
          </div>
        </div>
        <div class="pipeline-stage-list">${stageMarkup}</div>
      </section>
    </div>
  `;
}

function renderCurrentCandidateProgress(job: JobStateResponse | undefined): string {
  if (!job || typeof job.currentCandidate !== "number" || typeof job.candidatesTotal !== "number") {
    return "";
  }

  const completedCount =
    typeof job.candidatesCompleted === "number"
      ? Math.max(0, Math.min(job.candidatesCompleted, job.candidatesTotal))
      : undefined;
  const percent =
    typeof completedCount === "number" && job.candidatesTotal > 0
      ? Math.round((completedCount / job.candidatesTotal) * 100)
      : undefined;

  return `
    <div class="candidate-progress-panel">
      <span class="candidate-progress-chip">
        ${escapeHtml(job.currentDifficulty ? `${capitalizeDifficulty(job.currentDifficulty)} evolution` : "Candidate progress")}
      </span>
      <strong>Candidate ${job.currentCandidate} of ${job.candidatesTotal}</strong>
      ${
        typeof percent === "number"
          ? `
            <div class="candidate-progress-bar" aria-hidden="true">
              <span style="width: ${percent}%"></span>
            </div>
          `
          : ""
      }
    </div>
  `;
}

function mapStageStateToLineState(
  state: PipelineStageState,
): "completed" | "active" | "upcoming" | "failed" | "cancelled" {
  if (state === "complete") {
    return "completed";
  }
  if (state === "active") {
    return "active";
  }
  if (state === "failed") {
    return "failed";
  }
  if (state === "cancelled") {
    return "cancelled";
  }
  return "upcoming";
}

function capitalizeDifficulty(value: string): string {
  if (!value) {
    return value;
  }

  return `${value[0]?.toUpperCase() ?? ""}${value.slice(1)}`;
}
