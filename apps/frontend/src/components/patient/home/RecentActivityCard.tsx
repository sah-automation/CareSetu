"use client";

// #506: the home "Recent activity" card (PROTO-2.7 binding, shell-light.html
// `recent.*`). Shows the top few events of the patient's record timeline -
// consultations, prescriptions, lab results, metric logs - rendered through
// the shared My Record describe/format helper, so per-type badges and copy
// stay exactly consistent with the timeline. It reads ONLY the own-record
// timeline client (`GET /v1/records`); the access-audit client is never
// imported, so access-history reads can never leak into recent activity (the
// two are separate data sources by construction). A record with nothing on it
// yet renders the friendly empty state. A failed read renders nothing at all
// (never a calm "no activity yet" empty state - the record page's honesty
// rule), with the failure logged. "View all" targets the live My Record route
// from the patient nav config.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { PATIENT_RECORD_ROUTE } from "@/components/dashboard/nav-config";
import { EmptyState } from "@/components/layout/EmptyState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { fetchOwnRecord, type RecordEntryView } from "@/lib/record/api";
import {
  BADGE_TONE,
  describeEntry,
  sortTimelineDesc,
} from "@/lib/record/timelineView";
import { cn } from "@/lib/utils";

// The card is a preview, never the full timeline: the top few events after the
// timeline's reverse-chronological sort, with View all for the rest.
export const RECENT_ACTIVITY_MAX = 3;

export function RecentActivityCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].recent;
  const recordT = STRINGS[lang].record;
  // null = resolving the timeline; [] = a record with no activity yet.
  const [entries, setEntries] = useState<RecordEntryView[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchOwnRecord()
      .then((record) => {
        if (active) setEntries(record.entries);
      })
      .catch((err: unknown) => {
        // Third-party-integration standard + record-page honesty rule: a failed
        // read never renders as a calm "no activity" empty state - it would lie
        // about why the card is empty. The preview stays absent, with the
        // failure logged so it stays distinguishable from a truly empty record.
        console.warn(
          "[recent-activity] record fetch failed, hiding card:",
          err,
        );
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const visible = useMemo(() => {
    if (entries === null) return [];
    return sortTimelineDesc(entries).slice(0, RECENT_ACTIVITY_MAX);
  }, [entries]);

  // Completely absent when the source could not be read - never a fake-empty
  // preview (ActionRequiredCard's absent-on-unreadable pattern).
  if (failed) return null;

  return (
    <section
      data-testid="recent-activity"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h2 className="text-[1.05rem] font-semibold text-txt">{t.title}</h2>
        <Link
          href={PATIENT_RECORD_ROUTE}
          data-testid="recent-view-all"
          className="text-sm font-medium text-accent-strong hover:underline"
        >
          {t.all}
        </Link>
      </div>

      {entries === null ? (
        <div
          data-testid="recent-loading"
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
      ) : visible.length === 0 ? (
        <div data-testid="recent-empty" className="mt-3">
          <EmptyState title={t.empty} body={t.emptyBody} />
        </div>
      ) : (
        <ul className="mt-3 space-y-2" data-testid="recent-list">
          {visible.map((entry) => {
            const card = describeEntry(entry, recordT, lang);
            return (
              <li key={entry.entry_id}>
                <div
                  data-testid={`recent-entry-${entry.entry_id}`}
                  className="flex min-h-11 min-w-0 items-center gap-2.5 rounded-lg border border-hairline px-3 py-2"
                >
                  <span aria-hidden="true" className="shrink-0">
                    {card.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-txt">
                      {card.title}
                    </span>
                    {card.subtitle && (
                      <span className="block truncate text-xs text-txt-muted">
                        {card.subtitle}
                      </span>
                    )}
                  </span>
                  {card.badge && (
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                        BADGE_TONE[card.badge.tone],
                      )}
                    >
                      {card.badge.label}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
