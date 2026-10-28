// Operator settings HTTP client (#797). Read-only in this ticket: the effective
// settings read with its source and allowlist metadata. Writes land in #798.

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
