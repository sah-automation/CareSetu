// MOD-011 audit HTTP surface client for the patient PWA (PHASE-5 T1, #278).
// Thin fetch wrapper over the backend's GET /v1/audit/access-history endpoint;
// the response shape mirrors modules/health/facade.py's AccessHistoryView.
// Session cookie auth follows the same pattern as record/api.ts (ADR-0005).

import { guardShape, request } from "@/lib/request";

export interface AccessHistoryEntry {
  actor_id: number;
  actor_type?: string | null;
  // #670: the composition-root-resolved counterparty name (#668) travels beside
  // the id - an enrichment that the three-step label falls back from, never the
  // only identity a row carries. Null for an unresolvable row.
  actor_display_name: string | null;
  scope?: string | null;
  accessed_at: string;
  denied: boolean;
  denial_reason?: string | null;
}

export interface AccessHistoryView {
  entries: AccessHistoryEntry[];
}

function isAccessHistoryEntry(value: unknown): value is AccessHistoryEntry {
  if (typeof value !== "object" || value === null) return false;
  const v = value as AccessHistoryEntry;
  return (
    "actor_id" in value &&
    // The display name is an enrichment of the id, but once declared it is on
    // the wire for every row: a missing key is backend drift, and a non-string
    // would render as a label. Both fail loudly here rather than the row
    // rendering nothing - the same rule the consent client pins (#661).
    "actor_display_name" in value &&
    (typeof v.actor_display_name === "string" ||
      v.actor_display_name === null) &&
    "accessed_at" in value &&
    "denied" in value
  );
}

function isAccessHistoryView(value: unknown): value is AccessHistoryView {
  return (
    typeof value === "object" &&
    value !== null &&
    "entries" in value &&
    Array.isArray((value as AccessHistoryView).entries) &&
    (value as AccessHistoryView).entries.every(isAccessHistoryEntry)
  );
}

export async function fetchAccessHistory(
  patientId: number,
): Promise<AccessHistoryView> {
  const search = new URLSearchParams();
  search.set("patient_id", String(patientId));
  const data = await request<unknown>(`/v1/audit/access-history?${search}`);
  return guardShape(
    data,
    isAccessHistoryView,
    "The API returned an unexpected access history shape",
  );
}

// ---------------------------------------------------------------------
// MOD-011 operator audit-ledger query surface (PHASE-4 T6, #240). Thin
// fetch wrapper over GET /v1/audit/events. Session cookie auth follows the
// same pattern as the rest of the audit client.
// ---------------------------------------------------------------------

export interface AuditEventView {
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

export interface AuditPageView {
  events: AuditEventView[];
  total_count: number;
}

function isAuditEventView(value: unknown): value is AuditEventView {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.event_type === "string" &&
    typeof v.metadata === "object" &&
    v.metadata !== null &&
    typeof v.timestamp === "string" &&
    typeof v.prev_hash === "string" &&
    typeof v.hash === "string"
  );
}

function isAuditPageView(value: unknown): value is AuditPageView {
  if (typeof value !== "object" || value === null) return false;
  const page = value as Record<string, unknown>;
  return (
    Array.isArray(page.events) &&
    page.events.every(isAuditEventView) &&
    typeof page.total_count === "number"
  );
}

/** Read one page of the audit ledger (operator only), newest first. */
export async function fetchAuditEvents(
  params: { event_type?: string; page_size?: number } = {},
): Promise<AuditEventView[]> {
  const search = new URLSearchParams();
  if (params.event_type) search.set("event_type", params.event_type);
  if (params.page_size) search.set("page_size", String(params.page_size));
  const query = search.toString();
  const data = await request<unknown>(
    `/v1/audit/events${query ? `?${query}` : ""}`,
  );
  const page = guardShape(
    data,
    isAuditPageView,
    "The API returned an unexpected audit page shape",
  );
  return page.events;
}

/** Alias kept for callers that speak in query terms. */
export const queryAuditEvents = fetchAuditEvents;

/** Read the operator user-management events (invite/tier/active) from the audit ledger. */
export async function fetchOperatorChangeHistory(): Promise<AuditEventView[]> {
  const types = [
    "operator.invited",
    "operator.tier_changed",
    "operator.active_changed",
  ];
  const pages = await Promise.all(
    types.map((event_type) => fetchAuditEvents({ event_type, page_size: 50 })),
  );
  const seen = new Set<string>();
  const combined: AuditEventView[] = [];
  for (const page of pages) {
    for (const event of page) {
      if (seen.has(event.id)) continue;
      seen.add(event.id);
      combined.push(event);
    }
  }
  combined.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
  return combined;
}

/** Aliases kept for callers that spell the seam differently. */
export const fetchOperatorAuditHistory = fetchOperatorChangeHistory;
export const fetchOperatorHistory = fetchOperatorChangeHistory;
