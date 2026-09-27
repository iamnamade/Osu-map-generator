import Phaser from "phaser";

import { loadBeatmap } from "./game/BeatmapLoader";
import {
  loadCorrectionReport,
  type CorrectionReportLoadResult,
} from "./game/CorrectionReportLoader";
import { GameScene } from "./game/GameScene";
import {
  loadValidationReport,
  type ValidationReportLoadResult,
} from "./game/ValidationReportLoader";
import {
  loadTournamentReport,
  type TournamentReportLoadResult,
} from "./game/TournamentReportLoader";
import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  type Beatmap,
  type CorrectionAction,
  type CorrectionReport,
  type GameState,
  type HudSnapshot,
  type ResultsSnapshot,
  type TournamentReport,
  type ValidationReport,
  type ValidationIssue,
} from "./game/types";
import {
  buildGameUrl,
  buildEditorUrl,
  getProjectMapCatalog,
  initializeProjectMapCatalog,
  resolveRequestedProjectMap,
  type ProjectMapCatalogEntry,
} from "./shared/mapCatalog";
import "./style.css";

type MapOption = ProjectMapCatalogEntry;

type QualityPanelState =
  | { status: "unavailable"; message: string }
  | { status: "loading"; message: string }
  | { status: "missing"; message: string }
  | { status: "error"; message: string }
  | {
      status: "ready";
      report: ValidationReport;
      correctionReport?: CorrectionReport;
    };

type TournamentPanelState =
  | { status: "unavailable"; message: string }
  | { status: "loading"; message: string }
  | { status: "missing"; message: string }
  | { status: "error"; message: string }
  | { status: "ready"; report: TournamentReport };

const defaultHud: HudSnapshot = {
  score: 0,
  combo: 0,
  accuracy: 100,
  progress: 0,
  currentJudgment: "Ready",
  elapsedMs: 0,
  durationMs: 0,
};

let mapOptions: MapOption[] = [];

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("App root was not found.");
}

root.innerHTML = `
  <div class="app-shell">
    <aside class="info-panel">
      <div class="brand-lockup">
        <p class="eyebrow">Rhythm Generator</p>
        <h1>Pulse Practice</h1>
        <p class="subtitle">Manual and generated beatmaps running through the same Phaser gameplay core.</p>
      </div>

      <section class="meta-panel">
        <div>
          <p class="eyebrow">Beatmap</p>
          <h2 id="song-title">Loading map...</h2>
          <p id="song-artist" class="meta-copy">Preparing local assets</p>
        </div>
        <span id="status-pill" class="status-pill">loading</span>
      </section>

      <section class="map-select-panel">
        <div>
          <p class="eyebrow">Map Source</p>
          <h2>Select a Beatmap</h2>
          <p id="map-description" class="meta-copy">Choose a manual, generated, improved, or champion map before starting.</p>
        </div>
        <label class="select-label" for="map-select">Current selection</label>
        <select id="map-select" class="map-select"></select>
      </section>

      <section class="quality-panel">
        <div>
          <p class="eyebrow">Quality Report</p>
          <h2>Map Quality</h2>
          <p class="meta-copy">Validation scores, improvement deltas, and the most important local issues or corrections.</p>
        </div>
        <div id="quality-content" class="quality-content"></div>
      </section>

      <section class="tournament-panel">
        <div>
          <p class="eyebrow">Tournament</p>
          <h2>Champion Context</h2>
          <p class="meta-copy">When a champion map is selected, this panel shows the winning candidate and the top of the ranked field.</p>
        </div>
        <div id="tournament-content" class="quality-content"></div>
      </section>

      <section class="stat-grid">
        <article class="stat-card">
          <span class="stat-label">Score</span>
          <strong id="hud-score">0</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">Combo</span>
          <strong id="hud-combo">0x</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">Accuracy</span>
          <strong id="hud-accuracy">100.00%</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">Judgment</span>
          <strong id="hud-judgment">Ready</strong>
        </article>
      </section>

      <section class="timeline-panel">
        <div class="timeline-head">
          <span>Song progress</span>
          <span id="hud-time">00:00 / 00:00</span>
        </div>
        <div class="progress-track">
          <div id="progress-fill" class="progress-fill"></div>
        </div>
      </section>

      <section class="rules-panel">
        <p class="eyebrow">Timing windows</p>
        <ul>
          <li>Perfect: 50ms</li>
          <li>Good: 100ms</li>
          <li>Okay: 160ms</li>
          <li>Miss: over 160ms</li>
        </ul>
      </section>
    </aside>

    <main class="stage-panel">
      <div id="game-shell" class="game-shell">
        <div id="game-host" class="game-host"></div>
        <div id="screen-overlay" class="screen-overlay"></div>
      </div>
      <p class="stage-note">All hit timing is read from the current audio playback time every frame.</p>
    </main>
  </div>
`;

