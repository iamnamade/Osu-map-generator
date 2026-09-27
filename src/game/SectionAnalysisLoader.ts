import { parseSectionAnalysis, type SectionAnalysis } from "../shared/sectionData";

export type SectionAnalysisLoadResult =
  | { status: "ok"; analysis: SectionAnalysis }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadSectionAnalysis(
  url: string,
): Promise<SectionAnalysisLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Section analysis has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Section analysis could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Section analysis has not been generated yet.",
    };
  }

  let rawData: unknown;
  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Section analysis JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      analysis: parseSectionAnalysis(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Section analysis at ${url} is malformed: ${error.message}`
          : `Section analysis at ${url} is malformed.`,
    };
  }
}
