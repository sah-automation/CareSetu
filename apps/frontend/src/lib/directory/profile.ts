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

/** The public provider profile (verified-safe projection, FEAT-005). */
export interface ProviderProfile {
  partner_id: number;
  practice_name: string | null;
  partner_type: ProviderType;
  specialty: string | null;
  area: string | null;
  verified: boolean;
  credentials: ProviderCredential[];
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
    record.credentials.every(isProviderCredential)
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
