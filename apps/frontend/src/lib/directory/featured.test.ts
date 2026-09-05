// PHASE-6 T05b (#318): featured-doctor integration wiring - the homepage
// proof-of-supply endpoint now resolves through the real public directory
// search API (gap G2), keeping the FeaturedDoctor shape minus the dropped
// `consultType`. Only verified rows survive the mapping (FEAT-004 Rule 1 /
// ADR-0011), and `area` stays null because the search projection never
// carries it - no invented strings.

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchFeaturedDoctors } from "./featured";

function directoryRow(overrides: Record<string, unknown> = {}) {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
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
          directoryRow({ partner_id: 1 }),
          directoryRow({ partner_id: 2, partner_type: "lab", specialty: null }),
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchFeaturedDoctors()).resolves.toEqual([
      {
        id: 1,
        name: "Dr. A. Kumar",
        specialty: "General Physician",
        area: null,
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

  it("drops any false-tick row defensively (tick gone = card gone)", async () => {
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

    await expect(fetchFeaturedDoctors()).resolves.toEqual([
      {
        id: 1,
        name: "Dr. A. Kumar",
        specialty: "General Physician",
        area: null,
      },
    ]);
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
