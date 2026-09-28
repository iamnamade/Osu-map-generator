import {
  GeneratorApiClient,
  GeneratorApiError,
} from "./GeneratorApiClient";
import {
  accumulateJobEvents,
  applyMappingPresetToSettings,
  applySharedGenerationSettings,
  cloneWorkspaceMetadata,
  createInitialFileTransferState,
  createInitialGeneratorState,
  formatBytes,
  isTerminalJobStatus,
  type DifficultyName,
  type FileTransferState,
  type GeneratorState,
  type JobStateResponse,
  type MappingPresetName,
  type WizardStep,
  type WorkspaceMetadata,
  type WorkspaceResponse,
} from "./GeneratorModels";
import {
  clearPersistedGeneratorState,
  loadPersistedGeneratorState,
  savePersistedGeneratorState,
} from "./GeneratorPersistence";
import { GeneratorStore } from "./GeneratorStore";
import {
  applyDetectedMetadataSuggestion,
  computeElapsedMs,
  deriveWizardStep,
  isMappingPresetName,
  isWizardStep,
  validateDifficultySelection,
  validateMetadataDraft,
} from "./GeneratorValidation";
import { escapeHtml, formatClockTimeMs } from "../shared/format";
import { renderIcon } from "./components/GeneratorIcons";
import {
  computeWaveformPeaks,
  drawGeneratorWaveform,
} from "./components/GeneratorWaveform";
import { renderDifficultyStep } from "./steps/DifficultyStep";
import { renderGenerationStep } from "./steps/GenerationStep";
import { renderMetadataStep } from "./steps/MetadataStep";
import { renderResultsStep } from "./steps/ResultsStep";
import { renderUploadStep } from "./steps/UploadStep";

const STEP_ORDER: WizardStep[] = [
  "upload",
  "metadata",
  "difficulties",
  "generate",
  "results",
];

const DIFFICULTY_ORDER: Record<DifficultyName, number> = {
  easy: 1,
  normal: 2,
  hard: 3,
};

const MAPPING_CONTROL_KEYS = new Set([
  "circleDensity",
  "sliderDensity",
  "spinnerFrequency",
  "jumpIntensity",
  "streamIntensity",
  "burstIntensity",
  "rhythmComplexity",
  "patternVariety",
  "spacing",
  "aggression",
  "sectionSensitivity",
]);

const GENERATOR_DOCS_URL = new URL(
  "../../docs/LOCAL_GENERATOR_WORKFLOW.md",
  import.meta.url,
).href;
const VALIDATOR_GUIDE_URL = new URL(
  "../../docs/MAP_VALIDATION.md",
  import.meta.url,
).href;
const EXPORT_HELP_URL = new URL(
  "../../docs/OSU_FORMAT_INTEROPERABILITY.md",
  import.meta.url,
).href;
const MAP_GENERATOR_GUIDE_URL = new URL(
  "../../docs/MAP_GENERATOR.md",
  import.meta.url,
).href;

export class GeneratorApp {
  private readonly api = new GeneratorApiClient();
  private readonly store = new GeneratorStore(createInitialGeneratorState());
  private unsubscribe?: () => void;
  private pollTimer: number | null = null;
  private audioDropzoneActive = false;
  private backgroundPreviewUrl: string | null = null;
  // P1.2: decoded peaks for the step-4 waveform preview (null until decoded).
  private waveformPeaks: number[] | null = null;
  // P1.3: while an IME composition is active we defer re-rendering so the
  // browser keeps ownership of the composition (and its caret) uninterrupted.
  private isComposing = false;

  constructor(private readonly root: HTMLElement) {}

  async start(): Promise<void> {
    this.bindEvents();
    this.unsubscribe = this.store.subscribe((state) => {
      savePersistedGeneratorState(state);
      // P1.3: hold off rebuilding the DOM during an IME composition so the
      // browser keeps the in-progress composition (and its caret) intact.
      if (this.isComposing) {
        return;
      }
      this.render(state);
    });
    await this.bootstrap();
  }

  dispose(): void {
    this.stopPolling();
    this.replaceBackgroundPreviewUrl(null);
    this.waveformPeaks = null;
    this.unsubscribe?.();
  }

