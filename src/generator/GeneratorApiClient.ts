import type {
  AudioUploadResponse,
  BackgroundUploadResponse,
  HealthResponse,
  JobStateResponse,
  WorkspaceMetadata,
  WorkspaceResponse,
} from "./GeneratorModels";

export class GeneratorApiError extends Error {
  constructor(
    message: string,
    readonly statusCode?: number,
  ) {
    super(message);
    this.name = "GeneratorApiError";
  }
}

export class GeneratorApiClient {
  constructor(private readonly basePath = "/api") {}

  async health(): Promise<HealthResponse> {
    return await this.requestJson<HealthResponse>("/health");
  }

  async createWorkspace(): Promise<WorkspaceResponse> {
    return await this.requestJson<WorkspaceResponse>("/workspaces", {
      method: "POST",
    });
  }

  async getWorkspace(workspaceId: string): Promise<WorkspaceResponse> {
    return await this.requestJson<WorkspaceResponse>(`/workspaces/${workspaceId}`);
  }

  async uploadAudio(
    workspaceId: string,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<AudioUploadResponse> {
    return await this.uploadFile<AudioUploadResponse>(
      `/workspaces/${workspaceId}/audio`,
      file,
      onProgress,
    );
  }

  async uploadBackground(
    workspaceId: string,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<BackgroundUploadResponse> {
    return await this.uploadFile<BackgroundUploadResponse>(
      `/workspaces/${workspaceId}/background`,
      file,
      onProgress,
    );
  }

  // P1.1: stable server URLs for local previews. Unlike client-side blob URLs
  // these survive a page reload, so the UI can rebuild the previews on boot.
  backgroundPreviewUrl(workspaceId: string, filename: string): string {
    return this.resolvePath(
      `/workspaces/${encodeURIComponent(workspaceId)}/preview-background/${encodeURIComponent(filename)}`,
    );
  }

  // P1.2: the waveform decodes from the same preview endpoint the pipeline uses.
  audioPreviewUrl(workspaceId: string, filename: string): string {
    return this.resolvePath(
      `/workspaces/${encodeURIComponent(workspaceId)}/source-audio/${encodeURIComponent(filename)}`,
    );
  }

  async updateMetadata(
    workspaceId: string,
    payload: WorkspaceMetadata,
  ): Promise<WorkspaceResponse> {
    return await this.requestJson<WorkspaceResponse>(
      `/workspaces/${workspaceId}/metadata`,
      {
        method: "PUT",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    );
  }

  async startGeneration(workspaceId: string): Promise<JobStateResponse> {
    return await this.requestJson<JobStateResponse>(
      `/workspaces/${workspaceId}/generate`,
      {
        method: "POST",
      },
    );
  }

  async getJob(jobId: string, since = 0): Promise<JobStateResponse> {
    const query = since > 0 ? `?since=${encodeURIComponent(String(since))}` : "";
    return await this.requestJson<JobStateResponse>(`/jobs/${jobId}${query}`);
  }

  async cancelJob(jobId: string): Promise<JobStateResponse> {
    return await this.requestJson<JobStateResponse>(`/jobs/${jobId}/cancel`, {
      method: "POST",
    });
  }

  async deleteWorkspace(workspaceId: string): Promise<void> {
    await this.requestJson<{ status: string }>(`/workspaces/${workspaceId}`, {
      method: "DELETE",
    });
  }

  private async requestJson<T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(this.resolvePath(path), init);
    } catch (error) {
      throw new GeneratorApiError(
        error instanceof Error
          ? `Local API request failed: ${error.message}`
          : "Local API request failed.",
      );
    }

    let parsedBody: unknown;
    const responseText = await response.text();
    if (responseText) {
      try {
        parsedBody = JSON.parse(responseText) as unknown;
      } catch {
        parsedBody = responseText;
      }
    }

    if (!response.ok) {
      throw new GeneratorApiError(
        extractApiErrorMessage(parsedBody, response.statusText),
        response.status,
      );
    }

    return parsedBody as T;
  }

  private async uploadFile<T>(
    path: string,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<T> {
    return await new Promise<T>((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", this.resolvePath(path), true);
      request.responseType = "text";

      request.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable || !onProgress) {
          return;
        }

        const nextPercent = Math.max(
          0,
          Math.min(100, Math.round((event.loaded / event.total) * 100)),
        );
        onProgress(nextPercent);
      });

      request.addEventListener("load", () => {
        const responseText =
          typeof request.response === "string" ? request.response : request.responseText;
        let parsedBody: unknown;
        if (responseText) {
          try {
            parsedBody = JSON.parse(responseText) as unknown;
          } catch {
            parsedBody = responseText;
          }
        }

        if (request.status < 200 || request.status >= 300) {
          reject(
            new GeneratorApiError(
              extractApiErrorMessage(parsedBody, request.statusText),
              request.status,
            ),
          );
          return;
        }

        resolve(parsedBody as T);
      });

      request.addEventListener("error", () => {
        reject(new GeneratorApiError("Local API upload failed."));
      });

      const formData = new FormData();
      formData.append("file", file, file.name);
      request.send(formData);
    });
  }

  private resolvePath(path: string): string {
    const normalizedBase = this.basePath.endsWith("/")
      ? this.basePath.slice(0, -1)
      : this.basePath;
    return `${normalizedBase}${path.startsWith("/") ? path : `/${path}`}`;
  }
}

export function extractApiErrorMessage(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }

  if (typeof value === "object" && value !== null) {
    const detail = (value as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
    if (typeof detail === "object" && detail !== null) {
      const detailMessage = (detail as Record<string, unknown>).message;
      if (typeof detailMessage === "string" && detailMessage.trim().length > 0) {
        return detailMessage;
      }

      const detailFields = (detail as Record<string, unknown>).fields;
      if (typeof detailFields === "object" && detailFields !== null) {
        const firstFieldMessage = Object.values(
          detailFields as Record<string, unknown>,
        ).find(
          (fieldValue) =>
            typeof fieldValue === "string" && fieldValue.trim().length > 0,
        );
        if (typeof firstFieldMessage === "string") {
          return firstFieldMessage;
        }
      }
    }

    const message = (value as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
  }

  return fallback || "Local API request failed.";
}
