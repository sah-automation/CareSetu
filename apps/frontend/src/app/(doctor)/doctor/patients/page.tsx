"use client";

// PHASE-8.1 (#541): doctor console Patients index - the live destination
// behind the un-sooned Patients tab. Renders the derived Current/Past patient
// groups from the consent-gated list API (#539): rows carry granted-scope
// badges and the latest case stage, a light name filter narrows the list, and
// each row deep-links into the per-patient detail view (US-11..US-19). Every
// patient read goes through the gated detail API; the page renders exactly
// what the backend answers. All copy bilingual en/hi (REQ-006).
//
// MOD-012 / FEAT-008 (#645/#651): each row is the shared DoctorListCard - a
// card grid per bucket (multi-column at the large breakpoint, single column
// below, US-68) built from the card/badge/avatar primitives, with the stage
// tone+label from the shared map. Test ids, states, search, and the bounded
// fetch are unchanged.

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import {
  listDoctorPatients,
  type DoctorPatientBucket,
  type DoctorPatientRow,
} from "@/lib/doctor/api";
import { stageChipView } from "@/lib/doctor/stageChip";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  DoctorListCard,
  type DoctorCardChip,
} from "@/components/doctor/DoctorListCard";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";

type LoadStatus = "loading" | "ready" | "error";

// The worded state for a patient with no open case (US-18): quiet surface
// tone, never an empty chip - an absent stage must not read as an unknown one.
const NO_CASE_STAGE_TONE = "bg-surface text-txt-muted";

function LoadingSkeleton() {
  return (
    <div
      className="grid grid-cols-1 gap-4 lg:grid-cols-2"
      data-testid="patients-skeleton"
    >
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="flex items-start gap-3">
            <Skeleton className="h-9 w-9 rounded-full" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-5 w-24 rounded-full" />
            </div>
          </div>
          <Skeleton className="mt-3 h-4 w-16" />
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

function scopeChips(
  scopes: DoctorPatientRow["granted_scopes"],
  t: Dictionary["doctorPatients"],
): DoctorCardChip[] {
  return scopes.map((scope) => ({
    key: scope,
    label: t.scopeBadge[scope],
    testId: `patient-row-scope-${scope}`,
  }));
}

function PatientRow({ row, t, consoleT }: PatientRowProps) {
  const name = row.name ?? consoleT.patientFallback;
  const stage =
    row.latest_case_stage == null
      ? { label: t.noCaseStage, tone: NO_CASE_STAGE_TONE }
      : stageChipView(row.latest_case_stage, consoleT);
  return (
    <li data-testid="patient-row" className="min-w-0">
      <DoctorListCard
        href={`/doctor/patients/${row.patient_id}`}
        name={name}
        ageText={row.age != null ? consoleT.patientAge(row.age) : null}
        chips={scopeChips(row.granted_scopes, t)}
        stage={stage}
        meta={t.openPatientAction}
        accessibleName={t.openPatientNamed(name)}
        nameTestId="patient-row-name"
        stageTestId="patient-row-stage"
        linkTestId="patient-row-open"
      />
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
        <ul
          data-testid={`patient-list-${bucket}`}
          className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2"
        >
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
