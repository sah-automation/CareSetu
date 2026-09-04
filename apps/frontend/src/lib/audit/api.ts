// MOD-011 audit HTTP surface client for the patient PWA (PHASE-5 T1, #278).
// Thin fetch wrapper over the backend's GET /v1/audit/access-history endpoint;
// the response shape mirrors modules/health/facade.py's AccessHistoryView.
// Session cookie auth follows the same pattern as record/api.ts (ADR-0005).

import { guardShape, request } from "@/lib/request";

export interface AccessHistoryEntry {
  actor_id: number;
  actor_type?: string | null;
  scope?: string | null;
  accessed_at: string;
  denied: boolean;
  denial_reason?: string | null;
}

export interface AccessHistoryView {
  entries: AccessHistoryEntry[];
}

function isAccessHistoryEntry(value: unknown): value is AccessHistoryEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    "actor_id" in value &&
    "accessed_at" in value &&
    "denied" in value
  );
}

function isAccessHistoryView(value: unknown): value is AccessHistoryView {
  return (
    typeof value === "object" &&
    value !== null &&
    "entries" in value &&
    Array.isArray((value as AccessHistoryView).entries) &&
    (value as AccessHistoryView).entries.every(isAccessHistoryEntry)
  );
}

export async function fetchAccessHistory(
  patientId: number,
): Promise<AccessHistoryView> {
  const search = new URLSearchParams();
  search.set("patient_id", String(patientId));
  const data = await request<unknown>(`/v1/audit/access-history?${search}`);
  return guardShape(
    data,
    isAccessHistoryView,
    "The API returned an unexpected access history shape",
  );
}
