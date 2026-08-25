// PHASE-3 T8/T9 (#217/#218): consent-surface HTTP client for the patient PWA.
// Thin fetch wrapper over the backend's GET /v1/consents, POST
// /v1/consents/{id}/revoke, and GET /v1/consents/egress-log endpoints;
// response shapes mirror modules/consent/facade.py's Pydantic models exactly.
// Session cookie auth follows the same pattern as record/api.ts (ADR-0005).

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import { ApiError, parseErrorEnvelope } from "@/lib/api-errors";

export interface ConsentEventView {
  kind: string;
  version: number;
  actor_patient_id: number;
  occurred_at: string;
}

export interface ConsentView {
  consent_id: number;
  lineage_ref: string;
  patient_id: number;
  counterparty_type: string;
  counterparty_id: string;
  record_scope: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
  events: ConsentEventView[];
}

export interface ConsentLog {
  items: ConsentView[];
}

export interface EgressLogEntry {
  egress_id: number;
  patient_id: number;
  consent_id: number | null;
  lineage_ref: string;
  version: number;
  counterparty_type: string;
  counterparty_id: string;
  record_scope: string;
  disclosed_entry_ids: number[];
  disclosed_at: string;
}

export interface EgressLog {
  items: EgressLogEntry[];
}

function isConsentEventView(value: unknown): value is ConsentEventView {
  return (
    typeof value === "object" &&
    value !== null &&
    "kind" in value &&
    "version" in value &&
    "actor_patient_id" in value &&
    "occurred_at" in value
  );
}

function isConsentView(value: unknown): value is ConsentView {
  return (
    typeof value === "object" &&
    value !== null &&
    "consent_id" in value &&
    "status" in value &&
    "events" in value &&
    Array.isArray((value as ConsentView).events) &&
    (value as ConsentView).events.every(isConsentEventView)
  );
}

function isConsentLog(value: unknown): value is ConsentLog {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    Array.isArray((value as ConsentLog).items) &&
    (value as ConsentLog).items.every(isConsentView)
  );
}

function isEgressLogEntry(value: unknown): value is EgressLogEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    "egress_id" in value &&
    "disclosed_entry_ids" in value &&
    Array.isArray((value as EgressLogEntry).disclosed_entry_ids)
  );
}

function isEgressLog(value: unknown): value is EgressLog {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    Array.isArray((value as EgressLog).items)
  );
}

async function consentFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await authedFetch(`${API_BASE_URL}${path}`, options);
  } catch {
    throw new ApiError({
      code: "NETWORK_ERROR",
      message: "Could not reach the CareSetu API",
      trace_id: "",
      details: {},
    });
  }

  if (!response.ok) {
    throw new ApiError(await parseErrorEnvelope(response));
  }

  return (await response.json()) as T;
}

export async function fetchConsentLog(): Promise<ConsentLog> {
  const data = await consentFetch<unknown>("/v1/consents");
  if (!isConsentLog(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected consent log shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function revokeConsent(consentId: number): Promise<ConsentView> {
  const data = await consentFetch<unknown>(`/v1/consents/${consentId}/revoke`, {
    method: "POST",
  });
  if (!isConsentView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected consent view shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export interface GrantConsentRequest {
  counterparty_type: "doctor" | "lab" | "chemist";
  counterparty_id: string;
  record_scope:
    | "consultations"
    | "prescriptions"
    | "lab_results"
    | "metrics"
    | "full_record";
}

export async function grantConsent(
  request: GrantConsentRequest,
): Promise<ConsentView> {
  const data = await consentFetch<unknown>("/v1/consents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!isConsentView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected consent view shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function fetchEgressLog(): Promise<EgressLog> {
  const data = await consentFetch<unknown>("/v1/consents/egress-log");
  if (!isEgressLog(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected egress log shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}