  private bindEvents(): void {
    this.root.addEventListener("click", (event) => {
      void this.handleClick(event);
    });
    this.root.addEventListener("change", (event) => {
      void this.handleChange(event);
    });
    this.root.addEventListener("input", (event) => {
      this.handleInput(event);
    });
    this.root.addEventListener("dragenter", (event) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-dropzone='audio']")) {
        event.preventDefault();
        this.setAudioDropzoneActive(true);
      }
    });
    this.root.addEventListener("dragover", (event) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-dropzone='audio']")) {
        event.preventDefault();
        this.setAudioDropzoneActive(true);
      }
    });
    this.root.addEventListener("dragleave", (event) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-dropzone='audio']")) {
        const relatedTarget = event.relatedTarget;
        if (
          !(relatedTarget instanceof Node) ||
          !target.closest("[data-dropzone='audio']")?.contains(relatedTarget)
        ) {
          this.setAudioDropzoneActive(false);
        }
      }
    });
    this.root.addEventListener("drop", (event) => {
      void this.handleDrop(event);
    });
    // P1.3: track IME composition globally; every metadata field and control
    // lives under `root`, so a single pair of delegated listeners suffices.
    this.root.addEventListener("compositionstart", () => {
      this.isComposing = true;
    });
    this.root.addEventListener("compositionend", () => {
      this.isComposing = false;
      this.render(this.store.getState());
    });
  }

  private async bootstrap(): Promise<void> {
    this.stopPolling();
    this.store.update((state) => ({
      ...state,
      bootState: "booting",
      healthStatus: "checking",
      healthMessage: "Checking local API availability...",
      busyMessage: "Connecting to the local generator services...",
      errorMessage: undefined,
      noticeMessage: undefined,
    }));

    try {
      const health = await this.api.health();
      const persisted = loadPersistedGeneratorState();
      let workspace: WorkspaceResponse | undefined;
      let detectedMetadata = persisted?.detectedMetadata
        ? { ...persisted.detectedMetadata }
        : undefined;
      let currentStep: WizardStep = "upload";
      let job = undefined;

      if (persisted?.workspaceId) {
        try {
          workspace = await this.api.getWorkspace(persisted.workspaceId);
        } catch {
          clearPersistedGeneratorState();
        }
      }

      if (!workspace) {
        workspace = await this.api.createWorkspace();
      }

      // P1.1: rebuild the background preview from the server so it survives a
      // page reload (the previous session-only blob URL is gone by now).
      this.replaceBackgroundPreviewUrl(
        workspace.workspace.background
          ? this.api.backgroundPreviewUrl(
              workspace.workspace.workspaceId,
              workspace.workspace.background.normalizedFilename,
            )
          : null,
      );

      const metadataDraft = persisted?.metadataDraft
        ? hydrateMetadataDraftFromPersistence(
            persisted.metadataDraft,
            workspace.workspace.metadata,
          )
        : cloneWorkspaceMetadata(workspace.workspace.metadata);

      if (persisted?.jobId) {
        try {
          job = await this.api.getJob(persisted.jobId);
        } catch {
          job = undefined;
        }
      }

      currentStep =
        persisted?.currentStep && isWizardStep(persisted.currentStep)
          ? persisted.currentStep
          : deriveWizardStep({ workspace, job });

      if (job?.status === "completed" && (job.result || workspace.workspace.lastResult)) {
        currentStep = "results";
      }

      this.store.setState({
        ...createInitialGeneratorState(),
        bootState: "ready",
        currentStep,
        workspace,
        job,
        jobId: job?.jobId,
        detectedMetadata,
        metadataDraft,
        audioUpload: buildTransferStateFromWorkspaceFile(workspace.workspace.audio),
        backgroundUpload: buildTransferStateFromWorkspaceFile(
          workspace.workspace.background,
        ),
        healthStatus: health.pipelineAvailable ? "ready" : "error",
        healthMessage: health.pipelineAvailable
          ? "Local API ready on 127.0.0.1:8765."
          : "Local API responded, but the generation pipeline reported unavailable.",
        advancedSettingsOpen: persisted?.advancedSettingsOpen ?? false,
        logsExpanded: persisted?.logsExpanded ?? Boolean(job),
        technicalDetailsExpanded:
          persisted?.technicalDetailsExpanded ?? false,
      });

      // P1.2: decode the already-uploaded track so the step-4 waveform renders
      // even when the wizard is resumed after a reload.
      const audioFile = workspace.workspace.audio;
      if (audioFile) {
        void this.loadWaveformFromUrl(
          this.api.audioPreviewUrl(
            workspace.workspace.workspaceId,
            audioFile.normalizedFilename,
          ),
        );
      } else {
        this.waveformPeaks = null;
      }

      if (job && !isTerminalJobStatus(job.status)) {
        this.startPolling(job.jobId);
      }
    } catch (error) {
      this.store.update((state) => ({
        ...state,
        bootState: "error",
        healthStatus: "error",
        healthMessage: "Could not reach the local API.",
        busyMessage: undefined,
        errorMessage: toReadableError(error),
      }));
      return;
    }

    this.store.update((state) => ({
      ...state,
      busyMessage: undefined,
    }));
  }

  private render(state: GeneratorState): void {
    const workspaceId = state.workspace?.workspace.workspaceId;
    const statusLabel = resolveModeLabel(state.healthStatus);
    const apiEndpoint = extractApiEndpoint(state.healthMessage);
    const showGlobalBanners = state.currentStep !== "generate";
    // P1.3: capture the focused control + caret before the wholesale innerHTML
    // swap and restore them afterwards, so typing (and IME) stays stable.
    const focusSnapshot = captureFocusSnapshot(this.root);
    this.root.innerHTML = `
      <div class="generator-shell">
        <header class="generator-header">
          <div class="generator-brand">
            <div class="generator-brand-mark">
              ${renderIcon("brand", "generator-brand-icon")}
            </div>
            <div class="generator-brand-copy">
              <h1>PULSE PRACTICE</h1>
              <p>OSU MAP GENERATOR</p>
            </div>
          </div>

          <nav class="wizard-stepper" aria-label="Generator steps">
            ${STEP_ORDER.map((step, index) => {
              const visualState = getWizardStepState(step, state);
              const isClickable = canJumpToStep(step, state) || step === state.currentStep;
              return `
                <button
                  type="button"
                  class="wizard-step wizard-step--${visualState}"
                  data-action="jump-step"
                  data-step="${step}"
                  aria-current="${step === state.currentStep ? "step" : "false"}"
                  ${isClickable ? "" : "disabled"}
                >
                  <span class="wizard-step-index">
                    ${renderWizardStepGlyph(visualState, index + 1)}
                  </span>
                  <span class="wizard-step-label">${escapeHtml(stepLabel(step))}</span>
                </button>
              `;
            }).join("")}
          </nav>

          <div class="generator-status-cluster">
            <div class="generator-utility-actions">
              <button
                type="button"
                class="generator-utility-button"
                data-action="jump-step"
                data-step="difficulties"
                aria-label="Open generator settings"
                ${canJumpToStep("difficulties", state) ? "" : "disabled"}
              >
                ${renderIcon("settings")}
              </button>
              <a
                class="generator-utility-button"
                href="${escapeHtml(GENERATOR_DOCS_URL)}"
                target="_blank"
                rel="noreferrer"
                aria-label="Open generator help"
              >
                ${renderIcon("help")}
              </a>
            </div>
            <div class="generator-status-meta">
              <div class="status-pill status-pill--api status-pill--${state.healthStatus}">
                <span class="mode-badge__dot"></span>
                <div class="status-pill-copy">
                  <strong>${statusLabel}</strong>
                  <span>${escapeHtml(apiEndpoint ?? state.healthMessage)}</span>
                </div>
              </div>
              <div class="status-pill status-pill--workspace">
                <div class="status-pill-copy">
                  <strong>Workspace</strong>
                  <span>${workspaceId ? escapeHtml(workspaceId.slice(0, 8)) : "pending"}</span>
                </div>
              </div>
            </div>
            ${
              state.healthStatus === "ready" || !state.healthMessage
                ? ""
                : `<p class="generator-status-note">${escapeHtml(state.healthMessage)}</p>`
            }
          </div>
        </header>

        ${
          showGlobalBanners
            ? `
              <div class="generator-banner-stack">
                ${renderMessageBanner("error", state.errorMessage)}
                ${renderMessageBanner("notice", state.noticeMessage)}
                ${renderBusyBanner(state.busyMessage)}
              </div>
            `
            : ""
        }

        <div class="generator-layout">
          <aside class="generator-sidebar">
            ${this.renderSidebar(state)}
          </aside>
          <main class="generator-main">
            ${this.renderMain(state)}
          </main>
        </div>

        ${this.renderFooter()}
      </div>
    `;
    restoreFocusSnapshot(this.root, focusSnapshot);

    if (state.currentStep === "generate") {
      this.drawActiveWaveform();
    }
  }

  private renderSidebar(state: GeneratorState): string {
    const workspace = state.workspace?.workspace;
    const lastResult = state.job?.result ?? workspace?.lastResult;
    const selectedDifficulties = state.metadataDraft.selectedDifficulties;
    const audio = workspace?.audio;
    const background = workspace?.background;
    const jobStatus = state.job?.status ?? workspace?.jobStatus ?? null;
    const jobDetails = state.job
      ? [
          state.job.currentStageLabel ?? state.job.latestMessage,
          `${state.job.overallProgressPercent}% overall`,
          `Elapsed ${formatClockTimeMs(computeElapsedMs(state.job))}`,
        ]
      : lastResult
        ? [
            `${lastResult.title} ready`,
            formatBytes(lastResult.packageSizeBytes),
            "Artifacts available in results",
          ]
        : ["No active job", "Waiting for generation start"];

    return `
      <section class="sidebar-card sidebar-card--workspace">
        <div class="sidebar-card-head">
          <span class="sidebar-icon-box">
            ${renderIcon("terminal")}
          </span>
          <div>
            <p class="section-eyebrow">Workspace</p>
            <h2>LOCAL SESSION</h2>
          </div>
        </div>
        <p class="sidebar-support-copy">All data stays on this machine inside an isolated workspace.</p>
      </section>

      <div class="sidebar-status-stack">
        ${renderSidebarTile({
          icon: renderIcon("audio"),
          label: "Audio",
          status: audio ? "Uploaded" : resolveTransferStateLabel(state.audioUpload.status, "Not uploaded"),
          accent: audio ? "success" : state.audioUpload.status === "error" ? "danger" : "muted",
          lines: audio
            ? [
                audio.originalFilename,
                buildAudioMetadataLine(audio),
                `${formatFileType(audio.originalFilename, audio.contentType)} / ${formatBytes(audio.sizeBytes)}`,
              ]
            : ["No source file selected yet"],
        })}
        ${renderSidebarTile({
          icon: renderIcon("background"),
          label: "Background",
          status: background ? "Attached" : "Optional",
          accent: background ? "success" : "muted",
          lines: background
            ? [
                background.originalFilename,
                `${formatFileType(background.originalFilename, background.contentType)} / ${formatBytes(background.sizeBytes)}`,
              ]
            : ["Optional artwork for the final package"],
        })}
        ${renderSidebarTile({
          icon: renderIcon("difficulties"),
          label: "Difficulties",
          status: selectedDifficulties.length > 0 ? `${selectedDifficulties.length} selected` : "None selected",
          accent: selectedDifficulties.length > 0 ? "success" : "muted",
          lines:
            selectedDifficulties.length > 0
              ? selectedDifficulties.map((difficulty) => capitalize(difficulty))
              : ["Select Easy, Normal, or Hard"],
        })}
        ${renderSidebarTile({
          icon: renderIcon("job"),
          label: "Job Status",
          status: jobStatus ? capitalize(jobStatus) : "Idle",
          accent: resolveJobAccent(jobStatus),
          lines: jobDetails,
        })}
      </div>

      <section class="sidebar-card sidebar-card--privacy">
        <div class="sidebar-card-head">
          <span class="sidebar-icon-box">
            ${renderIcon("lock")}
          </span>
          <div>
            <p class="section-eyebrow">Privacy &amp; Scope</p>
            <h2>LOCAL ONLY</h2>
          </div>
        </div>
        <ul class="sidebar-note-list">
          <li>Uploaded audio and artwork stay on this machine.</li>
          <li>No cloud services, accounts, or remote AI are used.</li>
          <li>Everything is processed locally and privately.</li>
          <li>Every workspace remains isolated until you delete it.</li>
        </ul>
        <p class="sidebar-footnote">
          Phase 8A.1 exports remain circle-only. Sliders and spinners stay deferred to Phase 8B.
        </p>
      </section>
    `;
  }

  private renderFooter(): string {
    return `
      <footer class="generator-footer" id="generator-footer">
        <section class="footer-panel footer-panel--brand">
          <p class="section-eyebrow">Pulse Practice Generator</p>
          <h2>Create, validate, and export osu! mapsets locally.</h2>
          <p class="muted-copy">You keep full control of the workspace, logs, and outputs from upload through package export.</p>
        </section>

        <section class="footer-panel">
          <p class="section-eyebrow">Quick Links</p>
          <div class="footer-link-list">
            ${renderFooterLink(MAP_GENERATOR_GUIDE_URL, "Generator Docs", "docs", true)}
            ${renderFooterLink(VALIDATOR_GUIDE_URL, "Validator Guide", "check", true)}
            ${renderFooterLink("./editor.html", "Editor", "editor")}
            ${renderFooterLink(EXPORT_HELP_URL, "Export Help", "package", true)}
          </div>
        </section>

        <section class="footer-panel">
          <p class="section-eyebrow">Local Tools</p>
          <div class="footer-icon-row">
            ${renderFooterIconLink("./index.html", "Open rhythm workspace", "game")}
            ${renderFooterIconLink("./editor.html", "Open editor", "editor")}
            ${renderFooterIconLink(GENERATOR_DOCS_URL, "Open workflow help", "help", true)}
            ${renderFooterIconLink(VALIDATOR_GUIDE_URL, "Open validator guide", "docs", true)}
          </div>
        </section>
      </footer>
    `;
  }

  private renderMain(state: GeneratorState): string {
    if (state.bootState === "booting") {
      return renderSystemCard(
        "Preparing Generator",
        "Checking the local API and restoring the workspace state.",
      );
    }

    if (state.bootState === "error") {
      return `
        ${renderSystemCard(
          "Generator Unavailable",
          state.errorMessage ?? "The local API could not be reached.",
        )}
        <div class="wizard-actions">
          <button
            type="button"
            class="generator-primary-button"
            data-action="retry-bootstrap"
          >
            Retry Connection
          </button>
        </div>
      `;
    }

    if (state.currentStep === "upload") {
      return renderUploadStep(state, this.audioDropzoneActive);
    }

    if (state.currentStep === "metadata") {
      return renderMetadataStep(state, this.backgroundPreviewUrl ?? undefined);
    }

    if (state.currentStep === "difficulties") {
      return renderDifficultyStep(state);
    }

    if (state.currentStep === "generate") {
      return renderGenerationStep(state);
    }

    return renderResultsStep(state);
  }

  private async handleClick(event: MouseEvent): Promise<void> {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    const actionTarget = target.closest<HTMLElement>("[data-action]");
    if (!actionTarget) {
      return;
    }

    const action = actionTarget.dataset.action;
    if (!action) {
      return;
    }

    if (action === "pick-audio") {
      this.root
        .querySelector<HTMLInputElement>("#generator-audio-input")
        ?.click();
      return;
    }

    if (action === "pick-background") {
      this.root
        .querySelector<HTMLInputElement>("#generator-background-input")
        ?.click();
      return;
    }

    if (action === "continue-to-metadata") {
      this.setCurrentStep("metadata");
      return;
    }

    if (action === "back-to-upload") {
      this.setCurrentStep("upload");
      return;
    }

    if (action === "continue-to-difficulties") {
      const validation = validateMetadataDraft(this.store.getState().metadataDraft);
      if (validation.summary.length > 0) {
        this.setError(validation.summary[0]);
        return;
      }
      this.setCurrentStep("difficulties");
      return;
    }

    if (action === "back-to-metadata") {
      this.setCurrentStep("metadata");
      return;
    }

    if (action === "continue-to-generate") {
      await this.saveConfiguration();
      return;
    }

    if (action === "continue-to-results") {
      this.setCurrentStep("results");
      return;
    }

    if (action === "back-to-difficulties") {
      const job = this.store.getState().job;
      if (job && !isTerminalJobStatus(job.status)) {
        return;
      }
      this.setCurrentStep("difficulties");
      return;
    }

    if (action === "start-generation") {
      await this.startGeneration();
      return;
    }

    if (action === "cancel-generation") {
      await this.cancelGeneration();
      return;
    }

    if (action === "toggle-advanced-settings") {
      this.store.update((state) => ({
        ...state,
        advancedSettingsOpen: !state.advancedSettingsOpen,
      }));
      return;
    }

    if (action === "toggle-logs") {
      this.store.update((state) => ({
        ...state,
        logsExpanded: !state.logsExpanded,
      }));
      return;
    }

    if (action === "toggle-technical-details") {
      this.store.update((state) => ({
        ...state,
        technicalDetailsExpanded: !state.technicalDetailsExpanded,
      }));
      return;
    }

    if (action === "apply-detected-metadata") {
      const suggestion = this.store.getState().detectedMetadata;
      if (!suggestion) {
        return;
      }

      this.store.update((state) => ({
        ...state,
        metadataDraft: applyDetectedMetadataSuggestion(
          state.metadataDraft,
          suggestion,
        ),
        noticeMessage: "Applied detected title and artist fields.",
        errorMessage: undefined,
      }));
      return;
    }

    if (action === "toggle-difficulty") {
      const difficulty = actionTarget.dataset.difficulty as DifficultyName | undefined;
      if (!difficulty) {
        return;
      }

      this.toggleDifficulty(difficulty);
      return;
    }

    if (action === "set-mapping-preset") {
      const difficulty = actionTarget.dataset.difficulty as DifficultyName | undefined;
      const presetName = actionTarget.dataset.preset;
      if (!difficulty || !isMappingPresetName(presetName)) {
        return;
      }
      this.applyMappingPreset(difficulty, presetName);
      return;
    }

    if (action === "randomize-seed") {
      const difficulty = actionTarget.dataset.difficulty as DifficultyName | undefined;
      if (!difficulty) {
        return;
      }
      this.randomizeSeed(difficulty);
      return;
    }

    if (action === "apply-settings-to-all") {
      const difficulty = actionTarget.dataset.difficulty as DifficultyName | undefined;
      if (!difficulty) {
        return;
      }
      this.applySettingsToAllDifficulties(difficulty);
      return;
    }

    if (action === "jump-step") {
      const targetStep = actionTarget.dataset.step;
      if (
        isWizardStep(targetStep) &&
        canJumpToStep(targetStep, this.store.getState())
      ) {
        this.setCurrentStep(targetStep);
      }
      return;
    }

    if (action === "retry-bootstrap") {
      await this.bootstrap();
      return;
    }

    if (action === "dismiss-error") {
      this.store.update((state) => ({
        ...state,
        errorMessage: undefined,
      }));
      return;
    }

    if (action === "dismiss-notice") {
      this.store.update((state) => ({
        ...state,
        noticeMessage: undefined,
      }));
      return;
    }

    if (action === "copy-logs") {
      await this.copyLogsToClipboard();
      return;
    }

    if (action === "reset-workspace" || action === "start-new-song") {
      await this.startNewSong();
    }
  }

  private async handleChange(event: Event): Promise<void> {
    const target = event.target;
    if (
      !(target instanceof HTMLInputElement) &&
      !(target instanceof HTMLSelectElement)
    ) {
      return;
    }

    if (target instanceof HTMLSelectElement && target.dataset.setting && target.dataset.difficulty) {
      this.updateDifficultySetting(target);
      return;
    }

    if (target instanceof HTMLInputElement && target.id === "generator-audio-input") {
      const file = target.files?.[0];
      target.value = "";
      if (file) {
        await this.uploadAudio(file);
      }
      return;
    }

    if (target instanceof HTMLInputElement && target.id === "generator-background-input") {
      const file = target.files?.[0];
      target.value = "";
      if (file) {
        await this.uploadBackground(file);
      }
      return;
    }

    if (target.dataset.setting && target.dataset.difficulty) {
      this.updateDifficultySetting(target);
    }
  }

  private handleInput(event: Event): void {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.name) {
      if (target.dataset.setting && target.dataset.difficulty) {
        if (target.type !== "checkbox" && target.type !== "radio") {
          this.updateDifficultySetting(target);
        }
        return;
      }

      this.updateMetadataField(target.name, target.value);
      return;
    }

    if (target instanceof HTMLTextAreaElement && target.name) {
      this.updateMetadataField(target.name, target.value);
    }
  }

  private async handleDrop(event: DragEvent): Promise<void> {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    if (!target.closest("[data-dropzone='audio']")) {
      return;
    }

    event.preventDefault();
    this.setAudioDropzoneActive(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      await this.uploadAudio(file);
    }
  }

  private async uploadAudio(file: File): Promise<void> {
    const workspaceId = this.store.getState().workspace?.workspace.workspaceId;
    if (!workspaceId) {
      this.setError("Workspace is not ready yet. Retry once initialization completes.");
      return;
    }

    this.store.update((state) => ({
      ...state,
      errorMessage: undefined,
      noticeMessage: undefined,
      audioUpload: {
        status: "uploading",
        progressPercent: 0,
        fileName: file.name,
        fileSizeBytes: file.size,
      },
    }));

    try {
      const response = await this.api.uploadAudio(workspaceId, file, (percent) => {
        this.store.update((state) => ({
          ...state,
          audioUpload: {
            ...state.audioUpload,
            status: "uploading",
            progressPercent: percent,
            fileName: file.name,
            fileSizeBytes: file.size,
          },
        }));
      });

      this.store.update((state) => {
        const nextMetadataDraft = applyDetectedMetadataSuggestion(
          {
            ...state.metadataDraft,
            backgroundFilename:
              response.workspace.metadata.backgroundFilename ??
              state.metadataDraft.backgroundFilename,
          },
          response.detectedMetadata,
        );

        return {
          ...state,
          workspace: response,
          detectedMetadata: response.detectedMetadata,
          audioUpload: {
            status: "uploaded",
            progressPercent: 100,
            fileName: file.name,
            fileSizeBytes: file.size,
          },
          metadataDraft: nextMetadataDraft,
          currentStep: "metadata",
          errorMessage: undefined,
          noticeMessage: `Uploaded ${file.name} into the local workspace.`,
        };
      });
    } catch (error) {
      this.store.update((state) => ({
        ...state,
        audioUpload: {
          status: "error",
          progressPercent: 0,
          fileName: file.name,
          fileSizeBytes: file.size,
          error: toReadableError(error),
        },
        errorMessage: toReadableError(error),
      }));
    }
  }

  private async uploadBackground(file: File): Promise<void> {
    const workspaceId = this.store.getState().workspace?.workspace.workspaceId;
    if (!workspaceId) {
      this.setError("Workspace is not ready yet. Retry once initialization completes.");
      return;
    }

    this.store.update((state) => ({
      ...state,
      errorMessage: undefined,
      noticeMessage: undefined,
      backgroundUpload: {
        status: "uploading",
        progressPercent: 0,
        fileName: file.name,
        fileSizeBytes: file.size,
      },
    }));

    try {
      const response = await this.api.uploadBackground(
        workspaceId,
        file,
        (percent) => {
          this.store.update((state) => ({
            ...state,
            backgroundUpload: {
              ...state.backgroundUpload,
              status: "uploading",
              progressPercent: percent,
              fileName: file.name,
              fileSizeBytes: file.size,
            },
          }));
        },
      );

      this.replaceBackgroundPreviewUrl(URL.createObjectURL(file));
      // P1.2: decode the freshly uploaded track into waveform peaks.
      void this.loadWaveformFromFile(file);
      this.store.update((state) => ({
        ...state,
        workspace: response,
        metadataDraft: {
          ...state.metadataDraft,
          backgroundFilename:
            response.workspace.metadata.backgroundFilename ?? undefined,
        },
        backgroundUpload: {
          status: "uploaded",
          progressPercent: 100,
          fileName: file.name,
          fileSizeBytes: file.size,
        },
        errorMessage: undefined,
        noticeMessage: `Attached ${file.name} as the optional background image.`,
      }));
    } catch (error) {
      this.store.update((state) => ({
        ...state,
        backgroundUpload: {
          status: "error",
          progressPercent: 0,
          fileName: file.name,
          fileSizeBytes: file.size,
          error: toReadableError(error),
        },
        errorMessage: toReadableError(error),
      }));
    }
  }

  private updateMetadataField(fieldName: string, value: string): void {
    this.store.update((state) => ({
      ...state,
      metadataDraft: {
        ...state.metadataDraft,
        [fieldName]: value,
      },
      errorMessage: undefined,
    }));
  }

  private toggleDifficulty(difficulty: DifficultyName): void {
    this.store.update((state) => {
      const selected = state.metadataDraft.selectedDifficulties.includes(difficulty);
      const nextSelected = selected
        ? state.metadataDraft.selectedDifficulties.filter((item) => item !== difficulty)
        : [...state.metadataDraft.selectedDifficulties, difficulty];
      return {
        ...state,
        metadataDraft: {
          ...state.metadataDraft,
          selectedDifficulties: nextSelected.sort(sortDifficultyNames),
        },
        errorMessage: undefined,
      };
    });
  }

  private updateDifficultySetting(
    target: HTMLInputElement | HTMLSelectElement,
  ): void {
    const difficulty = target.dataset.difficulty as DifficultyName | undefined;
    const setting = target.dataset.setting;
    if (!difficulty || !setting) {
      return;
    }

    this.store.update((state) => {
      const currentSettings = state.metadataDraft.difficultySettings[difficulty];
      let nextValue: unknown;
      if (target instanceof HTMLSelectElement) {
        nextValue = target.value;
      } else if (target.type === "checkbox") {
        nextValue = target.checked;
      } else if (target.type === "radio") {
        nextValue = target.checked ? target.value : currentSettings[setting as keyof typeof currentSettings];
      } else if (target.dataset.scale === "percent") {
        nextValue = Math.min(1, Math.max(0, (Number(target.value) || 0) / 100));
      } else {
        nextValue = Math.max(0, Math.round(Number(target.value) || 0));
      }

      const nextSettings = {
        ...currentSettings,
        [setting]: nextValue,
        // Manual edits to any mapping control take precedence over the
        // stored preset; otherwise the backend would apply the preset's
        // values and the edit would have no effect.
        ...(MAPPING_CONTROL_KEYS.has(setting)
          ? { mappingPreset: "custom" as const }
          : {}),
      };
      return {
        ...state,
        metadataDraft: {
          ...state.metadataDraft,
          difficultySettings: {
            ...state.metadataDraft.difficultySettings,
            [difficulty]: nextSettings,
          },
        },
        errorMessage: undefined,
      };
    });
  }

  private applyMappingPreset(difficulty: DifficultyName, preset: MappingPresetName): void {
    this.store.update((state) => {
      const currentSettings = state.metadataDraft.difficultySettings[difficulty];
      return {
        ...state,
        metadataDraft: {
          ...state.metadataDraft,
          difficultySettings: {
            ...state.metadataDraft.difficultySettings,
            [difficulty]: applyMappingPresetToSettings(currentSettings, preset),
          },
        },
        errorMessage: undefined,
        noticeMessage: `Applied the ${preset} mapping preset to ${capitalize(difficulty)}.`,
      };
    });
  }

  private randomizeSeed(difficulty: DifficultyName): void {
    this.store.update((state) => {
      const currentSettings = state.metadataDraft.difficultySettings[difficulty];
      const randomSeed = Math.floor(Math.random() * 2_000_000_000);
      return {
        ...state,
        metadataDraft: {
          ...state.metadataDraft,
          difficultySettings: {
            ...state.metadataDraft.difficultySettings,
            [difficulty]: {
              ...currentSettings,
              rootSeed: randomSeed,
              seedMode: "manual",
            },
          },
        },
        errorMessage: undefined,
        noticeMessage: `Generated a random seed for ${capitalize(difficulty)}: ${randomSeed}`,
      };
    });
  }

  private async saveConfiguration(): Promise<boolean> {
    const state = this.store.getState();
    const workspaceId = state.workspace?.workspace.workspaceId;
    if (!workspaceId) {
      this.setError("Workspace is not ready yet.");
      return false;
    }

    // Materialize automatic seeds: a random seed is chosen now and becomes a
    // fixed manual seed so reruns of the same saved configuration stay
    // deterministic.
    this.store.update((current) => ({
      ...current,
      metadataDraft: materializeAutomaticSeeds(current.metadataDraft),
    }));
    const materialized = this.store.getState();

    const metadataErrors = validateMetadataDraft(materialized.metadataDraft);
    if (metadataErrors.summary.length > 0) {
      this.setError(metadataErrors.summary[0]);
      this.setCurrentStep("metadata");
      return false;
    }

    const difficultyErrors = validateDifficultySelection(materialized.metadataDraft);
    if (difficultyErrors.length > 0) {
      this.setError(difficultyErrors[0]);
      this.setCurrentStep("difficulties");
      return false;
    }

    this.store.update((current) => ({
      ...current,
      busyMessage: "Saving workspace metadata and difficulty settings...",
      errorMessage: undefined,
      noticeMessage: undefined,
    }));

    try {
      const response = await this.api.updateMetadata(
        workspaceId,
        materialized.metadataDraft,
      );
      this.store.update((current) => ({
        ...current,
        workspace: response,
        metadataDraft: cloneWorkspaceMetadata(response.workspace.metadata),
        currentStep: "generate",
        busyMessage: undefined,
        errorMessage: undefined,
        noticeMessage: "Saved metadata and generation settings.",
      }));
      return true;
    } catch (error) {
      this.store.update((current) => ({
        ...current,
        busyMessage: undefined,
        errorMessage: toReadableError(error),
      }));
      return false;
    }
  }

  private async startGeneration(): Promise<void> {
    const saved = await this.saveConfiguration();
    if (!saved) {
      return;
    }

    const state = this.store.getState();
    const workspaceId = state.workspace?.workspace.workspaceId;
    if (!workspaceId || !state.workspace?.readyForGeneration) {
      return;
    }

    this.store.update((current) => ({
      ...current,
      busyMessage: "Starting the local generation job...",
      errorMessage: undefined,
      noticeMessage: undefined,
    }));

    try {
      const job = await this.api.startGeneration(workspaceId);
      this.store.update((current) => ({
        ...current,
        job,
        jobId: job.jobId,
        currentStep: "generate",
        logsExpanded: true,
        busyMessage: undefined,
        noticeMessage: "Background generation job started.",
      }));
      this.startPolling(job.jobId);
    } catch (error) {
      this.store.update((current) => ({
        ...current,
        busyMessage: undefined,
        errorMessage: toReadableError(error),
      }));
    }
  }

  private async cancelGeneration(): Promise<void> {
    const jobId = this.store.getState().job?.jobId;
    if (!jobId) {
      return;
    }

    try {
      const job = await this.api.cancelJob(jobId);
      this.store.update((state) => ({
        ...state,
        job,
        noticeMessage:
          "Cancellation requested. The pipeline will stop between safe stage boundaries.",
        errorMessage: undefined,
      }));
    } catch (error) {
      this.setError(toReadableError(error));
    }
  }

  private startPolling(jobId: string): void {
    this.stopPolling();

    // P3.4: tail the bounded backend log — each poll requests only events
    // newer than the highest index we hold and merges them into the client
    // log (also capped), so neither side accumulates an unbounded array.
    let lastEventIndex = 0;

    const poll = async () => {
      try {
        const job = await this.api.getJob(jobId, lastEventIndex);
        const previousEvents = this.store.getState().job?.events ?? [];
        const merged = accumulateJobEvents(previousEvents, job.events);
        const nextJob: JobStateResponse = { ...job, events: merged };
        lastEventIndex = merged.reduce(
          (max, event) => Math.max(max, event.index),
          lastEventIndex,
        );
        this.store.update((state) => ({
          ...state,
          job: nextJob,
          jobId: job.jobId,
          currentStep:
            job.status === "completed" && (job.result || state.workspace?.workspace.lastResult)
              ? "results"
              : "generate",
          busyMessage: undefined,
        }));

        if (isTerminalJobStatus(job.status)) {
          this.stopPolling();
          const workspace = await this.api.getWorkspace(job.workspaceId);
          this.store.update((state) => ({
            ...state,
            workspace,
            currentStep:
              job.status === "completed" && (job.result || workspace.workspace.lastResult)
                ? "results"
                : "generate",
            noticeMessage:
              job.status === "completed"
                ? "Generation completed successfully."
                : job.status === "cancelled"
                  ? "Generation stopped after a safe cancellation point."
                  : state.noticeMessage,
          }));
          return;
        }
      } catch (error) {
        this.store.update((state) => ({
          ...state,
          errorMessage: toReadableError(error),
        }));
      }

      this.pollTimer = window.setTimeout(() => {
        void poll();
      }, 1000);
    };

    void poll();
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      window.clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private async startNewSong(): Promise<void> {
    const state = this.store.getState();
    const job = state.job;
    if (job && !isTerminalJobStatus(job.status)) {
      this.setError("Cancel the active generation job before starting a new song.");
      return;
    }

    const shouldDeleteCurrent = window.confirm(
      "Start a new local song workspace? This will delete the current workspace files.",
    );
    if (!shouldDeleteCurrent) {
      return;
    }

    const currentWorkspaceId = state.workspace?.workspace.workspaceId;
    this.stopPolling();
    this.store.update((current) => ({
      ...current,
      busyMessage: "Creating a fresh local workspace...",
      errorMessage: undefined,
      noticeMessage: undefined,
    }));

    try {
      if (currentWorkspaceId) {
        await this.api.deleteWorkspace(currentWorkspaceId);
      }
      this.replaceBackgroundPreviewUrl(null);
      this.waveformPeaks = null;
      const workspace = await this.api.createWorkspace();
      clearPersistedGeneratorState();
      this.store.setState({
        ...createInitialGeneratorState(),
        bootState: "ready",
        currentStep: "upload",
        workspace,
        metadataDraft: cloneWorkspaceMetadata(workspace.workspace.metadata),
        audioUpload: createInitialFileTransferState(),
        backgroundUpload: createInitialFileTransferState(),
        healthStatus: "ready",
        healthMessage: "Local API ready on 127.0.0.1:8765.",
        noticeMessage: "New workspace created. You can upload a different song now.",
      });
    } catch (error) {
      this.store.update((current) => ({
        ...current,
        busyMessage: undefined,
        errorMessage: toReadableError(error),
      }));
    }
  }

  private async copyLogsToClipboard(): Promise<void> {
    const job = this.store.getState().job;
    const logText = buildJobLogText(job);
    if (!logText.trim()) {
      this.store.update((state) => ({
        ...state,
        noticeMessage: "No logs are available to copy yet.",
        errorMessage: undefined,
      }));
      return;
    }

    try {
      await navigator.clipboard.writeText(logText);
      this.store.update((state) => ({
        ...state,
        noticeMessage: "Copied the current pipeline logs to the clipboard.",
        errorMessage: undefined,
      }));
    } catch (error) {
      this.store.update((state) => ({
        ...state,
        errorMessage: toReadableError(error),
      }));
    }
  }

  private setAudioDropzoneActive(isActive: boolean): void {
    if (this.audioDropzoneActive === isActive) {
      return;
    }

    this.audioDropzoneActive = isActive;
    if (this.store.getState().currentStep === "upload") {
      this.render(this.store.getState());
    }
  }

  private replaceBackgroundPreviewUrl(nextUrl: string | null): void {
    // Only blob URLs need revoking; the P1.1 server preview URLs are plain.
    if (this.backgroundPreviewUrl?.startsWith("blob:")) {
      URL.revokeObjectURL(this.backgroundPreviewUrl);
    }
    this.backgroundPreviewUrl = nextUrl;
  }

  private applySettingsToAllDifficulties(source: DifficultyName): void {
    this.store.update((state) => {
      const sourceSettings = state.metadataDraft.difficultySettings[source];
      const nextSettings = { ...state.metadataDraft.difficultySettings };
      let appliedCount = 0;

      for (const difficulty of state.metadataDraft.selectedDifficulties) {
        if (difficulty === source) {
          continue;
        }
        nextSettings[difficulty] = applySharedGenerationSettings(
          sourceSettings,
          nextSettings[difficulty],
        );
        appliedCount += 1;
      }

      return {
        ...state,
        metadataDraft: { ...state.metadataDraft, difficultySettings: nextSettings },
        errorMessage: undefined,
        noticeMessage:
          appliedCount > 0
            ? `Applied ${capitalize(source)} settings to ${appliedCount} other difficult${appliedCount === 1 ? "y" : "ies"}.`
            : `Select another difficulty before applying ${capitalize(source)} settings.`,
      };
    });
  }

  private async loadWaveformFromFile(file: File): Promise<void> {
    const peaks = await computeWaveformPeaks(file);
    this.waveformPeaks = peaks ?? null;
    this.drawActiveWaveform();
  }

  private async loadWaveformFromUrl(url: string): Promise<void> {
    const peaks = await computeWaveformPeaks(url);
    this.waveformPeaks = peaks ?? null;
    this.drawActiveWaveform();
  }

  private drawActiveWaveform(): void {
    if (typeof document === "undefined") {
      return;
    }

    const canvas = this.root.querySelector<HTMLCanvasElement>(
      "canvas[data-role='generator-waveform']",
    );
    if (canvas) {
      drawGeneratorWaveform(canvas, this.waveformPeaks ?? undefined);
    }
  }

  private setCurrentStep(step: WizardStep): void {
    this.store.update((state) => ({
      ...state,
      currentStep: step,
      errorMessage: undefined,
    }));
  }

  private setError(message: string): void {
    this.store.update((state) => ({
      ...state,
      errorMessage: message,
    }));
  }
}

