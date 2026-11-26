// PHASE-8.1 T2 (#488): patient profile HTTP client. Thin typed wrapper over
// the protected /v1/me/profile read + upsert surface (backend #482): GET
// answers the typed "not set" shape the PWA hydrates from before its local
// draft fallback, PUT persists the profile-completion result and answers the
// same shape so one contract covers both. Uses the shared request helper
// (lib/request.ts) so network failures and the error envelope are handled
// once, and PUT carries an Idempotency-Key header (api-standards §5); the
// write itself is a server-side upsert, so a retried Finish replays the same
// request id against an already-idempotent operation.
//
// #548: the photo surface is its own endpoint trio on the same profile row
// (backend #533) - PUT and DELETE /v1/me/photo both answer the read envelope
// with the updated profile (so the caller's photo ref is never guesswork), and
// GET /v1/me/photo streams the stored bytes because the ref is private profile
// media and never a public URL (ADR-0020).

import { ApiError } from "@/lib/api-errors";
import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { guardShape, request, requestBlob } from "@/lib/request";

/** The stored profile row shape (modules/iam/identity_facade.py PatientProfile). */
export interface StoredPatientProfile {
  name: string;
  age: number;
  gender: string;
  preferred_language: string;
  /** Optional and unsettable - null when the patient left it empty. */
  area: string | null;
  emergency_contact: string | null;
  photo_ref: string | null;
}

/**
 * The typed round-trip answer of GET and PUT /v1/me/profile. `set` separates a
 * stored profile (profile populated) from the typed "not set" answer (profile
 * null) the client-side hydration treats as "absent profile".
 */
export interface ProfileReadResult {
  set: boolean;
  profile: StoredPatientProfile | null;
}

export function isStoredPatientProfile(
  value: unknown,
): value is StoredPatientProfile {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.name === "string" &&
    typeof v.age === "number" &&
    typeof v.gender === "string" &&
    typeof v.preferred_language === "string" &&
    (v.area === null || typeof v.area === "string") &&
    (v.emergency_contact === null || typeof v.emergency_contact === "string") &&
    (v.photo_ref === null || typeof v.photo_ref === "string")
  );
}

function isProfileReadResult(value: unknown): value is ProfileReadResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.set === "boolean" &&
    (v.profile === null || isStoredPatientProfile(v.profile))
  );
}

/** Read the caller's saved profile, or the typed "not set" answer. */
export async function getProfile(): Promise<ProfileReadResult> {
  const data = await request<unknown>("/v1/me/profile");
  return guardShape(
    data,
    isProfileReadResult,
    "The API returned an unexpected profile read shape",
  );
}

/**
 * The backend always answers a profile write with `set=true` and the saved
 * row; a non-set answer is a broken response, not a user error. Shared by
 * every mutation that answers the read envelope (profile upsert, photo
 * upload, photo remove) so the shape guard and the non-set refusal are stated
 * once.
 */
function unwrapProfileWrite(
  data: unknown,
  message: string,
): StoredPatientProfile {
  const result = guardShape(data, isProfileReadResult, message);
  if (!result.set || result.profile === null) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API refused the saved profile",
      trace_id: "",
      details: {},
    });
  }
  return result.profile;
}

/**
 * Upsert the caller's profile-completion data. The backend always answers
 * `set=true` with the saved row; a non-set answer is a broken response, not a
 * user error.
 */
export async function saveProfile(
  payload: StoredPatientProfile,
  retryKey?: string,
): Promise<StoredPatientProfile> {
  const data = await request<unknown>("/v1/me/profile", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
    },
    body: JSON.stringify(payload),
  });
  return unwrapProfileWrite(
    data,
    "The API returned an unexpected profile write shape",
  );
}

/**
 * Upload or replace the caller's profile photo and resolve the updated
 * profile. The multipart body is sent without an explicit Content-Type so the
 * browser sets the boundary itself - the backend stores an opaque
 * `patient/` profile-media key, never a public URL (ADR-0020). Media type and
 * size are the backend's contract to enforce (JPEG/PNG/WebP, 5MB); the client
 * only surfaces the rejection.
 */
export async function uploadPatientPhoto(
  file: File,
  retryKey?: string,
): Promise<StoredPatientProfile> {
  const body = new FormData();
  body.append("file", file);
  const data = await request<unknown>("/v1/me/photo", {
    method: "PUT",
    headers: { [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey) },
    body,
  });
  return unwrapProfileWrite(
    data,
    "The API returned an unexpected photo upload shape",
  );
}

/**
 * Stream the caller's own stored photo bytes for the preview. The ref is
 * private profile media, so the image is read through the authed transport
 * rather than linked as a public URL; a missing photo answers 404 and the
 * caller degrades to the photo-picker state.
 */
export async function fetchPatientPhoto(): Promise<Blob> {
  return requestBlob("/v1/me/photo");
}

/**
 * Clear the caller's stored photo and resolve the updated profile. Removal is
 * idempotent on the backend: a caller with no photo answers the unchanged
 * profile, so this is safe to re-issue after a failed attempt.
 */
export async function deletePatientPhoto(
  retryKey?: string,
): Promise<StoredPatientProfile> {
  const data = await request<unknown>("/v1/me/photo", {
    method: "DELETE",
    headers: { [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey) },
  });
  return unwrapProfileWrite(
    data,
    "The API returned an unexpected photo removal shape",
  );
}
