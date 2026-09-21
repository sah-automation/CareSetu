// PHASE-2.7 T2 (#503): patient-home "Recommended near you" integration point
// over the public directory-search client (lib/directory/search). One call per
// active Doctor / Lab / Chemist scope. Search visibility and the verified tick
// share one derivation - only [Active] partners with valid credentials within
// the Daltonganj service area are ever returned (FEAT-004 Rule 1), so
// `verified` is true on returned rows by construction. The rail still filters
// defensively before showing ("tick gone = card gone", ADR-0011) and sorts
// client-side by `distance_km` ascending, because the search view returns
// distance per entry but makes no ordering guarantee. `fell_back` (wider-area
// fallback) is not consumed here: the rail stays scoped to the home area by
// design (REQ-008 single-service-area), so empty means genuinely no verified
// supply nearby.

import { searchDirectory, type DirectoryEntry } from "./search";
import type { ProviderType } from "./links";

/** Fetch the verified, distance-sorted recommendations for one scope. An empty
 * array means no verified supply exists for that provider type in the area. */
export async function fetchRecommended(
  partnerType: ProviderType,
): Promise<DirectoryEntry[]> {
  const view = await searchDirectory({ partnerType });
  return view.items
    .filter((entry) => entry.verified)
    .sort((a, b) => a.distance_km - b.distance_km);
}
