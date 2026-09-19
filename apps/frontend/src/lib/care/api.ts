// MOD-006 care-plan HTTP surface client (PHASE-8.1 T10, #446). Thin typed
// wrapper over the backend's /v1/care doctor routes; the request/response
// shapes mirror modules/care/care_models.py exactly, following the same
// per-module client pattern as partner/api.ts and consent/api.ts (request.ts
// + shape guards, session/auth travel via api-base.ts, ADR-0005). Every care
// mutation sets the Idempotency-Key header through the shared helper
// (lib/idempotency.ts) so a client retry cannot double-execute a mutation.

import { guardShape, request } from "@/lib/request";
import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";

// Canonical vocabulary mirrored from modules/care/schema/models.py (snake_case).
export type CareCaseStage = "pre_summary" | "prescription_pending" | "closed";
export type RxSource = "ai_draft" | "manual";
export type RxStatus =
  | "draft"
  | "doctor_reviewed"
  | "rejected"
  | "issued"
  | "fulfilled";
export type DoctorInputType = "voice" | "photo";
export type SensitiveClass = "normal" | "sensitive" | "restricted";
export type CloseReason =
  | "patient_withdrawn"
  | "doctor_rejected"
  | "no_show"
  | "duplicate"
  | "system";

export interface CaseDetailView {
  case_id: number;
  patient_id: number;
  doctor_id: number | null;
  pre_summary_id: number | null;
  stage: CareCaseStage;
  forced_review: boolean;
  closed_at: string | null;
  close_reason: CloseReason | null;
  created_at: string;
  updated_at: string;
}

export interface RxItemInput {
  name: string;
  dose?: string | null;
  duration?: string | null;
  frequency?: string | null;
}

export interface RxItemView {
  rx_item_id: number;
  prescription_id: number;
  sequence: number;
  name: string;
  dose: string | null;
  duration: string | null;
  frequency: string | null;
}

export interface PrescriptionDetailView {
  prescription_id: number;
  case_id: number;
  status: RxStatus;
  source: RxSource;
  attempt_no: number;
  draft_snapshot: Record<string, unknown>;
  issued_at: string | null;
  attributed_doctor: number | null;
  attributed_doctor_name: string | null;
  items: RxItemView[];
  created_at: string;
  updated_at: string;
}

export interface DoctorInputResult {
  input_id: number;
  case_id: number;
  input_type: DoctorInputType;
  media_ref: string;
  sensitive_class: SensitiveClass | null;
}

export interface DoctorInputRequest {
  input_type: DoctorInputType;
  media_ref: string;
  sensitive_class?: SensitiveClass | null;
}

export interface RxDraftRequest {
  source: RxSource;
  items?: RxItemInput[] | null;
}

export interface RxRevisionRequest {
  rx_items: RxItemInput[];
}

export interface RxRejectRequest {
  reason: string;
}

export interface CaseCloseRequest {
  close_reason: CloseReason;
}

function isCaseDetailView(value: unknown): value is CaseDetailView {
  return (
    typeof value === "object" &&
    value !== null &&
    "case_id" in value &&
    "patient_id" in value &&
    "doctor_id" in value &&
    "pre_summary_id" in value &&
    "stage" in value &&
    "forced_review" in value &&
    "closed_at" in value &&
    "close_reason" in value &&
    "created_at" in value &&
    "updated_at" in value
  );
}

function isRxItemView(value: unknown): value is RxItemView {
  return (
    typeof value === "object" &&
    value !== null &&
    "rx_item_id" in value &&
    "prescription_id" in value &&
    "sequence" in value &&
    "name" in value &&
    "dose" in value &&
    "duration" in value &&
    "frequency" in value
  );
}

function isPrescriptionDetailView(
  value: unknown,
): value is PrescriptionDetailView {
  return (
    typeof value === "object" &&
    value !== null &&
    "prescription_id" in value &&
    "case_id" in value &&
    "status" in value &&
    "source" in value &&
    "attempt_no" in value &&
    "draft_snapshot" in value &&
    "issued_at" in value &&
    "attributed_doctor" in value &&
    "attributed_doctor_name" in value &&
    "items" in value &&
    Array.isArray((value as PrescriptionDetailView).items) &&
    (value as PrescriptionDetailView).items.every(isRxItemView)
  );
}

