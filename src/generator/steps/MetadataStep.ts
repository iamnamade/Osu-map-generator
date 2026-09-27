import type { GeneratorState } from "../GeneratorModels";
import { validateMetadataDraft } from "../GeneratorValidation";
import { renderMetadataForm } from "../components/MetadataForm";

export function renderMetadataStep(
  state: GeneratorState,
  backgroundPreviewUrl?: string,
): string {
  const validation = validateMetadataDraft(state.metadataDraft);
  const continueDisabled = validation.summary.length > 0;

  return `
    <section class="wizard-stage-panel">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Step 2</p>
        <h2>Confirm Metadata</h2>
        <p>Review the detected song info, confirm editable fields, and optionally attach background art for the exported mapset.</p>
      </div>

      ${renderMetadataForm({
        metadata: state.metadataDraft,
        validation,
        detectedMetadata: state.detectedMetadata,
        backgroundUpload: state.backgroundUpload,
        workspace: state.workspace,
        backgroundPreviewUrl,
      })}

      <div class="panel-actions">
        <button
          type="button"
          class="generator-secondary-button"
          data-action="back-to-upload"
        >
          Back
        </button>
        <button
          type="button"
          class="generator-primary-button"
          data-action="continue-to-difficulties"
          ${continueDisabled ? "disabled" : ""}
        >
          Continue To Difficulties
        </button>
      </div>
    </section>
  `;
}
