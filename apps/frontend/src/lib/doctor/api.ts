// MOD-012 doctor console HTTP surface client: the Patients list + detail (#541)
// and the calling doctor's own private profile (#543). Thin typed wrapper over
// the backend's /v1/doctor doctor routes; the request/response shapes mirror
// modules/doctor/doctor_models.py and modules/partner/doctor_profile_models.py
// exactly (guardShape + request from lib/request.ts, session/auth travel via
// api-base.ts, ADR-0005). Every patient read here goes through the consent-
// gated detail API - the page renders exactly what the backend answers, and
// ungranted sections come back as the locked (null) shape, never an error.
//
// Vocabulary (glossary): record scope is the closed enum
// consultations | prescriptions | lab_results | metrics | health_background |
// full_record; a section the doctor is not granted is null, which the UI
// renders as a calm "not shared" state.

import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { guardShape, request, requestBlob, requestVoid } from "@/lib/request";
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

// ---- the calling doctor's own private profile (#542, ADR-0020) ----
//
// The private projection is the single read model for the Profile page: photo,
// practice details, experience, languages, about, availability, credential
// status, notifications and the consultation fee. The consultation fee itself
// stays on its own PATCH route (`updateConsultationFee` in lib/partner/api.ts)
// against the same partner record, so this module never writes it.

export type DoctorCredentialStatus =
  | "pending"
  | "verified"
  | "expired"
  | "revoked"
  | "reverification_failed";

export interface DoctorProfileCredential {
  credential_type: string;
  status: DoctorCredentialStatus;
  expires_at: string | null;
}

export interface DoctorProfileView {
  partner_id: number;
  photo_ref: string | null;
  practice_name: string | null;
  /**
   * The building the doctor practises in, distinct from `practice_name`, which is
   * the doctor's own name. Nullable: a doctor can name who they are before they
   * have named the building they see patients in.
   */
  clinic_name: string | null;
  /**
   * The declared specialty SELECTION, not one value: a doctor may practise more
   * than one kind of care. The values are the closed pick-list's own
   * display-ready strings, so the chip row renders them verbatim.
   */
  specialties: string[];
  /**
   * The stored verification indicator, derived server-side from activation state
   * plus credential dates and never recomputed here. Both the identity band's
   * tick and the verified band's own tick read this one flag, so they cannot
   * disagree about the same doctor.
   */
  verified: boolean;
  /**
   * A DENORMALISED display projection of the structured address parts below,
   * read-only on the client. Served beside the parts rather than instead of them:
   * it is assembled from them, so parsing it back into fields would be guessing
   * at a format this client does not own.
   */
  practice_address: string;
  address_line: string | null;
  landmark: string | null;
  locality: string | null;
  city: string | null;
  pin_code: string | null;
  /**
   * Server-written and never client-written: the practice position is derived
   * from the declared PIN code, so the doctor is never asked a question only a map
   * could answer. Still served because the band reads it back as a confirmation.
   */
  practice_latitude: number;
  practice_longitude: number;
  /**
   * The platform's service-area vocabulary name. Deliberately NOT rendered to
   * the doctor: the concept was demoted to non-user-facing because it is a
   * platform seed, not the neighbourhood a practice sits in (`locality` is).
   */
  area: string | null;
  languages: string[];
  experience_years: number | null;
  about: string | null;
  consultation_fee: number | null;
  /**
   * The declared consulting-day SELECTION, closed over the seven days of the
   * week, replacing the retired free-text `availability` blob whose days and
   * hours were one string. The hours survive separately as prose.
   */
  consulting_days: string[];
  consulting_hours: string | null;
  credentials: DoctorProfileCredential[];
  notification_preferences: Record<string, boolean>;
}

/**
 * The editable body of the private profile. It is a whole-form PUT, not a
 * patch: the backend requires the practice address and coordinates on every
 * call, so a caller always sends the complete editable projection.
 */
/**
 * The transitional whole-form write's body, as this client still sends it.
 *
 * `availability` is GONE: #615 removed the only editor that fed it, and #610
 * already retired the column it projected. The projection no longer carries the
 * field either, so declaring it here would mean the page has to invent a value
 * for a blob the backend has no writer for.
 *
 * What this type still describes is a route #611 removed. That is a known
 * transitional gap this ticket deliberately does not close - the section-write
 * calls (#616/#617) replace it, and each of them declares a different body
 * (`DoctorProfilePracticeUpdate` and friends) rather than this one.
 */
