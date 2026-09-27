import type { GeneratorState } from "../GeneratorModels";
import {
  MAPPING_CONTROLS,
  capitalize,
  findMappingPreset,
  isTerminalJobStatus,
  toPercent,
} from "../GeneratorModels";
import { renderPipelineProgress } from "../components/PipelineProgress";
import { renderJobLogPanel } from "../components/JobLogPanel";
import { escapeHtml } from "../../shared/format";
import { renderIcon } from "../components/GeneratorIcons";

export function renderGenerationStep(state: GeneratorState): string {
  const job = state.job;
  const hasActiveJob = Boolean(job && !isTerminalJobStatus(job.status));
  const canStartGeneration =
    Boolean(state.workspace?.readyForGeneration) && !hasActiveJob;
  const hasResultsAvailable = Boolean(job?.result || state.workspace?.workspace.lastResult);
  const primaryAction = resolvePrimaryAction(state, canStartGeneration, hasResultsAvailable);
  const statusBanner = renderGenerateStatusBanner(state);

  return `
    <section class="wizard-stage-panel wizard-stage-panel--generation">
      ${statusBanner}
      ${renderGenerateStepStrip()}

      ${renderGenerationConfigPreview(state)}

      <div class="generation-hero">
        <div class="wizard-stage-head wizard-stage-head--generation">
          <p class="section-eyebrow">Step 4</p>
          <h2>Run Local Pipeline</h2>
          <p>Progress is reported from the actual Python stages. No synthetic progress is shown between stage boundaries.</p>
        </div>
        <div class="generation-waveform" aria-hidden="true">
          <div class="generation-waveform-grid"></div>
          <div class="generation-waveform-signal">
            ${Array.from({ length: 18 }, (_, index) => {
              const heights = [
                12, 18, 22, 30, 26, 42, 58, 76, 104, 68, 44, 32, 24, 20, 28, 22,
                18, 12,
              ];
              return `<span style="height:${heights[index]}px"></span>`;
            }).join("")}
          </div>
        </div>
      </div>

      ${renderPipelineProgress({
        metadata: state.metadataDraft,
        job,
      })}

      ${renderJobLogPanel({
        job,
        logsExpanded: state.logsExpanded,
        technicalDetailsExpanded: state.technicalDetailsExpanded,
      })}

      <div class="panel-actions generation-action-bar">
        <button
          type="button"
          class="generator-secondary-button"
          data-action="back-to-difficulties"
          ${hasActiveJob ? "disabled" : ""}
        >
          Back
        </button>
        <button
          type="button"
          class="generator-danger-button"
          data-action="cancel-generation"
          ${hasActiveJob ? "" : "disabled"}
        >
          Cancel Job
        </button>
        <button
          type="button"
          class="generator-primary-button"
          data-action="${primaryAction.action}"
          ${primaryAction.enabled ? "" : "disabled"}
        >
          ${escapeHtml(primaryAction.label)}
        </button>
      </div>
    </section>
  `;
}

function renderGenerationConfigPreview(state: GeneratorState): string {
  const selected = state.metadataDraft.selectedDifficulties;
  if (selected.length === 0) {
    return "";
  }

  const cards = selected.map((difficulty) => {
    const settings = state.metadataDraft.difficultySettings[difficulty];
    const preset = findMappingPreset(settings.mappingPreset);
    const presetLabel = preset ? preset.label : "Custom";
    const controlLines = MAPPING_CONTROLS.map((control) => {
      const percent = toPercent(settings[control.key]);
      const isSpinner = control.key === "spinnerFrequency";
      return `
        <div class="config-preview-line">
          <span>${escapeHtml(control.label)}</span>
          <strong>${isSpinner && percent === 0 ? "None" : `${percent}%`}</strong>
        </div>
      `;
    }).join("");

    const targetLine =
      settings.difficultyTarget === "custom" &&
      typeof settings.customTargetStar === "number" &&
      typeof settings.customMinStar === "number" &&
      typeof settings.customMaxStar === "number"
        ? `Target: ${settings.customTargetStar.toFixed(1)} stars (${settings.customMinStar.toFixed(1)}-${settings.customMaxStar.toFixed(1)})`
        : "Auto (match difficulty)";

    return `
      <section class="config-preview-card">
        <div class="config-preview-head">
          <span class="section-eyebrow">${escapeHtml(capitalize(difficulty))}</span>
          <strong>${escapeHtml(presetLabel)}</strong>
        </div>
        <div class="config-preview-columns">
          <div class="config-preview-controls">${controlLines}</div>
          <div class="config-preview-meta">
            <div class="config-preview-line">
              <span>Difficulty Target</span>
              <strong>${escapeHtml(targetLine)}</strong>
            </div>
            <div class="config-preview-line">
              <span>Candidates</span>
              <strong>${settings.candidateCount}</strong>
            </div>
            <div class="config-preview-line">
              <span>Evolution Passes</span>
              <strong>${settings.evolutionPasses}</strong>
            </div>
            <div class="config-preview-line">
              <span>Seed</span>
              <strong>${settings.seedMode === "auto" ? "Auto" : settings.rootSeed}</strong>
            </div>
            <div class="config-preview-line">
              <span>Replay Profile</span>
              <strong>${escapeHtml(capitalize(settings.replayProfile))}</strong>
            </div>
            <div class="config-preview-line">
              <span>Section Sensitivity</span>
              <strong>${toPercent(settings.sectionSensitivity)}%</strong>
            </div>
            <div class="config-preview-line">
              <span>Tournament / Hybrid</span>
              <strong>${settings.tournamentEnabled ? "on" : "off"} / ${settings.hybridAssemblyEnabled ? "on" : "off"}</strong>
            </div>
          </div>
        </div>
      </section>
    `;
  }).join("");

  return `
    <section class="config-preview">
      <div class="config-preview-title">
        <p class="section-eyebrow">Step 4</p>
        <h3>Generation Configuration</h3>
        <p>The exact values below drive the pipeline. Identical configuration reproduces identical maps.</p>
      </div>
      <div class="config-preview-grid">${cards}</div>
    </section>
  `;
}

