"use client";

// PHASE-8.1 T11 (#449): the patient pick-a-doctor step (US-1/US-9; the
// continuation target the pre-summary and intake-status pages re-point here).
// The patient-authed selection runs over the same verified directory the
// public /doctors surface reads (ADR-0011 "tick gone = card gone"), defaulted
// to presetType doctor and pre-filtered by a suggested specialty derived from
// the intake's structured symptoms (US-2) - shown as a start-here filter,
// never a verdict, so the patient keeps full choice (US-3). Cards carry the
// verified tick, practice, specialty, distance, fee-or-fee-not-set (US-10)
// and credentials summary, and deep-link to the verified profile. "Book with
// this doctor" opens the pick consent sheet; Allow records the pick + consent
// atomically and the page swaps to confirmation with what happens next.
// A low-confidence pre-summary gets a symptom-edit link before the pick
// (US-8). Bilingual EN/HI.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { formatDistanceKm } from "@/components/directory/DirectoryCard";
import {
  DoctorPickCard,
  formatFeePaise,
} from "@/components/pick/DoctorPickCard";
import { PickConsentSheet } from "@/components/pick/PickConsentSheet";
import { ApiError } from "@/lib/api-errors";
import {
  DIRECTORIES_SPECIALTIES,
  searchDirectory,
  type DirectoryEntry,
  type DirectorySearchView,
  type Specialty,
} from "@/lib/directory/search";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { fetchPreSummary } from "@/lib/intake/api";
import type { PickDoctorResult } from "@/lib/pick/api";
import { deriveSpecialtyFromSymptoms } from "@/lib/pick/suggest";

type LoadState = "loading" | "loaded" | "error";

const SPECIALTY_LABEL_KEY: Record<
  string,
  keyof (typeof STRINGS)["en"]["directory"]["specialties"]
> = {
  "General Physician": "generalPhysician",
  Pediatrician: "pediatrician",
  Gynecologist: "gynecologist",
  Dentist: "dentist",
};

const chipClass = (active: boolean) =>
  `rounded-full border px-3 py-1.5 text-sm shadow-sm transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong ${
    active
      ? "border-accent-border bg-accent-soft text-accent-strong"
      : "border-hairline bg-surface text-txt-sub"
  }`;

