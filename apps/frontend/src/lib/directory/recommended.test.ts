// PHASE-2.7 T2 (#503): the recommended-near-you integration point. One call
// per scope encoded as the partner-type filter; only verified rows survive the
// defensive gate ("tick gone = card gone", ADR-0011 - the API never returns an
// unverified row, but the rail drops one if it ever arrives); an ascending
// client-side distance sort because the search view makes no ordering
// guarantee.

import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "./search";
import { searchDirectory } from "./search";
import { fetchRecommended } from "./recommended";

vi.mock("./search", () => ({
  searchDirectory: vi.fn(),
}));

const mockSearch = vi.mocked(searchDirectory);

function entry(overrides: Partial<DirectoryEntry> = {}): DirectoryEntry {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: 1.2,
    verified: true,
    consultation_fee: 50000,
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("fetchRecommended (#503)", () => {
  it("queries the active scope and returns only verified rows", async () => {
    mockSearch.mockResolvedValue({
      fell_back: false,
      items: [
        entry({ partner_id: 1 }),
        entry({ partner_id: 2, verified: false }),
        entry({ partner_id: 3 }),
      ],
    });

    await expect(fetchRecommended("doctor")).resolves.toEqual([
      expect.objectContaining({ partner_id: 1 }),
      expect.objectContaining({ partner_id: 3 }),
    ]);
    expect(mockSearch).toHaveBeenCalledWith({ partnerType: "doctor" });
  });

  it("sorts ascending by distance_km after fetch", async () => {
    mockSearch.mockResolvedValue({
      fell_back: false,
      items: [
        entry({ partner_id: 1, distance_km: 3.6 }),
        entry({ partner_id: 2, distance_km: 0.8 }),
        entry({ partner_id: 3, distance_km: 1.2 }),
      ],
    });

    await expect(fetchRecommended("lab")).resolves.toEqual([
      expect.objectContaining({ partner_id: 2 }),
      expect.objectContaining({ partner_id: 3 }),
      expect.objectContaining({ partner_id: 1 }),
    ]);
    expect(mockSearch).toHaveBeenCalledWith({ partnerType: "lab" });
  });

  it("passes every scope through to the partner-type filter", async () => {
    mockSearch.mockResolvedValue({ fell_back: false, items: [] });
    for (const scope of ["doctor", "lab", "chemist"] as const) {
      await fetchRecommended(scope);
    }
    expect(mockSearch.mock.calls).toEqual([
      [{ partnerType: "doctor" }],
      [{ partnerType: "lab" }],
      [{ partnerType: "chemist" }],
    ]);
  });

  it("resolves empty when the scope has no verified supply", async () => {
    mockSearch.mockResolvedValue({ fell_back: false, items: [] });

    await expect(fetchRecommended("chemist")).resolves.toEqual([]);
  });
});
