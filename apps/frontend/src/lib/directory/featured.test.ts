// PHASE-6 T05b (#318): featured-doctor integration wiring - the homepage
// proof-of-supply endpoint now resolves through the real public directory
// search API (gap G2), keeping the FeaturedDoctor shape minus the dropped
// `consultType`. Every returned row is verified by construction (ADR-0011),
// so the mapping carries `area` through without filtering on `entry.verified`
// - no invented strings.

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchFeaturedDoctors } from "./featured";

function directoryRow(overrides: Record<string, unknown> = {}) {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    area: null,
    distance_km: 1.2,
    verified: true,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchFeaturedDoctors (T05b - real search API wiring)", () => {
  it("queries the public search for doctors and maps verified rows to the FeaturedDoctor shape", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        fell_back: false,
        items: [
          directoryRow({ partner_id: 1, area: "Medininagar Rd" }),
          directoryRow({
            partner_id: 2,
            partner_type: "lab",
            specialty: null,
            area: null,
          }),
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchFeaturedDoctors()).resolves.toEqual([
      {
        id: 1,
        name: "Dr. A. Kumar",
        specialty: "General Physician",
        area: "Medininagar Rd",
      },
      {
        id: 2,
        name: "Dr. A. Kumar",
        specialty: null,
        area: null,
      },
    ]);

    // The featured fetch is a doctor-type search on the public
    // unauthenticated directory endpoint - no consultType anywhere.
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://localhost:8000/v1/directory/search?partner_type=doctor",
    );
  });

  it("falls back to a generic name when practice_name is null", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fell_back: false,
          items: [directoryRow({ practice_name: null })],
        }),
      ),
    );

    await expect(fetchFeaturedDoctors()).resolves.toEqual([
      {
        id: 1,
        name: "CareSetu provider",
        specialty: "General Physician",
        area: null,
      },
    ]);
  });

  it("carries area through when the search row has one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fell_back: false,
          items: [directoryRow({ area: "Medininagar Rd" })],
        }),
      ),
    );

    await expect(fetchFeaturedDoctors()).resolves.toEqual([
      {
        id: 1,
        name: "Dr. A. Kumar",
        specialty: "General Physician",
        area: "Medininagar Rd",
      },
    ]);
  });

  it("does not filter on entry.verified - the API guarantees verified rows only", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fell_back: false,
          items: [
            directoryRow({ partner_id: 1 }),
            directoryRow({ partner_id: 2, verified: false }),
          ],
        }),
      ),
    );

    // The dead `.filter((entry) => entry.verified)` is gone: the mapping
    // trusts ADR-0011 that every returned row is verified and passes all of
    // them straight through.
    const result = await fetchFeaturedDoctors();
    expect(result).toHaveLength(2);
    expect(result[1]).toMatchObject({ id: 2 });
  });

  it("propagates search failures (the featured section degrades to its empty state)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchFeaturedDoctors()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });
});
