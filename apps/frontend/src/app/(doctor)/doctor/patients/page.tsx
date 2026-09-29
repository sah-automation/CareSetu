"use client";

// PHASE-8.1 (#541): doctor console Patients index - the live destination
// behind the un-sooned Patients tab. Renders the derived Current/Past patient
// groups from the consent-gated list API (#539): rows carry granted-scope
// badges and the latest case stage, a light name filter narrows the list, and
// each row deep-links into the per-patient detail view (US-11..US-19). Every
// patient read goes through the gated detail API; the page renders exactly
// what the backend answers. All copy bilingual en/hi (REQ-006).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import {
  listDoctorPatients,
  type DoctorPatientBucket,
  type DoctorPatientRow,
} from "@/lib/doctor/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";

type LoadStatus = "loading" | "ready" | "error";

// The row's latest case stage mirrors the care case stage enum (care/api.ts);
// a stage we do not know renders as itself, like the cases index fallback.
function stageLabel(stage: string, t: Dictionary["doctorConsole"]): string {
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
    <div className="space-y-3" data-testid="patients-skeleton">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-24 rounded-full" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

interface PatientRowProps {
  row: DoctorPatientRow;
  t: Dictionary["doctorPatients"];
  consoleT: Dictionary["doctorConsole"];
}

function scopeBadges(
  scopes: DoctorPatientRow["granted_scopes"],
  t: Dictionary["doctorPatients"],
) {
  return scopes.map((scope) => (
    <span
      key={scope}
      data-testid={`patient-row-scope-${scope}`}
      className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
    >
      {t.scopeBadge[scope]}
    </span>
  ));
}

function PatientRow({ row, t, consoleT }: PatientRowProps) {
  return (
    <li
      data-testid="patient-row"
      className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className="text-sm font-medium text-txt"
            data-testid="patient-row-name"
          >
            {row.name ?? consoleT.patientFallback}
          </span>
          {row.age != null && (
            <span className="text-xs text-txt-muted">
              {consoleT.patientAge(row.age)}
            </span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {row.granted_scopes.length > 0 && scopeBadges(row.granted_scopes, t)}
          <span
            data-testid="patient-row-stage"
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
              row.latest_case_stage == null
                ? "bg-surface text-txt-muted"
                : row.latest_case_stage === "pre_summary"
                  ? "bg-warn-soft text-warn-text"
                  : "bg-accent-soft text-accent-strong",
            )}
          >
            {row.latest_case_stage == null
              ? t.noCaseStage
              : stageLabel(row.latest_case_stage, consoleT)}
          </span>
        </div>
      </div>
      <Link
        href={`/doctor/patients/${row.patient_id}`}
        data-testid="patient-row-open"
        className="inline-flex shrink-0 items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
      >
        {t.openPatientAction}
      </Link>
    </li>
  );
}

interface PatientGroupProps {
  bucket: DoctorPatientBucket;
  rows: DoctorPatientRow[];
  t: Dictionary["doctorPatients"];
  consoleT: Dictionary["doctorConsole"];
}

function PatientGroup({ bucket, rows, t, consoleT }: PatientGroupProps) {
  const current = bucket === "current";
  const heading = current ? t.currentHeading : t.pastHeading;
  const emptyTitle = current ? t.currentEmpty : t.pastEmpty;
  return (
    <section
      data-testid={`patient-group-${bucket}`}
      aria-label={heading}
      className="mb-6"
    >
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-txt-muted">
        {heading}
      </h2>
      {rows.length === 0 ? (
        <EmptyState title={emptyTitle} />
      ) : (
        <ul data-testid={`patient-list-${bucket}`} className="space-y-2">
          {rows.map((row) => (
            <PatientRow
              key={row.patient_id}
              row={row}
              t={t}
              consoleT={consoleT}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function DoctorPatientsIndexPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorPatients;
  const consoleT = STRINGS[lang].doctorConsole;

  const [rows, setRows] = useState<DoctorPatientRow[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    // A doctor's patient list is small in this phase; fetch the API's max
    // page and filter by name client-side (the light search the US calls for).
    listDoctorPatients({ perPage: 100 })
      .then((view) => {
        setRows(view.items);
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

  const query = search.trim().toLowerCase();
  const visible = rows.filter(
    (row) =>
      query.length === 0 ||
      (row.name != null && row.name.toLowerCase().includes(query)),
  );
  const current = visible.filter((row) => row.bucket === "current");
  const past = visible.filter((row) => row.bucket === "past");

  const ready = loadStatus === "ready";
  const empty = ready && rows.length === 0;
  const searching = query.length > 0;

  return (
    <>
      <PageHeader title={t.title} description={t.description} />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {loadStatus === "loading" && <LoadingSkeleton />}

      {ready && (
        <div className="mb-4">
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t.searchPlaceholder}
            aria-label={t.searchPlaceholder}
            data-testid="patient-search"
            className="w-full max-w-sm rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt placeholder:text-txt-muted focus:border-accent-border focus:outline-none"
          />
        </div>
      )}

      {empty && <EmptyState title={t.patientsEmpty} />}

      {ready && !empty && visible.length === 0 && searching && (
        <EmptyState title={t.noResultsTitle} body={t.noResultsBody} />
      )}

      {ready && !empty && visible.length > 0 && (
        <div>
          <PatientGroup
            bucket="current"
            rows={current}
            t={t}
            consoleT={consoleT}
          />
          <PatientGroup bucket="past" rows={past} t={t} consoleT={consoleT} />
        </div>
      )}
    </>
  );
}
