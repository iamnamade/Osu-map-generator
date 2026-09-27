import type { Beatmap } from "../../game/types";
import {
  analyzeDifficultyLive,
  type LiveDifficultyAnalysis,
} from "../../shared/difficultyEngine";
import type { DifficultyReport } from "../../shared/difficultyReport";
import { escapeHtml, formatTimeMs } from "../../shared/format";
import type { EditorRootState } from "../EditorState";
import type { EditorStore } from "../EditorStore";

export class DifficultyPanel {
  private unsubscribe?: () => void;
  private lastComputedRevision = -1;
  private lastMapKey?: string;
  private cachedAnalysis?: LiveDifficultyAnalysis;

  constructor(
    private readonly container: HTMLElement,
    store: EditorStore,
  ) {
    this.unsubscribe = store.subscribe((state) => {
      this.render(state);
    });
  }

  dispose(): void {
    this.unsubscribe?.();
  }

  private render(state: EditorRootState): void {
    const workingMap = state.session.workingMap;
    const savedReport = state.session.difficultyReport;

    if (!workingMap) {
      this.container.innerHTML = `
        <section class="panel-subheading">
          <h3>Difficulty Intelligence</h3>
        </section>
        <p class="panel-empty-copy">Load a map to analyze its difficulty profile.</p>
      `;
      return;
    }

    // Live recalculation after edits: recompute when the map identity or the
    // edit revision changes. The map key guards against stale cached analysis
    // when a new map loads with the same revision counter (e.g. 0).
    const mapKey = mapIdentityKey(workingMap, state.session.source?.id);
    if (
      this.lastMapKey !== mapKey ||
      this.lastComputedRevision !== state.session.changedRevision
    ) {
      this.cachedAnalysis = analyzeDifficultyLive({
        beatmap: toGameBeatmap(workingMap),
        sections: state.session.sectionAnalysis?.sections,
        targetName: state.session.source?.difficulty,
      });
      this.lastMapKey = mapKey;
      this.lastComputedRevision = state.session.changedRevision;
    }

    const analysis = this.cachedAnalysis;
    if (!analysis) {
      return;
    }

    const stars = analysis.starRating;
    const target = analysis.target;
    const withinTarget =
      stars.overall >= target.min && stars.overall <= target.max;

    this.container.innerHTML = `
      <section class="difficulty-star-card">
        <div class="difficulty-star-score">
          <span>Overall Stars</span>
          <strong>${stars.overall.toFixed(2)}</strong>
        </div>
        <div class="difficulty-star-meta">
          <span class="difficulty-badge">${escapeHtml(analysis.recommendedPlayerLevel)}</span>
          <span class="difficulty-badge${withinTarget ? " is-ok" : " is-off"}">Target ${escapeHtml(target.name)} ${target.min.toFixed(1)}-${target.max.toFixed(1)}</span>
          <span class="difficulty-badge">Consistency ${Math.round(analysis.consistencyScore * 100)}%</span>
        </div>
      </section>

      <section class="difficulty-axis-grid">
        ${renderAxis("Aim", stars.aim)}
        ${renderAxis("Speed", stars.speed)}
        ${renderAxis("Reading", stars.reading)}
        ${renderAxis("Rhythm", stars.rhythm)}
        ${renderAxis("Stamina", stars.stamina)}
        ${renderAxis("Technical", stars.technical)}
      </section>

      ${
        savedReport
          ? renderSavedReportNote(savedReport, stars.overall)
          : ""
      }

      <section class="panel-subheading">
        <h3>Difficulty Curve</h3>
      </section>
      ${renderCurve(analysis)}

      <section class="panel-subheading">
        <h3>Section Difficulty</h3>
      </section>
      ${renderSections(analysis)}

      <section class="panel-subheading">
        <h3>Pattern Scores</h3>
      </section>
      ${renderPatterns(analysis)}

      <section class="panel-subheading">
        <h3>Gameplay Estimates</h3>
      </section>
      ${renderGameplay(analysis)}

      <section class="panel-subheading">
        <h3>Hardest Objects</h3>
      </section>
      ${renderHardestObjects(analysis)}

      ${
        savedReport && savedReport.verification.length > 0
          ? `
            <section class="panel-subheading">
              <h3>Saved Report Verification</h3>
            </section>
            <ul class="issue-list">
              ${savedReport.verification
                .map(
                  (issue) => `
                    <li class="issue-list-item severity-${escapeHtml(issue.severity)}">
                      <div>
                        <strong>${escapeHtml(issue.code)}</strong>
                        <p>${escapeHtml(issue.message)}</p>
                      </div>
                    </li>
                  `,
                )
                .join("")}
            </ul>
          `
          : ""
      }
    `;
  }
}

