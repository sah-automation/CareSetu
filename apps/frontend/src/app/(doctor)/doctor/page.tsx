"use client";

// PHASE-8.1 T12 (#450): doctor console landing page - replaces the Phase 5
// placeholder with the review queue (low-confidence first, oldest within each
// group, US-11/12), open care cases (US-15), the consultation fee editor
// (US-25), and coming-soon patients/profile tabs (US-26). The review queue
// items link into the case workspace (review/[intakeId], cases/[caseId]);
// those pages are built by #451-#453. All copy bilingual en/hi (REQ-006).

import type { FormEvent } from "react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatFeePaise } from "@/components/pick/DoctorPickCard";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import { fetchReviewQueue, type ReviewQueueItem } from "@/lib/intake/api";
import {
  listOpenCases,
  type CaseDetailView,
  type CareCaseStage,
} from "@/lib/care/api";
import { updateConsultationFee } from "@/lib/partner/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// ---- helpers ----

type LoadStatus = "loading" | "ready" | "error";

function waitingSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "<1h";
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

function confidenceDisplay(
  value: number | null,
  t: Dictionary["doctorConsole"],
): string {
  if (value == null) return "\u2014";
  return `${Math.round(value * 100)}%`;
}

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

function sortQueue(items: ReviewQueueItem[]): ReviewQueueItem[] {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (a.low_confidence !== b.low_confidence) return a.low_confidence ? -1 : 1;
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });
  return sorted;
}

// ---- sub-components ----

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="queue-skeleton">
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

// ---- main page ----