const songTitle = mustFindElement<HTMLHeadingElement>("#song-title");
const songArtist = mustFindElement<HTMLParagraphElement>("#song-artist");
const statusPill = mustFindElement<HTMLSpanElement>("#status-pill");
const overlay = mustFindElement<HTMLDivElement>("#screen-overlay");
const mapSelect = mustFindElement<HTMLSelectElement>("#map-select");
const mapDescription = mustFindElement<HTMLParagraphElement>("#map-description");
const scoreValue = mustFindElement<HTMLElement>("#hud-score");
const comboValue = mustFindElement<HTMLElement>("#hud-combo");
const accuracyValue = mustFindElement<HTMLElement>("#hud-accuracy");
const judgmentValue = mustFindElement<HTMLElement>("#hud-judgment");
const timeValue = mustFindElement<HTMLElement>("#hud-time");
const progressFill = mustFindElement<HTMLDivElement>("#progress-fill");
const qualityContent = mustFindElement<HTMLDivElement>("#quality-content");
const tournamentContent = mustFindElement<HTMLDivElement>("#tournament-content");

let state: GameState = "loading";
let beatmap: Beatmap | null = null;
let audio: HTMLAudioElement | null = null;
let latestResults: ResultsSnapshot | null = null;
let qualityPanelState: QualityPanelState = {
  status: "unavailable",
  message: "No quality report available.",
};
let tournamentPanelState: TournamentPanelState = {
  status: "unavailable",
  message: "Tournament data is only shown for champion selections.",
};
let selectedMapId = "";
let activeMapOption: MapOption | null = null;
let loadRequestId = 0;

const scene = new GameScene();
const handleAudioEnded = () => {
  scene.handleAudioEnded();
};

new Phaser.Game({
  type: Phaser.AUTO,
  width: PLAYFIELD_WIDTH,
  height: PLAYFIELD_HEIGHT,
  parent: "game-host",
  transparent: true,
  scale: {
    parent: "game-host",
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
    width: PLAYFIELD_WIDTH,
    height: PLAYFIELD_HEIGHT,
  },
  scene: [scene],
});

renderMapSelectOptions();
mapSelect.addEventListener("change", () => {
  void prepareSelectedMap(mapSelect.value);
});
setState("loading", "Loading beatmap and audio...");
applyHud(defaultHud);
renderQualityPanel();
renderTournamentPanel();
void boot();

async function boot(): Promise<void> {
  await initializeProjectMapCatalog();
  const catalogEntries = getProjectMapCatalog();
  const requestedMapOption = resolveRequestedProjectMap(
    new URLSearchParams(window.location.search),
  );
  mapOptions = requestedMapOption
    ? [requestedMapOption, ...catalogEntries.filter((entry) => entry.id !== requestedMapOption.id)]
    : catalogEntries;
  const initialMapOption = requestedMapOption ?? mapOptions[0];
  if (!initialMapOption) {
    throw new Error("No project maps are available.");
  }

  selectedMapId = initialMapOption.id;
  activeMapOption = initialMapOption;
  renderMapSelectOptions();
  await prepareSelectedMap(selectedMapId);
}

