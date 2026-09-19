// MOD-005 patient intake HTTP surface client (PHASE-7 T15, #359). Thin typed
// wrapper over the backend's /v1/intake patient routes (T12, #356); response
// shapes mirror modules/intake/intake_models.py exactly. Uses the standard
// request/authedFetch conventions (api-base.ts + request.ts) so auth travels
// the same cookie/Bearer path as every other authed call. The AI pipeline runs
// asynchronously: submit returns a captured intake, and the pre-summary is
// read later at the {intake_id}/pre-summary route.

import { guardShape, request, requestBlob } from "@/lib/request";
import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";

export type IntakeMode = "voice" | "text";
export type IntakeLanguage = "hi" | "en";

/** Backend intake lifecycle status values (state_machine.py IntakeStatus). */
export type IntakeStatus =
  | "captured"
  | "structuring"
  | "ready_for_review"
  | "re_record"
  | "failed";

export interface MediaUploadRef {
  object_key: string;
  media_type: string;
  audio_duration_ms: number | null;
  file_size_bytes: number | null;
  record_attempt: number;
}

export interface IntakeSubmitResult {
  intake_id: number;
  status: string;
}

export interface ReRecordResult {
  intake_id: number;
  accepted: boolean;
  status: string;
  record_attempts: number;
  forced_text: boolean;
  media_ref_id: number | null;
}

export interface MediaRefView {
  media_ref_id: number;
  media_type: string;
  object_key: string;
  audio_duration_ms: number | null;
  file_size_bytes: number | null;
  record_attempt: number;
}

export interface IntakeDetailView {
  intake_id: number;
  patient_id: number;
  mode: IntakeMode;
  language: IntakeLanguage;
  status: IntakeStatus;
  record_attempts: number;
  text: string | null;
  transcript: string | null;
  transcript_usability: string | null;
  forced_text: boolean;
  media_refs: MediaRefView[];
  created_at: string;
  updated_at: string;
}

export interface StructuredFields {
  chief_complaints: string[];
  symptoms: string[];
  duration: string | null;
}

export interface PreSummaryView {
  pre_summary_id: number;
  intake_id: number;
  structured_fields: StructuredFields;
  structuring_confidence: number | null;
  low_confidence: boolean;
  review_state: string;
  patient_edits: Record<string, string | string[]> | null;
  doctor_corrections: Record<string, string | string[]> | null;
  review_attribution: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PatientEditsResult {
  intake_id: number;
  pre_summary_id: number;
  patient_edits: Record<string, string | string[]> | null;
}

export type ClinicalEdits = Record<string, string | string[]>;

/** One pre-summary awaiting the assigned doctor's review (PHASE-8.1 T07, #447). */
export interface ReviewQueueItem {
  pre_summary_id: number;
  intake_id: number;
  structuring_confidence: number | null;
  low_confidence: boolean;
  review_state: string;
  created_at: string;
  updated_at: string;
}

/** Outcome of the doctor's attributed one-action review-and-finalize (#442). */
export interface PreSummaryReviewResult {
  intake_id: number;
  pre_summary_id: number;
  review_state: string;
  reviewed_copy: ClinicalEdits;
  changed_fields: string[];
  review_attribution: string;
  reviewed_by: number;
  reviewed_at: string;
}

export interface SubmitIntakeRequest {
  mode: IntakeMode;
  language: IntakeLanguage;
  text?: string | null;
  media_ref?: MediaUploadRef | null;
}

function isMediaUploadRef(value: unknown): value is MediaUploadRef {
  return (
    typeof value === "object" &&
    value !== null &&
    "object_key" in value &&
    "media_type" in value &&
    "record_attempt" in value
  );
}

function isIntakeSubmitResult(value: unknown): value is IntakeSubmitResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "status" in value
  );
}

function isReRecordResult(value: unknown): value is ReRecordResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "accepted" in value &&
    "status" in value &&
    "record_attempts" in value &&
    "forced_text" in value
  );
}

function isMediaRefView(value: unknown): value is MediaRefView {
  return (
    typeof value === "object" &&
    value !== null &&
    "media_ref_id" in value &&
    "media_type" in value &&
    "object_key" in value &&
    "record_attempt" in value
  );
}

