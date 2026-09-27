import type {
  DifficultyName,
  DifficultySettings,
  WorkspaceMetadata,
} from "../GeneratorModels";
import {
  DIFFICULTY_CARDS,
  MAPPING_CONTROLS,
  MAPPING_PRESETS,
  REPLAY_PROFILES,
  capitalize,
  findMappingPreset,
  toPercent,
} from "../GeneratorModels";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml } from "../../shared/format";

export function renderDifficultySelector(params: {
  metadata: WorkspaceMetadata;
  advancedSettingsOpen: boolean;
  errors: string[];
  warnings: string[];
}): string {
  const cards = DIFFICULTY_CARDS.map((card) => {
    const selected = params.metadata.selectedDifficulties.includes(card.difficulty);
    const settings = params.metadata.difficultySettings[card.difficulty];

    return `
      <button
        type="button"
        class="difficulty-card ${selected ? "is-selected" : ""}"
        data-action="toggle-difficulty"
        data-difficulty="${card.difficulty}"
      >
        <div class="difficulty-card-head">
          <div>
            <span class="section-eyebrow">${escapeHtml(card.label)}</span>
            <strong>${selected ? "Selected" : "Available"}</strong>
          </div>
          <span class="difficulty-card-state difficulty-card-state--${selected ? "selected" : "idle"}">
            ${selected ? "ACTIVE" : "READY"}
          </span>
        </div>
        <p>${escapeHtml(card.description)}</p>
        <dl class="difficulty-metrics">
          <div>
            <dt>Mapping Preset</dt>
            <dd>${presetLabel(settings.mappingPreset)}</dd>
          </div>
          <div>
            <dt>Candidate Count</dt>
            <dd>${settings.candidateCount}</dd>
          </div>
          <div>
            <dt>Root Seed</dt>
            <dd>${settings.seedMode === "auto" ? "Auto" : settings.rootSeed}</dd>
          </div>
        </dl>
      </button>
    `;
  }).join("");

  const advancedMarkup = params.advancedSettingsOpen
    ? DIFFICULTY_CARDS.map((card) =>
        renderAdvancedSettings(card.difficulty, params.metadata),
      ).join("")
    : "";

  const errorsMarkup = params.errors.length
    ? `
      <div class="form-error-list">
        ${params.errors
          .map((message) => `<p>${escapeHtml(message)}</p>`)
          .join("")}
      </div>
    `
    : "";

  const warningsMarkup = params.warnings.length
    ? `
      <div class="form-warning-list">
        ${params.warnings
          .map(
            (message) => `
              <p>
                ${renderIcon("warning", "form-warning-icon")}
                <span>${escapeHtml(message)}</span>
              </p>
            `,
          )
          .join("")}
      </div>
    `
    : "";

  return `
    <div class="panel-section-group">
      <section class="panel-subsection">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Difficulty Cards</p>
            <h3>Choose Output Modes</h3>
            <p>Each difficulty keeps its own candidate counts, tournament behavior, and hybrid settings.</p>
          </div>
        </div>
        <div class="difficulty-card-grid">${cards}</div>
      </section>

      <section class="panel-subsection" id="difficulty-settings">
        <div class="advanced-settings-head">
          <div>
            <p class="section-eyebrow">Mapping Controls</p>
            <h3>Per-Difficulty Mapping Settings</h3>
            <p>Every control below changes the real generation parameters: event selection, spacing, sliders, spinners, patterns, and evolution ranking.</p>
          </div>
          <button
            type="button"
            class="generator-secondary-button"
            data-action="toggle-advanced-settings"
          >
            ${params.advancedSettingsOpen ? "Hide Mapping Controls" : "Show Mapping Controls"}
          </button>
        </div>

        ${
          params.advancedSettingsOpen
            ? `<div class="advanced-settings-grid">${advancedMarkup}</div>`
            : `<p class="muted-copy">Mapping controls stay collapsed to keep the main selection flow compact.</p>`
        }
        ${warningsMarkup}
        ${errorsMarkup}
      </section>
    </div>
  `;
}

