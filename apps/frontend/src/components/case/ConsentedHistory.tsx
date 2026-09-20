"use client";

// PHASE-8.1 T13 (#451): the doctor's consented-history read inside the case
// workspace. Fetches the patient's record scope through the partner
// consented-read surface (POST /v1/records/consented-read via
// readConsentedHistory), which fail-closes on a missing/revoked grant so a
// denial renders as an empty-history note, never a crash. The scope follows
// the standing grant recorded at pick-a-doctor (#443): consultations.

import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import {
  readConsentedHistory,
  type RecordEntryType,
  type RecordTimeline,
} from "@/lib/record/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export const HISTORY_SCOPE = "consultations";

type HistoryStatus = "idle" | "loading" | "ready" | "error";

function entryBadgeLabel(
  entryType: string,
  t: Dictionary["record"]["badge"],
): string {
  switch (entryType) {
    case "consultation":
    case "prescription":
    case "metric":
    case "settlement":
      return t[entryType];
    case "lab_report":
      return t.labReport;
    default:
      return entryType;
  }
}

export function formatHistoryDate(iso: string, lang: "en" | "hi"): string {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

export function ConsentedHistory({
  patientId,
  partnerId,
}: {
  patientId: number;
  partnerId: number;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const badgeT = STRINGS[lang].record.badge;

  const [timeline, setTimeline] = useState<RecordTimeline | null>(null);
  const [status, setStatus] = useState<HistoryStatus>("idle");
  const [traceId, setTraceId] = useState<string | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(() => {
    setStatus("loading");
    readConsentedHistory({
      patient_id: patientId,
      scope: HISTORY_SCOPE,
      counterparty_id: partnerId,
      counterparty_type: "doctor",
    })
      .then((result) => {
        setTimeline(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        setTraceId(err instanceof ApiError ? err.traceId : undefined);
        setStatus("error");
      });
  }, [patientId, partnerId]);

  useEffect(() => {
    setStatus("loading");
    setTimeline(null);
    load();
  }, [load, attempt]);

  if (status === "loading" || status === "idle") {
    return (
      <div data-testid="history-loading" className="space-y-2">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div data-testid="history-error">
        <p className="text-sm text-txt-muted">{t.historyLoadFail}</p>
        {traceId != null && (
          <p
            className="mt-1 text-xs text-txt-muted"
            data-testid="history-trace"
          >
            Trace: {traceId}
          </p>
        )}
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          data-testid="history-retry"
          className="mt-2 inline-flex items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          {STRINGS[lang].doctorConsole.retry}
        </button>
      </div>
    );
  }

  if (timeline === null || timeline.entries.length === 0) {
    return <EmptyState title={t.historyEmpty} />;
  }

  return (
    <ul className="space-y-2" data-testid="history-list">
      {timeline.entries.map((entry) => (
        <li
          key={entry.entry_id}
          data-testid="history-entry"
          className="flex items-center justify-between rounded-lg border border-hairline bg-surface px-4 py-3"
        >
          <span className="text-sm font-medium text-txt">
            {entryBadgeLabel(entry.entry_type as RecordEntryType, badgeT)}
          </span>
          <span className="text-xs text-txt-muted">
            {formatHistoryDate(entry.occurred_at, lang)}
          </span>
        </li>
      ))}
    </ul>
  );
}
