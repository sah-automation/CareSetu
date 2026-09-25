"use client";

// PHASE-8.1 T13 (#451): case workspace review stage. Two console entry points
// land here: the review queue link opens /doctor/review/[intakeId] (review +
// finalize), and the open-cases link opens /doctor/cases/[caseId] (stage +
// handshake). Both routes share the same workspace design, staged by the
// data available. This page implements the full review flow:
//
// 1. Fetch the full pre-summary for the assigned doctor (#448).
// 2. Resolve the matching care case via listOpenCases (patient_id + case_id).
//    A queue-originated review starts with no case (the outbox consumer births
//    it on pre_summary.ready), so after a one-action finalize the page re-reads
//    the case list until the async-birthed case shows up.
// 3. Show case stage, forced-review requirement, full pre-summary, and the
//    patient's consented health history.
// 4. One-action review-and-finalize for low-confidence pre-summaries (#442).
// 5. Consult-complete handshake into prescription-pending (US-24).
//
// All copy bilingual en/hi (REQ-006). Prescription drafting/approval stages
// are built by #452/#453.

import type { FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ConsentedHistory } from "@/components/case/ConsentedHistory";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  fetchPreSummaryForReview,
  reviewPreSummary,
  type PreSummaryView,
} from "@/lib/intake/api";
import {
  listOpenCases,
  markConsultComplete,
  type CaseDetailView,
  type CareCaseStage,
} from "@/lib/care/api";
import { fetchPartnerMe, type PartnerMeView } from "@/lib/partner/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// ---- helpers ----

function confidencePercent(value: number | null): string {
  if (value == null) return "\u2014";
  return `${Math.round(value * 100)}%`;
}

