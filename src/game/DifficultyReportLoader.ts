import { parseDifficultyReport } from "../shared/difficultyReport";
import type { DifficultyReport } from "../shared/difficultyReport";

type DifficultyReportLoadResult =
  | { status: "ok"; report: DifficultyReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadDifficultyReport(
  url: string,
): Promise<DifficultyReportLoadResult> {
  let response: Response;

  try {
    response = await fetch(url);
  } catch {
    return {
      status: "error",
      message: `Difficulty report could not be loaded from ${url}.`,
    };
  }

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Difficulty report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Difficulty report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Difficulty report has not been generated yet.",
    };
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Difficulty report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parseDifficultyReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Difficulty report at ${url} is malformed: ${error.message}`
          : `Difficulty report at ${url} is malformed.`,
    };
  }
}

export type { DifficultyReportLoadResult };
