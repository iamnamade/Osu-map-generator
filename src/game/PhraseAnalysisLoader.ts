import { parsePhraseReport, type PhraseReport } from "../shared/phraseData";

export type PhraseAnalysisLoadResult =
  | { status: "ok"; report: PhraseReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadPhraseAnalysis(
  url: string,
): Promise<PhraseAnalysisLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Phrase analysis has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Phrase analysis could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Phrase analysis has not been generated yet.",
    };
  }

  let rawData: unknown;
  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Phrase analysis JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parsePhraseReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Phrase analysis at ${url} is malformed: ${error.message}`
          : `Phrase analysis at ${url} is malformed.`,
    };
  }
}
