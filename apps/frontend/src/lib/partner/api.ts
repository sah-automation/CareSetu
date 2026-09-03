// MOD-00X partner HTTP surface client (PHASE-5 T1, #278). Thin fetch wrapper
// over the backend's /v1/partner endpoints; the request/response shapes mirror
// modules/partner/facade.py and modules/partner/adapters/routes.py exactly.
// Session cookie auth follows the same pattern as record/api.ts and
// consent/api.ts (ADR-0005).

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import { ApiError, parseErrorEnvelope } from "@/lib/api-errors";

export type PartnerType = "doctor" | "lab" | "chemist";

export type CredentialType =
  | "medical_registration"
  | "qualification_certificate"
  | "lab_license"
  | "accreditation"
  | "drug_license"
  | "pharmacist_registration";

export type PartnerStatus =
  | "Registered"
  | "Under Verification"
  | "Active"
  | "Rejected";

export interface RegisterPartnerResult {
  partner_id: number;
  identity_id: number;
  partner_type: PartnerType;
  status: PartnerStatus;
  round: number;
  created: boolean;
}

export interface CredentialSubmissionResult {
  partner_id: number;
  status: PartnerStatus;
  round: number;
  reason?: string | null;
}

export interface PartnerMeView {
  partner_id: number;
  status: PartnerStatus;
  partner_type: PartnerType;
  round: number;
  created_at?: string | null;
}

export interface PartnerVerificationStatusView {
  partner_id: number;
  round: number;
  status?: string | null;
  decision?: string | null;
  decision_reason?: string | null;
  decided_at?: string | null;
}

export interface RejectionReasonView {
  partner_id: number;
  rejection_reason: string;
  round: number;
}

export interface PartnerView {
  partner_id: number;
  status: PartnerStatus;
  round: number;
}

export interface RegisterPartnerRequest {
  phone: string;
  partner_type: PartnerType;
  practice_name?: string | null;
  practice_address: string;
  practice_latitude: number;
  practice_longitude: number;
  service_area_id?: number | null;
}

export interface CredentialDocumentRequest {
  credential_type: CredentialType;
  artifacts: string[];
}

export interface CredentialSubmissionRequest {
  credentials: CredentialDocumentRequest[];
}

function isRegisterPartnerResult(
  value: unknown,
): value is RegisterPartnerResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "identity_id" in value &&
    "partner_type" in value &&
    "status" in value &&
    "created" in value
  );
}

function isCredentialSubmissionResult(
  value: unknown,
): value is CredentialSubmissionResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "status" in value &&
    "round" in value
  );
}

function isPartnerMeView(value: unknown): value is PartnerMeView {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "status" in value &&
    "partner_type" in value &&
    "round" in value
  );
}

function isPartnerVerificationStatusView(
  value: unknown,
): value is PartnerVerificationStatusView {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "round" in value
  );
}

function isRejectionReasonView(value: unknown): value is RejectionReasonView {
  return (
    typeof value === "object" &&
    value !== null &&
    "partner_id" in value &&
    "rejection_reason" in value &&
    "round" in value
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

async function partnerFetch<T>(
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

export async function registerPartner(
  request: RegisterPartnerRequest,
): Promise<RegisterPartnerResult> {
  const data = await partnerFetch<unknown>("/v1/partner/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!isRegisterPartnerResult(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected registration result shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function submitCredentials(
  request: CredentialSubmissionRequest,
): Promise<CredentialSubmissionResult> {
  const data = await partnerFetch<unknown>("/v1/partner/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!isCredentialSubmissionResult(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected credential submission shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function fetchPartnerMe(): Promise<PartnerMeView> {
  const data = await partnerFetch<unknown>("/v1/partner/me");
  if (!isPartnerMeView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected partner status shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function fetchPartnerVerification(): Promise<PartnerVerificationStatusView> {
  const data = await partnerFetch<unknown>("/v1/partner/me/verification");
  if (!isPartnerVerificationStatusView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected verification status shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function fetchRejectionReason(): Promise<RejectionReasonView> {
  const data = await partnerFetch<unknown>("/v1/partner/rejection-reason");
  if (!isRejectionReasonView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected rejection reason shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}

export async function appealRejection(): Promise<PartnerView> {
  const data = await partnerFetch<unknown>("/v1/partner/appeal", {
    method: "POST",
  });
  if (!isPartnerView(data)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message: "The API returned an unexpected appeal result shape",
      trace_id: "",
      details: {},
    });
  }
  return data;
}
