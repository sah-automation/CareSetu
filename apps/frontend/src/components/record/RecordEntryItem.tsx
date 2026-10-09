// #677 (parent #673): the shared record-entry renderer. One presentational
// <li> that renders a consultation-history entry - its type tag and date, plus
// the per-type detail carried in the entry payload. The patient-detail
// consultation history (#680) and the case workspace History tab via
// ConsentedHistory (#682) adopt it, replacing their two near-duplicate
// tag-only markups, so the two doctor surfaces cannot disagree (US-33).
//
// It takes already-fetched data plus the `record` label bundle and performs no
// read, so it introduces no production seam. The payload is a loose bag: every
// field is read defensively and any entry whose payload carries no renderable
// detail falls back to type-tag-plus-date, never a half card (US-23/24).
//
// Per type: prescription shows status, one line per medicine (name, dose,
// frequency, duration) and the attributed doctor; lab_report shows the file
// name and order reference; settlement shows the amount (formatted from paise)
// and order reference. consultation, metric, unknown and empty payloads keep
// the scan line only.

import type { Dictionary } from "@/lib/i18n/dictionaries";
import type { RecordEntryView } from "@/lib/record/api";
import {
  attributedDoctorName,
  isDeliveredPrescription,
  medicineFields,
  prescriptionItems,
  TYPE_BADGE_KEY,
  type PrescriptionItem,
} from "@/lib/record/timelineView";
import { formatFeePaise } from "@/components/pick/DoctorPickCard";

type Lang = "en" | "hi";

export interface RecordEntryItemProps {
  entry: RecordEntryView;
  labels: Dictionary["record"];
  lang: Lang;
  /** Root test id; derived ids use `-type`, `-detail` and `-medicine`. */
  testId?: string;
}

// Unknown entry types (a payload the vocabulary does not yet name) fall back
// to the raw type string, the same honest default the tag markup used before.
function entryTypeLabel(
  entry: RecordEntryView,
  labels: Dictionary["record"],
): string {
  const key = TYPE_BADGE_KEY[entry.entry_type];
  return key !== undefined ? labels.badge[key] : entry.entry_type;
}

// Keeps the scan line honest for a malformed timestamp: an unparseable
// `occurred_at` renders verbatim rather than "Invalid Date".
function formatEntryDate(iso: string, lang: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function payloadString(entry: RecordEntryView, key: string): string | null {
  const value = entry.payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function payloadNumber(entry: RecordEntryView, key: string): number | null {
  const value = entry.payload[key];
  return typeof value === "number" ? value : null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="shrink-0 text-txt-muted">{label}</dt>
      <dd className="min-w-0 break-words text-txt-sub">{value}</dd>
    </div>
  );
}

function MedicineLines({
  items,
  labels,
  testId,
}: {
  items: PrescriptionItem[];
  labels: Dictionary["record"];
  testId: string;
}) {
  return (
    <ul className="mt-1 space-y-1">
      {items.map((item, index) => {
        // Every documented field keeps its own label - a present dose,
        // frequency or duration is never silently dropped from the line.
        const fields = medicineFields(item, labels.detail.medicine);
        return (
          <li key={index} data-testid={`${testId}-medicine`}>
            <span className="font-medium text-txt">{item.name}</span>
            {fields.length > 0 && (
              <span>
                {" - "}
                {fields
                  .map((field) => `${field.label}: ${field.value}`)
                  .join(" \u00b7 ")}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function EntryDetail({
  entry,
  labels,
  testId,
}: {
  entry: RecordEntryView;
  labels: Dictionary["record"];
  testId: string;
}) {
  switch (entry.entry_type) {
    case "prescription": {
      const items = prescriptionItems(entry);
      const doctor = attributedDoctorName(entry);
      const status = payloadString(entry, "status");
      if (items.length === 0 && doctor === null && status === null) return null;
      return (
        <dl data-testid={`${testId}-detail`} className="mt-2 space-y-1 text-xs">
          {status !== null && (
            <Row
              label={labels.history.status}
              value={
                isDeliveredPrescription(entry)
                  ? labels.badge.delivered
                  : labels.badge.active
              }
            />
          )}
          {items.length > 0 && (
            <div>
              <dt className="text-txt-muted">{labels.history.medicines}</dt>
              <dd>
                <MedicineLines items={items} labels={labels} testId={testId} />
              </dd>
            </div>
          )}
          {doctor !== null && (
            <Row label={labels.prescribedBy} value={doctor} />
          )}
        </dl>
      );
    }
    case "lab_report": {
      const filename = payloadString(entry, "filename");
      const orderId = payloadNumber(entry, "order_id");
      if (filename === null && orderId === null) return null;
      return (
        <dl data-testid={`${testId}-detail`} className="mt-2 space-y-1 text-xs">
          {filename !== null && (
            <Row label={labels.history.file} value={filename} />
          )}
          {orderId !== null && (
            <Row label={labels.history.order} value={`#${orderId}`} />
          )}
        </dl>
      );
    }
    case "settlement": {
      const amountPaise = payloadNumber(entry, "amount_paise");
      const orderRef = payloadString(entry, "order_ref");
      if (amountPaise === null && orderRef === null) return null;
      return (
        <dl data-testid={`${testId}-detail`} className="mt-2 space-y-1 text-xs">
          {amountPaise !== null && (
            <Row
              label={labels.history.amount}
              value={formatFeePaise(amountPaise)}
            />
          )}
          {orderRef !== null && (
            <Row label={labels.history.order} value={`#${orderRef}`} />
          )}
        </dl>
      );
    }
    default:
      return null;
  }
}

export function RecordEntryItem({
  entry,
  labels,
  lang,
  testId = "record-entry",
}: RecordEntryItemProps) {
  return (
    <li
      data-testid={testId}
      className="rounded-md border border-hairline bg-surface px-3 py-2"
    >
      <div className="flex items-center justify-between gap-3">
        <span
          data-testid={`${testId}-type`}
          className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
        >
          {entryTypeLabel(entry, labels)}
        </span>
        <span className="text-xs text-txt-muted">
          {formatEntryDate(entry.occurred_at, lang)}
        </span>
      </div>
      <EntryDetail entry={entry} labels={labels} testId={testId} />
    </li>
  );
}
