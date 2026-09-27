import { parseEvolutionReport } from "../shared/evolutionReport";
import type { EvolutionReport } from "../shared/evolutionReport";

type EvolutionReportLoadResult =
  | { status: "ok"; report: EvolutionReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadEvolutionReport(
  url: string,
): Promise<EvolutionReportLoadResult> {
  let response: Response;

  try {
    response = await fetch(url);
  } catch {
    return {
      status: "error",
      message: `Evolution report could not be loaded from ${url}.`,
    };
  }

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Evolution report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Evolution report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Evolution report has not been generated yet.",
    };
  }

  let rawData: unknown;

  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Evolution report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parseEvolutionReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Evolution report at ${url} is malformed: ${error.message}`
          : `Evolution report at ${url} is malformed.`,
    };
  }
}

export type { EvolutionReportLoadResult };
