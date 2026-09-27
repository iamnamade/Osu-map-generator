import { isJsonObject } from "./JsonTypes";

export type ProjectMapKind =
  | "manual"
  | "generated"
  | "improved"
  | "champion"
  | "hybrid"
  | "imported";
export type DifficultyName = "easy" | "normal" | "hard";

export interface ProjectMapCatalogEntry {
  id: string;
  label: string;
  path: string;
  kind: ProjectMapKind;
  group: string;
  description: string;
  difficulty?: DifficultyName;
  reportPath?: string;
  correctionReportPath?: string;
  tournamentReportPath?: string;
  analysisPath?: string;
  sectionAnalysisPath?: string;
  phraseAnalysisPath?: string;
  recoveryAnalysisPath?: string;
  hybridAssemblyPath?: string;
  hybridTransitionLogPath?: string;
  importReportPath?: string;
  difficultyReportPath?: string;
  evolutionReportPath?: string;
}

export interface RuntimeProjectMapSelection {
  path: string;
  label?: string;
  kind?: ProjectMapKind;
  description?: string;
  difficulty?: DifficultyName;
  reportPath?: string;
  correctionReportPath?: string;
  tournamentReportPath?: string;
  analysisPath?: string;
  sectionAnalysisPath?: string;
  phraseAnalysisPath?: string;
  recoveryAnalysisPath?: string;
  hybridAssemblyPath?: string;
  hybridTransitionLogPath?: string;
  importReportPath?: string;
  difficultyReportPath?: string;
  evolutionReportPath?: string;
}

interface ImportedMapManifest {
  version: number;
  maps: ImportedMapManifestEntry[];
}

interface ImportedMapManifestEntry {
  id: string;
  label: string;
  path: string;
  kind?: string;
  group?: string;
  description?: string;
  difficulty?: string;
  reportPath?: string;
  correctionReportPath?: string;
  tournamentReportPath?: string;
  analysisPath?: string;
  sectionAnalysisPath?: string;
  phraseAnalysisPath?: string;
  recoveryAnalysisPath?: string;
  hybridAssemblyPath?: string;
  hybridTransitionLogPath?: string;
  importReportPath?: string;
  difficultyReportPath?: string;
  evolutionReportPath?: string;
}

const IMPORTED_MAP_MANIFEST_PATH = "/maps/imported/index.json";

