import type { GeneratorState } from "../GeneratorModels";
import { renderDifficultySelector } from "../components/DifficultySelector";
import {
  validateDifficultySelection,
  validateMappingWarnings,
} from "../GeneratorValidation";

export function renderDifficultyStep(state: GeneratorState): string {
  const errors = validateDifficultySelection(state.metadataDraft);
  const warnings = validateMappingWarnings(state.metadataDraft);
  const continueDisabled = errors.length > 0;

  return `
    <section class="wizard-stage-panel">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Step 3</p>
        <h2>Select Difficulties</h2>
        <p>Choose the output tiers you want to generate, then tune the deterministic per-difficulty mapping controls.</p>
      </div>

      ${renderDifficultySelector({
        metadata: state.metadataDraft,
        advancedSettingsOpen: state.advancedSettingsOpen,
        errors,
        warnings,
      })}

      <div class="panel-actions">
        <button
          type="button"
          class="generator-secondary-button"
          data-action="back-to-metadata"
        >
          Back
        </button>
        <button
          type="button"
          class="generator-primary-button"
          data-action="continue-to-generate"
          ${continueDisabled ? "disabled" : ""}
        >
          Save Configuration
        </button>
      </div>
    </section>
  `;
}
