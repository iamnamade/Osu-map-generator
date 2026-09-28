import type {
  DifficultyName,
  JobStateResponse,
  StageTiming,
} from "../GeneratorModels";
import type {
  PipelineStageDescriptor,
  PipelineStageState,
} from "../GeneratorValidation";
import { capitalize } from "../GeneratorModels";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml, formatClockTimeMs } from "../../shared/format";

export function renderPipelineStageCard(params: {
  stage: PipelineStageDescriptor;
  state: PipelineStageState;
  job?: JobStateResponse;
  index: number;
}): string {
  const detail = resolveStageDetail(params.stage, params.state, params.job);
  const badgeLabel = resolveStageBadge(params.state);
  const rowMeta = renderStageMeta(params.stage, params.state, params.job);

  return `
    <article class="pipeline-stage-row pipeline-stage-row--${params.state}">
      <span class="pipeline-stage-badge pipeline-stage-badge--${params.state}">
        ${badgeLabel}
      </span>
      <div class="pipeline-stage-row-index">${params.index}</div>
      <div class="pipeline-stage-row-copy">
        <strong>${escapeHtml(params.stage.label)}</strong>
        <p>${escapeHtml(detail)}</p>
      </div>
      <div class="pipeline-stage-row-meta">
        ${rowMeta}
      </div>
      <div class="pipeline-stage-row-icon">
        ${renderStageIcon(params.state)}
      </div>
    </article>
  `;
}

function renderStageIcon(state: PipelineStageState): string {
  if (state === "complete") {
    return renderIcon("check");
  }
  if (state === "active") {
    return renderIcon("job");
  }
  if (state === "failed") {
    return renderIcon("error");
  }
  if (state === "cancelled") {
    return renderIcon("warning");
  }
  return renderIcon("workspace");
}

function resolveStageBadge(state: PipelineStageState): string {
  if (state === "complete") {
    return "OK";
  }
  if (state === "active") {
    return "RUN";
  }
  if (state === "failed") {
    return "FAIL";
  }
  if (state === "cancelled") {
    return "CANCELLED";
  }
  return "WAIT";
}

function resolveStageDetail(
  stage: PipelineStageDescriptor,
  state: PipelineStageState,
  job: JobStateResponse | undefined,
): string {
  if (state === "active" && stage.code.startsWith("evolution-")) {
    return formatCandidateProgress(stage.difficulty, job);
  }

  if (state === "active") {
    return job?.latestMessage ?? "Running now.";
  }

  if (state === "complete") {
    const timing = findStageTiming(job, stage.code);
    return timing
      ? `Completed in ${formatStageDuration(timing.durationMs)}.`
      : "Completed.";
  }

  if (state === "failed") {
    return job?.latestMessage || "Stopped during this stage.";
  }

  if (state === "cancelled") {
    return "Cancellation requested before completion.";
  }

  if (job?.status === "running" || job?.status === "queued") {
    return "Queued.";
  }

  return "Waiting to start.";
}

function renderStageMeta(
  stage: PipelineStageDescriptor,
  state: PipelineStageState,
  job: JobStateResponse | undefined,
): string {
  const items: string[] = [];
  if (stage.difficulty) {
    items.push(
      `<span class="pipeline-stage-chip">${escapeHtml(capitalize(stage.difficulty))}</span>`,
    );
  }

  const candidateChip = renderCandidateChip(stage.difficulty, state, job);
  if (candidateChip) {
    items.push(candidateChip);
  }

  // P2.4: show the server-measured duration for stages that have finished.
  const timing = findStageTiming(job, stage.code);
  if (timing) {
    items.push(
      `<span class="pipeline-stage-chip pipeline-stage-chip--timing">${escapeHtml(formatStageDuration(timing.durationMs))}</span>`,
    );
  }

  return items.join("");
}

function findStageTiming(
  job: JobStateResponse | undefined,
  stageCode: string,
): StageTiming | undefined {
  return job?.stageTimings?.find((timing) => timing.stage === stageCode);
}

function formatStageDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${Math.max(1, Math.round(durationMs))} ms`;
  }
  if (durationMs < 60_000) {
    return `${(durationMs / 1000).toFixed(1)} s`;
  }
  return formatClockTimeMs(durationMs);
}

function renderCandidateChip(
  difficulty: DifficultyName | undefined,
  state: PipelineStageState,
  job: JobStateResponse | undefined,
): string {
  if (
    !difficulty ||
    state !== "active" ||
    job?.currentDifficulty !== difficulty ||
    typeof job.currentCandidate !== "number" ||
    typeof job.candidatesTotal !== "number"
  ) {
    return "";
  }

  return `
    <span class="pipeline-stage-chip pipeline-stage-chip--active">
      Candidate ${job.currentCandidate}/${job.candidatesTotal}
    </span>
  `;
}

function formatCandidateProgress(
  difficulty: DifficultyName | undefined,
  job: JobStateResponse | undefined,
): string {
  if (!job || job.currentDifficulty !== difficulty) {
    return "Preparing candidates.";
  }

  if (
    typeof job.currentCandidate === "number" &&
    typeof job.candidatesTotal === "number"
  ) {
    return `${capitalize(difficulty ?? "current")} evolution / Candidate ${job.currentCandidate} of ${job.candidatesTotal}`;
  }

  return "Preparing candidates.";
}
