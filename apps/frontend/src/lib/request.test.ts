// #286: shared request<T> helper. Cover the three failure paths (network
// error, non-ok error envelope, shape guard) plus the success JSON parse.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { guardShape, request } from "./request";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("resolves the parsed JSON payload on success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ partner_id: 7, ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/v1/placeholder")).resolves.toEqual({
      partner_id: 7,
      ok: true,
    });

    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/placeholder",
    );
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(request("/v1/placeholder")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
    await expect(request("/v1/placeholder")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INVALID_ARGS",
            message: "bad",
            trace_id: "t",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(request("/v1/placeholder")).rejects.toMatchObject({
      code: "INVALID_ARGS",
    });
  });
});

describe("guardShape", () => {
  const isThing = (value: unknown): value is { id: number } =>
    typeof value === "object" &&
    value !== null &&
    "id" in (value as { id?: unknown }) &&
    typeof (value as { id?: unknown }).id === "number";

  it("returns the value when the guard passes", () => {
    expect(guardShape({ id: 1 }, isThing, "bad shape")).toEqual({ id: 1 });
  });

  it("throws ApiError with UNEXPECTED_ERROR when the guard fails", () => {
    expect(() => guardShape({ id: "x" }, isThing, "bad shape")).toThrow(
      ApiError,
    );
    try {
      guardShape({ id: "x" }, isThing, "unexpected thing shape");
    } catch (error) {
      expect((error as ApiError).code).toBe("UNEXPECTED_ERROR");
      expect(error).toMatchObject({ message: "unexpected thing shape" });
    }
  });
});
