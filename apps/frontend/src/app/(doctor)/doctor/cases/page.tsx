"use client";

// PHASE-8.1 T8 (#483): doctor console Cases index - the live destination
// behind the un-sooned Cases tab. Renders the doctor's open care cases from
// the existing open-cases read (listOpenCases), each linking into its case
// workspace (cases/[caseId]). An alternative entry to the landing page's
// open-cases section (US-8); patients/profile tabs stay coming-soon. All
// copy bilingual en/hi (REQ-006).
//
// PHASE-8.2 T3 (#545): restyled to patient-shell visual language - cards,
// status chips, spacing, loading/empty states per PROTO-2.7 binding.
// Data fetching, state logic, and tests unchanged.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  listOpenCases,
  type CareCaseStage,
  type CaseDetailView,
} from "@/lib/care/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadStatus = "loading" | "ready" | "error";

function stageLabel(
  stage: CareCaseStage,
  t: Dictionary["doctorConsole"],
): string {
  switch (stage) {
    case "pre_summary":
      return t.stagePreSummary;
    case "prescription_pending":
      return t.stagePrescriptionPending;
    case "closed":
      return t.stageClosed;
    default:
      return stage;
  }
}

function stageChipClass(stage: CareCaseStage): string {
  switch (stage) {
    case "pre_summary":
      return "bg-warn-soft text-warn-text";
    case "prescription_pending":
      return "bg-accent-soft text-accent-strong";
    case "closed":
      return "bg-hairline-soft text-txt-muted";
    default:
      return "bg-hairline-soft text-txt-muted";
  }
}

function LoadingSkeleton() {
  return (
    <section
      data-testid="cases-skeleton"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="h-6 w-32 animate-pulse rounded bg-hairline-soft" />
      </div>
      <div className="space-y-2.5">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded-lg bg-hairline-soft"
          />
        ))}
      </div>
    </section>
  );
}

export default function DoctorCasesIndexPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const [cases, setCases] = useState<CaseDetailView[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    listOpenCases()
      .then((items) => {
        setCases(items);
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const ready = loadStatus === "ready";
  const empty = ready && cases.length === 0;

  return (
    <>
      <PageHeader
        title={t.casesIndexTitle}
        description={t.casesIndexDescription}
      />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {loadStatus === "loading" && <LoadingSkeleton />}

      {empty && (
        <section
          className="rounded-lg border border-hairline bg-surface p-4"
          data-testid="empty-state-wrapper"
        >
          <EmptyState title={t.casesEmpty} body={t.casesEmptyBody} />
        </section>
      )}

      {ready && cases.length > 0 && (
        <section
          className="rounded-lg border border-hairline bg-surface p-4"
          data-testid="cases-list-wrapper"
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <h2 className="text-[1.05rem] font-semibold text-txt">
              {t.casesHeading}
            </h2>
          </div>
          <ul data-testid="cases-list">
            {cases.map((c) => (
              <li
                key={c.case_id}
                data-testid="case-item"
                className="border-b border-hairline-soft py-2.5 last:border-b-0 last:py-0"
              >
                <div className="flex min-h-11 min-w-0 items-center gap-3.5">
                  <div className="min-w-0 flex-1">
                    <span
                      className="text-sm font-medium text-txt"
                      data-testid="case-item-id"
                    >
                      {t.caseItemMeta(c.case_id)}
                    </span>
                    <div className="mt-1">
                      <span
                        data-testid="case-item-stage"
                        className={cn(
                          "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
                          stageChipClass(c.stage),
                        )}
                      >
                        {stageLabel(c.stage, t)}
                      </span>
                    </div>
                  </div>
                  <Link
                    href={`/doctor/cases/${c.case_id}`}
                    data-testid="case-item-open"
                    className="inline-flex shrink-0 items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                  >
                    {t.openCaseAction}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