export interface DoctorProfileUpdate {
  practice_name: string | null;
  practice_address: string;
  practice_latitude: number;
  practice_longitude: number;
  experience_years: number | null;
  languages: string[];
  about: string | null;
  notification_preferences: Record<string, boolean>;
}

export interface DoctorProfilePhotoRef {
  photo_ref: string;
}

/**
 * The Address section write's body (#609), mirroring
 * `DoctorProfileAddressUpdate`.
 *
 * **No coordinate field, and that is the guarantee rather than an omission.**
 * The backend model sets `extra="forbid"`, so a body still carrying
 * `practice_latitude` or `practice_longitude` is a 422 rather than a silently
 * discarded one - accepting it would tell a doctor their coordinates saved when
 * they did not. The practice position is derived from `pin_code` by the server
 * (ADR-0022), so the doctor is never asked the question only a map could answer.
 *
 * `pin_code` is the only required part because it is the only one the position is
 * derived from. Deliberately **no** pattern or length bound here either: the
 * backend's domain decision (#603) owns that rule and reports malformed and
 * unlisted as two machine reasons inside one PIN-keyed envelope, so a bound
 * checked here would refuse the value before the rule that explains it ever
 * runs. The client's mirror of that rule is the card's validation pass, which
 * refuses a submission rather than rewriting the value.
 */
export interface DoctorProfileAddressUpdate {
  address_line: string | null;
  landmark: string | null;
  locality: string | null;
  city: string | null;
  pin_code: string;
}

/**
 * The Address section write's answer (#609): the profile projection plus the
 * outside-the-belt warning.
 *
 * A separate type rather than two nullable fields on `DoctorProfileView`,
 * because **only this write evaluates the belt** - the decision needs the PIN's
 * resolved centroid, which exists only inside this write's transaction. So a
 * plain profile read carries no belt field at all rather than carrying one whose
 * meaning depends on which endpoint produced it, and the card has nothing to
 * render a notice from before its first save. That is the honest state: absent,
 * not a spinner and not a promise.
 *
 * It is a warning, never a refusal. The position is written either way and the
 * save succeeds; only this doctor's own listing surfaces as an outside-your-area
 * result (the wider-area fallback, glossary).
 */
export interface DoctorProfileAddressView extends DoctorProfileView {
  outside_peri_urban_belt: boolean;
  /** Carried so the notice can say how far out the practice sits, not only that it is. */
  distance_from_belt_centre_km: number;
}

const CREDENTIAL_STATUSES: readonly string[] = [
  "pending",
  "verified",
  "expired",
  "revoked",
  "reverification_failed",
];

function isDoctorProfileCredential(
  value: unknown,
): value is DoctorProfileCredential {
  return (
    typeof value === "object" &&
    value !== null &&
    "credential_type" in value &&
    "status" in value &&
    "expires_at" in value &&
    CREDENTIAL_STATUSES.includes(
      (value as DoctorProfileCredential).status as string,
    )
  );
}

function isDoctorProfileView(value: unknown): value is DoctorProfileView {
  if (
    typeof value !== "object" ||
    value === null ||
    !("partner_id" in value) ||
    !("photo_ref" in value) ||
    !("practice_name" in value) ||
    !("clinic_name" in value) ||
    !("specialties" in value) ||
    !("verified" in value) ||
    !("practice_address" in value) ||
    !("address_line" in value) ||
    !("landmark" in value) ||
    !("locality" in value) ||
    !("city" in value) ||
    !("pin_code" in value) ||
    !("practice_latitude" in value) ||
    !("practice_longitude" in value) ||
    !("area" in value) ||
    !("languages" in value) ||
    !("experience_years" in value) ||
    !("about" in value) ||
    !("consultation_fee" in value) ||
    !("consulting_days" in value) ||
    !("consulting_hours" in value) ||
    !("credentials" in value) ||
    !("notification_preferences" in value)
  ) {
    return false;
  }
  const view = value as DoctorProfileView;
  return (
    Array.isArray(view.specialties) &&
    Array.isArray(view.languages) &&
    Array.isArray(view.consulting_days) &&
    Array.isArray(view.credentials) &&
    view.credentials.every(isDoctorProfileCredential) &&
    typeof view.notification_preferences === "object" &&
    view.notification_preferences !== null
  );
}

