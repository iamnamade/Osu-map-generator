import {
  parseHybridAssemblyReport,
  type HybridAssemblyReport,
} from "../shared/sectionData";

export type HybridAssemblyReportLoadResult =
  | { status: "ok"; report: HybridAssemblyReport }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

export async function loadHybridAssemblyReport(
  url: string,
): Promise<HybridAssemblyReportLoadResult> {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (response.status === 404) {
    return {
      status: "missing",
      message: "Hybrid assembly report has not been generated yet.",
    };
  }

  if (!response.ok) {
    return {
      status: "error",
      message: `Hybrid assembly report could not be loaded from ${url}.`,
    };
  }

  if (!contentType.includes("application/json")) {
    return {
      status: "missing",
      message: "Hybrid assembly report has not been generated yet.",
    };
  }

  let rawData: unknown;
  try {
    rawData = await response.json();
  } catch (error) {
    return {
      status: "error",
      message: `Hybrid assembly report JSON at ${url} is invalid: ${
        error instanceof Error ? error.message : "unknown parse error"
      }`,
    };
  }

  try {
    return {
      status: "ok",
      report: parseHybridAssemblyReport(rawData),
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error
          ? `Hybrid assembly report at ${url} is malformed: ${error.message}`
          : `Hybrid assembly report at ${url} is malformed.`,
    };
  }
}