const BASE_PROJECT_MAP_CATALOG: ProjectMapCatalogEntry[] = [
  {
    id: "manual-test",
    label: "Manual Test Map",
    path: "/maps/test-map.json",
    kind: "manual",
    group: "Manual",
    description:
      "The hand-authored baseline map used to validate the original gameplay MVP.",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
  },
  {
    id: "generated-easy",
    label: "Generated Easy",
    path: "/maps/generated/test-song-easy.json",
    kind: "generated",
    group: "Generated",
    difficulty: "easy",
    reportPath: "/reports/test-song-easy-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-easy-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-easy-transitions.json",
    difficultyReportPath: "/difficulty/test-song-easy-difficulty.json",
    description:
      "Algorithmic easy map with wider timing gaps, larger circles, and smoother jumps.",
  },
  {
    id: "generated-normal",
    label: "Generated Normal",
    path: "/maps/generated/test-song-normal.json",
    kind: "generated",
    group: "Generated",
    difficulty: "normal",
    reportPath: "/reports/test-song-normal-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-normal-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-normal-transitions.json",
    difficultyReportPath: "/difficulty/test-song-normal-difficulty.json",
    description:
      "Algorithmic normal map with moderate density and some stronger off-beat detail.",
  },
  {
    id: "generated-hard",
    label: "Generated Hard",
    path: "/maps/generated/test-song-hard.json",
    kind: "generated",
    group: "Generated",
    difficulty: "hard",
    reportPath: "/reports/test-song-hard-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-hard-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-hard-transitions.json",
    difficultyReportPath: "/difficulty/test-song-hard-difficulty.json",
    description:
      "Algorithmic hard map with shorter approach time and more aggressive movement variation.",
  },
  {
    id: "improved-easy",
    label: "Improved Easy",
    path: "/maps/improved/test-song-easy-improved.json",
    kind: "improved",
    group: "Improved",
    difficulty: "easy",
    reportPath: "/reports/improved/test-song-easy-improved-report.json",
    correctionReportPath: "/corrections/test-song-easy-corrections.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-easy-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-easy-transitions.json",
    description:
      "Deterministically post-processed easy map with validator-backed corrections and a full change log.",
  },
  {
    id: "improved-normal",
    label: "Improved Normal",
    path: "/maps/improved/test-song-normal-improved.json",
    kind: "improved",
    group: "Improved",
    difficulty: "normal",
    reportPath: "/reports/improved/test-song-normal-improved-report.json",
    correctionReportPath: "/corrections/test-song-normal-corrections.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-normal-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-normal-transitions.json",
    description:
      "Deterministically post-processed normal map with validator-backed corrections and a full change log.",
  },
  {
    id: "improved-hard",
    label: "Improved Hard",
    path: "/maps/improved/test-song-hard-improved.json",
    kind: "improved",
    group: "Improved",
    difficulty: "hard",
    reportPath: "/reports/improved/test-song-hard-improved-report.json",
    correctionReportPath: "/corrections/test-song-hard-corrections.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-hard-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-hard-transitions.json",
    description:
      "Deterministically post-processed hard map with validator-backed corrections and a full change log.",
  },
  {
    id: "champion-easy",
    label: "Champion Easy",
    path: "/maps/champions/test-song-easy.json",
    kind: "champion",
    group: "Champions",
    difficulty: "easy",
    reportPath: "/reports/champions/test-song-easy-report.json",
    tournamentReportPath: "/tournaments/test-song-easy-tournament.json",
    difficultyReportPath: "/difficulty/test-song-easy-difficulty.json",
    evolutionReportPath: "/evolution/test-song-easy-evolution.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-easy-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-easy-transitions.json",
    description:
      "Champion promoted by the deterministic candidate evolution engine after comparing, ranking, and improving multiple candidates.",
  },
  {
    id: "champion-normal",
    label: "Champion Normal",
    path: "/maps/champions/test-song-normal.json",
    kind: "champion",
    group: "Champions",
    difficulty: "normal",
    reportPath: "/reports/champions/test-song-normal-report.json",
    tournamentReportPath: "/tournaments/test-song-normal-tournament.json",
    difficultyReportPath: "/difficulty/test-song-normal-difficulty.json",
    evolutionReportPath: "/evolution/test-song-normal-evolution.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-normal-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-normal-transitions.json",
    description:
      "Champion promoted by the deterministic candidate evolution engine after comparing, ranking, and improving multiple candidates.",
  },
  {
    id: "champion-hard",
    label: "Champion Hard",
    path: "/maps/champions/test-song-hard.json",
    kind: "champion",
    group: "Champions",
    difficulty: "hard",
    reportPath: "/reports/champions/test-song-hard-report.json",
    tournamentReportPath: "/tournaments/test-song-hard-tournament.json",
    difficultyReportPath: "/difficulty/test-song-hard-difficulty.json",
    evolutionReportPath: "/evolution/test-song-hard-evolution.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-hard-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-hard-transitions.json",
    description:
      "Champion promoted by the deterministic candidate evolution engine after comparing, ranking, and improving multiple candidates.",
  },
  {
    id: "hybrid-easy",
    label: "Hybrid Easy",
    path: "/maps/hybrid/test-song-easy.json",
    kind: "hybrid",
    group: "Hybrid",
    difficulty: "easy",
    reportPath: "/reports/hybrid/test-song-easy-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-easy-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-easy-transitions.json",
    description:
      "Section-aware easy hybrid assembled from multiple tournament candidates with transition checks and validator-backed promotion rules.",
  },
  {
    id: "hybrid-normal",
    label: "Hybrid Normal",
    path: "/maps/hybrid/test-song-normal.json",
    kind: "hybrid",
    group: "Hybrid",
    difficulty: "normal",
    reportPath: "/reports/hybrid/test-song-normal-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-normal-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-normal-transitions.json",
    description:
      "Section-aware normal hybrid assembled from multiple tournament candidates with transition checks and validator-backed promotion rules.",
  },
  {
    id: "hybrid-hard",
    label: "Hybrid Hard",
    path: "/maps/hybrid/test-song-hard.json",
    kind: "hybrid",
    group: "Hybrid",
    difficulty: "hard",
    reportPath: "/reports/hybrid/test-song-hard-report.json",
    analysisPath: "/analysis/test-song-analysis.json",
    sectionAnalysisPath: "/sections/test-song-sections.json",
    hybridAssemblyPath: "/hybrids/test-song-hard-assembly.json",
    hybridTransitionLogPath: "/hybrids/test-song-hard-transitions.json",
    description:
      "Section-aware hard hybrid assembled from multiple tournament candidates with transition checks and validator-backed promotion rules.",
  },
];