async function startGame(): Promise<void> {
  if (!beatmap || !audio) {
    setState("error", "Beatmap or audio is not ready yet.");
    return;
  }

  setState("loading", "Starting audio playback...");

  try {
    audio.pause();
    audio.currentTime = 0;
    scene.resetToReady();
    await audio.play();
    scene.startRun();
    latestResults = null;
    setState("playing");
  } catch (error) {
    audio.pause();
    audio.currentTime = 0;
    scene.resetToReady();
    setState(
      "error",
      `Audio playback failed. ${
        error instanceof Error ? error.message : "Check the local MP3 file."
      }`,
    );
  }
}

async function prepareSelectedMap(mapId: string): Promise<void> {
  const requestId = ++loadRequestId;
  const nextMapOption = getMapOption(mapId);
  if (!nextMapOption) {
    throw new Error(`Selected map ${mapId} is not available in the current catalog.`);
  }

  selectedMapId = nextMapOption.id;
  activeMapOption = nextMapOption;
  mapSelect.value = nextMapOption.id;
  mapDescription.textContent = nextMapOption.description;
  latestResults = null;

  scene.stopRun();
  disposeCurrentAudio();
  setState("loading", `Loading ${nextMapOption.label}...`);
  setQualityPanelState(
    nextMapOption.reportPath
      ? {
          status: "loading",
          message: `Loading ${nextMapOption.label} quality report...`,
        }
      : {
          status: "unavailable",
          message: "No quality report available for the manual test map.",
        },
  );
  setTournamentPanelState(
    nextMapOption.kind === "champion"
      ? {
          status: "loading",
          message: `Loading ${nextMapOption.label} tournament report...`,
        }
      : {
          status: "unavailable",
          message: "Tournament data is only shown for champion selections.",
        },
  );

  try {
    const loadedBeatmap = await loadBeatmap(nextMapOption.path);
    const [loadedAudio, nextQualityPanelState, nextTournamentPanelState] =
      await Promise.all([
        loadAudio(loadedBeatmap.audio),
        loadQualityPanelState(nextMapOption),
        loadTournamentPanelState(nextMapOption),
      ]);

    if (requestId !== loadRequestId) {
      loadedAudio.pause();
      loadedAudio.currentTime = 0;
      return;
    }

    loadedAudio.volume = 0.9;
    loadedAudio.addEventListener("ended", handleAudioEnded);

    beatmap = loadedBeatmap;
    audio = loadedAudio;
    setQualityPanelState(nextQualityPanelState);
    setTournamentPanelState(nextTournamentPanelState);

    scene.bindSession(
      { beatmap: loadedBeatmap, audio: loadedAudio },
      {
        onHudUpdate: (hud) => {
          applyHud(hud);
        },
        onResults: (results) => {
          latestResults = results;
          setState("finished");
        },
        onError: (message) => {
          setState("error", message);
        },
      },
    );

    updateSongMeta(loadedBeatmap, nextMapOption);
    setState("ready");
  } catch (error) {
    if (requestId !== loadRequestId) {
      return;
    }

    beatmap = null;
    audio = null;
    setQualityPanelState(
      activeMapOption.reportPath
        ? {
            status: "error",
            message: "Beatmap load failed before the quality report could be shown.",
          }
        : {
            status: "unavailable",
            message: "No quality report available for the manual test map.",
          },
    );
    setTournamentPanelState(
      activeMapOption.kind === "champion"
        ? {
            status: "error",
            message: "Champion map load failed before the tournament report could be shown.",
          }
        : {
            status: "unavailable",
            message: "Tournament data is only shown for champion selections.",
          },
    );
    setState("error", formatMapLoadError(error, nextMapOption));
  }
}

function setState(nextState: GameState, message?: string): void {
  state = nextState;
  statusPill.textContent = nextState;
  statusPill.dataset.state = nextState;
  mapSelect.disabled = nextState === "loading" || nextState === "playing";
  renderOverlay(message);
}

