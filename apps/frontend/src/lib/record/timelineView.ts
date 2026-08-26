// PHASE-3 T7 (#216): pure view-model helpers for the My Record timeline
// (blueprint §5.5). The API contract already delivers entries newest-first;
// the sort stays defensive so the screen is reverse-chronological even if a
// caller hands it unordered data. Entry cards are shaped from the documented
// payload fields only (modules/health/adapters/__init__.py) - never invented
// copy, so the timeline stays honest about what this phase actually stores.

import type { RecordEntryView } from "@/lib/record/api";

// Filter values mirror the four timeline types the UI can scope to; a
// settlement entry is real in the schema vocabulary but has no dedicated
// filter chip - it surfaces only under All.
export type RecordFilter =
  | "all"
  | "consultation"
  | "prescription"
  | "lab_report"
  | "metric";

// Chip order per the binding prototype (#entry-filters): All | Consultations
// | Prescriptions | Lab results | Metrics. The ratified filter-bar outcome
// collapses Lab results + Metrics into the mobile More dropdown (<720px).
export const RECORD_FILTERS: readonly RecordFilter[] = [
  "all",
  "consultation",
  "prescription",
  "lab_report",
  "metric",
];

export const MORE_OVERFLOW_FILTERS: readonly RecordFilter[] = [
  "lab_report",
  "metric",
];

// Reverse-chron by clinical time, id as the deterministic tiebreaker
// (mirrors the backend's ORDER BY occurred_at DESC, id DESC).
export function sortTimelineDesc(
  entries: RecordEntryView[],
): RecordEntryView[] {
  return [...entries].sort((a, b) => {
    const byTime =
      new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime();
    if (byTime !== 0) return byTime;
    return b.entry_id - a.entry_id;
  });
}

export function applyRecordFilter(
  entries: RecordEntryView[],
  filter: RecordFilter,
): RecordEntryView[] {
  if (filter === "all") return entries;
  return entries.filter((entry) => entry.entry_type === filter);
}

export type BadgeTone = "success" | "accent" | "warm" | "muted";

export interface EntryBadge {
  label: string;
  tone: BadgeTone;
}

export interface EntryCardStrings {
  badge: {
    consultation: string;
    prescription: string;
    labReport: string;
    metric: string;
    settlement: string;
    issued: string;
    delivered: string;
  };
  filedFromBooking: string;
}

export interface EntryCard {
  icon: string;
  title: string;
  subtitle: string | null;
  badge: EntryBadge | null;
}

function payloadString(entry: RecordEntryView, key: string): string | null {
  const value = entry.payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function payloadNumber(entry: RecordEntryView, key: string): number | null {
  const value = entry.payload[key];
  return typeof value === "number" ? value : null;
}

export function formatOccurredAt(iso: string, lang: "en" | "hi"): string {
  // Data arrives post-mount only, so this never runs during SSR/hydration.
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

export function describeEntry(
  entry: RecordEntryView,
  t: EntryCardStrings,
  lang: "en" | "hi",
): EntryCard {
  const date = formatOccurredAt(entry.occurred_at, lang);
  const parts: string[] = [];

  switch (entry.entry_type) {
    case "consultation":
      parts.push(date);
      return {
        icon: "\u{1FA7A}",
        title: t.badge.consultation,
        subtitle: parts.join(" \u00b7 "),
        badge: { label: t.badge.consultation, tone: "warm" },
      };
    case "prescription": {
      const prescriptionId = payloadNumber(entry, "prescription_id");
      if (prescriptionId !== null) parts.push(`Rx #${prescriptionId}`);
      parts.push(date);
      const delivered = payloadString(entry, "status") === "delivered";
      return {
        icon: "\u{1F48A}",
        title: t.badge.prescription,
        subtitle: parts.join(" \u00b7 "),
        badge: delivered
          ? { label: t.badge.delivered, tone: "success" }
          : { label: t.badge.issued, tone: "warm" },
      };
    }
    case "lab_report": {
      const orderId = payloadNumber(entry, "order_id");
      if (orderId !== null) parts.push(`${t.filedFromBooking} #${orderId}`);
      parts.push(date);
      return {
        icon: "\u{1F9EA}",
        title: payloadString(entry, "filename") ?? t.badge.labReport,
        subtitle: parts.join(" \u00b7 "),
        badge: { label: t.badge.labReport, tone: "accent" },
      };
    }
    case "metric":
      parts.push(date);
      return {
        icon: "\u{1F4C8}",
        title: t.badge.metric,
        subtitle: parts.join(" \u00b7 "),
        badge: { label: t.badge.metric, tone: "muted" },
      };
    case "settlement": {
      const amountPaise = payloadNumber(entry, "amount_paise");
      if (amountPaise !== null)
        parts.push(`\u20b9${(amountPaise / 100).toFixed(2)}`);
      const orderRef = payloadString(entry, "order_ref");
      if (orderRef !== null) parts.push(`#${orderRef}`);
      parts.push(date);
      return {
        icon: "\u{1F4B3}",
        title: t.badge.settlement,
        subtitle: parts.join(" \u00b7 "),
        badge: { label: t.badge.settlement, tone: "muted" },
      };
    }
  }
}
