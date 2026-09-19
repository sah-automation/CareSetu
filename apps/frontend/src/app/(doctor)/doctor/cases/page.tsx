"use client";

// PHASE-8.1 T8 (#483): doctor console Cases index - the live destination
// behind the un-sooned Cases tab. Renders the doctor's open care cases from
// the existing open-cases read (listOpenCases), each linking into its case
// workspace (cases/[caseId]). An alternative entry to the landing page's
// open-cases section (US-8); patients/profile tabs stay coming-soon. All
// copy bilingual en/hi (REQ-006).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
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

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="cases-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-lg border border-hairline bg-surface p-4"
        >
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-4 w-12" />
        </div>
      ))}
    </div>
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

      {empty && <EmptyState title={t.casesEmpty} />}

      {ready && cases.length > 0 && (
        <ul className="space-y-2" data-testid="cases-list">
          {cases.map((c) => (
            <li
              key={c.case_id}
              data-testid="case-item"
              className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
            >
              <div className="min-w-0">
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
                      "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                      c.stage === "pre_summary"
                        ? "bg-warning-soft text-warning-text"
                        : "bg-accent-soft text-accent-strong",
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
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
