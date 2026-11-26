// #286: shared request<T> helper. Cover the three failure paths (network
// error, non-ok error envelope, shape guard) plus the success JSON parse.
// #543 adds the no-content transport the 204-returning photo delete needs.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { guardShape, request, requestVoid } from "./request";

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

describe("requestVoid", () => {
  it("resolves without reading a body on a 204", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      requestVoid("/v1/doctor/profile/photo", { method: "DELETE" }),
    ).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still maps a non-ok response to the error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "PERMISSION_DENIED",
            message: "nope",
            trace_id: "t",
            details: {},
          },
          403,
        ),
      ),
    );

    await expect(
      requestVoid("/v1/doctor/profile/photo", { method: "DELETE" }),
    ).rejects.toMatchObject({ code: "PERMISSION_DENIED" });
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
