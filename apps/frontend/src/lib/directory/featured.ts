// PHASE-6 T05b (#318): homepage featured-doctor integration point, now wired
// to the real public directory-search API (MOD-002, FEAT-004, gap G2 - the
// PHASE-2.6 T09/#200 stub is replaced, the signature/shape is kept minus the
// dropped `consultType`). Only [Active] partners with valid credentials are
// ever returned (FEAT-004 Rule 1), so every card carries a truthful verified
// indicator by construction (ADR-0011 "tick gone = card gone").
//
// #961: the prototype card template needs distance and consult fee when the
// search payload carries them, so both ride the mapping through as raw fields
// (fee stays in integer paise until display). Fields the payload does not
// have (rating, reviews, photo) are simply absent from this shape - the card
// omits them rather than inventing values.

import { searchDirectory } from "./search";

export interface FeaturedDoctor {
  id: number;
  name: string;
  specialty: string | null;
  area: string | null;
  /** Distance from the search scope in km (always present on the search view). */
  distance_km: number;
  /** Consultation fee in integer paise; null until the doctor sets one. */
  consultation_fee: number | null;
}

export async function fetchFeaturedDoctors(): Promise<FeaturedDoctor[]> {
  const view = await searchDirectory({ partnerType: "doctor" });
  return view.items.map((entry) => ({
    id: entry.partner_id,
    name: entry.practice_name ?? "CareSetu provider",
    specialty: entry.specialty,
    area: entry.area,
    distance_km: entry.distance_km,
    consultation_fee: entry.consultation_fee,
  }));
}
