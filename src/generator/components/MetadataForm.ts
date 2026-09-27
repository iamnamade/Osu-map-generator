import type {
  AudioMetadataSuggestion,
  FileTransferState,
  WorkspaceMetadata,
  WorkspaceResponse,
} from "../GeneratorModels";
import { formatBytes } from "../GeneratorModels";
import type { MetadataValidationResult } from "../GeneratorValidation";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml, formatClockTimeMs } from "../../shared/format";

export function renderMetadataForm(params: {
  metadata: WorkspaceMetadata;
  validation: MetadataValidationResult;
  detectedMetadata?: AudioMetadataSuggestion;
  backgroundUpload: FileTransferState;
  workspace?: WorkspaceResponse;
  backgroundPreviewUrl?: string;
}): string {
  const background = params.workspace?.workspace.background;
  const backgroundProgressMarkup =
    params.backgroundUpload.status === "uploading"
      ? `
        <div class="upload-progress upload-progress--compact">
          <div class="upload-progress-copy">
            <strong>Uploading ${escapeHtml(params.backgroundUpload.fileName ?? "background image")}</strong>
            <span>${params.backgroundUpload.progressPercent}% complete</span>
          </div>
          <div class="upload-progress-track">
            <span style="width: ${params.backgroundUpload.progressPercent}%"></span>
          </div>
        </div>
      `
      : "";

  const backgroundErrorMarkup = params.backgroundUpload.error
    ? `<p class="form-error">${escapeHtml(params.backgroundUpload.error)}</p>`
    : "";

  return `
    <div class="panel-section-group">
      ${renderDetectedMetadataSuggestion(params.detectedMetadata)}

      <section class="panel-subsection">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Core Metadata</p>
            <h3>Required Song Fields</h3>
            <p>These values define the exported mapset identity and stay editable until generation begins.</p>
          </div>
        </div>
        <div class="metadata-grid">
          ${renderField(
            "Title",
            "generator-field-title",
            "title",
            params.metadata.title,
            params.validation.fieldErrors.title,
            "Main song title shown in the final package.",
          )}
          ${renderField(
            "Artist",
            "generator-field-artist",
            "artist",
            params.metadata.artist,
            params.validation.fieldErrors.artist,
            "Performer or original artist name.",
          )}
          ${renderField(
            "Creator",
            "generator-field-creator",
            "creator",
            params.metadata.creator,
            params.validation.fieldErrors.creator,
            "Local creator tag preserved in exported files.",
          )}
        </div>
      </section>

      <section class="panel-subsection">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Optional Metadata</p>
            <h3>Additional Tagging</h3>
            <p>Unicode fields, source, and tags remain optional but help keep the workspace organized.</p>
          </div>
        </div>
        <div class="metadata-grid">
          ${renderField(
            "Unicode Title",
            "generator-field-title-unicode",
            "titleUnicode",
            params.metadata.titleUnicode ?? "",
            undefined,
            "Use if the song title should keep native characters.",
          )}
          ${renderField(
            "Unicode Artist",
            "generator-field-artist-unicode",
            "artistUnicode",
            params.metadata.artistUnicode ?? "",
            undefined,
            "Use if the artist name should keep native characters.",
          )}
          ${renderField(
            "Source",
            "generator-field-source",
            "source",
            params.metadata.source,
            params.validation.fieldErrors.source,
            "Optional origin or game reference.",
          )}
          <label class="field field--wide" for="generator-field-tags">
            <span>Tags</span>
            <textarea
              id="generator-field-tags"
              name="tags"
              rows="4"
            >${escapeHtml(params.metadata.tags)}</textarea>
            <small class="field-helper">Space-separated tags for local search, export context, or later review.</small>
            ${renderFieldError(params.validation.fieldErrors.tags)}
          </label>
        </div>
      </section>

      <section class="panel-subsection panel-subsection--artwork">
        <div class="panel-subsection-head">
          <div>
            <p class="section-eyebrow">Artwork</p>
            <h3>Optional Background Image</h3>
            <p>Attach JPEG, PNG, or WebP art to include it in the final .osz package.</p>
          </div>
          <button
            type="button"
            class="generator-secondary-button"
            data-action="pick-background"
          >
            ${background ? "Replace Background" : "Add Background"}
          </button>
        </div>

        <input
          id="generator-background-input"
          class="visually-hidden"
          type="file"
          accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
        />

        <div class="background-layout">
          <div class="background-preview-card">
            ${
              params.backgroundPreviewUrl
                ? `
                  <img
                    class="background-preview-image"
                    src="${escapeHtml(params.backgroundPreviewUrl)}"
                    alt="Uploaded background preview"
                  />
                `
                : `
                  <div class="background-preview-placeholder">
                    ${renderIcon("background")}
                    <span>${background ? "Preview available after replacing this image in the current session." : "No background image attached yet."}</span>
                  </div>
                `
            }
          </div>

          <div class="background-details-card">
            <div class="background-details-head">
              <span class="sidebar-status-badge sidebar-status-badge--${background ? "success" : "muted"}">
                ${background ? "Attached" : "Optional"}
              </span>
            </div>
            ${
              background
                ? `
                  <dl class="upload-summary-grid upload-summary-grid--compact">
                    <div>
                      <dt>Filename</dt>
                      <dd>${escapeHtml(background.originalFilename)}</dd>
                    </div>
                    <div>
                      <dt>Type</dt>
                      <dd>${resolveFileType(background.originalFilename, background.contentType)}</dd>
                    </div>
                    <div>
                      <dt>Size</dt>
                      <dd>${formatBytes(background.sizeBytes)}</dd>
                    </div>
                    <div>
                      <dt>Stored As</dt>
                      <dd>${escapeHtml(background.normalizedFilename)}</dd>
                    </div>
                  </dl>
                `
                : `
                  <p class="muted-copy">Skip this if you only need audio and beatmap outputs. You can still add art later before generation.</p>
                `
            }
            ${backgroundProgressMarkup}
            ${backgroundErrorMarkup}
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderDetectedMetadataSuggestion(
  suggestion: AudioMetadataSuggestion | undefined,
): string {
  if (!suggestion || (!suggestion.title && !suggestion.artist && !suggestion.durationMs)) {
    return "";
  }

  return `
    <section class="panel-subsection suggestion-panel">
      <div class="panel-subsection-head">
        <div>
          <p class="section-eyebrow">Detected Metadata</p>
          <h3>Local Audio Suggestions</h3>
          <p>Detected values stay separate from your confirmed fields until you explicitly apply them.</p>
        </div>
        <button
          type="button"
          class="generator-secondary-button"
          data-action="apply-detected-metadata"
        >
          Use Detected Title And Artist
        </button>
      </div>

      <div class="suggestion-metrics">
        ${renderSuggestionMetric("Title", suggestion.title ?? "Unknown title")}
        ${renderSuggestionMetric("Artist", suggestion.artist ?? "Unknown artist")}
        ${renderSuggestionMetric(
          "Duration",
          suggestion.durationMs ? formatClockTimeMs(suggestion.durationMs) : "Unavailable",
        )}
        ${renderSuggestionMetric(
          "Codec",
          suggestion.codec ? suggestion.codec.toUpperCase() : "Unavailable",
        )}
      </div>
    </section>
  `;
}

function renderSuggestionMetric(label: string, value: string): string {
  return `
    <article class="suggestion-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `;
}

function renderField(
  label: string,
  id: string,
  name: string,
  value: string,
  error?: string,
  helperText?: string,
): string {
  return `
    <label class="field" for="${id}">
      <span>${label}</span>
      <input id="${id}" name="${name}" type="text" value="${escapeHtml(value)}" />
      ${helperText ? `<small class="field-helper">${escapeHtml(helperText)}</small>` : ""}
      ${renderFieldError(error)}
    </label>
  `;
}

function renderFieldError(error: string | undefined): string {
  return error ? `<small class="field-error">${escapeHtml(error)}</small>` : "";
}

function resolveFileType(filename: string, contentType: string): string {
  const extension = filename.split(".").at(-1)?.trim();
  if (extension) {
    return extension.toUpperCase();
  }

  if (contentType.includes("/")) {
    return contentType.split("/").at(-1)?.toUpperCase() ?? contentType;
  }

  return contentType.toUpperCase();
}
