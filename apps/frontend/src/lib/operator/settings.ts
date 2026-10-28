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