export default function DoctorDashboardPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [cases, setCases] = useState<CaseDetailView[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  // Fee editor state
  const [feeInput, setFeeInput] = useState("");
  const [feeCurrentPaise, setFeeCurrentPaise] = useState<number | null>(null);
  const [feeSaving, setFeeSaving] = useState(false);
  const [feeSaved, setFeeSaved] = useState(false);
  const [feeError, setFeeError] = useState(false);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    Promise.all([fetchReviewQueue(), listOpenCases()])
      .then(([q, c]) => {
        setQueue(q);
        setCases(c);
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

  const sortedQueue = useMemo(() => sortQueue(queue), [queue]);

  // ---- fee handlers ----

  async function handleSaveFee(e: FormEvent) {
    e.preventDefault();
    setFeeSaving(true);
    setFeeSaved(false);
    setFeeError(false);
    try {
      const rupees = Number(feeInput);
      if (!Number.isFinite(rupees) || rupees < 0) throw new Error("invalid");
      const paise = Math.round(rupees * 100);
      await updateConsultationFee(paise);
      setFeeCurrentPaise(paise);
      setFeeSaved(true);
    } catch {
      setFeeError(true);
    } finally {
      setFeeSaving(false);
    }
  }

  async function handleClearFee() {
    setFeeSaving(true);
    setFeeSaved(false);
    setFeeError(false);
    try {
      await updateConsultationFee(null);
      setFeeCurrentPaise(null);
      setFeeInput("");
      setFeeSaved(true);
    } catch {
      setFeeError(true);
    } finally {
      setFeeSaving(false);
    }
  }

  // ---- render ----

  const queueReady = loadStatus === "ready";
  const queueEmpty = queueReady && sortedQueue.length === 0;
  const casesEmpty = queueReady && cases.length === 0;

  return (
    <>
      <PageHeader title={t.title} description={t.consoleDescription} />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {/* Review queue section */}
      <section className="space-y-3" data-testid="review-queue">
        <h2 className="text-sm font-semibold text-txt">{t.queueHeading}</h2>

        {loadStatus === "loading" && <LoadingSkeleton />}

        {queueEmpty && <EmptyState title={t.queueEmpty} />}

        {queueReady && sortedQueue.length > 0 && (
          <ul className="space-y-2" data-testid="queue-list">
            {sortedQueue.map((item) => (
              <li
                key={item.pre_summary_id}
                data-testid="queue-item"
                className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="text-sm font-medium text-txt"
                      data-testid="queue-item-title"
                    >
                      {item.patient_name ?? t.patientFallback}
                    </span>
                    {item.patient_age != null && (
                      <span
                        className="text-xs text-txt-muted"
                        data-testid="queue-item-age"
                      >
                        {t.patientAge(item.patient_age)}
                      </span>
                    )}
                    {item.low_confidence && (
                      <span
                        data-testid="queue-item-verify"
                        className="inline-flex items-center rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning-text"
                      >
                        {t.verifyChip}
                      </span>
                    )}
                    <span
                      data-testid="queue-item-sections"
                      className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
                    >
                      {t.sectionsCount(item.section_count)}
                    </span>
                  </div>
                  {item.snippet != null && item.snippet.length > 0 && (
                    <p
                      data-testid="queue-item-snippet"
                      className="line-clamp-2 text-xs text-txt-muted"
                    >
                      {item.snippet}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 text-xs text-txt-muted">
                    <span data-testid="queue-item-intake">
                      {t.queueItemMeta(item.intake_id)}
                    </span>
                    <span data-testid="queue-item-confidence">
                      {t.confidenceLabel}:{" "}
                      {confidenceDisplay(item.structuring_confidence, t)}
                    </span>
                    <span data-testid="queue-item-waiting">
                      {t.waitingFor(waitingSince(item.created_at))}
                    </span>
                  </div>
                </div>
                <Link
                  href={`/doctor/review/${item.intake_id}`}
                  data-testid="queue-item-review"
                  className="inline-flex shrink-0 items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                >
                  {t.reviewAction}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Open cases section */}
      <section className="mt-6 space-y-3" data-testid="open-cases">
        <h2 className="text-sm font-semibold text-txt">{t.casesHeading}</h2>

        {loadStatus === "loading" && <LoadingSkeleton />}

        {casesEmpty && <EmptyState title={t.casesEmpty} />}

        {queueReady && cases.length > 0 && (
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
      </section>

      {/* Consultation fee editor */}
      <section
        className="mt-6 rounded-lg border border-border bg-bg p-4"
        data-testid="fee-editor"
      >
        <h2 className="text-sm font-semibold text-txt">{t.feeEditorHeading}</h2>
        <p className="mt-1 text-sm text-txt-muted">{t.feeEditorHelp}</p>

        {feeCurrentPaise !== null && (
          <p className="mt-2 text-sm text-txt" data-testid="fee-current">
            {formatFeePaise(feeCurrentPaise)}
          </p>
        )}

        <form className="mt-3 flex items-end gap-2" onSubmit={handleSaveFee}>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-txt-muted">
              {t.feeFieldLabel}
            </span>
            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="1"
              value={feeInput}
              onChange={(e) => setFeeInput(e.target.value)}
              placeholder={t.feeFieldPlaceholder}
              className="h-9 rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              data-testid="fee-input"
            />
          </label>
          <Button
            type="submit"
            size="sm"
            disabled={feeSaving || feeInput === ""}
            loading={feeSaving}
            data-testid="fee-save"
          >
            {t.saveFee}
          </Button>
          {feeCurrentPaise !== null && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={feeSaving}
              onClick={handleClearFee}
              data-testid="fee-clear"
            >
              {t.clearFee}
            </Button>
          )}
        </form>

        {feeSaved && (
          <p className="mt-2 text-sm text-success" data-testid="fee-message">
            {t.feeSaved}
          </p>
        )}
        {feeError && (
          <p
            className="mt-2 text-sm text-danger"
            data-testid="fee-message"
            role="alert"
          >
            {t.feeSaveFailed}
          </p>
        )}
      </section>

      {/* Coming-soon tabs */}
      <section className="mt-6 space-y-2" data-testid="coming-soon">
        <Link
          href="#"
          aria-disabled="true"
          tabIndex={-1}
          className="pointer-events-none block rounded-lg border border-hairline bg-accent-soft px-4 py-3 text-txt opacity-60"
          data-testid="coming-soon-patients"
        >
          <span className="text-sm font-medium">{t.patientsComingSoon}</span>
          <p className="mt-0.5 text-xs text-txt-muted">{t.comingSoonBody}</p>
        </Link>
        <Link
          href="#"
          aria-disabled="true"
          tabIndex={-1}
          className="pointer-events-none block rounded-lg border border-hairline bg-accent-soft px-4 py-3 text-txt opacity-60"
          data-testid="coming-soon-profile"
        >
          <span className="text-sm font-medium">{t.profileComingSoon}</span>
          <p className="mt-0.5 text-xs text-txt-muted">{t.comingSoonBody}</p>
        </Link>
      </section>
    </>
  );
}
