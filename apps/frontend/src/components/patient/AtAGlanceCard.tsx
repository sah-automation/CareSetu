"use client";

// MOD-003 (record timeline) / FEAT-003 (patient trust view): #666/#671 the
// "At a glance" counts card, extracted from the record page rail (#666) and
// composed into the homepage rail (#671) so both surfaces render one summary
// from payload-derived counts - never a second source of truth.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import type { LabFlagSummary, RecordCounts } from "@/lib/record/timelineView";

export type AtAGlanceCardProps = {
  counts: RecordCounts;
  issuedCount: number;
  flagged: LabFlagSummary;
};

export function AtAGlanceCard({
  counts,
  issuedCount,
  flagged,
}: AtAGlanceCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].record;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
      data-testid="record-rail-summary"
    >
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-txt-muted">
        {t.summaryLabel}
      </h2>
      <ul className="flex flex-col gap-1">
        {[
          {
            label: t.filter.consultation,
            value: counts.consultation,
            sub: null as null | string,
          },
          {
            label: t.filter.prescription,
            value: counts.prescription,
            sub: t.snapshotIssued(issuedCount),
          },
          {
            label: t.filter.labReport,
            value: counts.lab_report,
            sub:
              flagged.entries > 0 ? t.snapshotFlagged(flagged.entries) : null,
          },
          {
            label: t.filter.metric,
            value: counts.metric,
            sub: null,
          },
        ].map((row) => (
          <li
            key={row.label}
            className="flex items-center justify-between gap-2 border-b border-hairline-soft py-2 text-[0.9375rem] text-txt-sub last:border-0"
          >
            <span>{row.label}</span>
            <span className="flex items-center gap-2 text-[1.125rem] font-bold text-txt">
              {row.value}
              {row.sub && (
                <span className="text-[0.8125rem] font-medium text-txt-muted">
                  {row.sub}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {flagged.values > 0 && (
        <p
          className="mt-3 text-xs text-txt-muted"
          data-testid="record-rail-flag-footnote"
        >
          {t.outOfRange.footnote(flagged.values)}
        </p>
      )}
    </section>
  );
}