export default function PickDoctorPage() {
  const params = useParams<{ intakeId: string }>();
  const intakeId = Number(params.intakeId);
  const { lang } = useLang();
  const t = STRINGS[lang].pick;
  const directory = STRINGS[lang].directory;
  const nav = STRINGS[lang].nav;
  const intakeDict = STRINGS[lang].intake;

  const [summaryStage, setSummaryStage] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [lowConfidence, setLowConfidence] = useState(false);
  const [suggested, setSuggested] = useState<Specialty | null>(null);
  const [filter, setFilter] = useState<Specialty | null>(null);
  const [dirStage, setDirStage] = useState<LoadState>("loading");
  const [view, setView] = useState<DirectorySearchView | null>(null);
  const [loadError, setLoadError] = useState<{
    title: string;
    body: string;
    traceId?: string;
  } | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [picking, setPicking] = useState<DirectoryEntry | null>(null);
  const [picked, setPicked] = useState<DirectoryEntry | null>(null);

  const reloadSummary = () => {
    setSummaryStage("loading");
    setLoadError(null);
    void fetchPreSummary(intakeId)
      .then((ps) => {
        setLowConfidence(ps.low_confidence);
        const s = deriveSpecialtyFromSymptoms(ps.structured_fields);
        setSuggested(s);
        setSummaryStage("ready");
        setFilter((prev) => {
          // Start-here filter: the suggestion pre-fills the filter until the
          // patient chooses otherwise (never blocks - chips stay interactive).
          if (prev === null) return s;
          return prev;
        });
      })
      .catch((error: unknown) => {
        setSummaryStage("error");
        setLoadError({
          title: t.errorTitle,
          body: t.errorBody,
          traceId: error instanceof ApiError ? error.traceId : undefined,
        });
      });
  };

  useEffect(() => {
    reloadSummary();
    // reloadSummary changes identity per render (reads lang-bound strings);
    // the fetch itself is idempotent so a single mount fetch is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intakeId]);

  // Directory fetch is gated on the pre-summary resolving, so the start-here
  // filter commits only once (no useless all-doctors fetch then a refetch).
  useEffect(() => {
    if (summaryStage !== "ready") return;
    let active = true;
    setDirStage("loading");
    searchDirectory({ partnerType: "doctor", specialty: filter })
      .then((result) => {
        if (active) {
          setView(result);
          setDirStage("loaded");
        }
      })
      .catch((err: unknown) => {
        if (active) {
          console.error("[pick] directory search failed:", err);
          setView(null);
          setDirStage("error");
        }
      });
    return () => {
      active = false;
    };
  }, [summaryStage, filter, retryNonce]);

  const handleBook = (entry: DirectoryEntry) => {
    setPicking(entry);
  };

  const handlePicked = (result: PickDoctorResult) => {
    setPicked(picking);
    setPicking(null);
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-4 pb-14 pt-6">
      <PageHeader
        title={t.title}
        description={t.subtitle}
        breadcrumbs={[
          { label: nav.home, href: "/patient" },
          { label: intakeDict.breadcrumb, href: "/patient/intake" },
          { label: t.breadcrumb },
        ]}
      />

      {/* Low-confidence: symptom-edit link before the pick (US-8) */}
      {summaryStage === "ready" && lowConfidence && !picked && (
        <div
          data-testid="lowconf-hint"
          className="mb-4 flex flex-col gap-1 rounded-lg border border-warn-border bg-warn-soft px-4 py-3"
        >
          <p className="text-sm text-txt">{t.lowConfidenceHint}</p>
          <Link
            href={`/patient/intake/${intakeId}/pre-summary`}
            data-testid="pick-edit-symptoms"
            className="text-sm font-medium text-accent-strong underline-offset-4 hover:underline"
          >
            {t.editSymptoms}
          </Link>
        </div>
      )}

      {picked ? (
        <section
          className="flex flex-col gap-4"
          data-testid="pick-confirmation"
          role="status"
        >
          <p className="flex items-center justify-center gap-2 rounded-lg bg-success-soft p-3 font-medium text-success-text">
            <span aria-hidden="true">✓</span>
            <span data-testid="pick-confirm-title">{t.confirmTitle}</span>
          </p>

          <div className="rounded-lg border border-hairline bg-surface p-4 shadow-card">
            <p className="text-sm text-txt-sub">{t.confirmBody}</p>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                  {t.feeLabel}
                </dt>
                <dd className="mt-0.5 text-txt" data-testid="pick-confirm-fee">
                  {picked.consultation_fee !== null
                    ? formatFeePaise(picked.consultation_fee)
                    : t.feeNotSet}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                  {directory.verified}
                </dt>
                <dd
                  className="mt-0.5 font-medium text-txt"
                  data-testid="pick-confirm-doctor"
                >
                  {picked.practice_name ?? "CareSetu provider"}
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-lg border border-hairline bg-surface p-4 shadow-card">
            <h2 className="text-sm font-semibold text-txt">
              {t.whatHappensNext}
            </h2>
            <p
              className="mt-1 text-sm text-txt-muted"
              data-testid="pick-confirm-next"
            >
              {t.whatHappensNextItems}
            </p>
          </div>

          <Button
            asChild
            size="lg"
            className="w-full"
            data-testid="btn-case-status"
          >
            <Link href={`/patient/intake/${intakeId}/status`}>
              {t.viewIntakeStatus}
            </Link>
          </Button>
        </section>
      ) : (
        <>
          {/* Specialty chips - the suggestion is a start-here filter (US-3) */}
          <div
            className="flex flex-col gap-2"
            role="group"
            aria-label={t.suggestedSpecialtyLabel}
          >
            {summaryStage === "ready" && suggested && (
              <p
                className="inline-flex items-center gap-2 text-sm font-medium text-txt"
                data-testid="suggested-label"
              >
                <span
                  className="inline-block h-2 w-2 rounded-full bg-accent"
                  aria-hidden="true"
                />
                {t.suggestedSpecialtyLabel}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                data-testid="specialty-chip-all"
                data-active={filter === null}
                aria-pressed={filter === null}
                onClick={() => setFilter(null)}
                className={chipClass(filter === null)}
              >
                {directory.typeAll}
              </button>
              {DIRECTORIES_SPECIALTIES.map((specialty) => {
                const active = filter === specialty;
                return (
                  <button
                    key={specialty}
                    type="button"
                    data-testid={`specialty-chip-${specialty}`}
                    data-active={active}
                    aria-pressed={active}
                    onClick={() => setFilter(active ? null : specialty)}
                    className={chipClass(active)}
                  >
                    {directory.specialties[SPECIALTY_LABEL_KEY[specialty]]}
                  </button>
                );
              })}
            </div>
            {summaryStage === "ready" && suggested && (
              <p
                className="text-xs text-txt-muted"
                data-testid="suggestion-note"
              >
                {t.suggestionNote}
              </p>
            )}
          </div>

          <section aria-live="polite" className="mt-5">
            {loadError || summaryStage === "error" ? (
              <div data-testid="pick-summary-error">
                <ErrorBanner
                  message={
                    <>
                      <strong className="font-semibold">
                        {loadError?.title}
                      </strong>
                      <span className="block">{loadError?.body}</span>
                    </>
                  }
                  traceId={loadError?.traceId}
                  onRetry={() => reloadSummary()}
                  onDismiss={() => setLoadError(null)}
                />
              </div>
            ) : dirStage === "error" ? (
              <div
                data-testid="pick-error"
                className="rounded-lg border border-hairline bg-accent-soft px-6 py-10 text-center"
              >
                <p className="font-medium text-txt">{t.errorTitle}</p>
                <p className="mt-1 text-sm text-txt-muted">{t.errorBody}</p>
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-4"
                  onClick={() => {
                    setDirStage("loading");
                    setRetryNonce((n) => n + 1);
                  }}
                >
                  {t.retry}
                </Button>
              </div>
            ) : summaryStage === "loading" || dirStage === "loading" ? (
              <div
                data-testid="pick-loading"
                className="grid gap-4 sm:grid-cols-2"
                role="status"
              >
                <span className="sr-only">{t.loading}</span>
                {[0, 1].map((i) => (
                  <div
                    key={i}
                    className="h-40 animate-pulse rounded-lg bg-hairline-soft"
                  />
                ))}
              </div>
            ) : view && view.items.length === 0 ? (
              <EmptyState
                title={t.noDoctorsTitle}
                body={t.noDoctorsBody}
                action={
                  <Button variant="secondary" onClick={() => setFilter(null)}>
                    {directory.typeAll}
                  </Button>
                }
              />
            ) : view ? (
              <div
                className="grid gap-4 sm:grid-cols-2"
                data-testid="pick-cards"
              >
                {view.items.map((entry) => (
                  <DoctorPickCard
                    key={entry.partner_id}
                    entry={entry}
                    typeLabel={directory.typeDoctor}
                    specialtyLabel={
                      entry.specialty
                        ? directory.specialties[
                            SPECIALTY_LABEL_KEY[entry.specialty] ??
                              "generalPhysician"
                          ]
                        : null
                    }
                    verifiedLabel={directory.verified}
                    distanceLabel={formatDistanceKm(
                      entry.distance_km,
                      directory.distanceKm,
                    )}
                    feeLabel={t.feeLabel}
                    feeNotSetLabel={t.feeNotSet}
                    credentialsVerifiedLabel={t.credentialsVerified}
                    bookCtaLabel={t.bookCta}
                    viewProfileLabel={t.viewProfile}
                    onBook={handleBook}
                  />
                ))}
              </div>
            ) : null}
          </section>
        </>
      )}

      {picking && (
        <PickConsentSheet
          intakeId={intakeId}
          entry={picking}
          doctorName={picking.practice_name ?? "CareSetu provider"}
          open
          onOpenChange={(open) => {
            if (!open) setPicking(null);
          }}
          onPicked={handlePicked}
        />
      )}
    </main>
  );
}
