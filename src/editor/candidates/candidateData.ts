import { isJsonObject } from "../../shared/JsonTypes";
import { parseEditorMapDocument } from "../EditorMapLoader";
import type { EditorMapDocument } from "../models/EditorModels";
import type {
  CandidateRebalanceDetail,
  CandidateReplayDetail,
  CandidateSectionRebalance,
  CandidateSectionReplay,
} from "./candidateModels";

export function toBrowserPath(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const withoutPublic = normalized.replace(/^public\//, "");
  return withoutPublic.startsWith("/") ? withoutPublic : `/${withoutPublic}`;
}

export async function loadCandidateMapDocument(
  mapPath: string,
): Promise<EditorMapDocument | null> {
  const url = toBrowserPath(mapPath);

  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }

    const rawData = (await response.json()) as unknown;
    return parseEditorMapDocument(rawData);
  } catch {
    return null;
  }
}

export async function loadCandidateReplayDetail(
  replayReportPath: string | null,
): Promise<CandidateReplayDetail | null> {
  if (!replayReportPath) {
    return null;
  }

  const rawData = await fetchJson(toBrowserPath(replayReportPath));
  if (!rawData) {
    return null;
  }

  const expectedAccuracy = numberField(rawData, "expectedAccuracy");
  const expectedMisses = numberField(rawData, "expectedMisses");
  const combo = isJsonObject(rawData.combo)
    ? rawData.combo
    : undefined;
  const fatigue = isJsonObject(rawData.fatigue)
    ? rawData.fatigue
    : undefined;
  const reading = isJsonObject(rawData.reading)
    ? rawData.reading
    : undefined;
  const scoreBreakdown = isJsonObject(rawData.scoreBreakdown)
    ? rawData.scoreBreakdown
    : undefined;

  return {
    expectedAccuracy,
    expectedMisses,
    expectedComboPct: numberField(combo, "expectedComboPct"),
    fatigueAverage: numberField(fatigue, "average"),
    fatiguePeak: numberField(fatigue, "peak"),
    readingScore: numberField(reading, "score"),
    replayScore: numberField(scoreBreakdown, "overall"),
    sections: parseReplaySections(rawData),
  };
}

export async function loadCandidateRebalanceDetail(
  rebalanceReportPath: string | null,
): Promise<CandidateRebalanceDetail | null> {
  if (!rebalanceReportPath) {
    return null;
  }

  const rawData = await fetchJson(toBrowserPath(rebalanceReportPath));
  if (!rawData) {
    return null;
  }

  const summary = isJsonObject(rawData.summary) ? rawData.summary : undefined;

  return {
    qualityGain: numberField(summary, "qualityGain"),
    replayGain: numberField(summary, "replayGain"),
    qualityBefore: numberField(summary, "qualityBefore"),
    qualityAfter: numberField(summary, "qualityAfter"),
    sections: parseRebalanceSections(rawData),
  };
}

export async function loadCandidateDetails(
  entry: {
    mapPath: string;
    replayReportPath: string | null;
    rebalanceReportPath: string | null;
  },
): Promise<{
  replay: CandidateReplayDetail | null;
  rebalance: CandidateRebalanceDetail | null;
}> {
  const [replay, rebalance] = await Promise.all([
    loadCandidateReplayDetail(entry.replayReportPath),
    loadCandidateRebalanceDetail(entry.rebalanceReportPath),
  ]);

  return { replay, rebalance };
}

function parseReplaySections(rawData: Record<string, unknown>): CandidateSectionReplay[] {
  if (!Array.isArray(rawData.sections)) {
    return [];
  }

  const output: CandidateSectionReplay[] = [];
  for (const item of rawData.sections) {
    if (!isJsonObject(item)) {
      continue;
    }

    const sectionId = numberField(item, "sectionId");
    const label = typeof item.label === "string" ? item.label : "";
    if (sectionId === null) {
      continue;
    }

    output.push({
      sectionId,
      label,
      objectCount: numberField(item, "objectCount") ?? 0,
      accuracy: numberField(item, "accuracy") ?? 0,
      fatiguePeak: numberField(item, "fatiguePeak") ?? 0,
      readingDemand: numberField(item, "readingDemand") ?? 0,
    });
  }

  return output.sort((left, right) => left.sectionId - right.sectionId);
}

function parseRebalanceSections(
  rawData: Record<string, unknown>,
): CandidateSectionRebalance[] {
  if (!Array.isArray(rawData.sections)) {
    return [];
  }

  const output: CandidateSectionRebalance[] = [];
  for (const item of rawData.sections) {
    if (!isJsonObject(item)) {
      continue;
    }

    const sectionId = numberField(item, "sectionId");
    const label = typeof item.label === "string" ? item.label : "";
    if (sectionId === null) {
      continue;
    }

    output.push({
      sectionId,
      label,
      objectCount: numberField(item, "objectCount") ?? 0,
      starRating: numberField(item, "starRating") ?? 0,
      density: numberField(item, "density") ?? 0,
      rhythmConsistency: numberField(item, "rhythmConsistency") ?? 0,
      cursorTravelPx: numberField(item, "cursorTravelPx") ?? 0,
      readingScore: numberField(item, "readingScore") ?? 0,
      fatigueAverage: numberField(item, "fatigueAverage") ?? 0,
      qualityScore: numberField(item, "qualityScore") ?? 0,
    });
  }

  return output.sort((left, right) => left.sectionId - right.sectionId);
}

async function fetchJson(url: string): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }

    const rawData = (await response.json()) as unknown;
    return isJsonObject(rawData) ? rawData : null;
  } catch {
    return null;
  }
}

function numberField(
  record: Record<string, unknown> | undefined,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