function renderOverlay(message?: string): void {
  overlay.classList.toggle("hidden", state === "playing");

  if (state === "loading") {
    overlay.innerHTML = `
      <div class="overlay-card">
        <p class="eyebrow">Loading</p>
        <h2>Preparing the selected map</h2>
        <p>${message ?? "Please wait while local assets load."}</p>
      </div>
    `;
    return;
  }

  if (state === "ready" && beatmap) {
    overlay.innerHTML = `
      <div class="overlay-card">
        <p class="eyebrow">Ready</p>
        <h2>${activeMapOption?.label ?? "Loaded Map"}</h2>
        <p>${beatmap.title} is loaded. ${activeMapOption?.description ?? ""}</p>
        <div class="overlay-action-row">
          <button id="start-button" class="action-button">Start Game</button>
          <button id="open-editor-button" class="action-button secondary-button">Open Map Editor</button>
        </div>
      </div>
    `;
    mustFindElement<HTMLButtonElement>("#start-button").addEventListener(
      "click",
      () => {
        void startGame();
      },
    );
    mustFindElement<HTMLButtonElement>("#open-editor-button").addEventListener(
      "click",
      () => {
        window.location.href = activeMapOption
          ? buildEditorUrl(activeMapOption)
          : buildEditorUrl();
      },
    );
    return;
  }

  if (state === "finished" && latestResults) {
    overlay.innerHTML = `
      <div class="overlay-card results-card">
        <p class="eyebrow">Results</p>
        <h2>${latestResults.title}</h2>
        <div class="results-grid">
          <div><span>Score</span><strong>${formatNumber(latestResults.score)}</strong></div>
          <div><span>Accuracy</span><strong>${formatAccuracy(latestResults.accuracy)}</strong></div>
          <div><span>Max Combo</span><strong>${latestResults.maxCombo}x</strong></div>
          <div><span>Total Notes</span><strong>${latestResults.totalObjects}</strong></div>
          <div><span>Perfect</span><strong>${latestResults.counts.Perfect}</strong></div>
          <div><span>Good</span><strong>${latestResults.counts.Good}</strong></div>
          <div><span>Okay</span><strong>${latestResults.counts.Okay}</strong></div>
          <div><span>Miss</span><strong>${latestResults.counts.Miss}</strong></div>
        </div>
        <button id="restart-button" class="action-button">Restart</button>
      </div>
    `;
    mustFindElement<HTMLButtonElement>("#restart-button").addEventListener(
      "click",
      () => {
        void startGame();
      },
    );
    return;
  }

  if (state === "error") {
    overlay.innerHTML = `
      <div class="overlay-card error-card">
        <p class="eyebrow">Error</p>
        <h2>Could not start the game</h2>
        <p>${message ?? "A local file is missing or invalid."}</p>
        <button id="retry-button" class="action-button secondary-button">Retry Load</button>
        <button id="return-to-catalog-button" class="action-button">Open Catalog Default</button>
      </div>
    `;
    mustFindElement<HTMLButtonElement>("#retry-button").addEventListener(
      "click",
      () => {
        void prepareSelectedMap(selectedMapId);
      },
    );
    mustFindElement<HTMLButtonElement>("#return-to-catalog-button").addEventListener(
      "click",
      () => {
        const fallbackOption = mapOptions.find((option) => !option.id.startsWith("runtime:"));
        window.location.href = buildGameUrl(fallbackOption?.path);
      },
    );
  }
}

function updateSongMeta(currentBeatmap: Beatmap, mapOption: MapOption): void {
  songTitle.textContent = currentBeatmap.title;
  songArtist.textContent = `${currentBeatmap.artist} - ${mapOption.label} - ${currentBeatmap.objects.length} circles`;
}

function applyHud(hud: HudSnapshot): void {
  scoreValue.textContent = formatNumber(hud.score);
  comboValue.textContent = `${hud.combo}x`;
  accuracyValue.textContent = formatAccuracy(hud.accuracy);
  judgmentValue.textContent = hud.currentJudgment;
  judgmentValue.dataset.judgment = hud.currentJudgment;
  timeValue.textContent = `${formatTime(hud.elapsedMs)} / ${formatTime(
    hud.durationMs,
  )}`;
  progressFill.style.width = `${(hud.progress * 100).toFixed(2)}%`;
}

function mustFindElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);

  if (!element) {
    throw new Error(`Missing DOM element: ${selector}`);
  }

  return element;
}

async function loadAudio(url: string): Promise<HTMLAudioElement> {
  const audioElement = new Audio(url);
  audioElement.preload = "auto";

  return await new Promise((resolve, reject) => {
    const cleanup = () => {
      audioElement.removeEventListener("canplaythrough", handleReady);
      audioElement.removeEventListener("loadedmetadata", handleReady);
      audioElement.removeEventListener("error", handleError);
    };

    const handleReady = () => {
      cleanup();
      resolve(audioElement);
    };

    const handleError = () => {
      cleanup();
      reject(
        new Error(
          `Audio file could not be loaded from ${url}. Put a valid MP3 at public${url}.`,
        ),
      );
    };

    audioElement.addEventListener("canplaythrough", handleReady, {
      once: true,
    });
    audioElement.addEventListener("loadedmetadata", handleReady, {
      once: true,
    });
    audioElement.addEventListener("error", handleError, { once: true });
    audioElement.load();
  });
}

function formatAccuracy(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(Math.round(value));
}

function formatTime(valueMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(valueMs / 1000));
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");

  return `${minutes}:${seconds}`;
}

function renderMapSelectOptions(): void {
  mapSelect.innerHTML = mapOptions
    .map(
      (option) => `
        <option value="${option.id}">
          ${option.label}
        </option>
      `,
    )
    .join("");

  mapSelect.value = selectedMapId;
  mapDescription.textContent =
    activeMapOption?.description ??
    "Choose a manual, generated, improved, champion, hybrid, or imported map before starting.";
}

function getMapOption(mapId: string): MapOption | undefined {
  return mapOptions.find((option) => option.id === mapId) ?? mapOptions[0];
}

function disposeCurrentAudio(): void {
  if (!audio) {
    return;
  }

  audio.pause();
  audio.currentTime = 0;
  audio.removeEventListener("ended", handleAudioEnded);
}

function formatMapLoadError(error: unknown, mapOption: MapOption): string {
  const message =
    error instanceof Error ? error.message : "Unknown startup failure.";

  if (
    (mapOption.kind === "generated" ||
      mapOption.kind === "improved" ||
      mapOption.kind === "champion" ||
      mapOption.kind === "hybrid" ||
      mapOption.kind === "imported") &&
    message.startsWith("Beatmap could not be loaded")
  ) {
    if (mapOption.kind === "improved") {
      return `${mapOption.label} has not been generated yet. Run the post-processor first to create ${mapOption.path}.`;
    }

    if (mapOption.kind === "champion") {
      return `${mapOption.label} has not been generated yet. Run the tournament pipeline first to create ${mapOption.path}.`;
    }

    if (mapOption.kind === "hybrid") {
      return `${mapOption.label} has not been generated yet. Run the section-aware hybrid pipeline first to create ${mapOption.path}.`;
    }

    if (mapOption.kind === "imported") {
      return `${mapOption.label} is listed as an imported map, but ${mapOption.path} could not be loaded. Re-run the .osu import pipeline or remove the stale manifest entry.`;
    }

    return `${mapOption.label} has not been created yet. Run the generator first to create ${mapOption.path}.`;
  }

  return message;
}

async function loadQualityPanelState(
  mapOption: MapOption,
): Promise<QualityPanelState> {
  if (!mapOption.reportPath) {
    return {
      status: "unavailable",
      message: "No quality report available for the manual test map.",
    };
  }

  const reportResult = await safeLoadValidationReport(mapOption.reportPath);
  if (reportResult.status !== "ok") {
    return reportResult;
  }

  if (mapOption.kind !== "improved") {
    return { status: "ready", report: reportResult.report };
  }

  if (!mapOption.correctionReportPath) {
    return {
      status: "error",
      message: "Improved map metadata is missing its correction report path.",
    };
  }

  const correctionResult = await safeLoadCorrectionReport(
    mapOption.correctionReportPath,
  );
  if (correctionResult.status !== "ok") {
    return correctionResult;
  }

  return {
    status: "ready",
    report: reportResult.report,
    correctionReport: correctionResult.report,
  };
}

