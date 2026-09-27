import {
  parseCandidateSectionReport,
  type CandidateSectionReport,
} from "../shared/sectionData";

export type CandidateSectionReportLoadResult =
  | { status: "ok"; report: CandidateSectionReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadCandidateSectionReport(
  url: string,
): Promise<CandidateSectionReportLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Candidate section report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Candidate section report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Candidate section report has not been generated yet.",
    };
  }

  let rawData: unknown;
  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Candidate section report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parseCandidateSectionReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Candidate section report at ${url} is malformed: ${error.message}`
          : `Candidate section report at ${url} is malformed.`,
    };
  }
}