function isIntakeDetailView(value: unknown): value is IntakeDetailView {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "patient_id" in value &&
    "mode" in value &&
    "language" in value &&
    "status" in value &&
    "record_attempts" in value &&
    "forced_text" in value &&
    "media_refs" in value &&
    Array.isArray((value as IntakeDetailView).media_refs) &&
    (value as IntakeDetailView).media_refs.every(isMediaRefView)
  );
}

function isPreSummaryView(value: unknown): value is PreSummaryView {
  return (
    typeof value === "object" &&
    value !== null &&
    "pre_summary_id" in value &&
    "intake_id" in value &&
    "structured_fields" in value &&
    "structuring_confidence" in value &&
    "low_confidence" in value &&
    "review_state" in value &&
    "patient_edits" in value &&
    "doctor_corrections" in value &&
    "review_attribution" in value &&
    "reviewed_by" in value &&
    "reviewed_at" in value &&
    "created_at" in value &&
    "updated_at" in value
  );
}

function isPatientEditsResult(value: unknown): value is PatientEditsResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "pre_summary_id" in value &&
    "patient_edits" in value
  );
}

function isReviewQueueItem(value: unknown): value is ReviewQueueItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "pre_summary_id" in value &&
    "intake_id" in value &&
    "structuring_confidence" in value &&
    "low_confidence" in value &&
    "review_state" in value &&
    "created_at" in value &&
    "updated_at" in value
  );
}

function isPreSummaryReviewResult(
  value: unknown,
): value is PreSummaryReviewResult {
  return (
    typeof value === "object" &&
    value !== null &&
    "intake_id" in value &&
    "pre_summary_id" in value &&
    "review_state" in value &&
    "reviewed_copy" in value &&
    "changed_fields" in value &&
    Array.isArray((value as PreSummaryReviewResult).changed_fields) &&
    "review_attribution" in value &&
    "reviewed_by" in value &&
    "reviewed_at" in value
  );
}

/** Capture a symptom intake (text or voice). Emits intake.captured. */
export async function submitIntake(
  req: SubmitIntakeRequest,
): Promise<IntakeSubmitResult> {
  const data = await request<unknown>("/v1/intake/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return guardShape(
    data,
    isIntakeSubmitResult,
    "The API returned an unexpected intake submit result shape",
  );
}

/**
 * Upload an audio clip for a voice intake. Sends multipart/form-data with the
 * raw clip plus optional audio-duration and file-size query params; returns
 * the opaque clip ticket for use with submitIntake or reRecordIntake.
 */
export async function uploadIntakeMedia(
  file: Blob,
  options: {
    filename?: string;
    audioDurationMs?: number;
    fileSizeBytes?: number;
  } = {},
): Promise<MediaUploadRef> {
  const form = new FormData();
  const filename =
    options.filename ?? (file instanceof File ? file.name : "recording.webm");
  form.append("file", file, filename);
  const query = new URLSearchParams();
  if (options.audioDurationMs !== undefined) {
    query.set("audio_duration_ms", String(options.audioDurationMs));
  }
  if (options.fileSizeBytes !== undefined) {
    query.set("file_size_bytes", String(options.fileSizeBytes));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const data = await request<unknown>(`/v1/intake/upload-media${suffix}`, {
    method: "POST",
    body: form,
  });
  return guardShape(
    data,
    isMediaUploadRef,
    "The API returned an unexpected upload ticket shape",
  );
}

/** Attach a fresh recording attempt to a voice intake (capped at 3). */
export async function reRecordIntake(
  intakeId: number,
  mediaRef: MediaUploadRef,
): Promise<ReRecordResult> {
  const data = await request<unknown>(`/v1/intake/${intakeId}/re-record`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_ref: mediaRef }),
  });
  return guardShape(
    data,
    isReRecordResult,
    "The API returned an unexpected re-record result shape",
  );
}

/** Read an intake with transcript, media refs, and status. */
export async function fetchIntake(intakeId: number): Promise<IntakeDetailView> {
  const data = await request<unknown>(`/v1/intake/${intakeId}`);
  return guardShape(
    data,
    isIntakeDetailView,
    "The API returned an unexpected intake detail shape",
  );
}

