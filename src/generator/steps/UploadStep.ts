import type { GeneratorState } from "../GeneratorModels";
import { renderAudioDropzone } from "../components/AudioDropzone";
import { renderIcon } from "../components/GeneratorIcons";

export function renderUploadStep(
  state: GeneratorState,
  isAudioDropzoneActive: boolean,
): string {
  const continueDisabled = !state.workspace?.workspace.audio;
  return `
    <section class="wizard-stage-panel wizard-stage-panel--upload">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Step 1</p>
        <h2>Upload Song</h2>
        <p>Drag an audio file here or browse from disk. The file stays local and is stored inside an isolated workspace.</p>
      </div>

      ${renderAudioDropzone({
        audioUpload: state.audioUpload,
        workspace: state.workspace,
        isDragActive: isAudioDropzoneActive,
      })}

      <div class="panel-actions panel-actions--end">
        <button
          type="button"
          class="generator-primary-button"
          data-action="continue-to-metadata"
          ${continueDisabled ? "disabled" : ""}
        >
          Continue To Metadata
          ${renderIcon("arrow-right")}
        </button>
      </div>
    </section>
  `;
}
