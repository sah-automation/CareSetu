// #797: the effective-settings read. The client must reject a payload whose
// settings rows do not carry the documented fields, especially an unknown
// `source` - the page renders that source as a badge, so a surprise value is a
// contract break rather than something to display raw.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { request } from "@/lib/request";

import { fetchEffectiveSettings } from "./settings";

vi.mock("@/lib/request", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/request")>();
  return { ...actual, request: vi.fn() };
});

const mockRequest = vi.mocked(request);

describe("fetchEffectiveSettings (#797)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reads the effective settings endpoint", async () => {
    const settings = [
      {
        key: "ai.model",
        value: null,
        source: "environment",
        editable: false,
        restart_required: true,
      },
      {
        key: "ai.timeout_seconds",
        value: 30,
        source: "database",
        editable: true,
        restart_required: false,
      },
    ];
    mockRequest.mockResolvedValue({ settings });

    await expect(fetchEffectiveSettings()).resolves.toEqual(settings);
    expect(mockRequest).toHaveBeenCalledWith("/v1/operator/settings/effective");
  });

  it("rejects an unknown source", async () => {
    mockRequest.mockResolvedValue({
      settings: [
        {
          key: "ai.model",
          value: "gpt",
          source: "vault",
          editable: true,
          restart_required: false,
        },
      ],
    });

    await expect(fetchEffectiveSettings()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a payload without a settings array", async () => {
    mockRequest.mockResolvedValue({ items: [] });

    await expect(fetchEffectiveSettings()).rejects.toBeInstanceOf(ApiError);
  });
});