async function loadTournamentPanelState(
  mapOption: MapOption,
): Promise<TournamentPanelState> {
  if (mapOption.kind !== "champion" || !mapOption.tournamentReportPath) {
    return {
      status: "unavailable",
      message: "Tournament data is only shown for champion selections.",
    };
  }

  const reportResult = await safeLoadTournamentReport(
    mapOption.tournamentReportPath,
  );
  if (reportResult.status !== "ok") {
    return reportResult;
  }

  return {
    status: "ready",
    report: reportResult.report,
  };
}

function setQualityPanelState(nextState: QualityPanelState): void {
  qualityPanelState = nextState;
  renderQualityPanel();
}

function setTournamentPanelState(nextState: TournamentPanelState): void {
  tournamentPanelState = nextState;
  renderTournamentPanel();
}

function renderQualityPanel(): void {
  if (qualityPanelState.status !== "ready") {
    const message = qualityPanelState.message;
    const stateLabel = qualityPanelState.status.replace(/^\w/, (char) =>
      char.toUpperCase(),
    );

    qualityContent.innerHTML = `
      <div class="quality-empty-state">
        <strong>${escapeHtml(stateLabel)}</strong>
        <p>${escapeHtml(message)}</p>
      </div>
    `;
    return;
  }

  const { report, correctionReport } = qualityPanelState;
  const topIssues = report.issues.slice(0, 3);
  const issueMarkup =
    topIssues.length > 0
      ? topIssues
          .map(
            (issue) => `
              <li class="quality-issue-item">
                <span class="severity-pill" data-severity="${issue.severity}">${issue.severity}</span>
                <div>
                  <strong>${escapeHtml(issue.code)}</strong>
                  <p>${escapeHtml(issue.message)}</p>
                  <span class="quality-issue-meta">${escapeHtml(formatIssueContext(issue))}</span>
                </div>
              </li>
            `,
          )
          .join("")
      : `<li class="quality-issue-item"><div><strong>No issues</strong><p>No validator issues were reported for this map.</p></div></li>`;
  const qualityTitle = correctionReport
    ? `Validated improved map${
        correctionReport.accepted ? "" : " (original kept copy)"
      }`
    : report.interpretation;

  qualityContent.innerHTML = `
    <div class="quality-score-row">
      <div class="quality-score-badge">
        <strong>${report.scores.overall.toFixed(1)}</strong>
        <span>overall</span>
      </div>
      <div class="quality-score-copy">
        <h3>${escapeHtml(qualityTitle)}</h3>
        <p class="meta-copy">
          ${report.playable ? "Playable" : "Not safely playable"} -
          ${report.valid ? "Structurally valid" : "Structurally invalid"} -
          ${escapeHtml(report.map.difficulty)}
        </p>
      </div>
    </div>

    ${correctionReport ? renderCorrectionBlock(correctionReport) : ""}

    <div class="quality-summary-grid">
      <article class="quality-summary-card">
        <span>Critical</span>
        <strong>${report.summary.critical}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Errors</span>
        <strong>${report.summary.errors}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Warnings</span>
        <strong>${report.summary.warnings}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Info</span>
        <strong>${report.summary.info}</strong>
      </article>
    </div>

    <div class="quality-category-grid">
      ${renderCategoryScore("Structural", report.scores.structural)}
      ${renderCategoryScore("Timing", report.scores.timing)}
      ${renderCategoryScore("Rhythm", report.scores.rhythm)}
      ${renderCategoryScore("Movement", report.scores.movement)}
      ${renderCategoryScore("Readability", report.scores.readability)}
      ${renderCategoryScore("Spatial", report.scores.spatialBalance)}
      ${renderCategoryScore("Repetition", report.scores.repetition)}
      ${renderCategoryScore("Density", report.scores.densityConsistency)}
      ${renderCategoryScore("Difficulty", report.scores.difficultyConsistency)}
    </div>

    <div class="quality-issues-block">
      <div class="quality-issues-head">
        <h3>Highest-priority issues</h3>
        <span>${topIssues.length} shown</span>
      </div>
      <ul class="quality-issue-list">${issueMarkup}</ul>
    </div>
  `;
}

