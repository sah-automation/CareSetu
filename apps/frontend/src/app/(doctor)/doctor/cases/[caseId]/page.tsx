"use client";

// PHASE-8.1 T13 (#451): case workspace shell for the open-cases entry path.
// The console's "Open cases" deep-links to /doctor/cases/[caseId] (one per
// active care case). This page shows the case stage, the forced-review
// requirement (if any), the patient's consented health history, and the
// consult-complete handshake for pre_summary-stage cases. Prescription
// drafting and approval stages are out of scope here and will be built by
// #452/#453.
//
// All copy bilingual en/hi (REQ-006).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConsentedHistory } from "@/components/case/ConsentedHistory";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  fetchCareCase,
  markConsultComplete,
  type CaseDetailView,
  type CareCaseStage,
} from "@/lib/care/api";
import { fetchPartnerMe, type PartnerMeView } from "@/lib/partner/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

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

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="case-skeleton">
      {Array.from({ length: 2 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="h-4 w-1/2 rounded bg-muted-soft" />
          <div className="mt-2 h-3 w-1/4 rounded bg-muted-soft" />
        </div>
      ))}
    </div>
  );
}

export default function CaseWorkspacePage({
  params,
}: {
  params: { caseId: string };
}) {
  const caseId = Number(params.caseId);
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const consoleT = STRINGS[lang].doctorConsole;

  const [loadStatus, setLoadStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [careCase, setCareCase] = useState<CaseDetailView | null>(null);
  const [doctorMe, setDoctorMe] = useState<PartnerMeView | null>(null);

  const [handshaking, setHandshaking] = useState(false);
  const [handshakeError, setHandshakeError] = useState(false);
  const [handshakeDone, setHandshakeDone] = useState(false);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    setHandshakeError(false);

    Promise.all([fetchCareCase(caseId), fetchPartnerMe()])
      .then(([c, me]) => {
        setCareCase(c);
        setDoctorMe(me);
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleHandshake(e: React.FormEvent) {
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

  const isReady = loadStatus === "ready" && careCase !== null;
  const currentStage = careCase?.stage ?? "pre_summary";
  const isPreSummaryStage = currentStage === "pre_summary";
  const isPrescriptionPending =
    currentStage === "prescription_pending" || handshakeDone;
  const showHandshake = isPreSummaryStage && !handshakeDone;

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
        description={careCase ? consoleT.caseItemMeta(caseId) : undefined}
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

      {isReady && (
        <div className="space-y-6" data-testid="case-content">
          {/* Stage + forced-review requirement */}
          <section
            className="rounded-lg border border-hairline bg-bg p-4"
            data-testid="case-stage"
          >
            <div className="flex items-center gap-3">
              <span
                className="text-xs font-medium text-txt-muted"
                data-testid="stage-label"
              >
                {t.stageLabel}
              </span>
              <span
                data-testid="stage-chip"
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                  currentStage === "pre_summary"
                    ? "bg-warning-soft text-warning-text"
                    : "bg-accent-soft text-accent-strong",
                )}
              >
                {stageDisplayName(currentStage, consoleT)}
              </span>
            </div>

            {careCase.forced_review && (
              <div
                className="mt-3 rounded-md border border-warning/30 bg-warning-soft/40 px-3 py-2"
                data-testid="forced-review-banner"
              >
                <span className="inline-flex items-center gap-1 text-xs font-semibold text-warning-text">
                  {t.forcedReviewChip}
                </span>
                <p className="mt-1 text-xs text-txt-muted">
                  {t.forcedReviewDetail}
                </p>
              </div>
            )}
          </section>

          {/* Consented history */}
          {doctorMe != null && (
            <section
              className="rounded-lg border border-border bg-bg p-4"
              data-testid="case-history"
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

          {/* Handshake action - pre_summary stage only */}
          {showHandshake && (
            <section
              className="rounded-lg border border-hairline bg-bg p-4"
              data-testid="case-handshake"
            >
              <form onSubmit={handleHandshake}>
                <p className="text-xs text-txt-muted">{t.handshakeHelp}</p>
                <Button
                  type="submit"
                  size="sm"
                  disabled={handshaking}
                  loading={handshaking}
                  className="mt-2"
                  data-testid="handshake-action"
                >
                  {t.handshakeAction}
                </Button>
                {handshakeError && (
                  <p className="mt-1 text-sm text-danger" role="alert">
                    {t.handshakeFail}
                  </p>
                )}
              </form>
            </section>
          )}

          {/* Handshake success / prescription-pending state */}
          {isPrescriptionPending && (
            <div
              className="rounded-md bg-success-soft/30 px-3 py-3 text-sm text-success"
              data-testid="handshake-success"
            >
              <p>{t.handshakeSuccess}</p>
              <p className="mt-1 text-xs text-txt-muted">
                {t.prescriptionPendingCta}
              </p>
            </div>
          )}

          {/* Closed state */}
          {currentStage === "closed" && (
            <div
              className="rounded-md bg-muted-soft px-3 py-3 text-sm text-txt-muted"
              data-testid="closed-state"
            >
              <p>{consoleT.stageClosed}</p>
            </div>
          )}
        </div>
      )}
    </>
  );
}
