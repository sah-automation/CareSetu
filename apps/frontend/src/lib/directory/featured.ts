// PHASE-6 T05b (#318): homepage featured-doctor integration point, now wired
// to the real public directory-search API (MOD-002, FEAT-004, gap G2 - the
// PHASE-2.6 T09/#200 stub is replaced, the signature/shape is kept minus the
// dropped `consultType`). Only [Active] partners with valid credentials are
// ever returned (FEAT-004 Rule 1), so every card carries a truthful verified
// indicator by construction (ADR-0011 "tick gone = card gone").
//
// #961: the prototype card template needs distance and consult fee when the
// search payload carries them, so both ride the mapping through as raw fields
// (fee stays in integer paise until display).
//
// #962: `photo_ref` rides through too (the card streams it through the same
// profile-media hook the directory card uses), and the section shows only the
// nearest FEATURED_LIMIT doctors - the search API already answers
// nearest-first, so the slice is the closest supply and "View all doctors"
// is the path to the rest of the directory.
//
// #965: the full prototype card anatomy also needs the practice, experience
// and address fields the widened `DirectoryEntry` carries, so all of them
// ride through as well. Card-only decorations the payload has no field for
// (rating, reviews, video badge, ribbon, facts, tags) are not part of this
// shape - the card resolves those through lib/directory/mockDisplay.

import { searchDirectory } from "./search";

/**
 * Doctors shown in the homepage featured carousel. The search cap is 50; the
 * section keeps a compact nearest-first slice and links out for the rest.
 */
export const FEATURED_LIMIT = 8;

export interface FeaturedDoctor {
  id: number;
  name: string;
  specialty: string | null;
  area: string | null;
  /** Distance from the search scope in km (always present on the search view). */
  distance_km: number;
  /** Consultation fee in integer paise; null until the doctor sets one. */
  consultation_fee: number | null;
  /** Opaque profile-media ref for the doctor's photo, or null when none. */
  photo_ref: string | null;
  /** Clinic or hospital the practice sits in, or null when undeclared. */
  clinic_name: string | null;
  /** Declared years of practice, or null when undeclared. */
  experience_years: number | null;
  /** Languages the doctor consults in; empty list when none declared. */
  languages: string[];
  /** Street line of the declared address, or null when undeclared. */
  address_line: string | null;
  /** City of the declared address, or null when undeclared. */
  city: string | null;
}

export async function fetchFeaturedDoctors(): Promise<FeaturedDoctor[]> {
  const view = await searchDirectory({ partnerType: "doctor" });
  return view.items.slice(0, FEATURED_LIMIT).map((entry) => ({
    id: entry.partner_id,
    name: entry.practice_name ?? "CareSetu provider",
    specialty: entry.specialty,
    area: entry.area,
    distance_km: entry.distance_km,
    consultation_fee: entry.consultation_fee,
    photo_ref: entry.photo_ref ?? null,
    clinic_name: entry.clinic_name,
    experience_years: entry.experience_years,
    languages: entry.languages,
    address_line: entry.address_line,
    city: entry.city,
  }));
}
