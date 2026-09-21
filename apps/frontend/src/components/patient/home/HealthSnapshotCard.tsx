"use client";

// #507: the home "Health snapshot" card that fills the sticky right rail
// (PROTO-2.7 binding, shell-light.html `health.*`). Honest by construction:
// the card picks the newest metric and newest lab-report entries from the
// own-record timeline (entry_type === "metric" | "lab_report", newest first)
// and renders only what they actually document - never a fabricated number.
// When either slot has no entry, it renders the Soon teaser keyed to the
// metrics (P12) and lab-report (P9) phasing instead of guessing at a value.
// It reads ONLY the own-record timeline client, like RecentActivityCard; a
// record that could not be read renders nothing at all (never a calm "Soon"
// teaser, which would lie about why the slot is empty - the record page's
// honesty rule), with the failure logged.

import { useEffect, useMemo, useState } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { fetchOwnRecord, type RecordEntryView } from "@/lib/record/api";
import {
  describeEntry,
  formatOccurredAt,
  sortTimelineDesc,
} from "@/lib/record/timelineView";

// The latest-report tile: rendered through the shared My Record describe
// helper so its icon/title stay exactly consistent with the timeline. The
// title is the filed filename when present, the record.badge.labReport label
// otherwise; the "when" is the entry's real clinical time - never a
// substituted value.
function ReportTile({ entry }: { entry: RecordEntryView }) {
  const { lang } = useLang();
  const recordT = STRINGS[lang].record;
  const card = describeEntry(entry, recordT, lang);
  return (
    <div
      data-testid="health-report"
      className="flex min-w-0 items-center gap-2.5 rounded-lg border border-hairline px-3 py-2"
    >
      <span aria-hidden="true" className="shrink-0">
        {card.icon}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-txt">
        {card.title}
      </span>
      <span className="shrink-0 text-xs text-txt-muted">
        {formatOccurredAt(entry.occurred_at, lang)}
      </span>
    </div>
  );
}

export function HealthSnapshotCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].health;
  // null = resolving the timeline; [] = a record with no snapshot data yet.
  const [entries, setEntries] = useState<RecordEntryView[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchOwnRecord()
      .then((record) => {
        if (active) setEntries(record.entries);
      })
      .catch((err: unknown) => {
        // A failed read never passes itself off as an honest "Soon" teaser -
        // the slot would claim no data exists when the read simply failed.
        console.warn(
          "[health-snapshot] record fetch failed, hiding card:",
          err,
        );
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  // Derive, never invent: the newest of each snapshot slot by the timeline's
  // reverse-chronological order. Entries arrive sorted, but the defensive sort
  // keeps the pick correct if a caller hands unordered data.
  const { metric, report } = useMemo(() => {
    if (entries === null) return { metric: null, report: null };
    const sorted = sortTimelineDesc(entries);
    return {
      metric: sorted.find((entry) => entry.entry_type === "metric") ?? null,
      report: sorted.find((entry) => entry.entry_type === "lab_report") ?? null,
    };
  }, [entries]);

  // Completely absent when the source could not be read - never a fake "Soon"
  // snapshot (RecentActivityCard's absent-on-unreadable pattern).
  if (failed) return null;

  return (
    <section
      data-testid="health-snapshot"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <h2 className="text-[1.05rem] font-semibold text-txt">{t.title}</h2>

      {entries === null ? (
        <div
          data-testid="health-loading"
          role="status"
          aria-label={t.loading}
          className="mt-3 space-y-2"
        >
          {[0, 1, 2].map((row) => (
            <div
              key={row}
              className="h-14 animate-pulse rounded-lg bg-hairline-soft/60"
            />
          ))}
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          {metric ? (
            <div
              data-testid="health-metric"
              className="rounded-lg border border-hairline px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-txt-muted">
                  {t.metricLabel}
                </span>
                <span className="rounded-full border border-dashed border-hairline bg-hairline-soft px-2 py-0.5 text-[0.6875rem] font-medium tracking-wide text-txt-muted uppercase">
                  {t.trackSoon}
                </span>
              </div>
              <p className="mt-0.5 text-sm font-semibold text-txt">
                {formatOccurredAt(metric.occurred_at, lang)}
              </p>
            </div>
          ) : (
            <div
              data-testid="health-metric-teaser"
              className="space-y-1 rounded-lg bg-hairline-soft/60 px-3 py-2.5"
            >
              <strong className="block text-sm font-semibold text-txt">
                {t.teaser}
              </strong>
              <p className="text-xs text-txt-muted">{t.teaserBody}</p>
              <span className="inline-block rounded-full border border-dashed border-hairline bg-hairline-soft px-2 py-0.5 text-[0.6875rem] font-medium tracking-wide text-txt-muted uppercase">
                {t.soon}
              </span>
            </div>
          )}

          <div
            className="space-y-2 border-t border-hairline pt-2"
            data-testid="health-reports"
          >
            <span className="text-xs font-medium text-txt-muted">
              {t.reportsTitle}
            </span>
            {report ? (
              <ReportTile entry={report} />
            ) : (
              <p
                data-testid="health-report-teaser"
                className="text-xs text-txt-muted"
              >
                {t.reportSoon}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
