// PHASE-3 T7 (#216): pure view-model helpers for the My Record timeline
// (blueprint §5.5). The API contract already delivers entries newest-first;
// the sort stays defensive so the screen is reverse-chronological even if a
// caller hands it unordered data. Entry cards are shaped from the documented
// payload fields only (modules/health/adapters/__init__.py) - never invented
// copy, so the timeline stays honest about what this phase actually stores.

import type { RecordEntryType, RecordEntryView } from "@/lib/record/api";

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

// PROTO-3.1 (#511): date-grouped timeline. Entries are bucketed by their
// *local* calendar day so "Today"/"Yesterday" track the patient's own clock,
// not the server's; older entries fall into a "Month Year" bucket labelled
// via Intl (bilingual, never hardcoded month names). Groups keep the
// reverse-chronological reading order the input is expected in, so the UI can
// render them in encounter order without a second sort.
export interface TimelineGroup {
  /** "today" | "yesterday" | "YYYY-MM" of the group's local month. */
  key: string;
  label: string;
  entries: RecordEntryView[];
}

export interface GroupLabels {
  today: string;
  yesterday: string;
}

function startOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Bilingual month label ("September 2026" / "सितंबर 2026") via Intl. */
export function formatMonthYear(date: Date, lang: "en" | "hi"): string {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    month: "long",
    year: "numeric",
  }).format(date);
}

