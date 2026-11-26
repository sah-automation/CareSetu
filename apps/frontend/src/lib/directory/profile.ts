// PHASE-6 T06 (#312): public provider-profile HTTP client (MOD-002, FEAT-005).
// Thin unauthenticated wrapper over the backend's GET /v1/directory/providers
// /{id} route; the request/response shapes mirror modules/partner/facade.py
// (ProviderProfileView / ProviderCredential) exactly. The backend owns the
// verified-safe-field gate: it only resolves `[Active]` partners with a
// directory_index entry and valid (unexpired, unrevoked) credentials, so the
// returned payload can never carry raw credential documents, emails, phones
// or PHI - this client never requests or renders anything else.
//
// The `verified` indicator comes from the API's field (derived from the same
// predicate as search visibility, ADR-0011); the page must never invent its
// own verification. A non-visible / missing profile returns a 404 with the
// PROVIDER_PROFILE_NOT_FOUND error code - mapped here to `notFound` so the
// caller can render the clear not-found state.
//
// #619: the payload now also carries the DECLARED band - what the provider says
// about itself rather than what the platform checked. Widening the projection
// did not widen the gate, and did not widen what this client will render: the
// declared fields are the provider's own claims, so nothing in them may reach a
// verified marker, and a profile the gate rejects stays a 404 with none of them.

import { ApiError } from "@/lib/api-errors";
import { guardShape, request } from "@/lib/request";

import type { ProviderType } from "./links";

/** One credential on the public provider profile - the verified-safe
 * projection: closed `credential_type`, derived `status` label and the
 * recorded `expires_at`. No artifact refs, no document bytes. */
export interface ProviderCredential {
  credential_type: string;
  status: string;
  expires_at: string | null;
}

/** The public provider profile (verified-safe projection, FEAT-005, #613).
 *
 * It arrives in TWO bands, and the shape is the line between them: a patient tells
 * "we checked this" from "the provider wrote this" by WHICH FIELD they are reading,
 * not by an indicator's value.
 *
 * - **Verified** - `verified` and each `credential.status`. Derived on every read
 *   from the same predicate search visibility uses and never stored, so it cannot
 *   drift from the card's tick (ADR-0011).
 * - **Declared** - every field below the credentials. What the provider says about
 *   itself; nothing here was checked by anyone, which is why no field in this band
 *   is allowed to render a verified marker.
 *
 * Every declared field is as nullable as a half-finished profile really is: `null`
 * and `[]` are states a provider can hold, not gaps to paper over with an invented
 * string.
 */
export interface ProviderProfile {
  partner_id: number;
  practice_name: string | null;
  partner_type: ProviderType;
  specialty: string | null;
  area: string | null;
  verified: boolean;
  credentials: ProviderCredential[];
  // --- the declared band (#613) -------------------------------------------
  /** The building the practice is in, distinct from `practice_name`. */
  clinic_name: string | null;
  /** Every specialty the provider practises, not the one representative
   * `specialty` above. */
  specialties: string[];
  /** The languages a patient is understood in. */
  languages: string[];
  /** The days of the week they consult on. */
  consulting_days: string[];
  /** Their consulting hours, as the provider's own prose. */
  consulting_hours: string | null;
  /** The provider's own words about their practice, verbatim. */
  about: string | null;
  /** Years of practice, `0` included - a year of experience is still a fact. */
  experience_years: number | null;
  /** The structured address, as its five separately declared parts. */
  address_line: string | null;
  landmark: string | null;
  locality: string | null;
  city: string | null;
  pin_code: string | null;
}

/** A declared value, or the absence of one.
 *
 * A blank or whitespace-only string is the absence of a value, not a value, so it
 * renders as nothing rather than as a blank row. This is the one place that rule
 * lives, because the renderer that displays a declared field and the mapper that
 * builds one are two ends of the same question and a page that answered it two ways
 * would show a patient a row that says nothing.
 */
export function declaredText(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Outcome of fetching a profile: a reachable profile, or a not-found result
 * when the API 404s (partner not `[Active]`, no index entry, or an invalid
 * credential). The page renders the two distinctly. */
export type ProviderProfileResult =
  | { status: "found"; profile: ProviderProfile }
  | { status: "not-found" };

function isProviderCredential(value: unknown): value is ProviderCredential {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.credential_type === "string" &&
    typeof record.status === "string" &&
    (typeof record.expires_at === "string" || record.expires_at === null)
  );
}

/** A declared text field: a value, or the absence of one. Never a number or a
 * missing key, so a malformed field fails the guard instead of rendering. */
function isDeclaredText(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

/** One of the three closed selections. Every member must be a string; the server
 * has already narrowed the list to the vocabulary that owns it, so this checks the
 * wire's honesty rather than re-deciding what a valid member is.
 *
 * A blank member is allowed through. It is a content question, not a shape one, and
 * the renderer already has the answer for it - a member no label map holds renders
 * as nothing - so failing the whole profile over one empty string would trade a
 * dropped chip for a patient staring at an error page, which is the worse of the
 * two lies. */
function isDeclaredSelection(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((member) => typeof member === "string")
  );
}

/** The declared band's nullable-text fields. Listed so the guard walks the band as
 * a band: adding a declared field is one line here rather than a line here AND a
 * line in the predicate, which is how a guard and its interface drift apart. */
const DECLARED_TEXT_FIELDS = [
  "clinic_name",
  "consulting_hours",
  "about",
  "address_line",
  "landmark",
  "locality",
  "city",
  "pin_code",
] as const;

/** The declared band's three closed selections. The server has already narrowed
 * each to the vocabulary that owns it, so the guard checks the wire's honesty
 * rather than re-deciding what a valid member is. */
const DECLARED_SELECTION_FIELDS = [
  "specialties",
  "languages",
  "consulting_days",
] as const;

function isProviderProfile(value: unknown): value is ProviderProfile {
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
    typeof record.verified === "boolean" &&
    Array.isArray(record.credentials) &&
    record.credentials.every(isProviderCredential) &&
    // The declared band, guarded rather than cast: a server that quietly dropped
    // or mistyped one of these would otherwise render a profile silently short of
    // the one a patient was promised.
    DECLARED_TEXT_FIELDS.every((field) => isDeclaredText(record[field])) &&
    DECLARED_SELECTION_FIELDS.every((field) =>
      isDeclaredSelection(record[field]),
    ) &&
    (typeof record.experience_years === "number" ||
      record.experience_years === null)
  );
}

export async function fetchProviderProfile(
  partnerId: number,
): Promise<ProviderProfileResult> {
  try {
    const data = await request<unknown>(`/v1/directory/providers/${partnerId}`);
    return {
      status: "found",
      profile: guardShape(
        data,
        isProviderProfile,
        "The API returned an unexpected provider profile shape",
      ),
    };
  } catch (error) {
    // A non-visible or missing profile is a 404 with its own error code - map
    // it to the dedicated result so the caller can render the not-found state
    // (privacy posture: a hidden partner reads exactly like a missing one).
    if (
      error instanceof ApiError &&
      error.code === "PROVIDER_PROFILE_NOT_FOUND"
    ) {
      return { status: "not-found" };
    }
    throw error;
  }
}