function materializeAutomaticSeeds(
  metadata: WorkspaceMetadata,
): WorkspaceMetadata {
  let changed = false;
  const difficultySettings = { ...metadata.difficultySettings };
  for (const difficulty of metadata.selectedDifficulties) {
    const settings = difficultySettings[difficulty];
    if (settings.seedMode !== "auto") {
      continue;
    }
    const randomSeed = Math.floor(Math.random() * 2_000_000_000);
    difficultySettings[difficulty] = {
      ...settings,
      rootSeed: randomSeed,
      seedMode: "manual",
    };
    changed = true;
  }
  if (!changed) {
    return metadata;
  }
  return {
    ...metadata,
    difficultySettings,
  };
}

function renderBusyBanner(message: string | undefined): string {
  if (!message) {
    return "";
  }

  return `
    <div class="status-banner status-banner--busy">
      <strong>Working locally</strong>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
}

function renderMessageBanner(
  kind: "error" | "notice",
  message: string | undefined,
): string {
  if (!message) {
    return "";
  }

  const action = kind === "error" ? "dismiss-error" : "dismiss-notice";
  return `
    <div class="status-banner status-banner--${kind}">
      <div>
        <strong>${kind === "error" ? "Attention" : "Status Update"}</strong>
        <p>${escapeHtml(message)}</p>
      </div>
      <button
        type="button"
        class="generator-ghost-button"
        data-action="${action}"
      >
        Dismiss
      </button>
    </div>
  `;
}

function renderSystemCard(title: string, message: string): string {
  return `
    <section class="wizard-stage-panel system-card">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Generator</p>
        <h2>${escapeHtml(title)}</h2>
        <p>${escapeHtml(message)}</p>
      </div>
    </section>
  `;
}

function buildTransferStateFromWorkspaceFile(
  file:
    | WorkspaceResponse["workspace"]["audio"]
    | WorkspaceResponse["workspace"]["background"]
    | undefined
    | null,
): FileTransferState {
  if (!file) {
    return createInitialFileTransferState();
  }

  return {
    status: "uploaded",
    progressPercent: 100,
    fileName: file.originalFilename,
    fileSizeBytes: file.sizeBytes,
  };
}

function hydrateMetadataDraftFromPersistence(
  persisted: GeneratorState["metadataDraft"],
  workspaceMetadata: WorkspaceResponse["workspace"]["metadata"],
) {
  return {
    ...cloneWorkspaceMetadata(persisted),
    backgroundFilename:
      persisted.backgroundFilename ?? workspaceMetadata.backgroundFilename ?? undefined,
  };
}

function resolveModeLabel(status: GeneratorState["healthStatus"]): string {
  if (status === "ready") {
    return "LOCAL API READY";
  }
  if (status === "error") {
    return "API OFFLINE";
  }
  return "CHECKING API";
}

function extractApiEndpoint(message: string): string | undefined {
  const match = message.match(/\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b/);
  return match?.[0];
}

function getWizardStepState(
  step: WizardStep,
  state: GeneratorState,
): "completed" | "active" | "upcoming" | "error" {
  const currentIndex = STEP_ORDER.indexOf(state.currentStep);
  const stepIndex = STEP_ORDER.indexOf(step);
  const jobFailed =
    step === "generate" &&
    state.currentStep === "generate" &&
    (state.job?.status === "failed" || state.job?.status === "cancelled");

  if (jobFailed) {
    return "error";
  }
  if (step === state.currentStep) {
    return "active";
  }
  if (stepIndex < currentIndex) {
    return "completed";
  }
  return "upcoming";
}

function renderWizardStepGlyph(
  state: "completed" | "active" | "upcoming" | "error",
  stepNumber: number,
): string {
  if (state === "completed") {
    return renderIcon("check");
  }
  if (state === "error") {
    return renderIcon("warning");
  }
  return `${stepNumber}`;
}

function renderSidebarTile(params: {
  icon: string;
  label: string;
  status: string;
  accent: "success" | "warning" | "danger" | "muted";
  lines: string[];
}): string {
  const lines = params.lines.filter((line) => line.trim().length > 0);
  return `
    <article class="sidebar-status-card">
      <div class="sidebar-status-head">
        <span class="sidebar-icon-box sidebar-icon-box--small">
          ${params.icon}
        </span>
        <div class="sidebar-status-copy">
          <p class="section-eyebrow">${escapeHtml(params.label)}</p>
          <span class="sidebar-status-badge sidebar-status-badge--${params.accent}">
            ${escapeHtml(params.status)}
          </span>
        </div>
      </div>
      <div class="sidebar-status-lines">
        ${lines
          .map((line, index) => {
            const tag = index === 0 ? "strong" : "span";
            return `<${tag}>${escapeHtml(line)}</${tag}>`;
          })
          .join("")}
      </div>
    </article>
  `;
}

function resolveTransferStateLabel(
  status: FileTransferState["status"],
  idleLabel: string,
): string {
  if (status === "uploading") {
    return "Uploading";
  }
  if (status === "uploaded") {
    return "Uploaded";
  }
  if (status === "error") {
    return "Needs attention";
  }
  return idleLabel;
}

function buildAudioMetadataLine(
  file: NonNullable<WorkspaceResponse["workspace"]["audio"]>,
): string {
  const parts: string[] = [];
  if (file.detectedMetadata?.durationMs) {
    parts.push(formatClockTimeMs(file.detectedMetadata.durationMs));
  }
  if (file.detectedMetadata?.codec) {
    parts.push(file.detectedMetadata.codec.toUpperCase());
  }
  if (file.detectedMetadata?.bitrateKbps) {
    parts.push(`${file.detectedMetadata.bitrateKbps} kbps`);
  }
  return parts.join(" / ") || "Metadata scan pending";
}

function formatFileType(filename: string, contentType: string): string {
  const extension = filename.split(".").at(-1)?.trim();
  if (extension) {
    return extension.toUpperCase();
  }
  if (contentType.includes("/")) {
    return contentType.split("/").at(-1)?.toUpperCase() ?? contentType;
  }
  return contentType.toUpperCase();
}

function resolveJobAccent(
  status: JobStateResponse["status"] | WorkspaceResponse["workspace"]["jobStatus"] | null,
): "success" | "warning" | "danger" | "muted" {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "running" || status === "queued" || status === "cancelled") {
    return "warning";
  }
  return "muted";
}

function renderFooterLink(
  href: string,
  label: string,
  icon: Parameters<typeof renderIcon>[0],
  external = href.endsWith(".md"),
): string {
  return `
    <a
      class="footer-link"
      href="${escapeHtml(href)}"
      ${external ? 'target="_blank" rel="noreferrer"' : ""}
    >
      ${renderIcon(icon)}
      <span>${escapeHtml(label)}</span>
    </a>
  `;
}

function renderFooterIconLink(
  href: string,
  label: string,
  icon: Parameters<typeof renderIcon>[0],
  external = false,
): string {
  return `
    <a
      class="footer-icon-link"
      href="${escapeHtml(href)}"
      aria-label="${escapeHtml(label)}"
      ${external ? 'target="_blank" rel="noreferrer"' : ""}
    >
      ${renderIcon(icon)}
    </a>
  `;
}

function buildJobLogText(job: JobStateResponse | undefined): string {
  if (!job || job.events.length === 0) {
    return "";
  }

  return job.events
    .map(
      (event) =>
        `[${event.timestamp}] ${event.level.toUpperCase()} ${event.message}`,
    )
    .join("\n");
}

interface FocusSnapshot {
  id: string;
  selectionStart: number | null;
  selectionEnd: number | null;
  selectionDirection: "forward" | "backward" | "none" | null;
}

/**
 * P1.3: record the focused control and caret so ``render()`` can restore them
 * after its innerHTML swap. Returns null when nothing relevant is focused.
 */
function captureFocusSnapshot(root: HTMLElement): FocusSnapshot | null {
  if (typeof document === "undefined") {
    return null;
  }

  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !active.id || !root.contains(active)) {
    return null;
  }

  const selectable = active as HTMLInputElement | HTMLTextAreaElement;
  const supportsSelection = typeof selectable.selectionStart === "number";
  return {
    id: active.id,
    selectionStart: supportsSelection ? selectable.selectionStart : null,
    selectionEnd: supportsSelection ? selectable.selectionEnd : null,
    selectionDirection: supportsSelection ? selectable.selectionDirection : null,
  };
}

function restoreFocusSnapshot(
  root: HTMLElement,
  snapshot: FocusSnapshot | null,
): void {
  if (!snapshot || typeof document === "undefined") {
    return;
  }

  const idSelector =
    typeof CSS !== "undefined" && typeof CSS.escape === "function"
      ? CSS.escape(snapshot.id)
      : snapshot.id;
  const element = root.querySelector<HTMLElement>(`#${idSelector}`);
  if (!element) {
    return;
  }

  element.focus({ preventScroll: true });
  if (snapshot.selectionStart === null || snapshot.selectionEnd === null) {
    return;
  }

  const selectable = element as HTMLInputElement | HTMLTextAreaElement;
  try {
    selectable.setSelectionRange(
      snapshot.selectionStart,
      snapshot.selectionEnd,
      snapshot.selectionDirection ?? undefined,
    );
  } catch {
    // Some input types (e.g. number) reject selection ranges; focus still wins.
  }
}