let projectMapCatalog = BASE_PROJECT_MAP_CATALOG.slice();
let catalogLoadPromise: Promise<ProjectMapCatalogEntry[]> | null = null;

export function getProjectMapCatalog(): ProjectMapCatalogEntry[] {
  return projectMapCatalog.slice();
}

export async function initializeProjectMapCatalog(
  forceRefresh = false,
): Promise<ProjectMapCatalogEntry[]> {
  if (forceRefresh) {
    catalogLoadPromise = null;
  }

  if (!catalogLoadPromise) {
    catalogLoadPromise = loadProjectMapCatalogEntries()
      .then((entries) => {
        projectMapCatalog = entries;
        return getProjectMapCatalog();
      })
      .catch((error) => {
        catalogLoadPromise = null;
        throw error;
      });
  }

  return await catalogLoadPromise;
}

export function getProjectMapById(
  mapId: string,
): ProjectMapCatalogEntry | undefined {
  return projectMapCatalog.find((entry) => entry.id === mapId);
}

export function getProjectMapByPath(
  path: string,
): ProjectMapCatalogEntry | undefined {
  return projectMapCatalog.find((entry) => entry.path === path);
}

export function groupProjectMaps(): Array<{
  label: string;
  items: ProjectMapCatalogEntry[];
}> {
  const grouped = new Map<string, ProjectMapCatalogEntry[]>();

  for (const entry of projectMapCatalog) {
    const existing = grouped.get(entry.group);
    if (existing) {
      existing.push(entry);
      continue;
    }

    grouped.set(entry.group, [entry]);
  }

  return Array.from(grouped.entries()).map(([label, items]) => ({
    label,
    items,
  }));
}

export function buildEditorUrl(
  mapPath?: string | RuntimeProjectMapSelection,
): string {
  if (!mapPath) {
    return "/editor.html";
  }

  if (typeof mapPath === "string") {
    const params = new URLSearchParams({ map: mapPath });
    return `/editor.html?${params.toString()}`;
  }

  return buildPreviewPageUrl("/editor.html", mapPath);
}

export function buildGameUrl(
  mapSelection?: string | RuntimeProjectMapSelection,
): string {
  if (!mapSelection) {
    return "/index.html";
  }

  if (typeof mapSelection === "string") {
    const params = new URLSearchParams({ map: mapSelection });
    return `/index.html?${params.toString()}`;
  }

  return buildPreviewPageUrl("/index.html", mapSelection);
}

