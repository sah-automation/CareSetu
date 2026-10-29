// Operator settings HTTP client (#797/#798). Reads the effective settings with
// their source and allowlist metadata, writes an allowlisted AI knob, and reads
// the append-only setting history the AI section shows after a save.

import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { guardShape, request } from "@/lib/request";

/** Where an effective value came from, in precedence order. */
export type SettingSource = "database" | "environment" | "default";

export interface EffectiveSetting {
  key: string;
  value: unknown;
  source: SettingSource;
  editable: boolean;
  restart_required: boolean;
}

/** A value the API accepts for an allowlisted setting write. */
export type SettingWriteValue = string | number | boolean | string[] | null;

export interface SettingWriteResult {
  setting_key: string;
  value: unknown;
  version: number;
}

export interface SettingHistoryEntry {
  setting_key: string;
  value: unknown;
  version: number;
  changed_by: number | null;
  changed_at: string;
}

export interface AlertDeliveryRow {
  id: number;
  alert_id: string;
  channel: string;
  status: string;
  attempts: number;
  next_retry_at: string | null;
  last_attempt_at: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertDeliveryPage {
  deliveries: AlertDeliveryRow[];
  total_count: number;
  page: number;
  page_size: number;
}

export interface AlertDeliveryTestResult {
  success: boolean;
  error: string | null;
  response: Record<string, unknown> | null;
}

export interface AlertDeliveryRedeliverResult {
  success: boolean;
  delivery_id: number;
}

function isSettingSource(value: unknown): value is SettingSource {
  return value === "database" || value === "environment" || value === "default";
}

interface EffectiveSettingsResponse {
  settings: EffectiveSetting[];
}

function isEffectiveSetting(value: unknown): value is EffectiveSetting {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.key === "string" &&
    isSettingSource(row.source) &&
    typeof row.editable === "boolean" &&
    typeof row.restart_required === "boolean" &&
    "value" in row
  );
}

function isEffectiveSettingsResponse(
  value: unknown,
): value is EffectiveSettingsResponse {
  if (typeof value !== "object" || value === null) return false;
  const settings = (value as { settings?: unknown }).settings;
  return (
    Array.isArray(settings) && settings.every((row) => isEffectiveSetting(row))
  );
}

function isSettingWriteResult(value: unknown): value is SettingWriteResult {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.setting_key === "string" &&
    typeof row.version === "number" &&
    "value" in row
  );
}

function isSettingHistoryEntry(value: unknown): value is SettingHistoryEntry {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.setting_key === "string" &&
    typeof row.version === "number" &&
    (row.changed_by === null || typeof row.changed_by === "number") &&
    typeof row.changed_at === "string" &&
    "value" in row
  );
}

interface SettingsHistoryResponse {
  history: SettingHistoryEntry[];
}

function isSettingsHistoryResponse(
  value: unknown,
): value is SettingsHistoryResponse {
  if (typeof value !== "object" || value === null) return false;
  const history = (value as { history?: unknown }).history;
  return (
    Array.isArray(history) && history.every((row) => isSettingHistoryEntry(row))
  );
}

function isAlertDeliveryRow(value: unknown): value is AlertDeliveryRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === "number" &&
    typeof row.alert_id === "string" &&
    typeof row.channel === "string" &&
    typeof row.status === "string" &&
    typeof row.attempts === "number" &&
    (row.next_retry_at === null || typeof row.next_retry_at === "string") &&
    (row.last_attempt_at === null || typeof row.last_attempt_at === "string") &&
    (row.delivered_at === null || typeof row.delivered_at === "string") &&
    typeof row.created_at === "string" &&
    typeof row.updated_at === "string"
  );
}

interface AlertDeliveryPageResponse {
  deliveries: AlertDeliveryRow[];
  total_count: number;
  page: number;
  page_size: number;
}

function isAlertDeliveryPageResponse(
  value: unknown,
): value is AlertDeliveryPageResponse {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    Array.isArray(row.deliveries) &&
    row.deliveries.every((d) => isAlertDeliveryRow(d)) &&
    typeof row.total_count === "number" &&
    typeof row.page === "number" &&
    typeof row.page_size === "number"
  );
}

function isAlertDeliveryTestResult(
  value: unknown,
): value is AlertDeliveryTestResult {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.success === "boolean" &&
    (row.error === null || typeof row.error === "string") &&
    (row.response === null || typeof row.response === "object")
  );
}

function isAlertDeliveryRedeliverResult(
  value: unknown,
): value is AlertDeliveryRedeliverResult {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.success === "boolean" && typeof row.delivery_id === "number"
  );
}

/**
 * Read alert delivery attempts, newest first.
 */
export async function fetchAlertDeliveries(
  page = 1,
  pageSize = 25,
  status?: string,
): Promise<AlertDeliveryPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (status) query.set("status", status);
  const data = await request<unknown>(
    `/v1/operator/observability/alert-delivery?${query.toString()}`,
  );
  const read = guardShape(
    data,
    isAlertDeliveryPageResponse,
    "The API returned an unexpected alert delivery shape",
  );
  return read;
}

/**
 * Send a test notification via a delivery channel.
 */
export async function testAlertDelivery(
  channel: "slack" | "email",
): Promise<AlertDeliveryTestResult> {
  const data = await request<unknown>(
    "/v1/operator/observability/alert-delivery/test",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel }),
    },
  );
  return guardShape(
    data,
    isAlertDeliveryTestResult,
    "The API returned an unexpected test delivery shape",
  );
}

/**
 * Redeliver a failed or dead-letter alert delivery.
 */
export async function redeliverAlertDelivery(
  deliveryId: number,
): Promise<AlertDeliveryRedeliverResult> {
  const data = await request<unknown>(
    `/v1/operator/observability/alert-delivery/${deliveryId}/redeliver`,
    { method: "POST" },
  );
  return guardShape(
    data,
    isAlertDeliveryRedeliverResult,
    "The API returned an unexpected redelivery shape",
  );
}

/**
 * Read every effective setting with its source, editability and restart flag.
 * The endpoint is admin-only; a non-admin session receives the API's own 403.
 */
export async function fetchEffectiveSettings(): Promise<EffectiveSetting[]> {
  const data = await request<unknown>("/v1/operator/settings/effective");
  const read = guardShape(
    data,
    isEffectiveSettingsResponse,
    "The API returned an unexpected effective settings shape",
  );
  return read.settings;
}

/**
 * Read the append-only setting history, newest first. The API narrows by key
 * when one is given; the AI section asks for the whole list once and filters.
 */
export async function fetchSettingHistory(
  settingKey?: string,
): Promise<SettingHistoryEntry[]> {
  const query =
    settingKey === undefined
      ? ""
      : `?setting_key=${encodeURIComponent(settingKey)}`;
  const data = await request<unknown>(`/v1/operator/settings/history${query}`);
  const read = guardShape(
    data,
    isSettingsHistoryResponse,
    "The API returned an unexpected setting history shape",
  );
  return read.history;
}

/**
 * Write one allowlisted setting. The endpoint is admin-only and idempotent: a
 * retry that replays the failed attempt's key returns the original result
 * rather than bumping the version twice. A refused value arrives as an
 * `ApiError` whose message names the bound that failed.
 */
export async function writeSetting(
  settingKey: string,
  value: SettingWriteValue,
  retryKey?: string,
): Promise<SettingWriteResult> {
  const data = await request<unknown>("/v1/operator/settings", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
    },
    body: JSON.stringify({ setting_key: settingKey, value }),
  });
  return guardShape(
    data,
    isSettingWriteResult,
    "The API returned an unexpected setting write shape",
  );
}