function stageDisplayName(
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

function reviewStateDisplayName(
  state: string,
  t: Dictionary["caseWorkspace"],
): string {
  switch (state) {
    case "draft":
      return t.reviewStateDraft;
    case "reviewed":
      return t.reviewStateReviewed;
    case "final":
      return t.reviewStateFinal;
    default:
      return state;
  }
}

// The review state is a status, so it wears a status chip: an amber "awaiting
// your review" pill, the teal in-progress treatment, then a green finalized one.
function reviewStateChipClass(state: string): string {
  switch (state) {
    case "final":
      return "bg-success-soft text-success-text";
    case "reviewed":
      return "bg-accent-soft text-accent-strong";
    default:
      return "bg-warn-soft text-warn-text";
  }
}

function formatDate(iso: string, lang: "en" | "hi"): string {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

// The care case for a pre-summary is birthed asynchronously (the outbox
// consumer behind pre_summary.ready), so a queue-originated review that just
// finalized has no case yet. Re-read the open-cases list a few times so the
// handshake and consented-history sections appear without a manual refresh.
async function refreshMatchedCase(
  preSummaryId: number,
  fetchCases: () => Promise<CaseDetailView[]>,
  retryCount = 5,
): Promise<CaseDetailView | null> {
  for (let attempt = 0; attempt < retryCount; attempt += 1) {
    const cases = await fetchCases();
    const matched = cases.find((c) => c.pre_summary_id === preSummaryId);
    if (matched) return matched;
    if (attempt < retryCount - 1) {
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
  return null;
}

// ---- sub-components ----

function LoadingSkeleton() {
  return (
    <div className="space-y-4" data-testid="workspace-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="h-5 w-1/3 rounded bg-hairline-soft" />
          <div className="mt-3 h-4 w-1/2 rounded bg-hairline-soft" />
          <div className="mt-2 h-3 w-1/4 rounded bg-hairline-soft" />
        </div>
      ))}
    </div>
  );
}

// ---- main page ----

export default function ReviewWorkspacePage() {
  const params = useParams<{ intakeId: string }>();
  const intakeId = Number(params.intakeId);
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const consoleT = STRINGS[lang].doctorConsole;

  const [loadStatus, setLoadStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [preSummary, setPreSummary] = useState<PreSummaryView | null>(null);
  const [careCase, setCareCase] = useState<CaseDetailView | null>(null);
  const [doctorMe, setDoctorMe] = useState<PartnerMeView | null>(null);

  // Review action state
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState(false);
  const [finalizeSuccess, setFinalizeSuccess] = useState(false);

  // Handshake state
  const [handshaking, setHandshaking] = useState(false);
  const [handshakeError, setHandshakeError] = useState(false);
  const [handshakeDone, setHandshakeDone] = useState(false);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    setFinalizeError(false);
    setHandshakeError(false);

    Promise.all([
      fetchPreSummaryForReview(intakeId),
      listOpenCases(),
      fetchPartnerMe(),
    ])
      .then(([pre, cases, me]) => {
        setPreSummary(pre);
        setDoctorMe(me);
        const matched =
          cases.find((c) => c.pre_summary_id === pre.pre_summary_id) ?? null;
        setCareCase(matched);
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [intakeId]);

  useEffect(() => {
    load();
  }, [load]);

  // ---- action handlers ----

  async function handleFinalize(e: FormEvent) {
    e.preventDefault();
    if (!preSummary) return;
    setFinalizing(true);
    setFinalizeError(false);
    try {
      const result = await reviewPreSummary(preSummary.intake_id);
      setPreSummary((prev) =>
        prev
          ? {
              ...prev,
              review_state: result.review_state,
              review_attribution: result.review_attribution,
              reviewed_by: result.reviewed_by,
              reviewed_at: result.reviewed_at,
              doctor_corrections: null,
              // The server returns the authoritative copy (original fields overlaid
              // with the doctor's corrections). Merge it wholesale so no edited
              // field - including ones the current UI does not surface - is lost.
              structured_fields: {
                ...prev.structured_fields,
                ...result.reviewed_copy,
              },
            }
          : prev,
      );
      const birthed = await refreshMatchedCase(
        preSummary.pre_summary_id,
        listOpenCases,
      );
      if (birthed) setCareCase(birthed);
      setFinalizeSuccess(true);
    } catch {
      setFinalizeError(true);
    } finally {
      setFinalizing(false);
    }
  }

  async function handleHandshake(e: FormEvent) {
    e.preventDefault();
    if (!careCase) return;
    setHandshaking(true);
    setHandshakeError(false);
    try {
      const result = await markConsultComplete(careCase.case_id);
      setCareCase(result);
      setHandshakeDone(true);
    } catch {
      setHandshakeError(true);
    } finally {
      setHandshaking(false);
    }
  }

  // ---- derived state ----

  const isReady = loadStatus === "ready" && preSummary !== null;
  const isFinal = preSummary?.review_state === "final";
  const forcedReview =
    careCase?.forced_review === true || preSummary?.low_confidence === true;
  const currentStage = careCase?.stage ?? "pre_summary";
  const showHandshake = careCase != null && isFinal && !handshakeDone;

  // ---- render ----

  return (
    <>
      <Link
        href="/doctor"
        className="mb-4 inline-flex items-center gap-1 text-sm text-accent hover:underline"
        data-testid="back-to-console"
      >
        <span aria-hidden="true">&larr;</span> {t.backToConsole}
      </Link>

      <PageHeader
        title={t.title}
        description={preSummary ? consoleT.queueItemMeta(intakeId) : undefined}
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

      {loadStatus === "error" && !bannerOpen && (
        <div className="text-center">
          <Button variant="ghost" size="sm" onClick={load}>
            {STRINGS[lang].doctorConsole.retry}
          </Button>
        </div>
      )}

      {isReady && (
        <div className="space-y-6" data-testid="workspace-content">
          {/* Stage + forced-review requirement */}
          <section
            className="rounded-lg border border-hairline bg-surface p-4"
            data-testid="workspace-stage"
          >
            <div className="flex flex-wrap items-center gap-3">
              <span
                className="text-xs font-medium text-txt-muted"
                data-testid="stage-label"
              >
                {t.stageLabel}
              </span>
              <span
                data-testid="stage-chip"
                className={cn(
                  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                  currentStage === "pre_summary"
                    ? "bg-warn-soft text-warn-text"
                    : currentStage === "prescription_pending"
                      ? "bg-accent-soft text-accent-strong"
                      : "bg-hairline-soft text-txt-muted",
                )}
              >
                {stageDisplayName(currentStage, consoleT)}
              </span>
            </div>

            {forcedReview && (
              <div
                className="mt-3 rounded-md border border-hairline bg-warn-soft px-3 py-2.5"
                data-testid="forced-review-banner"
              >
                <div className="flex items-start gap-2">
                  <svg
                    className="mt-0.5 shrink-0 text-warn-text"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 8v4M12 16h.01" />
                  </svg>
                  <div className="min-w-0 flex-1">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-warn-text">
                      {t.forcedReviewChip}
                    </span>
                    <p className="mt-1 text-xs text-txt-muted">
                      {t.forcedReviewDetail}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* Pre-summary content - one field group per captured section, each
              split by a hairline under an uppercase group header. */}
          <section
            className="rounded-lg border border-hairline bg-surface p-4"
            data-testid="pre-summary"
          >
            <h2 className="text-sm font-semibold text-txt">
              {t.summaryHeading}
            </h2>

            <div className="mt-1">
              {/* Chief complaints */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-complaints"
              >
                <div className="px-1 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                  {t.chiefComplaintsLabel}
                </div>
                {preSummary.structured_fields.chief_complaints.length > 0 ? (
                  <ul className="space-y-1.5 px-1">
                    {preSummary.structured_fields.chief_complaints.map(
                      (c, idx) => (
                        <li
                          key={idx}
                          className="flex items-baseline gap-2 text-sm"
                        >
                          <span className="text-xs font-medium text-txt-muted">
                            #{idx + 1}
                          </span>
                          <span className="font-medium text-txt">{c}</span>
                        </li>
                      ),
                    )}
                  </ul>
                ) : (
                  <p className="px-1 text-sm text-txt-muted">
                    {t.durationNotSet}
                  </p>
                )}
              </div>

              {/* Symptoms */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-symptoms"
              >
                <div className="px-1 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                  {t.symptomsLabel}
                </div>
                {preSummary.structured_fields.symptoms.length > 0 ? (
                  <ul className="space-y-1.5 px-1">
                    {preSummary.structured_fields.symptoms.map((s, idx) => (
                      <li
                        key={idx}
                        className="flex items-baseline gap-2 text-sm"
                      >
                        <span className="text-xs font-medium text-txt-muted">
                          #{idx + 1}
                        </span>
                        <span className="font-medium text-txt">{s}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-1 text-sm text-txt-muted">
                    {t.durationNotSet}
                  </p>
                )}
              </div>

              {/* Duration */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-duration"
              >
                <div className="px-1 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                  {t.durationLabel}
                </div>
                <p className="px-1 text-sm font-medium text-txt">
                  {preSummary.structured_fields.duration ?? t.durationNotSet}
                </p>
              </div>

              {/* Confidence + low-confidence flag */}
              <div className="flex flex-wrap items-center gap-4 border-t border-hairline px-1 pt-3">
                <div data-testid="pre-summary-confidence">
                  <span className="text-xs font-medium text-txt-muted">
                    {t.confidenceLabel}
                  </span>
                  <span className="ml-1 text-sm text-txt">
                    {" "}
                    {confidencePercent(preSummary.structuring_confidence)}
                  </span>
                </div>
                {preSummary.low_confidence && (
                  <span
                    data-testid="pre-summary-low-confidence"
                    className="inline-flex items-center rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-text"
                  >
                    {consoleT.verifyChip}
                  </span>
                )}
              </div>

              {/* Patient edits */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-patient-edits"
              >
                <div className="px-1 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                  {t.patientEditsLabel}
                </div>
                <p className="px-1 text-sm font-medium text-txt">
                  {Object.keys(preSummary.patient_edits ?? {}).length > 0
                    ? Object.entries(preSummary.patient_edits ?? {})
                        .map(([k, v]) => `${k}: ${v}`)
                        .join("; ")
                    : t.patientEditsNone}
                </p>
              </div>

              {/* Review attribution */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-attribution"
              >
                <div className="px-1 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                  {t.attributionLabel}
                </div>
                <p className="px-1 text-sm font-medium text-txt">
                  {preSummary.review_attribution != null
                    ? preSummary.review_attribution
                    : t.notReviewedYet}
                </p>
              </div>

              {/* Review state - a status chip on the group header row */}
              <div
                className="border-t border-hairline"
                data-testid="pre-summary-review-state"
              >
                <div className="flex flex-wrap items-center gap-2 px-1 pt-3 pb-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-txt-muted">
                    {t.reviewStateLabel}
                  </span>
                  <span
                    data-testid="review-state-chip"
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                      reviewStateChipClass(preSummary.review_state),
                    )}
                  >
                    {reviewStateDisplayName(preSummary.review_state, t)}
                  </span>
                  {preSummary.reviewed_at && (
                    <span className="text-xs text-txt-muted">
                      ({t.reviewedOnLabel}:{" "}
                      {formatDate(preSummary.reviewed_at, lang)})
                    </span>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* Review action: one-action finalize, shown while not yet final */}
          {!isFinal && (
            <section
              className="rounded-lg border border-hairline bg-surface p-4"
              data-testid="workspace-review-action"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.reviewActionHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">{t.finalizeHelp}</p>
              <form className="mt-3" onSubmit={handleFinalize}>
                <Button
                  type="submit"
                  size="sm"
                  disabled={finalizing}
                  loading={finalizing}
                  data-testid="finalize-action"
                >
                  {t.finalizeAction}
                </Button>
                {finalizeError && (
                  <p className="mt-2 text-sm text-danger" role="alert">
                    {t.finalizeFail}
                  </p>
                )}
              </form>
            </section>
          )}

          {/* Finalized success message */}
          {finalizeSuccess && (
            <div
              className="flex items-start gap-2 rounded-md border border-hairline bg-success-soft px-3 py-3"
              data-testid="finalize-success"
            >
              <svg
                className="mt-0.5 shrink-0 text-success-text"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              <p className="text-sm font-medium text-success-text">
                {t.finalizeSuccess}
              </p>
            </div>
          )}

          {/* Consented history - only when case exists */}
          {careCase != null && doctorMe != null && (
            <section
              className="rounded-lg border border-hairline bg-surface p-4"
              data-testid="workspace-history"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.historyHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">
                {t.historyConsentNote}
              </p>
              <div className="mt-3">
                <ConsentedHistory
                  patientId={careCase.patient_id}
                  partnerId={doctorMe.partner_id}
                />
              </div>
            </section>
          )}

          {/* Case-not-showing empty state: a queue-originated review has no
              care case until the outbox consumer births it, and the re-poll
              after finalize can still come back empty. Name what is
              observable (no case in the open list) without asserting a cause. */}
          {careCase == null && (
            <section
              className="rounded-lg border border-dashed border-hairline bg-surface p-6 text-center"
              data-testid="workspace-case-pending"
            >
              <div
                className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-hairline-soft text-txt-muted"
                aria-hidden="true"
              >
                <svg
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                </svg>
              </div>
              <h2 className="text-sm font-semibold text-txt">
                {t.casePendingTitle}
              </h2>
              <p className="mx-auto mt-1 max-w-[34em] text-xs text-txt-muted">
                {t.casePendingBody}
              </p>
            </section>
          )}

          {/* Handshake */}
          {showHandshake && (
            <section
              className="rounded-lg border border-hairline bg-surface p-4"
              data-testid="workspace-handshake"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.handshakeHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">{t.handshakeHelp}</p>
              <form className="mt-3" onSubmit={handleHandshake}>
                <Button
                  type="submit"
                  size="sm"
                  disabled={handshaking}
                  loading={handshaking}
                  data-testid="handshake-action"
                >
                  {t.handshakeAction}
                </Button>
                {handshakeError && (
                  <p className="mt-2 text-sm text-danger" role="alert">
                    {t.handshakeFail}
                  </p>
                )}
              </form>
            </section>
          )}

          {/* Handshake success */}
          {(handshakeDone || currentStage === "prescription_pending") && (
            <div
              className="rounded-md border border-hairline bg-success-soft px-3 py-3"
              data-testid="handshake-success"
            >
              <p className="text-sm font-medium text-success-text">
                {t.handshakeSuccess}
              </p>
              <p className="mt-1 text-xs text-txt-muted">
                {t.prescriptionPendingCta}
              </p>
            </div>
          )}
        </div>
      )}
    </>
  );
}
