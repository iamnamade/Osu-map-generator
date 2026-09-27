import type { FileTransferState, WorkspaceResponse } from "../GeneratorModels";
import { formatBytes } from "../GeneratorModels";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml, formatClockTimeMs } from "../../shared/format";

export function renderAudioDropzone(params: {
  audioUpload: FileTransferState;
  workspace?: WorkspaceResponse;
  isDragActive: boolean;
}): string {
  const uploadedAudio = params.workspace?.workspace.audio;
  const detectedMetadata = uploadedAudio?.detectedMetadata;
  const progressMarkup =
    params.audioUpload.status === "uploading"
      ? `
        <div class="upload-progress">
          <div class="upload-progress-copy">
            <strong>Uploading ${escapeHtml(params.audioUpload.fileName ?? "audio file")}</strong>
            <span>${params.audioUpload.progressPercent}% complete</span>
          </div>
          <div class="upload-progress-track">
            <span style="width: ${params.audioUpload.progressPercent}%"></span>
          </div>
        </div>
      `
      : "";

  const errorMarkup = params.audioUpload.error
    ? `<p class="form-error">${escapeHtml(params.audioUpload.error)}</p>`
    : "";

  const uploadedMarkup = uploadedAudio
    ? `
      <section class="panel-subsection upload-ready-state">
        <div class="upload-ready-head">
          <div>
            <p class="section-eyebrow">Audio</p>
            <h3>${escapeHtml(uploadedAudio.originalFilename)}</h3>
            <p>Source file stored locally and ready for metadata confirmation.</p>
          </div>
          <span class="sidebar-status-badge sidebar-status-badge--success">Upload complete</span>
        </div>

        <dl class="upload-summary-grid">
          <div>
            <dt>Filename</dt>
            <dd>${escapeHtml(uploadedAudio.originalFilename)}</dd>
          </div>
          <div>
            <dt>Duration</dt>
            <dd>${detectedMetadata?.durationMs ? formatClockTimeMs(detectedMetadata.durationMs) : "Unavailable"}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>${resolveAudioType(uploadedAudio.originalFilename, uploadedAudio.contentType)}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>${formatBytes(uploadedAudio.sizeBytes)}</dd>
          </div>
          <div>
            <dt>Detected Title</dt>
            <dd>${escapeHtml(detectedMetadata?.title ?? "Unknown title")}</dd>
          </div>
          <div>
            <dt>Detected Artist</dt>
            <dd>${escapeHtml(detectedMetadata?.artist ?? "Unknown artist")}</dd>
          </div>
        </dl>

        <div class="panel-actions panel-actions--split">
          <p class="panel-inline-note">You can replace this file at any time before starting generation.</p>
          <div class="wizard-actions">
            <button type="button" class="generator-secondary-button" data-action="pick-audio">
              Replace File
            </button>
            <button type="button" class="generator-danger-button" data-action="reset-workspace">
              Remove File
            </button>
          </div>
        </div>
      </section>
    `
    : `
      <button
        type="button"
        class="dropzone-surface ${params.isDragActive ? "is-drag-active" : ""}"
        data-action="pick-audio"
        data-dropzone="audio"
      >
        <span class="dropzone-icon-box">
          ${renderIcon("audio")}
        </span>
        <strong>DRAG &amp; DROP YOUR SONG HERE</strong>
        <p>or click to browse</p>
        <div class="dropzone-meta-grid">
          <span>Supported: MP3, WAV, OGG, FLAC</span>
          <span>Maximum file size: 200 MB</span>
        </div>
        <span class="dropzone-cta">CHOOSE FILE</span>
        <span class="dropzone-note">Local only. Audio is stored inside this isolated workspace.</span>
      </button>
    `;

  return `
    <input
      id="generator-audio-input"
      class="visually-hidden"
      type="file"
      accept=".mp3,.wav,.ogg,.flac,audio/mpeg,audio/wav,audio/ogg,audio/flac"
    />
    <div class="panel-section panel-section--spacious">
      ${uploadedMarkup}
      ${progressMarkup}
      ${errorMarkup}
    </div>
  `;
}

function resolveAudioType(filename: string, contentType: string): string {
  const extension = filename.split(".").at(-1)?.trim();
  if (extension) {
    return extension.toUpperCase();
  }

  if (contentType.includes("/")) {
    return contentType.split("/").at(-1)?.toUpperCase() ?? contentType;
  }

  return contentType.toUpperCase();
}