export function resolveRequestedProjectMap(
  searchParams: URLSearchParams,
): ProjectMapCatalogEntry | undefined {
  const runtimePath = optionalString(searchParams.get("mapUrl") ?? undefined);
  if (runtimePath) {
    return {
      id: `runtime:${runtimePath}`,
      label: optionalString(searchParams.get("label") ?? undefined) ?? "Workspace Preview",
      path: runtimePath,
      kind: parseProjectMapKind(searchParams.get("kind")) ?? "generated",
      group: "Workspace Preview",
      description:
        optionalString(searchParams.get("description") ?? undefined) ??
        "Preview of a locally generated workspace map.",
      difficulty: toDifficultyName(searchParams.get("difficulty") ?? undefined),
      reportPath: optionalString(searchParams.get("reportPath") ?? undefined),
      correctionReportPath: optionalString(
        searchParams.get("correctionReportPath") ?? undefined,
      ),
      tournamentReportPath: optionalString(
        searchParams.get("tournamentReportPath") ?? undefined,
      ),
      analysisPath: optionalString(searchParams.get("analysisPath") ?? undefined),
      evolutionReportPath: optionalString(
        searchParams.get("evolutionReportPath") ?? undefined,
      ),
      sectionAnalysisPath: optionalString(
        searchParams.get("sectionAnalysisPath") ?? undefined,
      ),
      phraseAnalysisPath: optionalString(
        searchParams.get("phraseAnalysisPath") ?? undefined,
      ),
      recoveryAnalysisPath: optionalString(
        searchParams.get("recoveryAnalysisPath") ?? undefined,
      ),
      hybridAssemblyPath: optionalString(
        searchParams.get("hybridAssemblyPath") ?? undefined,
      ),
      hybridTransitionLogPath: optionalString(
        searchParams.get("hybridTransitionLogPath") ?? undefined,
      ),
      importReportPath: optionalString(
        searchParams.get("importReportPath") ?? undefined,
      ),
      difficultyReportPath: optionalString(
        searchParams.get("difficultyReportPath") ?? undefined,
      ),
    };
  }

  const catalogPath = optionalString(searchParams.get("map") ?? undefined);
  if (catalogPath) {
    return getProjectMapByPath(catalogPath);
  }

  const catalogId = optionalString(searchParams.get("mapId") ?? undefined);
  return catalogId ? getProjectMapById(catalogId) : undefined;
}

async function loadProjectMapCatalogEntries(): Promise<ProjectMapCatalogEntry[]> {
  const importedEntries = await loadImportedMapEntries();
  return [...BASE_PROJECT_MAP_CATALOG, ...importedEntries];
}

async function loadImportedMapEntries(): Promise<ProjectMapCatalogEntry[]> {
  const manifest = await loadImportedManifest();
  if (!manifest) {
    return [];
  }

  const entries = await Promise.all(
    manifest.maps.map((item) => toImportedCatalogEntry(item)),
  );

  return entries
    .filter((entry): entry is ProjectMapCatalogEntry => Boolean(entry))
    .sort((left, right) => left.label.localeCompare(right.label));
}

async function loadImportedManifest(): Promise<ImportedMapManifest | undefined> {
  if (typeof fetch !== "function") {
    return undefined;
  }

  let response: Response;
  try {
    response = await fetch(IMPORTED_MAP_MANIFEST_PATH, {
      cache: "no-store",
    });
  } catch {
    return undefined;
  }

  if (!response.ok) {
    return undefined;
  }

  let rawValue: unknown;
  try {
    rawValue = await response.json();
  } catch {
    return undefined;
  }

  return isImportedManifest(rawValue) ? rawValue : undefined;
}

async function toImportedCatalogEntry(
  item: ImportedMapManifestEntry,
): Promise<ProjectMapCatalogEntry | undefined> {
  if (!(await publicAssetExists(item.path))) {
    return undefined;
  }

  return {
    id: item.id,
    label: item.label,
    path: item.path,
    kind: "imported",
    group: item.group ?? "Imported Maps",
    description:
      item.description ??
      `Imported circle-only osu!standard map for ${item.label}.`,
    difficulty: toDifficultyName(item.difficulty),
    reportPath: optionalString(item.reportPath),
    correctionReportPath: optionalString(item.correctionReportPath),
    tournamentReportPath: optionalString(item.tournamentReportPath),
    analysisPath: optionalString(item.analysisPath),
    sectionAnalysisPath: optionalString(item.sectionAnalysisPath),
    phraseAnalysisPath: optionalString(item.phraseAnalysisPath),
    recoveryAnalysisPath: optionalString(item.recoveryAnalysisPath),
    hybridAssemblyPath: optionalString(item.hybridAssemblyPath),
    hybridTransitionLogPath: optionalString(item.hybridTransitionLogPath),
    importReportPath: optionalString(item.importReportPath),
    difficultyReportPath: optionalString(item.difficultyReportPath),
    evolutionReportPath: optionalString(item.evolutionReportPath),
  };
}