function isDoctorInputResult(value: unknown): value is DoctorInputResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "input_id" in value &&
    "case_id" in value &&
    "input_type" in value &&
    "media_ref" in value &&
    "sensitive_class" in value
  );
}

/** Mutation options: the shared Idempotency-Key header plus an optional JSON body. */
function mutationOptions(body?: unknown, retryKey?: string): RequestInit {
  const key = idempotencyKey(retryKey);
  const headers: Record<string, string> = {
    [IDEMPOTENCY_KEY_HEADER]: key,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  return {
    method: "POST",
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  };
}

/** List the doctor's open care cases, oldest first. */
export async function listOpenCases(): Promise<CaseDetailView[]> {
  const data = await request<unknown>("/v1/care/cases");
  return guardShape(
    data,
    (value): value is CaseDetailView[] =>
      Array.isArray(value) && value.every(isCaseDetailView),
    "The API returned an unexpected open case list shape",
  );
}

/** Read one care case belonging to the doctor. */
export async function fetchCareCase(caseId: number): Promise<CaseDetailView> {
  const data = await request<unknown>(`/v1/care/cases/${caseId}`);
  return guardShape(
    data,
    isCaseDetailView,
    "The API returned an unexpected care case shape",
  );
}

/** Record the consult-complete milestone and open the prescription stage. */
export async function markConsultComplete(
  caseId: number,
  key?: string,
): Promise<CaseDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/consult-complete`,
    mutationOptions(undefined, key),
  );
  return guardShape(
    data,
    isCaseDetailView,
    "The API returned an unexpected care case shape",
  );
}

/** Attach a doctor voice note or photo as prescribing input. */
export async function submitDoctorInput(
  caseId: number,
  req: DoctorInputRequest,
  key?: string,
): Promise<DoctorInputResult> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/doctor-input`,
    mutationOptions(req, key),
  );
  return guardShape(
    data,
    isDoctorInputResult,
    "The API returned an unexpected doctor input result shape",
  );
}

/** Create an AI or manual prescription draft. */
export async function createRxDraft(
  caseId: number,
  req: RxDraftRequest,
  key?: string,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/rx/draft`,
    mutationOptions(req, key),
  );
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}

/** Save the doctor's edited prescription revision. */
export async function saveRxRevision(
  caseId: number,
  rxId: number,
  req: RxRevisionRequest,
  key?: string,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/rx/${rxId}/revision`,
    mutationOptions(req, key),
  );
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}

/** Approve and issue a prescription with the required verification declaration. */
export async function approvePrescription(
  caseId: number,
  rxId: number,
  key?: string,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/rx/${rxId}/approve`,
    mutationOptions({ verification_declaration: true }, key),
  );
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}

/** Reject a prescription draft with a recorded reason. */
export async function rejectPrescription(
  caseId: number,
  rxId: number,
  req: RxRejectRequest,
  key?: string,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/rx/${rxId}/reject`,
    mutationOptions(req, key),
  );
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}

/** Close a visit without a prescription. */
export async function closeCaseWithoutRx(
  caseId: number,
  req: CaseCloseRequest,
  key?: string,
): Promise<CaseDetailView> {
  const data = await request<unknown>(
    `/v1/care/cases/${caseId}/close`,
    mutationOptions(req, key),
  );
  return guardShape(
    data,
    isCaseDetailView,
    "The API returned an unexpected care case shape",
  );
}

/** Read the doctor's in-progress prescription revision for a pending case. */
export async function fetchWorkingPrescription(
  caseId: number,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(`/v1/care/cases/${caseId}/rx/current`);
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}

/** Read an approved-and-issued e-prescription. */
export async function fetchApprovedPrescription(
  rxId: number,
): Promise<PrescriptionDetailView> {
  const data = await request<unknown>(`/v1/care/prescriptions/${rxId}`);
  return guardShape(
    data,
    isPrescriptionDetailView,
    "The API returned an unexpected prescription shape",
  );
}
