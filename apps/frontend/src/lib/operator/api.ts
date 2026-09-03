// Operator HTTP surface client (PHASE-5 T1, #278). Thin fetch wrapper over
// the backend's operator-scoped endpoints: MFA-gated operator login
// (/v1/auth/operator/*) and the partner verification queue/decision surface
// (/v1/partner/verification-queue etc.). Response shapes mirror
// modules/iam/session_facade.py (SessionResult), modules/iam/mfa_facade.py
// (EnrollMfaResult), and modules/partner/facade.py (PartnerQueue /
// PartnerVerificationDetail / PartnerView).

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import { ApiError, parseErrorEnvelope } from "@/lib/api-errors";
import type { SessionResult } from "@/lib/auth/api";
import type { PartnerView } from "@/lib/partner/api";

export type { SessionResult } from "@/lib/auth/api";
export type { PartnerType, PartnerView } from "@/lib/partner/api";

export interface OperatorLoginRequest {
  phone: string;
  code: string;
}

export interface EnrollMfaResult {
  identity_id: number;
  phone_e164: string;
  secret: string;
  provisioning_uri: string;
}

export interface PartnerQueueItem {
  partner_id: number;
  identity_id: number;
  partner_type: string;
  status: string;
  practice_name?: string | null;
  practice_address: string;
  created_at: string;
  round: number;
  audit_link?: string | null;
}

export interface PartnerQueue {
  items: PartnerQueueItem[];
}

export interface CredentialDetail {
  credential_id: number;
  credential_type: string;
  verified: boolean;
  expires_at?: string | null;
  artifact_refs: Record<string, string>;
}

export interface VerificationRound {
  round: number;
  status: string;
  decision?: string | null;
  decision_reason?: string | null;
  decision_by?: number | null;
  decided_at?: string | null;
  created_at: string;
}

export interface AuditEventDetail {
  id: string;
  event_type: string;
  actor_id?: string | null;
  target_id?: string | null;
  scope?: string | null;
  metadata: Record<string, unknown>;
  timestamp: string;
  prev_hash: string;
  hash: string;
}

export interface PartnerVerificationDetail {
  partner_id: number;
  identity_id: number;
  partner_type: string;
  status: string;
  practice_name?: string | null;
  practice_address: string;
  service_area_id?: number | null;
  created_at: string;
  credentials: CredentialDetail[];
  verification_history: VerificationRound[];
  audit_events: AuditEventDetail[];
  audit_link?: string | null;
}

export interface OperatorDecisionRequest {
  approve: boolean;
  reason?: string | null;
}

function isSessionResult(value: unknown): value is SessionResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "jwt" in value &&
    "jti" in value &&
    "scope" in value &&
    "identity_id" in value &&
    "expires_in_seconds" in value &&
    "refresh_token" in value
  );
}

function isEnrollMfaResult(value: unknown): value is EnrollMfaResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "identity_id" in value &&
    "phone_e164" in value &&
    "secret" in value &&
    "provisioning_uri" in value
  );
}

function isPartnerQueueItem(value: unknown): value is PartnerQueueItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "status" in value &&
    "round" in value
  );
}

function isPartnerQueue(value: unknown): value is PartnerQueue {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    Array.isArray((value as PartnerQueue).items) &&
    (value as PartnerQueue).items.every(isPartnerQueueItem)
  );
}

function isPartnerVerificationDetail(
  value: unknown,
): value is PartnerVerificationDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "credentials" in value &&
    Array.isArray((value as PartnerVerificationDetail).credentials) &&
    "verification_history" in value &&
    Array.isArray((value as PartnerVerificationDetail).verification_history)
  );
}

function isPartnerView(value: unknown): value is PartnerView {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "status" in value &&
    "round" in value
  );
}

async function operatorFetch<T>(
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

export async function operatorLogin(
  request: OperatorLoginRequest,
): Promise<SessionResult> {
  const data = await operatorFetch<unknown>("/v1/auth/operator/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!isSessionResult(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected login session shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function enrollOperatorMfa(): Promise<EnrollMfaResult> {
  const data = await operatorFetch<unknown>("/v1/auth/operator/mfa/enroll", {
    method: "POST",
  });
  if (!isEnrollMfaResult(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected MFA enrollment shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export interface VerificationQueueParams {
  partner_type?: string | null;
  status?: string | null;
  sort_by?: string | null;
}

export async function fetchVerificationQueue(
  params: VerificationQueueParams = {},
): Promise<PartnerQueue> {
  const search = new URLSearchParams();
  if (params.partner_type) search.set("partner_type", params.partner_type);
  if (params.status) search.set("status", params.status);
  if (params.sort_by) search.set("sort_by", params.sort_by);
  const query = search.toString();
  const data = await operatorFetch<unknown>(
    `/v1/partner/verification-queue${query ? `?${query}` : ""}`,
  );
  if (!isPartnerQueue(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected verification queue shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function fetchVerificationDetail(
  partnerId: number,
): Promise<PartnerVerificationDetail> {
  const data = await operatorFetch<unknown>(
    `/v1/partner/verification/${partnerId}`,
  );
  if (!isPartnerVerificationDetail(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected verification detail shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function submitOperatorDecision(
  partnerId: number,
  request: OperatorDecisionRequest,
): Promise<PartnerView> {
  const data = await operatorFetch<unknown>(
    `/v1/partner/verification/${partnerId}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!isPartnerView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected decision result shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}
