// MOD-012 doctor console HTTP surface client for the Patients list + detail
// (#541). Thin typed wrapper over the backend's /v1/doctor/patients doctor
// routes; the request/response shapes mirror modules/doctor/doctor_models.py
// exactly (guardShape + request from lib/request.ts, session/auth travel via
// api-base.ts, ADR-0005). Every client read here goes through the consent-
// gated detail API - the page renders exactly what the backend answers, and
// ungranted sections come back as the locked (null) shape, never an error.
//
// Vocabulary (glossary): record scope is the closed enum
// consultations | prescriptions | lab_results | metrics | health_background |
// full_record; a section the doctor is not granted is null, which the UI
// renders as a calm "not shared" state.

import { guardShape, request, requestBlob } from "@/lib/request";
import type { RecordTimeline } from "@/lib/record/api";

export type DoctorPatientBucket = "current" | "past";

export type RecordScope =
  | "consultations"
  | "prescriptions"
  | "lab_results"
  | "metrics"
  | "health_background"
  | "full_record";

export interface DoctorPatientRow {
  patient_id: number;
  name: string | null;
  age: number | null;
  photo_ref: string | null;
  bucket: DoctorPatientBucket;
  granted_scopes: RecordScope[];
  latest_case_stage: string | null;
}

export interface PatientsListView {
  items: DoctorPatientRow[];
  total: number;
}

export interface ContactSection {
  name: string | null;
  age: number | null;
  gender: string | null;
  area: string | null;
  emergency_contact: string | null;
  photo_ref: string | null;
}

export interface CaseWorkspaceLink {
  case_id: number;
  stage: string;
}

export interface HealthBackground {
  blood_group: string | null;
  conditions: string[];
  allergies: string[];
  medications: string[];
  immunizations: string[];
  family_history: string[];
}

export interface HealthBackgroundView {
  set: boolean;
  acknowledged: boolean;
  background: HealthBackground | null;
}

export interface DoctorPatientDetailView {
  patient_id: number;
  bucket: DoctorPatientBucket;
  granted_scopes: RecordScope[];
  latest_case_stage: string | null;
  case_workspace: CaseWorkspaceLink | null;
  contact: ContactSection | null;
  consultation_history: RecordTimeline | null;
  health_background: HealthBackgroundView | null;
}

function isDoctorPatientRow(value: unknown): value is DoctorPatientRow {
  return (
    typeof value === "object" &&
    value !== null &&
    "patient_id" in value &&
    "name" in value &&
    "age" in value &&
    "photo_ref" in value &&
    "bucket" in value &&
    "granted_scopes" in value &&
    "latest_case_stage" in value
  );
}

function isContactSection(value: unknown): value is ContactSection {
  return (
    typeof value === "object" &&
    value !== null &&
    "name" in value &&
    "age" in value &&
    "gender" in value &&
    "area" in value &&
    "emergency_contact" in value &&
    "photo_ref" in value
  );
}

function isCaseWorkspaceLink(value: unknown): value is CaseWorkspaceLink {
  return (
    typeof value === "object" &&
    value !== null &&
    "case_id" in value &&
    "stage" in value
  );
}

function isHealthBackground(value: unknown): value is HealthBackground {
  return (
    typeof value === "object" &&
    value !== null &&
    "blood_group" in value &&
    "conditions" in value &&
    "allergies" in value &&
    "medications" in value &&
    "immunizations" in value &&
    "family_history" in value
  );
}

function isHealthBackgroundView(value: unknown): value is HealthBackgroundView {
  return (
    typeof value === "object" &&
    value !== null &&
    "set" in value &&
    "acknowledged" in value &&
    "background" in value
  );
}

function isRecordTimeline(value: unknown): value is RecordTimeline {
  return (
    typeof value === "object" &&
    value !== null &&
    "record_id" in value &&
    "patient_id" in value &&
    "created_at" in value &&
    "entries" in value &&
    Array.isArray((value as RecordTimeline).entries)
  );
}

function isDoctorPatientDetailView(
  value: unknown,
): value is DoctorPatientDetailView {
  if (
    typeof value !== "object" ||
    value === null ||
    !("patient_id" in value) ||
    !("bucket" in value) ||
    !("granted_scopes" in value) ||
    !("latest_case_stage" in value) ||
    !("case_workspace" in value) ||
    !("contact" in value) ||
    !("consultation_history" in value) ||
    !("health_background" in value)
  ) {
    return false;
  }
  const detail = value as DoctorPatientDetailView;
  return (
    (detail.case_workspace === null ||
      isCaseWorkspaceLink(detail.case_workspace)) &&
    (detail.contact === null || isContactSection(detail.contact)) &&
    (detail.consultation_history === null ||
      isRecordTimeline(detail.consultation_history)) &&
    (detail.health_background === null ||
      isHealthBackgroundView(detail.health_background))
  );
}

export interface ListDoctorPatientsParams {
  search?: string;
  page?: number;
  perPage?: number;
}

/** List the calling doctor's current and past patients (US-13, ADR-0019). */
export async function listDoctorPatients(
  params: ListDoctorPatientsParams = {},
): Promise<PatientsListView> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.page != null) query.set("page", String(params.page));
  if (params.perPage != null) query.set("per_page", String(params.perPage));
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const data = await request<unknown>(`/v1/doctor/patients${suffix}`);
  return guardShape(
    data,
    (value): value is PatientsListView =>
      typeof value === "object" &&
      value !== null &&
      "items" in value &&
      Array.isArray((value as PatientsListView).items) &&
      (value as PatientsListView).items.every(isDoctorPatientRow) &&
      "total" in value,
    "The API returned an unexpected patients list shape",
  );
}

/** Read one consent-gated patient detail (US-15..18, ADR-0019). */
export async function fetchDoctorPatientDetail(
  patientId: number,
): Promise<DoctorPatientDetailView> {
  const data = await request<unknown>(`/v1/doctor/patients/${patientId}`);
  return guardShape(
    data,
    isDoctorPatientDetailView,
    "The API returned an unexpected patient detail shape",
  );
}

/** Stream one consent-gated patient's profile photo bytes (#540, ADR-0020). */
export async function fetchDoctorPatientPhoto(
  patientId: number,
): Promise<Blob> {
  return requestBlob(`/v1/doctor/patients/${patientId}/photo`);
}