function renderAdvancedSettings(
  difficulty: DifficultyName,
  metadata: WorkspaceMetadata,
): string {
  const settings = metadata.difficultySettings[difficulty];
  const disabled = !metadata.selectedDifficulties.includes(difficulty);
  const disabledAttribute = disabled ? "disabled" : "";

  return `
    <section class="advanced-card ${disabled ? "is-disabled" : ""}">
      <div class="advanced-card-head">
        <div>
          <h3>${capitalize(difficulty)}</h3>
          <p>${disabled ? "Enable this difficulty card first." : "Deterministic settings for this output tier."}</p>
        </div>
        <span class="sidebar-status-badge sidebar-status-badge--${disabled ? "muted" : "success"}">
          ${disabled ? "Locked" : "Enabled"}
        </span>
      </div>

      ${renderPresetPicker(difficulty, settings, disabledAttribute)}
      ${renderMappingSliders(difficulty, settings, disabledAttribute)}
      ${renderDifficultyTarget(difficulty, settings, disabledAttribute)}
      ${renderAdvancedFields(difficulty, settings, disabledAttribute)}
    </section>
  `;
}

function renderPresetPicker(
  difficulty: DifficultyName,
  settings: DifficultySettings,
  disabledAttribute: string,
): string {
  return `
    <div class="mapping-preset-block">
      <p class="mapping-section-label">Preset</p>
      <div class="mapping-preset-row" role="group" aria-label="Mapping preset for ${difficulty}">
        ${MAPPING_PRESETS.map((preset) => {
          const active = settings.mappingPreset === preset.name;
          return `
            <button
              type="button"
              class="mapping-preset-chip ${active ? "is-active" : ""}"
              data-action="set-mapping-preset"
              data-difficulty="${difficulty}"
              data-preset="${preset.name}"
              title="${escapeHtml(preset.description)}"
              ${disabledAttribute}
            >
              ${preset.label}
            </button>
          `;
        }).join("")}
        <button
          type="button"
          class="mapping-preset-chip ${settings.mappingPreset === "custom" ? "is-active" : ""}"
          data-action="set-mapping-preset"
          data-difficulty="${difficulty}"
          data-preset="custom"
          title="Use your exact settings below."
          ${disabledAttribute}
        >
          Custom
        </button>
      </div>
      <p class="mapping-preset-description">${presetDescription(settings.mappingPreset)}</p>
    </div>
  `;
}

function renderMappingSliders(
  difficulty: DifficultyName,
  settings: DifficultySettings,
  disabledAttribute: string,
): string {
  return `
    <div class="mapping-controls-grid">
      ${MAPPING_CONTROLS.map((control) => {
        const value = settings[control.key];
        const percent = toPercent(value);
        const isSpinner = control.key === "spinnerFrequency";
        const valueLabel =
          isSpinner && percent === 0 ? "None" : `${percent}%`;
        return `
          <label class="mapping-control" for="difficulty-${difficulty}-${control.key}">
            <span class="mapping-control-head">
              <span class="mapping-control-label">${control.label}</span>
              <output class="mapping-control-value" for="difficulty-${difficulty}-${control.key}">
                ${valueLabel}
              </output>
            </span>
            <input
              id="difficulty-${difficulty}-${control.key}"
              type="range"
              min="0"
              max="100"
              step="1"
              data-difficulty="${difficulty}"
              data-setting="${control.key}"
              data-scale="percent"
              value="${percent}"
              aria-label="${control.label} for ${difficulty}"
              ${disabledAttribute}
            />
            <span class="mapping-control-ends">
              <span>${escapeHtml(control.lowLabel)}</span>
              <span>${escapeHtml(control.highLabel)}</span>
            </span>
            <span class="mapping-control-hint">${escapeHtml(control.hint)}</span>
          </label>
        `;
      }).join("")}
    </div>
  `;
}

