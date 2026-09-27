import { isJsonObject } from "../../shared/JsonTypes";

export interface ChampionHistoryEntry {
  sequence: number;
  previousChampionIndex: number | null;
  previousMapPath: string | null;
  newChampionIndex: number;
  newChampionScore: number;
  newMapPath: string;
  timestamp: string;
  reason: string;
  manual: boolean;
}

export interface CandidateWorkspacePersistence {
  championCandidateIndex?: number;
  history: ChampionHistoryEntry[];
  notes: Record<string, string>;
}

const DEFAULT_HISTORY_LIMIT = 50;

export function createChampionHistoryEntry(params: {
  sequence: number;
  previousChampionIndex: number | null;
  previousMapPath: string | null;
  newChampionIndex: number;
  newChampionScore: number;
  newMapPath: string;
  timestamp?: string;
  reason: string;
  manual: boolean;
}): ChampionHistoryEntry {
  return {
    sequence: params.sequence,
    previousChampionIndex: params.previousChampionIndex,
    previousMapPath: params.previousMapPath ?? null,
    newChampionIndex: params.newChampionIndex,
    newChampionScore: params.newChampionScore,
    newMapPath: params.newMapPath,
    timestamp: params.timestamp ?? new Date().toISOString(),
    reason: params.reason,
    manual: params.manual,
  };
}

export function appendChampionHistory(
  history: ChampionHistoryEntry[],
  entry: ChampionHistoryEntry,
  limit = DEFAULT_HISTORY_LIMIT,
): ChampionHistoryEntry[] {
  return [...history, entry].slice(-limit);
}

export function parseChampionHistory(rawValue: unknown): ChampionHistoryEntry[] {
  if (!Array.isArray(rawValue)) {
    return [];
  }

  const output: ChampionHistoryEntry[] = [];
  for (const item of rawValue) {
    if (!isJsonObject(item)) {
      continue;
    }

    if (
      typeof item.sequence !== "number" ||
      typeof item.newChampionIndex !== "number" ||
      typeof item.newMapPath !== "string" ||
      typeof item.timestamp !== "string" ||
      typeof item.reason !== "string"
    ) {
      continue;
    }

    output.push({
      sequence: item.sequence,
      previousChampionIndex:
        item.previousChampionIndex === null || typeof item.previousChampionIndex === "number"
          ? item.previousChampionIndex
          : null,
      previousMapPath:
        typeof item.previousMapPath === "string" ? item.previousMapPath : null,
      newChampionIndex: item.newChampionIndex,
      newChampionScore:
        typeof item.newChampionScore === "number" && Number.isFinite(item.newChampionScore)
          ? item.newChampionScore
          : 0,
      newMapPath: item.newMapPath,
      timestamp: item.timestamp,
      reason: item.reason,
      manual: item.manual === true,
    });
  }

  return output.sort((left, right) => left.sequence - right.sequence);
}

export function serializeChampionHistory(
  history: ChampionHistoryEntry[],
): ChampionHistoryEntry[] {
  return history.map((entry) => ({ ...entry }));
}

export function buildCandidateWorkspaceKey(params: {
  title: string;
  artist?: string;
  difficulty: string;
}): string {
  const difficulty = params.difficulty || "unknown";
  const title = (params.title || "untitled").trim();
  const artist = (params.artist || "").trim();
  const rawKey = `${difficulty}:${title}:${artist}`;
  return `pulse-editor.candidates.${sanitizeStorageKey(rawKey)}`;
}

export function loadCandidateWorkspace(
  key: string,
): CandidateWorkspacePersistence | undefined {
  if (typeof localStorage === "undefined") {
    return undefined;
  }

  const rawValue = localStorage.getItem(key);
  if (!rawValue) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!isJsonObject(parsed)) {
      return undefined;
    }

    return {
      championCandidateIndex:
        typeof parsed.championCandidateIndex === "number" &&
        Number.isFinite(parsed.championCandidateIndex)
          ? parsed.championCandidateIndex
          : undefined,
      history: parseChampionHistory(parsed.history),
      notes: parseNotes(parsed.notes),
    };
  } catch {
    return undefined;
  }
}

export function saveCandidateWorkspace(
  key: string,
  data: CandidateWorkspacePersistence,
): boolean {
  if (typeof localStorage === "undefined") {
    return false;
  }

  try {
    localStorage.setItem(
      key,
      JSON.stringify({
        championCandidateIndex: data.championCandidateIndex,
        history: data.history,
        notes: data.notes,
      }),
    );
    return true;
  } catch {
    return false;
  }
}

export function clearCandidateWorkspace(key: string): void {
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem(key);
  }
}

export function candidateNoteKey(
  workspaceKey: string,
  candidateIndex: number,
): string {
  return `${workspaceKey}:candidate-${String(candidateIndex).padStart(3, "0")}`;
}

function parseNotes(rawValue: unknown): Record<string, string> {
  if (!isJsonObject(rawValue)) {
    return {};
  }

  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(rawValue)) {
    if (typeof value === "string") {
      output[key] = value;
    }
  }
  return output;
}

function sanitizeStorageKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9:._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 120);
}
