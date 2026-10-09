"use client";

// PHASE-8.1 T8 (#483): doctor console Cases index - the live destination
// behind the un-sooned Cases tab. Renders the doctor's open care cases, each
// linking into its case workspace (cases/[caseId]). An alternative entry to
// the landing page's open-cases section (US-8); patients/profile tabs stay
// coming-soon. All copy bilingual en/hi (REQ-006).
//
// PHASE-8.2 T3 (#545): restyled to patient-shell visual language - cards,
// status chips, spacing, loading/empty states per PROTO-2.7 binding.
//
// MOD-012 / FEAT-008 (#645/#652 "Shared doctor card"): each row is the shared
// DoctorListCard the patients list already renders - avatar initial, patient
// name and age, the case identifier kept citable (US-3), the stage chip off
// the one shared tone map, the amber Verify chip on a forced-review case
// (US-5), and a last-updated line so triage runs on staleness (US-6). The
// whole card is one overlay link: one focus stop whose accessible name
// includes the patient (US-66/67). Reads the doctor cases endpoint through
// lib/doctor/api (listDoctorCases), whose runtime guards are pinned against
// the exported OpenAPI slice by patients.contract.test.ts (#624/#652). The
// dashboard's open-cases section reads the same feed (#676); the care module's
// listOpenCases still serves the workspace routes and stays untouched there.

import { useCallback, useEffect, useState } from "react";

import { DoctorCaseCard } from "@/components/doctor/DoctorCaseCard";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import { listDoctorCases, type DoctorCaseRow } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadStatus = "loading" | "ready" | "error";

// The skeleton mirrors the card grid so the page does not jump when the data
// arrives (US-10): same grid columns as the ready list, one placeholder per
// card shape - avatar circle, name line, chip line, meta line.
function LoadingSkeleton() {
  return (
    <section
      data-testid="cases-skeleton"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <Skeleton className="mb-3 h-6 w-32" />
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            data-testid="cases-skeleton-card"
            className="rounded-lg border border-hairline bg-surface p-4"
          >
            <div className="flex items-start gap-3">
              <Skeleton className="h-9 w-9 shrink-0 rounded-full" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function DoctorCasesIndexPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const [cases, setCases] = useState<DoctorCaseRow[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    listDoctorCases()
      .then(({ items }) => {
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
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-[1.05rem] font-semibold text-txt">
              {t.casesHeading}
            </h2>
          </div>
          {/* Single column below the large breakpoint, so a phone never
              scrolls sideways (US-7/68); min-w-0 on each child lets the
              card's own truncation do the work (US-68). */}
          <ul
            data-testid="cases-list"
            className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2"
          >
            {cases.map((c) => (
              <li key={c.case_id} data-testid="case-item" className="min-w-0">
                <DoctorCaseCard row={c} t={t} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
