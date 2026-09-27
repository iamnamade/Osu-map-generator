import { parseRecoveryReport, type RecoveryReport } from "../shared/recoveryData";

export type RecoveryAnalysisLoadResult =
  | { status: "ok"; report: RecoveryReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadRecoveryAnalysis(
  url: string,
): Promise<RecoveryAnalysisLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Recovery & fatigue analysis has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Recovery analysis could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Recovery & fatigue analysis has not been generated yet.",
    };
  }

  let rawData: unknown;
  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Recovery analysis JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parseRecoveryReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Recovery analysis at ${url} is malformed: ${error.message}`
          : `Recovery analysis at ${url} is malformed.`,
    };
  }
}
