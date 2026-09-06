// PHASE-6 T05a (#317): directory search client contract. Each function must
// throw ApiError (NETWORK_ERROR on fetch failure, UNEXPECTED_ERROR on bad
// shape) and encode filters as query params on the expected public
// unauthenticated path (GET /v1/directory/search, gap G2).

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { searchDirectory } from "./search";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("searchDirectory", () => {
  it("GETs the search path with the given filters and resolves the view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        fell_back: false,
        items: [
          {
            partner_id: 1,
            practice_name: "Dr. A. Kumar",
            partner_type: "doctor",
            specialty: "General Physician",
            area: "Medininagar Rd",
            distance_km: 1.2,
            verified: true,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      searchDirectory({
        q: "Kumar",
        partnerType: "doctor",
        specialty: "General Physician",
      }),
    ).resolves.toEqual({
      fell_back: false,
      items: [
        {
          partner_id: 1,
          practice_name: "Dr. A. Kumar",
          partner_type: "doctor",
          specialty: "General Physician",
          area: "Medininagar Rd",
          distance_km: 1.2,
          verified: true,
        },
      ],
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/v1/directory/search?q=Kumar&partner_type=doctor&specialty=General+Physician",
    );
    // Public read - no method override, credentials ride through authedFetch.
    expect(init.method).toBeUndefined();
  });

  it("omits empty filters and trims the free-text query", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ fell_back: false, items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await searchDirectory({ q: "   ", partnerType: null, specialty: null });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/v1/directory/search");
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(searchDirectory({})).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INVALID_ARGS",
            message: "bad specialty",
            trace_id: "t",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(
      searchDirectory({ specialty: "Not a specialty" }),
    ).rejects.toMatchObject({ code: "INVALID_ARGS" });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [{ partner_id: 1 }] })),
    );

    await expect(searchDirectory({})).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects an entry that is not a valid provider type", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fell_back: false,
          items: [
            {
              partner_id: 1,
              practice_name: "Bad",
              partner_type: "nurse",
              specialty: null,
              area: null,
              distance_km: 1,
              verified: true,
            },
          ],
        }),
      ),
    );

    await expect(searchDirectory({})).rejects.toBeInstanceOf(ApiError);
  });
});