function renderTournamentPanel(): void {
  if (tournamentPanelState.status !== "ready") {
    const message = tournamentPanelState.message;
    const stateLabel = tournamentPanelState.status.replace(/^\w/, (char) =>
      char.toUpperCase(),
    );

    tournamentContent.innerHTML = `
      <div class="quality-empty-state">
        <strong>${escapeHtml(stateLabel)}</strong>
        <p>${escapeHtml(message)}</p>
      </div>
    `;
    return;
  }

  const { report } = tournamentPanelState;
  const topCandidates = report.ranking.slice(0, 3);
  const topCandidateMarkup =
    topCandidates.length > 0
      ? topCandidates
          .map(
            (candidate) => `
              <li class="quality-issue-item tournament-rank-item">
                <span class="severity-pill" data-severity="info">#${candidate.rank}</span>
                <div>
                  <strong>Candidate ${candidate.candidateIndex
                    .toString()
                    .padStart(3, "0")}</strong>
                  <p>${candidate.tournamentScore.toFixed(1)} tournament - ${candidate.qualityScore.toFixed(
                    1,
                  )} quality - ${candidate.stabilityScore.toFixed(1)} stability</p>
                </div>
              </li>
            `,
          )
          .join("")
      : `<li class="quality-issue-item tournament-rank-item"><div><strong>No ranked candidates</strong><p>The tournament report does not contain any eligible candidates.</p></div></li>`;

  tournamentContent.innerHTML = `
    <div class="quality-score-row">
      <div class="quality-score-badge">
        <strong>${report.champion.tournamentScore.toFixed(1)}</strong>
        <span>champion</span>
      </div>
      <div class="quality-score-copy">
        <h3>Candidate ${report.champion.candidateIndex
          .toString()
          .padStart(3, "0")}</h3>
        <p class="meta-copy">
          Quality ${report.champion.qualityScore.toFixed(1)} -
          Stability ${report.champion.stabilityScore.toFixed(1)} -
          ${report.summary.generated} generated
        </p>
      </div>
    </div>

    <div class="quality-summary-grid">
      <article class="quality-summary-card">
        <span>Eligible</span>
        <strong>${report.summary.eligible}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Rejected</span>
        <strong>${report.summary.rejected}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Unique</span>
        <strong>${report.summary.unique}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Near Duplicates</span>
        <strong>${report.summary.nearDuplicateGroups}</strong>
      </article>
    </div>

    <div class="quality-category-grid tournament-category-grid">
      ${renderCategoryScore("Root Seed", report.configuration.rootSeed)}
      ${renderCategoryScore("Candidate Count", report.configuration.candidateCount)}
      ${renderCategoryScore("Pair Diversity", report.diversity.averagePairwiseDiversity)}
      ${renderCategoryScore("Min Diversity", report.diversity.minimumPairwiseDiversity)}
      ${renderCategoryScore("Champion Quality", report.champion.qualityScore)}
      ${renderCategoryScore("Champion Stability", report.champion.stabilityScore)}
    </div>

    <div class="quality-issues-block">
      <div class="quality-issues-head">
        <h3>Top candidates</h3>
        <span>${topCandidates.length} shown</span>
      </div>
      <ul class="quality-issue-list">${topCandidateMarkup}</ul>
    </div>
  `;
}

function renderCategoryScore(label: string, value: number): string {
  return `
    <article class="quality-category-card">
      <span>${escapeHtml(label)}</span>
      <strong>${value.toFixed(1)}</strong>
    </article>
  `;
}

