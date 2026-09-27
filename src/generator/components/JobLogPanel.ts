import type { JobStateResponse } from "../GeneratorModels";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml, formatTimeMs } from "../../shared/format";

export function renderJobLogPanel(params: {
  job?: JobStateResponse;
  logsExpanded: boolean;
  technicalDetailsExpanded: boolean;
}): string {
  const events = params.job?.events ?? [];
  const logToggleLabel = params.logsExpanded ? "Collapse Logs" : "Expand Logs";
  const technicalDetails = params.job?.technicalDetails;
  const technicalToggleLabel = params.technicalDetailsExpanded
    ? "Hide Technical Details"
    : "Show Technical Details";

  return `
    <section class="panel-subsection log-panel">
      <div class="log-card-head">
        <div>
          <p class="section-eyebrow">Job Logs</p>
          <h3>Terminal Feed</h3>
          <p>Readable status messages from the local job runner.</p>
        </div>
        <div class="log-panel-actions">
          <button
            type="button"
            class="generator-secondary-button"
            data-action="copy-logs"
          >
            ${renderIcon("copy")}
            Copy Logs
          </button>
          <button
            type="button"
            class="generator-secondary-button"
            data-action="toggle-logs"
          >
            ${logToggleLabel}
          </button>
        </div>
      </div>

      ${
        params.logsExpanded
          ? `
            <div class="job-log-list">
              ${
                events.length > 0
                  ? events
                      .map(
                        (event) => `
                          <article class="job-log-entry job-log-entry--${event.level}">
                            <span class="job-log-entry__time">${escapeHtml(formatTimestamp(event.timestamp))}</span>
                            <strong class="job-log-entry__level">${escapeHtml(event.level.toUpperCase())}</strong>
                            <p class="job-log-entry__message">${escapeHtml(event.message)}</p>
                          </article>
                        `,
                      )
                      .join("")
                  : `<p class="muted-copy">Logs will appear here once the background job starts.</p>`
              }
            </div>
          `
          : ""
      }

      ${
        technicalDetails
          ? `
            <div class="technical-details">
              <button
                type="button"
                class="generator-secondary-button"
                data-action="toggle-technical-details"
              >
                ${technicalToggleLabel}
              </button>
              ${
                params.technicalDetailsExpanded
                  ? `<pre>${escapeHtml(technicalDetails)}</pre>`
                  : ""
              }
            </div>
          `
          : ""
      }
    </section>
  `;
}

function formatTimestamp(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }

  return formatTimeMs(parsed - new Date(parsed).setHours(0, 0, 0, 0));
}
