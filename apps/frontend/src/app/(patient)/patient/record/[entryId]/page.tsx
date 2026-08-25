"use client";

// PHASE-3 T8 (#217): Entry detail screen (blueprint section 5.5, binding
// prototype record-entry.html). Opens any record entry and shows where it
// came from (filer identity + filed-at timestamp), who has seen it (egress
// trail from real consent data), and - when disclosed - the consent lineage
// + version that authorized the disclosure. Lab-result entries render as a
// plain value table with block-level horizontal scroll on phones. All copy
// is fully bilingual EN/HI via the record.detail dictionary surface.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { SoonBadge } from "@/components/dashboard/NavItemLink";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import {
  fetchOwnRecord,
  RecordApiError,
  type RecordEntryView,
} from "@/lib/record/api";
import { describeEntry, formatOccurredAt } from "@/lib/record/timelineView";
import { fetchEgressLog, type EgressLogEntry } from "@/lib/consent/api";

type LoadStatus = "loading" | "ready" | "error" | "not-found";

interface LabResult {
  test: string;
  value: string;
  range: string;
  status: "in_range" | "below_range" | "above_range";
}

function payloadString(entry: RecordEntryView, key: string): string | null {
  const value = entry.payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function payloadNumber(entry: RecordEntryView, key: string): number | null {
  const value = entry.payload[key];
  return typeof value === "number" ? value : null;
}

function payloadResults(entry: RecordEntryView): LabResult[] | null {
  const raw = entry.payload.results;
  if (!Array.isArray(raw)) return null;
  return raw.filter(
    (r): r is LabResult =>
      typeof r === "object" &&
      r !== null &&
      typeof (r as Record<string, unknown>).test === "string" &&
      typeof (r as Record<string, unknown>).value === "string",
  );
}

const STATUS_TONE: Record<string, string> = {
  in_range: "bg-success-soft text-success-text",
  below_range: "bg-warm-soft text-warm-text",
  above_range: "bg-warm-soft text-warm-text",
};

export default function EntryDetailPage() {
  const params = useParams<{ entryId: string }>();
  const entryId = Number(params.entryId);

  const { lang } = useLang();
  const t = STRINGS[lang].record;
  const td = t.detail;

  const [entry, setEntry] = useState<RecordEntryView | null>(null);
  const [egressTrail, setEgressTrail] = useState<EgressLogEntry[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([fetchOwnRecord(), fetchEgressLog()])
      .then(([timeline, egressLog]) => {
        const found = timeline.entries.find((e) => e.entry_id === entryId);
        if (!found) {
          setStatus("not-found");
          return;
        }
        setEntry(found);
        setEgressTrail(
          egressLog.items.filter((item) =>
            item.disclosed_entry_ids.includes(entryId),
          ),
        );
        setStatus("ready");
        setBannerOpen(false);
      })
      .catch((error: unknown) => {
        setErrorTraceId(
          error instanceof RecordApiError ? error.traceId : undefined,
        );
        setStatus("error");
        setBannerOpen(true);
      });
  }, [entryId]);

  useEffect(() => {
    load();
  }, [load]);

  const card = useMemo(
    () => (entry ? describeEntry(entry, t, lang) : null),
    [entry, t, lang],
  );

  const labResults = useMemo(
    () => (entry ? payloadResults(entry) : null),
    [entry],
  );

  const filedDate = useMemo(
    () => (entry ? formatOccurredAt(entry.occurred_at, lang) : ""),
    [entry, lang],
  );

  const orderId = useMemo(
    () => (entry ? payloadNumber(entry, "order_id") : null),
    [entry],
  );

  const filename = useMemo(
    () => (entry ? payloadString(entry, "filename") : null),
    [entry],
  );

  const consentEntry = egressTrail.length > 0 ? egressTrail[0] : null;

  const breadcrumbs = useMemo(
    () => [
      { label: t.title, href: "/patient/record" },
      { label: card?.title ?? td.notFound },
    ],
    [t.title, card?.title, td.notFound],
  );

  return (
    <>
      <PageHeader
        title={card?.title ?? ""}
        description={
          <>
            {card?.badge && (
              <span
                className={cn(
                  "mr-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                  card.badge.tone === "accent"
                    ? "bg-accent-soft text-accent-strong"
                    : card.badge.tone === "success"
                      ? "bg-success-soft text-success-text"
                      : card.badge.tone === "warm"
                        ? "bg-warm-soft text-txt-sub"
                        : "bg-hairline-soft text-txt-muted",
                )}
              >
                {card.badge.label}
              </span>
            )}
            {td.filedOn} {filedDate}
            {orderId !== null && (
              <>
                {" "}
                \u00b7 {td.bookingRef} #{orderId}
              </>
            )}
          </>
        }
        breadcrumbs={breadcrumbs}
      />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message={td.loadError}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {status === "loading" ? (
        <div className="space-y-3" data-testid="entry-detail-loading">
          <div className="h-20 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
          <div className="h-32 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
        </div>
      ) : status === "error" ? null : status === "not-found" ? (
        <div
          className="rounded-lg border border-hairline bg-surface p-6 text-center"
          data-testid="entry-detail-not-found"
        >
          <p className="font-medium text-txt">{td.notFound}</p>
        </div>
      ) : entry ? (
        <>
          {/* Source + Consent reference card */}
          <section
            className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
            data-testid="entry-source-card"
          >
            <span className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
              {td.sourceHeading}
            </span>
            <div className="mt-2 flex items-start gap-3">
              <span
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent-strong"
                aria-hidden="true"
              >
                {filename
                  ? filename.slice(0, 2).toUpperCase()
                  : card?.title?.slice(0, 2).toUpperCase() ?? "??"}
              </span>
              <div>
                <strong className="text-base">
                  {filename ?? card?.title ?? td.sourceHeading}
                </strong>{" "}
                <span className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
                  {td.verified}
                </span>
              </div>
            </div>

            {consentEntry && (
              <>
                <hr className="my-3 border-hairline" />
                <span className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                  {td.consentHeading}
                </span>
                <p className="mt-1 text-sm text-txt">
                  {td.consentLine(
                    consentEntry.lineage_ref,
                    consentEntry.version,
                    formatOccurredAt(consentEntry.disclosed_at, lang),
                  )}
                </p>
                <Link
                  href="/patient/consent-log"
                  className="mt-1 text-sm font-medium text-accent-strong hover:underline"
                  data-testid="consent-log-link"
                >
                  {td.consentLink}
                </Link>
              </>
            )}
          </section>

          {/* Lab results table (block-level scroll on phones per PLAN.md) */}
          {entry.entry_type === "lab_report" && labResults && (
            <section
              className="mt-3 rounded-lg border border-hairline bg-surface p-4 shadow-card"
              data-testid="entry-results-table"
            >
              <h2 className="text-base font-semibold text-txt">
                {td.resultsHeading}
              </h2>
              <div className="mt-2 overflow-x-auto">
                <table
                  className="w-full text-sm"
                  data-testid="lab-results-table"
                >
                  <thead>
                    <tr className="border-b border-hairline text-left text-xs font-semibold uppercase tracking-wide text-txt-muted">
                      <th className="pb-2 pr-4">{td.resultsThTest}</th>
                      <th className="pb-2 pr-4">{td.resultsThValue}</th>
                      <th className="pb-2 pr-4">{td.resultsThRange}</th>
                      <th className="pb-2">{td.resultsThStatus}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {labResults.map((row, idx) => (
                      <tr
                        key={idx}
                        className="border-b border-hairline last:border-0"
                      >
                        <td className="py-2 pr-4 text-txt">{row.test}</td>
                        <td className="py-2 pr-4 font-semibold text-txt">
                          {row.value}
                        </td>
                        <td className="py-2 pr-4 text-txt-muted">
                          {row.range}
                        </td>
                        <td className="py-2">
                          <span
                            className={cn(
                              "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                              STATUS_TONE[row.status] ??
                                "bg-hairline-soft text-txt-muted",
                            )}
                            data-testid={`lab-status-${idx}`}
                          >
                            {row.status === "in_range"
                              ? td.resultsStatusInRange
                              : row.status === "below_range"
                                ? td.resultsStatusBelowRange
                                : td.resultsStatusAboveRange}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-txt-muted">{td.resultsNote}</p>
            </section>
          )}

          {/* Egress trail - only renders when disclosures exist */}
          {egressTrail.length > 0 && (
            <section
              className="mt-3 rounded-lg border border-hairline bg-surface p-4 shadow-card"
              data-testid="entry-egress-trail"
            >
              <strong className="text-base">{td.egressHeading}</strong>
              <ul className="mt-2 space-y-2">
                {egressTrail.map((item) => (
                  <li
                    key={item.egress_id}
                    className="flex items-start gap-2 text-sm text-txt"
                    data-testid={`egress-entry-${item.egress_id}`}
                  >
                    <span aria-hidden="true" className="mt-0.5">
                      &#128065;
                    </span>
                    <span>
                      {item.counterparty_type}{" "}
                      <span className="text-txt-muted">
                        \u00b7 {item.counterparty_id}
                      </span>{" "}
                      <span className="text-txt-muted">
                        \u00b7 {formatOccurredAt(item.disclosed_at, lang)}
                      </span>{" "}
                      <span className="text-txt-muted">
                        \u00b7 #{item.lineage_ref} v{item.version}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Action bar */}
          <div className="mt-3 flex gap-3" data-testid="entry-detail-actions">
            <Link
              href="/patient/consent-grant"
              className="flex-1 rounded-lg bg-accent px-4 py-2.5 text-center text-sm font-medium text-on-accent hover:bg-accent/90"
              data-testid="share-entry-btn"
            >
              {td.shareEntry}
            </Link>
            <button
              type="button"
              disabled
              aria-disabled="true"
              tabIndex={-1}
              className="flex-1 cursor-not-allowed rounded-lg border border-hairline bg-surface px-4 py-2.5 text-sm font-medium text-txt-muted opacity-70"
              data-testid="download-pdf-btn"
            >
              {td.downloadPdf} <SoonBadge />
            </button>
          </div>
        </>
      ) : null}
    </>
  );
}