function renderAxis(label: string, value: number): string {
  const percent = Math.round(Math.min(100, (value / 10) * 100));
  return `
    <div class="difficulty-axis">
      <div class="difficulty-axis-head">
        <span>${escapeHtml(label)}</span>
        <strong>${value.toFixed(2)}</strong>
      </div>
      <div class="difficulty-axis-track">
        <div class="difficulty-axis-fill" style="width: ${percent}%"></div>
      </div>
    </div>
  `;
}

function renderCurve(analysis: LiveDifficultyAnalysis): string {
  const points = analysis.curve;
  if (points.length === 0) {
    return `<p class="panel-empty-copy">Not enough objects to build a difficulty curve.</p>`;
  }

  const width = 520;
  const height = 120;
  const padding = 8;
  const maxScore = Math.max(
    0.05,
    ...points.map((point) => point.difficultyScore),
  );
  const maxDensity = Math.max(0.1, ...points.map((point) => point.density));
  const minTime = points[0]?.timeMs ?? 0;
  const maxTime = points[points.length - 1]?.timeMs ?? minTime + 1;
  const timeSpan = Math.max(1, maxTime - minTime);

  const coords = points
    .map((point) => {
      const x = padding + ((point.timeMs - minTime) / timeSpan) * (width - padding * 2);
      const y = height - padding - (point.difficultyScore / maxScore) * (height - padding * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const densityPolyline = points
    .map((point) => {
      const x = padding + ((point.timeMs - minTime) / timeSpan) * (width - padding * 2);
      const y = height - padding - (point.density / maxDensity) * (height - padding * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return `
    <div class="difficulty-graph-card">
      <svg viewBox="0 0 ${width} ${height}" class="difficulty-graph" role="img" aria-label="Difficulty curve">
        <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" class="difficulty-graph-axis" />
        <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" class="difficulty-graph-axis" />
        <polyline points="${densityPolyline}" class="difficulty-graph-density" fill="none" />
        <polyline points="${coords}" class="difficulty-graph-line" fill="none" />
        <circle cx="${padding}" cy="${height - padding}" r="2.5" class="difficulty-graph-dot" />
        <circle cx="${width - padding}" cy="${height - padding}" r="2.5" class="difficulty-graph-dot" />
      </svg>
      <div class="difficulty-graph-legend">
        <span><i class="legend-line difficulty-legend-main"></i> Difficulty</span>
        <span><i class="legend-line difficulty-legend-density"></i> Density</span>
        <span>Peak ${analysis.peakDifficulty.toFixed(3)}</span>
        <span>Avg ${analysis.averageDifficulty.toFixed(3)}</span>
      </div>
    </div>
  `;
}

function renderSections(analysis: LiveDifficultyAnalysis): string {
  const sections = analysis.sections;
  if (sections.length === 0) {
    return `<p class="panel-empty-copy">No sections to display.</p>`;
  }

  const maxScore = Math.max(0.05, ...sections.map((section) => section.difficultyScore));
  return `
    <ul class="difficulty-section-list">
      ${sections
        .map(
          (section) => `
            <li class="difficulty-section-item">
              <div class="difficulty-section-copy">
                <strong>${escapeHtml(section.label)}</strong>
                <span>${formatTimeMs(section.startMs)} - ${formatTimeMs(section.endMs)}</span>
              </div>
              <div class="difficulty-section-track">
                <div class="difficulty-section-fill" style="width: ${Math.round((section.difficultyScore / maxScore) * 100)}%"></div>
              </div>
              <span class="difficulty-section-score">${section.difficultyScore.toFixed(2)}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderPatterns(analysis: LiveDifficultyAnalysis): string {
  const patterns = analysis.patterns.slice(0, 12);
  if (patterns.length === 0) {
    return `<p class="panel-empty-copy">No distinct patterns detected.</p>`;
  }

  return `
    <ul class="difficulty-pattern-list">
      ${patterns
        .map(
          (pattern) => `
            <li class="difficulty-pattern-item">
              <span class="difficulty-pattern-name">${escapeHtml(pattern.pattern)}</span>
              <span class="difficulty-pattern-meta">${pattern.objectCount} objects</span>
              <strong>${pattern.score.toFixed(2)}</strong>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderGameplay(analysis: LiveDifficultyAnalysis): string {
  const gameplay = analysis.gameplay;
  return `
    <div class="validation-summary-grid">
      <div><span>Miss</span><strong>${Math.round(gameplay.estimatedMissProbability * 100)}%</strong></div>
      <div><span>Combo</span><strong>${Math.round(gameplay.estimatedComboStability * 100)}%</strong></div>
      <div><span>Stress</span><strong>${Math.round(gameplay.estimatedPlayerStress * 100)}%</strong></div>
      <div><span>Recovery</span><strong>${gameplay.recoveryWindowCount}</strong></div>
      <div><span>Hardest</span><strong>${formatTimeMs(gameplay.hardestPassageMs)}</strong></div>
    </div>
  `;
}

function renderHardestObjects(analysis: LiveDifficultyAnalysis): string {
  const objects = analysis.objectDifficulty.slice(0, 8);
  if (objects.length === 0) {
    return `<p class="panel-empty-copy">No object difficulty data.</p>`;
  }

  return `
    <ul class="difficulty-object-list">
      ${objects
        .map(
          (object) => `
            <li class="difficulty-object-item">
              <strong>#${object.objectId}</strong>
              <span>${escapeHtml(object.objectType)}</span>
              <span>${formatTimeMs(object.timeMs)}</span>
              <strong>${object.score.toFixed(3)}</strong>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderSavedReportNote(
  report: DifficultyReport,
  liveStars: number,
): string {
  const saved = report.starRating.overall;
  const delta = liveStars - saved;
  const deltaLabel = `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`;
  return `
    <section class="saved-report-card">
      <div class="panel-subheading">
        <h3>Saved Python Report</h3>
      </div>
      <p class="saved-report-copy">
        Baseline: <strong>${saved.toFixed(2)} stars</strong>
        &middot; Live edit delta <strong>${deltaLabel}</strong>
        &middot; ${escapeHtml(report.recommendedPlayerLevel)}
      </p>
    </section>
  `;
}

function toGameBeatmap(map: {
  title: string;
  artist: string;
  audio: string;
  approachTime: number;
  circleRadius: number;
  objects: Array<{
    id: number;
    type: "circle" | "slider" | "spinner";
    x?: number;
    y?: number;
    time: number;
    endTime?: number;
    pathType?: "bezier" | "linear" | "catmull" | "perfect";
    controlPoints?: Array<{ x: number; y: number }>;
    repeats?: number;
    pixelLength?: number;
  }>;
}): Beatmap {
  return {
    title: map.title,
    artist: map.artist,
    audio: map.audio,
    approachTime: map.approachTime,
    circleRadius: map.circleRadius,
    objects: map.objects.map((object) => {
      if (object.type === "spinner") {
        return {
          id: object.id,
          type: "spinner" as const,
          time: object.time,
          endTime: object.endTime ?? object.time + 1,
        };
      }

      if (object.type === "slider") {
        return {
          id: object.id,
          type: "slider" as const,
          x: object.x ?? 0,
          y: object.y ?? 0,
          time: object.time,
          endTime: object.endTime ?? object.time + 1,
          pathType: object.pathType ?? "bezier",
          controlPoints: object.controlPoints ?? [{ x: 0, y: 0 }],
          repeats: object.repeats ?? 1,
          pixelLength: object.pixelLength ?? 1,
        };
      }

      return {
        id: object.id,
        type: "circle" as const,
        x: object.x ?? 0,
        y: object.y ?? 0,
        time: object.time,
      };
    }),
  };
}

function mapIdentityKey(
  map: {
    title: string;
    artist: string;
    objects: Array<{ id: number; type: string; time: number }>;
  },
  sourceId?: string,
): string {
  return [
    sourceId ?? "",
    map.title,
    map.artist,
    map.objects.length,
    map.objects[0]?.id,
    map.objects[map.objects.length - 1]?.id,
  ].join(":");
}
