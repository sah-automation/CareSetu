// PHASE-5 T1 (#278): audit access-history client contract. GET the caller's
// own access history; throw ApiError on network failure or bad shape.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { fetchAccessHistory } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchAccessHistory", () => {
  it("resolves a populated access history view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        entries: [
          {
            actor_id: 3,
            actor_type: "doctor",
            scope: "consultations",
            accessed_at: "2026-09-01T00:00:00Z",
            denied: false,
            denial_reason: null,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAccessHistory(7)).resolves.toEqual({
      entries: [
        {
          actor_id: 3,
          actor_type: "doctor",
          scope: "consultations",
          accessed_at: "2026-09-01T00:00:00Z",
          denied: false,
          denial_reason: null,
        },
      ],
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/v1/audit/access-history?patient_id=7",
    );
    expect(init.credentials).toBe("include");
  });

  it("resolves the empty-list shape for a zero-setup patient", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ entries: [] })),
    );
    await expect(fetchAccessHistory(7)).resolves.toEqual({ entries: [] });
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(fetchAccessHistory(7)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { code: "FORBIDDEN", message: "no", trace_id: "t", details: {} },
            403,
          ),
        ),
    );
    await expect(fetchAccessHistory(7)).rejects.toMatchObject({
      code: "FORBIDDEN",
    });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ entries: "nope" })),
    );
    await expect(fetchAccessHistory(7)).rejects.toBeInstanceOf(ApiError);
  });
});
