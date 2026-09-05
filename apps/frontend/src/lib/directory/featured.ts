// PHASE-6 T05b (#318): homepage featured-doctor integration point, now wired
// to the real public directory-search API (MOD-002, FEAT-004, gap G2 - the
// PHASE-2.6 T09/#200 stub is replaced, the signature/shape is kept minus the
// dropped `consultType`). Only [Active] partners with valid credentials are
// ever returned (FEAT-004 Rule 1), so every card carries a truthful verified
// indicator by construction; the mapping still drops any false-tick row
// defensively (ADR-0011 "tick gone = card gone").

import { searchDirectory } from "./search";

export interface FeaturedDoctor {
  id: number;
  name: string;
  specialty: string | null;
  // `area` survives in the shape (homepage card meta) but the search
  // projection never carries it - it stays null and the card renders only
  // non-null meta. Never invent an area string (DirectoryCard rule).
  area: string | null;
}

export async function fetchFeaturedDoctors(): Promise<FeaturedDoctor[]> {
  const view = await searchDirectory({ partnerType: "doctor" });
  return view.items
    .filter((entry) => entry.verified)
    .map((entry) => ({
      id: entry.partner_id,
      name: entry.practice_name ?? "CareSetu provider",
      specialty: entry.specialty,
      area: null,
    }));
}