function renderGenerateStepStrip(): string {
  const steps = [
    { index: 1, label: "Upload", state: "completed" },
    { index: 2, label: "Metadata", state: "completed" },
    { index: 3, label: "Difficulties", state: "completed" },
    { index: 4, label: "Generate", state: "active" },
    { index: 5, label: "Results", state: "upcoming" },
  ] as const;

  return `
    <div class="generation-step-strip" aria-hidden="true">
      ${steps
        .map(
          (step) => `
            <div class="generation-step-pill generation-step-pill--${step.state}">
              <span class="generation-step-pill-index">
                ${step.state === "completed" ? renderIcon("check") : step.index}
              </span>
              <span class="generation-step-pill-label">${escapeHtml(step.label)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderGenerateStatusBanner(state: GeneratorState): string {
  if (state.errorMessage) {
    return renderInlineStatusBanner("error", "STATUS UPDATE", state.errorMessage, "dismiss-error");
  }

  if (state.noticeMessage) {
    const noticeVariant =
      state.job?.status === "completed"
        ? "success"
        : state.job?.status === "cancelled"
          ? "warning"
          : "info";
    return renderInlineStatusBanner(
      noticeVariant,
      "STATUS UPDATE",
      state.noticeMessage,
      "dismiss-notice",
    );
  }

  if (state.busyMessage) {
    return renderInlineStatusBanner("info", "STATUS UPDATE", state.busyMessage);
  }

  if (state.job?.status === "failed") {
    return renderInlineStatusBanner(
      "error",
      "FAILURE",
      state.job.latestMessage || "Generation failed during the active stage.",
    );
  }

  if (state.job?.status === "cancelled") {
    return renderInlineStatusBanner(
      "warning",
      "STATUS UPDATE",
      state.job.latestMessage || "Generation was cancelled.",
    );
  }

  return "";
}

function renderInlineStatusBanner(
  variant: "info" | "success" | "warning" | "error",
  label: string,
  message: string,
  dismissAction?: "dismiss-error" | "dismiss-notice",
): string {
  return `
    <div
      class="generation-inline-banner generation-inline-banner--${variant}"
      role="status"
      aria-live="polite"
    >
      <div class="generation-inline-banner-copy">
        <span>${escapeHtml(label)}</span>
        <p>${escapeHtml(message)}</p>
      </div>
      ${
        dismissAction
          ? `
            <button
              type="button"
              class="generator-secondary-button generation-inline-banner-dismiss"
              data-action="${dismissAction}"
            >
              Dismiss
            </button>
          `
          : ""
      }
    </div>
  `;
}

function resolvePrimaryAction(
  state: GeneratorState,
  canStartGeneration: boolean,
  hasResultsAvailable: boolean,
): {
  action: "start-generation" | "continue-to-results";
  label: string;
  enabled: boolean;
} {
  const job = state.job;
  if (!job) {
    return {
      action: "start-generation",
      label: "Start Generation",
      enabled: canStartGeneration,
    };
  }

  if (job.status === "failed" || job.status === "cancelled") {
    return {
      action: "start-generation",
      label: "Retry Generation",
      enabled: canStartGeneration,
    };
  }

  if (job.status === "completed" && hasResultsAvailable) {
    return {
      action: "continue-to-results",
      label: "Continue to Results",
      enabled: true,
    };
  }

  return {
    action: "start-generation",
    label: "Start Generation",
    enabled: canStartGeneration,
  };
}