function renderDifficultyTarget(
  difficulty: DifficultyName,
  settings: DifficultySettings,
  disabledAttribute: string,
): string {
  const custom = settings.difficultyTarget === "custom";
  return `
    <div class="mapping-target-block">
      <p class="mapping-section-label">Difficulty Target</p>
      <div class="mapping-radio-row" role="group" aria-label="Difficulty target for ${difficulty}">
        <label class="mapping-radio">
          <input
            type="radio"
            name="difficulty-${difficulty}-difficulty-target"
            data-difficulty="${difficulty}"
            data-setting="difficultyTarget"
            value="auto"
            ${custom ? "" : "checked"}
            ${disabledAttribute}
          />
          <span>Auto (match difficulty)</span>
        </label>
        <label class="mapping-radio">
          <input
            type="radio"
            name="difficulty-${difficulty}-difficulty-target"
            data-difficulty="${difficulty}"
            data-setting="difficultyTarget"
            value="custom"
            ${custom ? "checked" : ""}
            ${disabledAttribute}
          />
          <span>Custom stars</span>
        </label>
      </div>
      ${
        custom
          ? `
          <div class="mapping-star-fields">
            ${renderStarField(difficulty, "customMinStar", "Min Stars", settings.customMinStar, disabledAttribute)}
            ${renderStarField(difficulty, "customTargetStar", "Target Stars", settings.customTargetStar, disabledAttribute)}
            ${renderStarField(difficulty, "customMaxStar", "Max Stars", settings.customMaxStar, disabledAttribute)}
          </div>
        `
          : `<p class="mapping-control-hint">The tier's own star band is used for difficulty analysis and evolution ranking.</p>`
      }
    </div>
  `;
}

function renderStarField(
  difficulty: DifficultyName,
  setting: "customTargetStar" | "customMinStar" | "customMaxStar",
  label: string,
  value: number | null | undefined,
  disabledAttribute: string,
): string {
  return `
    <label class="field" for="difficulty-${difficulty}-${setting}">
      <span>${label}</span>
      <input
        id="difficulty-${difficulty}-${setting}"
        type="number"
        min="0.5"
        max="12"
        step="0.1"
        data-difficulty="${difficulty}"
        data-setting="${setting}"
        value="${typeof value === "number" ? value : ""}"
        placeholder="stars"
        ${disabledAttribute}
      />
    </label>
  `;
}

function renderAdvancedFields(
  difficulty: DifficultyName,
  settings: DifficultySettings,
  disabledAttribute: string,
): string {
  return `
    <div class="advanced-card-grid advanced-card-grid--phase19">
      ${renderNumberField(
        difficulty,
        "candidateCount",
        "Candidate Count",
        settings.candidateCount,
        1,
        64,
        disabledAttribute,
      )}
      ${renderNumberField(
        difficulty,
        "evolutionPasses",
        "Evolution Passes",
        settings.evolutionPasses,
        1,
        5,
        disabledAttribute,
      )}
      ${renderSeedField(difficulty, settings, disabledAttribute)}
      ${renderSelectField(
        difficulty,
        "replayProfile",
        "Replay Profile",
        settings.replayProfile,
        REPLAY_PROFILES,
        disabledAttribute,
      )}
      ${renderPercentField(
        difficulty,
        "sectionSensitivity",
        "Section Sensitivity",
        settings.sectionSensitivity,
        disabledAttribute,
      )}
      ${renderToggleField(
        difficulty,
        "timingVariation",
        "Timing Variation",
        settings.timingVariation,
        disabledAttribute,
      )}
      ${renderToggleField(
        difficulty,
        "tournamentEnabled",
        "Tournament Mode",
        settings.tournamentEnabled,
        disabledAttribute,
      )}
      ${renderToggleField(
        difficulty,
        "hybridAssemblyEnabled",
        "Hybrid Assembly",
        settings.hybridAssemblyEnabled,
        disabledAttribute,
      )}
    </div>
  `;
}

function renderSeedField(
  difficulty: DifficultyName,
  settings: DifficultySettings,
  disabledAttribute: string,
): string {
  const automatic = settings.seedMode === "auto";
  return `
    <div class="field mapping-seed-field">
      <span>Generation Seed</span>
      <div class="mapping-seed-controls">
        <label class="mapping-radio mapping-radio--compact">
          <input
            type="radio"
            name="difficulty-${difficulty}-seed-mode"
            data-difficulty="${difficulty}"
            data-setting="seedMode"
            value="auto"
            ${automatic ? "checked" : ""}
            ${disabledAttribute}
          />
          <span>Auto</span>
        </label>
        <label class="mapping-radio mapping-radio--compact">
          <input
            type="radio"
            name="difficulty-${difficulty}-seed-mode"
            data-difficulty="${difficulty}"
            data-setting="seedMode"
            value="manual"
            ${automatic ? "" : "checked"}
            ${disabledAttribute}
          />
          <span>Manual</span>
        </label>
        <input
          id="difficulty-${difficulty}-rootSeed"
          type="number"
          min="0"
          data-difficulty="${difficulty}"
          data-setting="rootSeed"
          value="${settings.rootSeed}"
          ${automatic ? "disabled" : disabledAttribute}
          aria-label="Root seed for ${difficulty}"
        />
        <button
          type="button"
          class="generator-ghost-button mapping-seed-randomize"
          data-action="randomize-seed"
          data-difficulty="${difficulty}"
          title="Generate a random seed"
          ${disabledAttribute}
        >
          ${renderIcon("refresh")}
        </button>
      </div>
      <span class="mapping-control-hint">${automatic ? "A random seed is locked in when you save this configuration." : "Identical seed + identical configuration reproduces identical maps."}</span>
    </div>
  `;
}

function renderNumberField(
  difficulty: DifficultyName,
  setting: "candidateCount" | "evolutionPasses",
  label: string,
  value: number,
  min: number,
  max: number,
  disabledAttribute: string,
): string {
  return `
    <label class="field" for="difficulty-${difficulty}-${setting}">
      <span>${label}</span>
      <input
        id="difficulty-${difficulty}-${setting}"
        type="number"
        min="${min}"
        max="${max}"
        data-difficulty="${difficulty}"
        data-setting="${setting}"
        value="${value}"
        ${disabledAttribute}
      />
    </label>
  `;
}

function renderPercentField(
  difficulty: DifficultyName,
  setting: "sectionSensitivity",
  label: string,
  value: number,
  disabledAttribute: string,
): string {
  const percent = toPercent(value);
  return `
    <label class="mapping-control" for="difficulty-${difficulty}-${setting}">
      <span class="mapping-control-head">
        <span class="mapping-control-label">${label}</span>
        <output class="mapping-control-value" for="difficulty-${difficulty}-${setting}">
          ${percent}%
        </output>
      </span>
      <input
        id="difficulty-${difficulty}-${setting}"
        type="range"
        min="0"
        max="100"
        step="1"
        data-difficulty="${difficulty}"
        data-setting="${setting}"
        data-scale="percent"
        value="${percent}"
        aria-label="${label} for ${difficulty}"
        ${disabledAttribute}
      />
      <span class="mapping-control-ends">
        <span>Fewer</span>
        <span>More</span>
      </span>
    </label>
  `;
}

function renderSelectField(
  difficulty: DifficultyName,
  setting: "replayProfile",
  label: string,
  value: string,
  options: Array<{ value: string; label: string }>,
  disabledAttribute: string,
): string {
  return `
    <label class="field" for="difficulty-${difficulty}-${setting}">
      <span>${label}</span>
      <select
        id="difficulty-${difficulty}-${setting}"
        data-difficulty="${difficulty}"
        data-setting="${setting}"
        ${disabledAttribute}
      >
        ${options
          .map(
            (option) =>
              `<option value="${option.value}" ${option.value === value ? "selected" : ""}>${escapeHtml(option.label)}</option>`,
          )
          .join("")}
      </select>
    </label>
  `;
}

function renderToggleField(
  difficulty: DifficultyName,
  setting:
    | "timingVariation"
    | "tournamentEnabled"
    | "hybridAssemblyEnabled",
  label: string,
  checked: boolean,
  disabledAttribute: string,
): string {
  return `
    <label class="toggle-field" for="difficulty-${difficulty}-${setting}">
      <input
        id="difficulty-${difficulty}-${setting}"
        type="checkbox"
        data-difficulty="${difficulty}"
        data-setting="${setting}"
        ${checked ? "checked" : ""}
        ${disabledAttribute}
      />
      <span>${label}</span>
      ${renderIcon("check", "toggle-field-icon")}
    </label>
  `;
}

function presetLabel(name: string): string {
  const preset = findMappingPreset(name);
  return preset ? preset.label : "Custom";
}

function presetDescription(name: string): string {
  const preset = findMappingPreset(name);
  return preset ? preset.description : "Uses your exact settings below.";
}
