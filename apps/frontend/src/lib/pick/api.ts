// PHASE-8.1 T11 (#449): patient pick-a-doctor + consent HTTP client.
// Thin typed wrapper over POST /v1/intake/{intake_id}/pick-doctor (PHASE-8.1
// T05, #443): records the patient's chosen doctor and consent grant in one
// atomic transaction (consent-at-pick, MOD-004, US-5/US-6). Uses the
// standard request helper + the shared idempotency-key header (api-standards
// A5, lib/idempotency.ts) so a client retry cannot double-execute a pick.

import { guardShape, request } from "@/lib/request";
import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";

/** The backend's pick-doctor result (intake_models.py PickDoctorResult). */
export interface PickDoctorResult {
  intake_id: number;
  assigned_partner_id: number;
  consent_id: number;
  consent_lineage_ref: string;
  consent_version: number;
}

function isPickDoctorResult(value: unknown): value is PickDoctorResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "assigned_partner_id" in value &&
    "consent_id" in value &&
    "consent_lineage_ref" in value &&
    "consent_version" in value
  );
}

/**
 * Record the patient's doctor choice and consent grant atomically.
 * The backend's exactly-one-doctor rule means a second pick for the same
 * intake is refused (409 CONFLICT). A client retry must pass the same
 * `retryKey` so the backend returns the original result (idempotent).
 */
export async function pickDoctor(
  intakeId: number,
  partnerId: number,
  retryKey?: string,
): Promise<PickDoctorResult> {
  const key = idempotencyKey(retryKey);
  const data = await request<unknown>(`/v1/intake/${intakeId}/pick-doctor`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: key,
    },
    body: JSON.stringify({ partner_id: partnerId }),
  });
  return guardShape(
    data,
    isPickDoctorResult,
    "The API returned an unexpected pick-doctor result shape",
  );
}
