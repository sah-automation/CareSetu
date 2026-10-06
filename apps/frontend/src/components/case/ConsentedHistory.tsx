"use client";

// PHASE-8.1 T13 (#451): the doctor's consented-history read inside the case
// workspace. Fetches the patient's record scope through the partner
// consented-read surface (POST /v1/records/consented-read via
// readConsentedHistory), which fail-closes on a missing/revoked grant so a
// denial renders as an empty-history note, never a crash. The scope follows
// the standing grant recorded at pick-a-doctor (#443): consultations.
//
// #658 (one history read, #645 US-62..65): the timeline prop is a three-state
// contract, because the three states mean three different things:
//   undefined - no projection was supplied, so this component performs its
//               own consented read (unchanged `consultations` scope);
//   an array  - render exactly what was given, no read of our own, so the
//               case workspace and the patient profile cannot disagree;
//   null      - the patient has not shared this section: render the calm
//               not-shared note and fetch nothing. Routing null through the
//               error branch would put a trace id and a retry button on a
//               screen where retrying cannot help, so it never reaches it.

import { useCallback, useEffect, useState } from "react";

import { NotSharedCard } from "@/components/doctor/NotSharedCard";
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
  timeline,
}: {
  patientId: number;
  partnerId: number;
  timeline?: RecordTimeline | null;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const badgeT = STRINGS[lang].record.badge;
  const notSharedT = STRINGS[lang].doctorPatients;

  const [fetchedTimeline, setFetchedTimeline] = useState<RecordTimeline | null>(
    null,
  );
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
        setFetchedTimeline(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        setTraceId(err instanceof ApiError ? err.traceId : undefined);
        setStatus("error");
      });
  }, [patientId, partnerId]);

  useEffect(() => {
    // A supplied timeline - an array or an explicit null - is the answer
    // already; only the propless call site performs the consented read.
    if (timeline !== undefined) return;
    setFetchedTimeline(null);
    load();
  }, [load, attempt, timeline]);

  if (timeline === null) {
    return (
      <NotSharedCard
        title={notSharedT.notSharedTitle}
        body={notSharedT.notSharedBody}
      />
    );
  }

  if (timeline === undefined) {
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
  }

  const shown = timeline ?? fetchedTimeline;

  if (shown === null || shown.entries.length === 0) {
    return (
      // Same density as the patient profile's consultation-history empty card
      // (#645 US-64): the workspace says "No history yet." but presents it in
      // the same calm, bordered quiet state, so the two surfaces still read
      // the same when there is nothing to read.
      <div
        data-testid="history-empty"
        className="rounded-lg border border-hairline bg-surface px-4 py-4 text-sm text-txt-muted"
      >
        {t.historyEmpty}
      </div>
    );
  }

  // Entry markup mirrors the patient profile's consultation-history block
  // (#645 US-64): same accent badge, same date, same fields per entry, so
  // moving between the two doctor surfaces teaches nothing new.
  return (
    <ul className="space-y-2" data-testid="history-list">
      {shown.entries.map((entry, index) => (
        <li
          key={entry.entry_id ?? index}
          data-testid="history-entry"
          className="flex items-center justify-between gap-3 rounded-md border border-hairline bg-surface px-3 py-2"
        >
          <span
            data-testid="history-entry-type"
            className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
          >
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