function renderCorrectionBlock(correctionReport: CorrectionReport): string {
  const topCorrections = correctionReport.actions
    .slice()
    .sort((left, right) => {
      if (left.accepted !== right.accepted) {
        return left.accepted ? -1 : 1;
      }

      if (left.confidence !== right.confidence) {
        return right.confidence - left.confidence;
      }

      return Math.abs(right.actualScoreImpact) - Math.abs(left.actualScoreImpact);
    })
    .slice(0, 3);
  const correctionItems =
    topCorrections.length > 0
      ? topCorrections
          .map(
            (action) => `
              <li class="quality-issue-item correction-action-item">
                <span class="severity-pill" data-severity="${action.accepted ? "info" : "warning"}">
                  ${action.accepted ? "accepted" : "reverted"}
                </span>
                <div>
                  <strong>${escapeHtml(action.reasonCode)}</strong>
                  <p>${escapeHtml(formatCorrectionAction(action))}</p>
                </div>
              </li>
            `,
          )
          .join("")
      : `<li class="quality-issue-item correction-action-item"><div><strong>No corrections</strong><p>No post-processing actions were recorded for this map.</p></div></li>`;

  return `
    <div class="quality-summary-grid correction-summary-grid">
      <article class="quality-summary-card">
        <span>Original</span>
        <strong>${correctionReport.before.overallScore.toFixed(1)}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Change</span>
        <strong>${formatSignedNumber(correctionReport.scoreChanges.overall)}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Accepted</span>
        <strong>${correctionReport.summary.acceptedActions}</strong>
      </article>
      <article class="quality-summary-card">
        <span>Reverted</span>
        <strong>${correctionReport.summary.revertedActions}</strong>
      </article>
    </div>

    <div class="quality-category-grid correction-count-grid">
      ${renderCategoryScore("Moved", correctionReport.summary.movedObjects)}
      ${renderCategoryScore("Retimed", correctionReport.summary.timingAdjustments)}
      ${renderCategoryScore("Removed", correctionReport.summary.removedObjects)}
      ${renderCategoryScore("Inserted", correctionReport.summary.insertedObjects)}
      ${renderCategoryScore("Density", correctionReport.scoreChanges.densityConsistency)}
      ${renderCategoryScore("Difficulty", correctionReport.scoreChanges.difficultyConsistency)}
    </div>

    <div class="quality-issues-block">
      <div class="quality-issues-head">
        <h3>Top corrections</h3>
        <span>${topCorrections.length} shown</span>
      </div>
      <ul class="quality-issue-list correction-action-list">${correctionItems}</ul>
    </div>
  `;
}

function formatIssueContext(issue: ValidationIssue): string {
  const fragments: string[] = [];

  if (typeof issue.startTimeMs === "number") {
    fragments.push(`t=${issue.startTimeMs}ms`);
  }

  if (issue.objectIds.length > 0) {
    fragments.push(`objects ${issue.objectIds.join(", ")}`);
  }

  if (typeof issue.measuredValue === "number") {
    fragments.push(`measured ${issue.measuredValue.toFixed(1)}`);
  }

  return fragments.join(" - ");
}

function formatCorrectionAction(action: CorrectionAction): string {
  const objectLabel =
    action.objectIds.length > 0 ? `objects ${action.objectIds.join(", ")}` : "map-level";

  return `${action.actionType} on ${objectLabel} (${formatSignedNumber(
    action.actualScoreImpact,
  )})`;
}

function formatSignedNumber(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

async function safeLoadValidationReport(
  reportPath: string,
): Promise<ValidationReportLoadResult> {
  try {
    return await loadValidationReport(reportPath);
  } catch (error) {
    return {
      status: "error",
      message: `Quality report loading failed. ${
        error instanceof Error ? error.message : "Unknown error."
      }`,
    };
  }
}

async function safeLoadCorrectionReport(
  reportPath: string,
): Promise<CorrectionReportLoadResult> {
  try {
    return await loadCorrectionReport(reportPath);
  } catch (error) {
    return {
      status: "error",
      message: `Improvement report loading failed. ${
        error instanceof Error ? error.message : "Unknown error."
      }`,
    };
  }
}

async function safeLoadTournamentReport(
  reportPath: string,
): Promise<TournamentReportLoadResult> {
  try {
    return await loadTournamentReport(reportPath);
  } catch (error) {
    return {
      status: "error",
      message: `Tournament report loading failed. ${
        error instanceof Error ? error.message : "Unknown error."
      }`,
    };
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
