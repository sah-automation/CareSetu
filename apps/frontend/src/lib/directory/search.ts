// PHASE-6 T05a (#317): public directory-search HTTP client (MOD-002,
// FEAT-004, gap G2). Thin unauthenticated wrapper over the backend's
// GET /v1/directory/search route; the request/response shapes mirror
// modules/partner/facade.py (DirectoryEntry / DirectorySearchView) exactly.
// Only [Active] partners with valid credentials are ever returned, so every
// card's verified tick is truthful by construction (ADR-0011 "tick gone =
// card gone" - the DirectoryCard gate still drops any false-tick row
// defensively).

import { guardShape, request } from "@/lib/request";

import type { ProviderType } from "./links";

/** Specialties the backend accepts for doctor entries (closed pick-list,
 * modules/partner/domain/vocabularies.py `Specialty`). Doctors only - labs and
 * chemists carry no specialty and match nothing when one is set (facade).
 *
 * #623: this list was four long, which left the other sixteen of the backend's
 * twenty unreachable from every frontend surface that offers a specialty -
 * the homepage chips, the directory filter and the pick-a-doctor pre-filter.
 * The frontend cannot import a Python enum, so the twenty values are restated
 * here; `tests/unit/directory-specialty-parity.test.ts` fails if the two
 * lists ever drift apart again.
 */
export const DIRECTORIES_SPECIALTIES = [
  "General Physician",
  "Pediatrician",
  "Gynecologist",
  "Dentist",
  "General Surgeon",
  "Orthopedic Surgeon",
  "Ophthalmologist",
  "ENT Specialist",
  "Dermatologist",
  "Psychiatrist",
  "Cardiologist",
  "Neurologist",
  "Gastroenterologist",
  "Urologist",
  "Nephrologist",
  "Pulmonologist",
  "Endocrinologist",
  "Oncologist",
  "Ayurvedic Practitioner",
  "Homeopathy Practitioner",
] as const;

export type Specialty = (typeof DIRECTORIES_SPECIALTIES)[number];

/** One public directory search result - the verified-safe projection of an
 * [Active] partner with valid credentials. `practice_name` is the display
 * name; `area` carries the partner's locality when present (card renders it
 * among non-null meta, never inventing a string when absent).
 * `consultation_fee` is in integer paise (null until the doctor sets one).
 *
 * #965 (backend #964): widened with the card-redesign band from the doctor's
 * declared profile - `clinic_name`, `experience_years`, `languages`,
 * `address_line` and `city` - so the interface mirrors the backend
 * `DirectoryEntry` payload exactly and TypeScript catches any drift. */
export interface DirectoryEntry {
  partner_id: number;
  /** Opaque profile-media ref for the partner's photo, or null when none. */
  photo_ref?: string | null;
  practice_name: string | null;
  partner_type: ProviderType;
  specialty: string | null;
  area: string | null;
  distance_km: number;
  verified: boolean;
  consultation_fee: number | null;
  /** Clinic or hospital the practice sits in, or null when undeclared. */
  clinic_name: string | null;
  /** Declared years of practice, or null when undeclared. */
  experience_years: number | null;
  /** Languages the partner consults in; empty list when none declared. */
  languages: string[];
  /** Street line of the declared address, or null when undeclared. */
  address_line: string | null;
  /** City of the declared address, or null when undeclared. */
  city: string | null;
}

/** The public directory search response. `fell_back` marks the wider-area
 * fallback: no entry matched within the peri-urban scope, so the location
 * constraint was relaxed (all other filters kept) and results must be
 * labelled "outside your area" (glossary). */
export interface DirectorySearchView {
  items: DirectoryEntry[];
  fell_back: boolean;
}

export interface DirectorySearchQuery {
  q?: string | null;
  partnerType?: ProviderType | null;
  specialty?: string | null;
}

function isDirectoryEntry(value: unknown): value is DirectoryEntry {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.partner_id === "number" &&
    (record.photo_ref === undefined ||
      record.photo_ref === null ||
      typeof record.photo_ref === "string") &&
    (typeof record.practice_name === "string" ||
      record.practice_name === null) &&
    (record.partner_type === "doctor" ||
      record.partner_type === "lab" ||
      record.partner_type === "chemist") &&
    (typeof record.specialty === "string" || record.specialty === null) &&
    (typeof record.area === "string" || record.area === null) &&
    typeof record.distance_km === "number" &&
    typeof record.verified === "boolean" &&
    (typeof record.consultation_fee === "number" ||
      record.consultation_fee === null) &&
    (typeof record.clinic_name === "string" || record.clinic_name === null) &&
    (typeof record.experience_years === "number" ||
      record.experience_years === null) &&
    Array.isArray(record.languages) &&
    record.languages.every((language) => typeof language === "string") &&
    (typeof record.address_line === "string" || record.address_line === null) &&
    (typeof record.city === "string" || record.city === null)
  );
}

function isDirectorySearchView(value: unknown): value is DirectorySearchView {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    Array.isArray(record.items) &&
    record.items.every(isDirectoryEntry) &&
    typeof record.fell_back === "boolean"
  );
}

export async function searchDirectory(
  query: DirectorySearchQuery,
): Promise<DirectorySearchView> {
  const params = new URLSearchParams();
  const freeText = query.q?.trim();
  if (freeText) params.set("q", freeText);
  if (query.partnerType) params.set("partner_type", query.partnerType);
  if (query.specialty) params.set("specialty", query.specialty);
  const qs = params.toString();
  const data = await request<unknown>(
    `/v1/directory/search${qs ? `?${qs}` : ""}`,
  );
  return guardShape(
    data,
    isDirectorySearchView,
    "The API returned an unexpected directory search shape",
  );
}
