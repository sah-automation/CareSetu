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
 * modules/partner/domain/credentials.py). Doctors only - labs and chemists
 * carry no specialty and match nothing when one is set (facade). */
export const DIRECTORIES_SPECIALTIES = [
  "General Physician",
  "Pediatrician",
  "Gynecologist",
  "Dentist",
] as const;

export type Specialty = (typeof DIRECTORIES_SPECIALTIES)[number];

/** One public directory search result - the verified-safe projection of an
 * [Active] partner with valid credentials. `practice_name` is the display
 * name; `area` carries the partner's locality when present (card renders it
 * among non-null meta, never inventing a string when absent). */
export interface DirectoryEntry {
  partner_id: number;
  practice_name: string | null;
  partner_type: ProviderType;
  specialty: string | null;
  area: string | null;
  distance_km: number;
  verified: boolean;
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
    (typeof record.practice_name === "string" ||
      record.practice_name === null) &&
    (record.partner_type === "doctor" ||
      record.partner_type === "lab" ||
      record.partner_type === "chemist") &&
    (typeof record.specialty === "string" || record.specialty === null) &&
    (typeof record.area === "string" || record.area === null) &&
    typeof record.distance_km === "number" &&
    typeof record.verified === "boolean"
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