function canJumpToStep(step: WizardStep, state: GeneratorState): boolean {
  const currentIndex = STEP_ORDER.indexOf(state.currentStep);
  const targetIndex = STEP_ORDER.indexOf(step);
  if (targetIndex < 0) {
    return false;
  }

  if (targetIndex > currentIndex) {
    return false;
  }

  const job = state.job;
  return !(
    job &&
    !isTerminalJobStatus(job.status) &&
    targetIndex < currentIndex &&
    step !== "generate"
  );
}

function sortDifficultyNames(left: DifficultyName, right: DifficultyName): number {
  return DIFFICULTY_ORDER[left] - DIFFICULTY_ORDER[right];
}

function stepLabel(step: WizardStep): string {
  if (step === "upload") {
    return "Upload";
  }
  if (step === "metadata") {
    return "Metadata";
  }
  if (step === "difficulties") {
    return "Difficulties";
  }
  if (step === "generate") {
    return "Generate";
  }
  return "Results";
}

function capitalize(value: string): string {
  if (!value) {
    return value;
  }

  return `${value[0]?.toUpperCase() ?? ""}${value.slice(1)}`;
}

function toReadableError(error: unknown): string {
  if (error instanceof GeneratorApiError) {
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "An unexpected local generator error occurred.";
}
