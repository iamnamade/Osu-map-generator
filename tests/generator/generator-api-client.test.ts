import { afterEach, describe, expect, it, vi } from "vitest";

import { GeneratorApiClient, GeneratorApiError } from "../../src/generator/GeneratorApiClient";
import { createEmptyMetadataDraft } from "../../src/generator/GeneratorModels";

const originalFetch = globalThis.fetch;

afterEach(() => {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    return;
  }

  delete (globalThis as { fetch?: unknown }).fetch;
});

describe("generator api client", () => {
  it("surfaces structured metadata validation errors as readable messages", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "INVALID_METADATA",
            message: "Song title is required before generation.",
            fields: {
              title: "Title is required.",
            },
          },
        }),
        {
          status: 422,
          statusText: "Unprocessable Entity",
          headers: { "content-type": "application/json" },
        },
      ),
    ) as typeof fetch;

    const client = new GeneratorApiClient();

    await expect(
      client.updateMetadata("workspace-1", createEmptyMetadataDraft()),
    ).rejects.toEqual(
      expect.objectContaining<Partial<GeneratorApiError>>({
        message: "Song title is required before generation.",
        statusCode: 422,
      }),
    );
  });
});
