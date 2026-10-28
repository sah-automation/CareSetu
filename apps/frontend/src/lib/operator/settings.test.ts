// #797: the effective-settings read. The client must reject a payload whose
// settings rows do not carry the documented fields, especially an unknown
// `source` - the page renders that source as a badge, so a surprise value is a
// contract break rather than something to display raw.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { IDEMPOTENCY_KEY_HEADER } from "@/lib/idempotency";
import { request } from "@/lib/request";

import {
  fetchEffectiveSettings,
  fetchSettingHistory,
  writeSetting,
} from "./settings";

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

describe("writeSetting (#798)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("puts the setting key and value with an idempotency key", async () => {
    mockRequest.mockResolvedValue({
      setting_key: "ai.timeout_seconds",
      value: 20,
      version: 4,
    });

    await expect(writeSetting("ai.timeout_seconds", 20)).resolves.toEqual({
      setting_key: "ai.timeout_seconds",
      value: 20,
      version: 4,
    });

    const [path, init] = mockRequest.mock.calls[0];
    expect(path).toBe("/v1/operator/settings");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({
      setting_key: "ai.timeout_seconds",
      value: 20,
    });
    expect(
      (init?.headers as Record<string, string>)[IDEMPOTENCY_KEY_HEADER],
    ).toBeTruthy();
  });

  it("rejects a payload without a version", async () => {
    mockRequest.mockResolvedValue({
      setting_key: "ai.timeout_seconds",
      value: 20,
    });

    await expect(writeSetting("ai.timeout_seconds", 20)).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("fetchSettingHistory (#798)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reads the history endpoint and encodes the key filter", async () => {
    const history = [
      {
        setting_key: "ai.timeout_seconds",
        value: 20,
        version: 4,
        changed_by: 7,
        changed_at: "2026-03-04T10:00:00Z",
      },
    ];
    mockRequest.mockResolvedValue({ history });

    await expect(fetchSettingHistory("ai.timeout_seconds")).resolves.toEqual(
      history,
    );
    expect(mockRequest).toHaveBeenCalledWith(
      "/v1/operator/settings/history?setting_key=ai.timeout_seconds",
    );
  });

  it("rejects a row with an unknown actor shape", async () => {
    mockRequest.mockResolvedValue({
      history: [
        {
          setting_key: "ai.timeout_seconds",
          value: 20,
          version: 4,
          changed_by: "admin",
          changed_at: "2026-03-04T10:00:00Z",
        },
      ],
    });

    await expect(fetchSettingHistory()).rejects.toBeInstanceOf(ApiError);
  });
});