function isDoctorProfilePhotoRef(
  value: unknown,
): value is DoctorProfilePhotoRef {
  return (
    typeof value === "object" &&
    value !== null &&
    "photo_ref" in value &&
    typeof (value as DoctorProfilePhotoRef).photo_ref === "string"
  );
}

function isDoctorProfileAddressView(
  value: unknown,
): value is DoctorProfileAddressView {
  // The profile guard first: the write's answer IS the profile projection, plus
  // the two fields only this write produces. Guarding them separately is what
  // makes a backend that quietly dropped the belt warning fail loudly here
  // rather than leave the card rendering nothing and saying nothing.
  if (!isDoctorProfileView(value)) return false;
  // Read off a widened local rather than off the narrowed value: the profile
  // guard's whole point is that those two fields are NOT on the projection, so
  // asking the narrowed type for them is the type error, not a runtime concern.
  const answer = value as Partial<DoctorProfileAddressView>;
  return (
    typeof answer.outside_peri_urban_belt === "boolean" &&
    typeof answer.distance_from_belt_centre_km === "number"
  );
}

/** Read the calling active doctor's private profile projection. */
export async function fetchDoctorProfile(): Promise<DoctorProfileView> {
  const data = await request<unknown>("/v1/doctor/profile");
  return guardShape(
    data,
    isDoctorProfileView,
    "The API returned an unexpected doctor profile shape",
  );
}

/** Write the editable profile fields; the fee and photo keep their own routes. */
export async function updateDoctorProfile(
  update: DoctorProfileUpdate,
  retryKey?: string,
): Promise<DoctorProfileView> {
  const data = await request<unknown>("/v1/doctor/profile", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
    },
    body: JSON.stringify(update),
  });
  return guardShape(
    data,
    isDoctorProfileView,
    "The API returned an unexpected doctor profile shape",
  );
}

/**
 * Save the calling active doctor's practice address through the section write
 * (#609), on its own path rather than on `/profile`.
 *
 * Its own path is load-bearing: the backend namespaces its stored idempotency
 * result per route, so a key issued against another write would otherwise be
 * served this write's response.
 *
 * `retryKey` carries the per-attempt discipline (api-standards §5): a retry of
 * the same attempt passes the failed attempt's key back, so a lost response
 * cannot write the address twice, while a fresh edit mints a new one. Nothing in
 * here mints a key - `idempotencyKey` is the shared module's, and the caller
 * owns the attempt.
 */
export async function updateDoctorProfileAddress(
  update: DoctorProfileAddressUpdate,
  retryKey?: string,
): Promise<DoctorProfileAddressView> {
  const data = await request<unknown>("/v1/doctor/profile/address", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
    },
    body: JSON.stringify(update),
  });
  return guardShape(
    data,
    isDoctorProfileAddressView,
    "The API returned an unexpected doctor address shape",
  );
}

/**
 * Upload or replace the doctor's private photo. The multipart body is sent
 * without an explicit Content-Type so the browser sets the boundary itself -
 * the backend stores a `doctor/` profile-media key, never a public URL.
 */
export async function uploadDoctorProfilePhoto(
  file: File,
  retryKey?: string,
): Promise<DoctorProfilePhotoRef> {
  const body = new FormData();
  body.append("file", file);
  const data = await request<unknown>("/v1/doctor/profile/photo", {
    method: "PUT",
    headers: { [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey) },
    body,
  });
  return guardShape(
    data,
    isDoctorProfilePhotoRef,
    "The API returned an unexpected doctor photo shape",
  );
}

/** Stream the doctor's own private photo bytes for the preview. */
export async function fetchDoctorProfilePhoto(): Promise<Blob> {
  return requestBlob("/v1/doctor/profile/photo");
}

/** Remove the doctor's photo; the endpoint answers 204. */
export async function deleteDoctorProfilePhoto(
  retryKey?: string,
): Promise<void> {
  await requestVoid("/v1/doctor/profile/photo", {
    method: "DELETE",
    headers: { [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey) },
  });
}
