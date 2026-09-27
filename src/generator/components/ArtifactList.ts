import type { ArtifactGroup } from "../GeneratorModels";
import { formatBytes } from "../GeneratorModels";
import { renderIcon } from "./GeneratorIcons";
import { escapeHtml } from "../../shared/format";

export function renderArtifactList(artifactGroups: ArtifactGroup[]): string {
  if (artifactGroups.length === 0) {
    return `
      <section class="wizard-stage-panel artifact-panel">
        <div class="wizard-stage-head">
          <p class="section-eyebrow">Artifacts</p>
          <h2>Generated Files</h2>
          <p>Files will appear here after the local pipeline produces them.</p>
        </div>
      </section>
    `;
  }

  return `
    <section class="wizard-stage-panel artifact-panel">
      <div class="wizard-stage-head">
        <p class="section-eyebrow">Artifacts</p>
        <h2>Generated Files</h2>
        <p>Download mapsets, reports, JSON artifacts, and developer logs from the active workspace.</p>
      </div>
      <div class="artifact-group-list">
        ${artifactGroups
          .map(
            (group) => `
              <section class="panel-subsection artifact-group">
                <div class="panel-subsection-head">
                  <div>
                    <p class="section-eyebrow">${escapeHtml(group.group)}</p>
                    <h3>${escapeHtml(group.group)}</h3>
                  </div>
                </div>
                <div class="artifact-item-list">
                  ${group.items
                    .map(
                      (item) => `
                        <a
                          class="artifact-item"
                          href="${escapeHtml(item.downloadUrl)}"
                          target="_blank"
                          rel="noreferrer"
                        >
                          <div class="artifact-item-copy">
                            <strong>${escapeHtml(item.fileName)}</strong>
                            <span>${escapeHtml(item.kind)} / ${formatBytes(item.sizeBytes)}</span>
                          </div>
                          <span class="artifact-item-icon">
                            ${renderIcon("download")}
                          </span>
                        </a>
                      `,
                    )
                    .join("")}
                </div>
              </section>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}
