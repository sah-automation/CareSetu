// MOD-003 (FEAT-002 record / FEAT-018 metrics), gated by MOD-004 (FEAT-002
// consent), #549: the patient health-background HTTP client (backend #534
// snapshot + #535 height/weight series). Thin typed wrapper over the owner's
// two surfaces; the request/response shapes mirror MOD-003's
// modules/health/facade.py Pydantic models exactly (guardShape + request from
// lib/request.ts, session/auth travel via api-base.ts, ADR-0005).
//
// Two facts shape this client. First, both routes are owner-only: the patient
// is resolved from the session subject, so nothing here sends a patient id -
// the client cannot read another patient's background even by accident.
// Second, the snapshot's `acknowledge_phi` is a required field, not an optional
// one: the backend refuses a first save that omits it (422
// HEALTH_BACKGROUND_ACK_REQUIRED) and stamps the acknowledgment only on that
// first save, so a later edit must send `false` rather than leave the field out.
//
// Vocabulary (glossary): the snapshot is the patient's one current health
// summary; the series is the append-only list of timestamped height/weight
// measurements. Row ids are server-minted, so neither client function accepts
// one - the metric request model forbids extra fields, so a client-supplied id
// is a 422 rather than a silent second row.

import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { guardShape, request } from "@/lib/request";

/** The blood group label plus the five free-form entry lists. */
export interface HealthBackground {
  blood_group: string | null;
  conditions: string[];
  allergies: string[];
  medications: string[];
  immunizations: string[];
  family_history: string[];
}

/**
 * The typed read-back. `set` discriminates a stored snapshot from the "not
 * recorded" answer, and `acknowledged` says whether the one-time first-save
 * confirmation has already been given - the gate the UI prompts behind. The
 * same shape answers GET and PUT so the zone handles one contract.
 */
export interface HealthBackgroundView {
  set: boolean;
  acknowledged: boolean;
  background: HealthBackground | null;
}

/** One stored measurement; the list is newest-first, and ids are server-minted. */
export interface HealthMetricEntry {
  entry_id: number;
  height_cm: number | null;
  weight_kg: number | null;
  recorded_at: string;
}

/** One bounded page of the series; `total` is the full series length. */
export interface HealthMetricPage {
  items: HealthMetricEntry[];
  total: number;
}

function isStringList(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
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
    "family_history" in value &&
    isStringList((value as HealthBackground).conditions) &&
    isStringList((value as HealthBackground).allergies) &&
    isStringList((value as HealthBackground).medications) &&
    isStringList((value as HealthBackground).immunizations) &&
    isStringList((value as HealthBackground).family_history)
  );
}

function isHealthBackgroundView(value: unknown): value is HealthBackgroundView {
  if (typeof value !== "object" || value === null) return false;
  const view = value as HealthBackgroundView;
  // `background: null` is the typed "not recorded" answer, not a bad shape:
  // a patient who has not saved a snapshot yet is a state the zone renders,
  // so the guard has to accept it.
  return (
    "set" in value &&
    "acknowledged" in value &&
    "background" in value &&
    (view.background === null || isHealthBackground(view.background))
  );
}

function isHealthMetricEntry(value: unknown): value is HealthMetricEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    "entry_id" in value &&
    "height_cm" in value &&
    "weight_kg" in value &&
    "recorded_at" in value
  );
}

function isHealthMetricPage(value: unknown): value is HealthMetricPage {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    "total" in value &&
    Array.isArray((value as HealthMetricPage).items) &&
    (value as HealthMetricPage).items.every(isHealthMetricEntry)
  );
}

export async function fetchHealthBackground(): Promise<HealthBackgroundView> {
  const data = await request<unknown>("/v1/me/health-background");
  return guardShape(
    data,
    isHealthBackgroundView,
    "The API returned an unexpected health-background shape",
  );
}

export interface SaveHealthBackgroundOptions {
  /**
   * The one-time first-save acknowledgment that the snapshot becomes visible
   * to the patient's verified-relationship doctors. True only on the first
   * save; later edits send false so they neither re-prompt nor re-grant.
   */
  acknowledgePhi: boolean;
  /** Idempotency key of a failed attempt, so a retry cannot double-save. */
  retryKey?: string;
}

export async function saveHealthBackground(
  background: HealthBackground,
  options: SaveHealthBackgroundOptions,
): Promise<HealthBackgroundView> {
  const data = await request<unknown>("/v1/me/health-background", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(options.retryKey),
    },
    body: JSON.stringify({
      acknowledge_phi: options.acknowledgePhi,
      background,
    }),
  });
  return guardShape(
    data,
    isHealthBackgroundView,
    "The API returned an unexpected health-background shape",
  );
}

/**
 * A page of the series. `perPage` is sent only when the caller asks for a
 * specific size: an unqualified read omits it so the server's own bound
 * (`routes.py _DEFAULT_PER_PAGE`) is the single source of truth rather than a
 * number re-declared here.
 */
export async function fetchHealthMetrics(
  page: { page?: number; perPage?: number } = {},
): Promise<HealthMetricPage> {
  const query = new URLSearchParams();
  query.set("page", String(page.page ?? 1));
  if (page.perPage !== undefined) {
    query.set("per_page", String(page.perPage));
  }
  const data = await request<unknown>(
    `/v1/me/health-background/metrics?${query.toString()}`,
  );
  return guardShape(
    data,
    isHealthMetricPage,
    "The API returned an unexpected health-metrics page shape",
  );
}

/** The three authored measurement values; absent ones stay out of the payload. */
export interface HealthMetricInput {
  heightCm: number | null;
  weightKg: number | null;
  recordedAt: string;
}

export async function appendHealthMetric(
  metric: HealthMetricInput,
  retryKey?: string,
): Promise<HealthMetricEntry> {
  const data = await request<unknown>("/v1/me/health-background/metrics", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
    },
    body: JSON.stringify({
      ...(metric.heightCm === null ? {} : { height_cm: metric.heightCm }),
      ...(metric.weightKg === null ? {} : { weight_kg: metric.weightKg }),
      recorded_at: metric.recordedAt,
    }),
  });
  return guardShape(
    data,
    isHealthMetricEntry,
    "The API returned an unexpected health-metric entry shape",
  );
}