/** Read the AI pre-summary with draft fields, confidence, and edits. */
export async function fetchPreSummary(
  intakeId: number,
): Promise<PreSummaryView> {
  const data = await request<unknown>(`/v1/intake/${intakeId}/pre-summary`);
  return guardShape(
    data,
    isPreSummaryView,
    "The API returned an unexpected pre-summary shape",
  );
}

/** Save patient corrections to a pre-summary (informational advice). */
export async function savePatientEdits(
  intakeId: number,
  fields: Record<string, unknown>,
): Promise<PatientEditsResult> {
  const data = await request<unknown>(`/v1/intake/${intakeId}/patient-edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  return guardShape(
    data,
    isPatientEditsResult,
    "The API returned an unexpected patient-edits result shape",
  );
}

/**
 * List pre-summaries assigned to the calling doctor that await review,
 * low-confidence first (PHASE-8.1 T07, #447). Each item carries the
 * confidence flag so the console can surface the items that most need
 * the doctor's attention (US-11/12).
 */
export async function fetchReviewQueue(): Promise<ReviewQueueItem[]> {
  const data = await request<unknown>("/v1/intake/review-queue");
  return guardShape(
    data,
    (value): value is ReviewQueueItem[] =>
      Array.isArray(value) && value.every(isReviewQueueItem),
    "The API returned an unexpected review-queue shape",
  );
}

/**
 * Read the full pre-summary content for the assigned doctor's review
 * (PHASE-8.1 T08, #448). Distinct doctor-scoped read from the patient GET
 * pre-summary: returns the structured summary, symptoms, confidence flag,
 * and review state for the doctor to whom the intake is assigned.
 */
export async function fetchPreSummaryForReview(
  intakeId: number,
): Promise<PreSummaryView> {
  const data = await request<unknown>(
    `/v1/intake/${intakeId}/pre-summary/review`,
  );
  return guardShape(
    data,
    isPreSummaryView,
    "The API returned an unexpected pre-summary shape",
  );
}

/**
 * Read an intake's transcript and media refs for the assigned doctor
 * (PHASE-8.1 T09, #484). Pre-summary-keyed doctor read backing the case
 * workspace pre-summary tab: the care case carries only the pre-summary id,
 * the facade resolves the intake and enforces the assigned-doctor scope.
 */
export async function fetchIntakeDetailForDoctor(
  preSummaryId: number,
): Promise<IntakeDetailView> {
  const data = await request<unknown>(
    `/v1/intake/pre-summary/${preSummaryId}/detail`,
  );
  return guardShape(
    data,
    isIntakeDetailView,
    "The API returned an unexpected intake detail shape",
  );
}

/**
 * Fetch the intake audio clip bytes (PHASE-8.1 #484). Reuses the existing
 * GET /v1/intake/{intake_id}/media/{media_ref_id} stream route with doctor
 * auth (PHASE-7 T13, #357). The stream is not JSON, so it goes through the
 * shared ``requestBlob`` transport (same auth + error-envelope handling as
 * ``request<T>``) instead of a JSON parse. Audio is PHI, so the blob is
 * consumed client-side only and never logged.
 */
export async function fetchIntakeMediaBlob(
  intakeId: number,
  mediaRefId: number,
): Promise<Blob> {
  return requestBlob(`/v1/intake/${intakeId}/media/${mediaRefId}`);
}

/**
 * Perform the single attributed doctor review-and-finalize (PHASE-8.1 T04,
 * #442). One action both attributes the review and moves the pre-summary to
 * the terminal ``final`` state for BOTH confidence classes - a low-confidence
 * summary can only reach ``final`` this way. Omitted or empty ``corrections``
 * is a review with no edits.
 */
export async function reviewPreSummary(
  intakeId: number,
  corrections?: Record<string, unknown> | null,
  retryKey?: string,
): Promise<PreSummaryReviewResult> {
  const body =
    corrections === undefined || corrections === null ? {} : { corrections };
  const key = idempotencyKey(retryKey);
  const data = await request<unknown>(`/v1/intake/${intakeId}/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: key,
    },
    body: JSON.stringify(body),
  });
  return guardShape(
    data,
    isPreSummaryReviewResult,
    "The API returned an unexpected review result shape",
  );
}