export function groupTimeline(
  entries: RecordEntryView[],
  labels: GroupLabels,
  lang: "en" | "hi",
): TimelineGroup[] {
  const today = startOfLocalDay(new Date());
  const yesterday = startOfLocalDay(new Date());
  yesterday.setDate(today.getDate() - 1);

  const groups: TimelineGroup[] = [];
  const byKey = new Map<string, TimelineGroup>();

  for (const entry of sortTimelineDesc(entries)) {
    const day = startOfLocalDay(new Date(entry.occurred_at));
    let key: string;
    let label: string;
    if (day.getTime() === today.getTime()) {
      key = "today";
      label = labels.today;
    } else if (day.getTime() === yesterday.getTime()) {
      key = "yesterday";
      label = labels.yesterday;
    } else {
      key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(
        2,
        "0",
      )}`;
      label = formatMonthYear(
        new Date(day.getFullYear(), day.getMonth(), 1),
        lang,
      );
    }
    let group = byKey.get(key);
    if (!group) {
      group = { key, label, entries: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.entries.push(entry);
  }
  return groups;
}

// PROTO-3.1 (#511): payload-derived counts. `all` is the total entry count so
// a settlement (which has no filter chip) still shows up in "Everything";
// the four typed counts let the snapshot/rail stay honest about what exists.
export type RecordCounts = Record<RecordFilter, number>;

export function countByType(entries: RecordEntryView[]): RecordCounts {
  const counts: RecordCounts = {
    all: entries.length,
    consultation: 0,
    prescription: 0,
    lab_report: 0,
    metric: 0,
  };
  for (const entry of entries) {
    if (entry.entry_type === "settlement") continue;
    counts[entry.entry_type] += 1;
  }
  return counts;
}

// PROTO-3.1 (#511): out-of-range lab rows. The backend does not produce
// `payload.results` yet, so these helpers are conditional today and light up
// the inline amber badges / flagged counts the moment a payload carries the
// documented shape - until then they degrade to empty/zero honestly.
export interface OutOfRangeRow {
  test: string;
  value: string;
  status: "below_range" | "above_range";
}

const OUT_OF_RANGE_STATUSES = new Set(["below_range", "above_range"]);

export function entryFlagRows(entry: RecordEntryView): OutOfRangeRow[] {
  if (entry.entry_type !== "lab_report") return [];
  const raw = entry.payload.results;
  if (!Array.isArray(raw)) return [];
  const rows: OutOfRangeRow[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const row = item as Record<string, unknown>;
    if (typeof row.status !== "string") continue;
    if (!OUT_OF_RANGE_STATUSES.has(row.status)) continue;
    if (typeof row.test !== "string" || row.test.length === 0) continue;
    if (typeof row.value !== "string" || row.value.length === 0) continue;
    rows.push({
      test: row.test,
      value: row.value,
      status: row.status as OutOfRangeRow["status"],
    });
  }
  return rows;
}

export interface LabFlagSummary {
  /** lab entries carrying at least one out-of-range value. */
  entries: number;
  /** total out-of-range rows across those entries. */
  values: number;
}

export function flaggedValues(entries: RecordEntryView[]): LabFlagSummary {
  let flaggedEntries = 0;
  let flaggedRowCount = 0;
  for (const entry of entries) {
    const rows = entryFlagRows(entry);
    if (rows.length > 0) {
      flaggedEntries += 1;
      flaggedRowCount += rows.length;
    }
  }
  return { entries: flaggedEntries, values: flaggedRowCount };
}

// The delivered-rule: a prescription is delivered only when its documented
// status is exactly "delivered". Anything else (including an absent status)
// stays issued - the honest default until the backend produces one. Centralized
// here so the snapshot/rail "n issued" count, the entry badge, and anything
// else that answers the same question can never drift apart.
export function isDeliveredPrescription(entry: RecordEntryView): boolean {
  return (
    entry.entry_type === "prescription" &&
    payloadString(entry, "status") === "delivered"
  );
}

// PROTO-3.1 (#511): prescriptions still outstanding. Each entry is judged by
// the same rule as the card badge above so the strip/rail never contradicts a
// tile's delivered/issued badge.
export function issuedPrescriptionCount(entries: RecordEntryView[]): number {
  let issued = 0;
  for (const entry of entries) {
    if (entry.entry_type !== "prescription") continue;
    if (!isDeliveredPrescription(entry)) issued += 1;
  }
  return issued;
}

export type BadgeTone = "success" | "accent" | "warm" | "muted";

// Tailwind chip classes per BadgeTone - the single tone map shared by every
// surface that renders a timeline entry badge (My Record timeline, the recent
// activity card on the home). One source so a tone retune never drifts between
// the preview and the timeline it previews.
export const BADGE_TONE: Record<BadgeTone, string> = {
  success: "bg-success-soft text-success-text",
  accent: "bg-accent-soft text-accent-strong",
  warm: "bg-warm-soft text-txt-sub",
  muted: "bg-hairline-soft text-txt-muted",
};

// PROTO-3.1 (#511): per-type card anatomy theme - a tinted left-edge stripe
// plus an icon-chip tint per entry type so the timeline scans by color.
// Tones reuse the existing semantic token palette (same mapping as the card
// anatomy in the binding prototype: warm = consultation, success = rx, accent
// = lab, muted = metric + settlement).
export interface EntryTone {
  stripe: string;
  chip: string;
}

export const ENTRY_TONE: Record<RecordEntryType, EntryTone> = {
  consultation: {
    stripe: "border-l-warm",
    chip: "bg-warm-soft text-warm",
  },
  prescription: {
    stripe: "border-l-success",
    chip: "bg-success-soft text-success-text",
  },
  lab_report: {
    stripe: "border-l-accent",
    chip: "bg-accent-soft text-accent-strong",
  },
  metric: {
    stripe: "border-l-hairline",
    chip: "bg-hairline-soft text-txt-muted",
  },
  settlement: {
    stripe: "border-l-hairline",
    chip: "bg-hairline-soft text-txt-muted",
  },
};

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
  options: { omitOccurredAt?: boolean } = {},
): EntryCard {
  // #509: the home's Recent activity preview renders the real date once, in
  // its own right-hand "when" column, so the subtitle job loses the
  // occurred-at there. The record timeline keeps the folded date by default -
  // existing call sites are unchanged unless they opt in.
  const { omitOccurredAt = false } = options;
  const date = formatOccurredAt(entry.occurred_at, lang);
  const parts: string[] = [];

  switch (entry.entry_type) {
    case "consultation":
      if (!omitOccurredAt) parts.push(date);
      return {
        icon: "\u{1FA7A}",
        title: t.badge.consultation,
        subtitle: parts.join(" \u00b7 ") || null,
        badge: { label: t.badge.consultation, tone: "warm" },
      };
    case "prescription": {
      const prescriptionId = payloadNumber(entry, "prescription_id");
      if (prescriptionId !== null) parts.push(`Rx #${prescriptionId}`);
      if (!omitOccurredAt) parts.push(date);
      const delivered = isDeliveredPrescription(entry);
      return {
        icon: "\u{1F48A}",
        title: t.badge.prescription,
        subtitle: parts.join(" \u00b7 ") || null,
        badge: delivered
          ? { label: t.badge.delivered, tone: "success" }
          : { label: t.badge.issued, tone: "warm" },
      };
    }
    case "lab_report": {
      const orderId = payloadNumber(entry, "order_id");
      if (orderId !== null) parts.push(`${t.filedFromBooking} #${orderId}`);
      if (!omitOccurredAt) parts.push(date);
      return {
        icon: "\u{1F9EA}",
        title: payloadString(entry, "filename") ?? t.badge.labReport,
        subtitle: parts.join(" \u00b7 ") || null,
        badge: { label: t.badge.labReport, tone: "accent" },
      };
    }
    case "metric":
      if (!omitOccurredAt) parts.push(date);
      return {
        icon: "\u{1F4C8}",
        title: t.badge.metric,
        subtitle: parts.join(" \u00b7 ") || null,
        badge: { label: t.badge.metric, tone: "muted" },
      };
    case "settlement": {
      const amountPaise = payloadNumber(entry, "amount_paise");
      if (amountPaise !== null)
        parts.push(`\u20b9${(amountPaise / 100).toFixed(2)}`);
      const orderRef = payloadString(entry, "order_ref");
      if (orderRef !== null) parts.push(`#${orderRef}`);
      if (!omitOccurredAt) parts.push(date);
      return {
        icon: "\u{1F4B3}",
        title: t.badge.settlement,
        subtitle: parts.join(" \u00b7 ") || null,
        badge: { label: t.badge.settlement, tone: "muted" },
      };
    }
  }
}