async function publicAssetExists(path: string): Promise<boolean> {
  if (typeof fetch !== "function") {
    return false;
  }

  try {
    const headResponse = await fetch(path, {
      method: "HEAD",
      cache: "no-store",
    });
    if (headResponse.ok) {
      return true;
    }
    if (headResponse.status !== 405) {
      return false;
    }
  } catch {
    // Some local static servers do not support HEAD consistently.
  }

  try {
    const getResponse = await fetch(path, {
      cache: "no-store",
    });
    return getResponse.ok;
  } catch {
    return false;
  }
}

function isImportedManifest(value: unknown): value is ImportedMapManifest {
  if (!isJsonObject(value)) {
    return false;
  }

  if (typeof value.version !== "number" || !Array.isArray(value.maps)) {
    return false;
  }

  return value.maps.every(isImportedManifestEntry);
}

function isImportedManifestEntry(value: unknown): value is ImportedMapManifestEntry {
  return (
    isJsonObject(value) &&
    typeof value.id === "string" &&
    value.id.trim().length > 0 &&
    typeof value.label === "string" &&
    value.label.trim().length > 0 &&
    typeof value.path === "string" &&
    value.path.startsWith("/maps/imported/")
  );
}

function optionalString(value: string | undefined): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function buildPreviewPageUrl(
  pagePath: string,
  selection: RuntimeProjectMapSelection,
): string {
  const params = new URLSearchParams({
    mapUrl: selection.path,
  });

  setOptionalParam(params, "label", selection.label);
  setOptionalParam(params, "kind", selection.kind);
  setOptionalParam(params, "description", selection.description);
  setOptionalParam(params, "difficulty", selection.difficulty);
  setOptionalParam(params, "reportPath", selection.reportPath);
  setOptionalParam(params, "correctionReportPath", selection.correctionReportPath);
  setOptionalParam(params, "tournamentReportPath", selection.tournamentReportPath);
  setOptionalParam(params, "analysisPath", selection.analysisPath);
  setOptionalParam(params, "sectionAnalysisPath", selection.sectionAnalysisPath);
  setOptionalParam(params, "phraseAnalysisPath", selection.phraseAnalysisPath);
  setOptionalParam(params, "recoveryAnalysisPath", selection.recoveryAnalysisPath);
  setOptionalParam(params, "hybridAssemblyPath", selection.hybridAssemblyPath);
  setOptionalParam(
    params,
    "hybridTransitionLogPath",
    selection.hybridTransitionLogPath,
  );
  setOptionalParam(params, "importReportPath", selection.importReportPath);
  setOptionalParam(params, "difficultyReportPath", selection.difficultyReportPath);
  setOptionalParam(params, "evolutionReportPath", selection.evolutionReportPath);
  return `${pagePath}?${params.toString()}`;
}

function setOptionalParam(
  params: URLSearchParams,
  key: string,
  value: string | undefined,
): void {
  if (value && value.trim().length > 0) {
    params.set(key, value);
  }
}

function parseProjectMapKind(value: string | null): ProjectMapKind | undefined {
  if (
    value === "manual" ||
    value === "generated" ||
    value === "improved" ||
    value === "champion" ||
    value === "hybrid" ||
    value === "imported"
  ) {
    return value;
  }

  return undefined;
}

function toDifficultyName(value: string | undefined): DifficultyName | undefined {
  if (value === "easy" || value === "normal" || value === "hard") {
    return value;
  }

  return undefined;
}
