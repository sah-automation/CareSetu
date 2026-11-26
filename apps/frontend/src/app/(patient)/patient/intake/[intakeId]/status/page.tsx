"use client";

// PHASE-7 T19 (#363): intake status list page - the patient sees where each
// submission stands with four statuses (Captured / Structuring / Ready for
// Review / Recapture needed) mapped 1:1 onto the backend machine status
// values (T02 state_machine.py). Statuses refresh from the backend
// (fetchIntake / fetchPreSummary) in-page via polling. A ready pre-summary
// offers a continue affordance into consultation booking (Phase 8 boundary);
// a ready intake with no pre-summary degrades to a raw-review note instead
// of the dead-end affordance (#390). Bilingual EN/HI per REQ-006.
// ARCH-P2 #835: intake detail and pre-summary read through useQuery.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useAuth } from "@/lib/auth/AuthContext";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchIntake,
  fetchPreSummary,
  type IntakeDetailView,
  type IntakeStatus,
  type PreSummaryView,
} from "@/lib/intake/api";
import { INTAKE_POLL_INTERVAL_MS, MAX_INTAKE_POLLS } from "@/lib/intake/voice";
import { cn } from "@/lib/utils";

type BannerState = {
  title: string;
  body: string;
  traceId?: string;
} | null;

/** The four UI-facing statuses shown in the list. */
const STATUS_STEPS: {
  key: IntakeStatus;
  i18nLabel: keyof typeof STRINGS.en.intake.status;
  i18nDesc: keyof typeof STRINGS.en.intake.status;
}[] = [
  {
    key: "captured",
    i18nLabel: "captured",
    i18nDesc: "capturedDesc",
  },
  {
    key: "structuring",
    i18nLabel: "structuring",
    i18nDesc: "structuringDesc",
  },
  {
    key: "ready_for_review",
    i18nLabel: "readyForReview",
    i18nDesc: "readyForReviewDesc",
  },
  {
    key: "re_record",
    i18nLabel: "reRecord",
    i18nDesc: "reRecordDesc",
  },
];

const TWO_MINUTES = 2 * 60 * 1000;

/**
 * Map a backend status to the index in STATUS_STEPS, or -1 if it is a
 * terminal/error state not in the four-step list.
 */
function statusIndex(status: IntakeStatus): number {
  return STATUS_STEPS.findIndex((s) => s.key === status);
}

/**
 * True when a fetchPreSummary rejection means no pre-summary exists for the
 * intake (ready_for_review degraded to raw doctor review). Any other failure
 * is a genuine error and keeps the page's error branch.
 */
function isMissingPreSummary(error: unknown): boolean {
  return error instanceof ApiError && error.code === "INTAKE_NOT_FOUND";
}

export function intakeStatusQueryKey(
  identityId: number | undefined,
  intakeId: number,
) {
  return ["intake", identityId, intakeId] as const;
}

export function intakePreSummaryQueryKey(
  identityId: number | undefined,
  intakeId: number,
) {
  return ["intake", identityId, intakeId, "pre-summary"] as const;
}

export default function IntakeStatusPage() {
  const params = useParams<{ intakeId: string }>();
  const intakeId = Number(params.intakeId);
  const { lang } = useLang();
  const dict = STRINGS[lang].intake;
  const t = dict.status;
  const nav = STRINGS[lang].nav;

  const { user } = useAuth();
  const identityId = user?.id;

  const [refreshing, setRefreshing] = useState(false);
  const [errorDismissed, setErrorDismissed] = useState(false);

  const queryClient = useQueryClient();

  const pollCountRef = useRef(0);

  const intakeQuery = useQuery({
    queryKey: intakeStatusQueryKey(identityId, intakeId),
    queryFn: () => fetchIntake(intakeId),
    staleTime: TWO_MINUTES,
    refetchInterval: (query) => {
      const data = query.state.data as IntakeDetailView | undefined;
      if (data?.status !== "structuring") {
        pollCountRef.current = 0;
        return false;
      }
      if (pollCountRef.current >= MAX_INTAKE_POLLS) return false;
      pollCountRef.current += 1;
      return INTAKE_POLL_INTERVAL_MS;
    },
  });

  const intake = intakeQuery.data ?? null;

  const preSummaryQuery = useQuery({
    queryKey: intakePreSummaryQueryKey(identityId, intakeId),
    queryFn: async () => {
      try {
        return await fetchPreSummary(intakeId);
      } catch (error: unknown) {
        if (isMissingPreSummary(error)) return null;
        throw error;
      }
    },
    enabled: intake?.status === "ready_for_review",
    staleTime: TWO_MINUTES,
  });

  const preSummary = preSummaryQuery.data ?? null;
  const preSummaryMissing =
    intake?.status === "ready_for_review" &&
    preSummaryQuery.isSuccess &&
    preSummary === null;

  const failingError = intakeQuery.isError
    ? intakeQuery.error
    : preSummaryQuery.isError
      ? preSummaryQuery.error
      : null;

  useEffect(() => {
    setErrorDismissed(false);
  }, [failingError]);

  const loadError: BannerState =
    failingError !== null && !errorDismissed
      ? {
          title: t.loadFailedTitle,
          body: t.loadFailedBody,
          traceId:
            failingError instanceof ApiError ? failingError.traceId : undefined,
        }
      : null;

  const reload = useCallback(async () => {
    const detailResult = await intakeQuery.refetch();
    const detail = detailResult.data;
    if (detail?.status === "ready_for_review") {
      await preSummaryQuery.refetch().catch(() => undefined);
    }
  }, [intakeQuery, preSummaryQuery]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const detailResult = await intakeQuery.refetch();
      const detail = detailResult.data;
      if (detail?.status === "ready_for_review") {
        await preSummaryQuery.refetch();
      } else {
        queryClient.removeQueries({
          queryKey: intakePreSummaryQueryKey(identityId, intakeId),
        });
      }
    } catch {
      // Silent - the existing state stays visible.
    } finally {
      setRefreshing(false);
    }
  }, [intakeQuery, preSummaryQuery, queryClient, identityId, intakeId]);

  if (intakeQuery.isPending && !intake) {
    return (
      <>
        <PageHeader
          title={t.title}
          breadcrumbs={[
            { label: nav.home, href: "/patient" },
            { label: dict.breadcrumb, href: "/patient/intake" },
            { label: t.breadcrumb },
          ]}
        />
        <p
          className="inline-flex items-center gap-2 text-sm text-txt-muted"
          data-testid="load-pending"
        >
          <span
            className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-hairline border-t-accent"
            aria-hidden="true"
          />
          {t.loading}
        </p>
      </>
    );
  }

  if (intakeQuery.isError || preSummaryQuery.isError || !intake) {
    return (
      <>
        <PageHeader
          title={t.title}
          breadcrumbs={[
            { label: nav.home, href: "/patient" },
            { label: dict.breadcrumb, href: "/patient/intake" },
            { label: t.breadcrumb },
          ]}
        />
        {loadError && (
          <ErrorBanner
            message={
              <>
                <strong className="font-semibold">{loadError.title}</strong>
                <span className="block">{loadError.body}</span>
              </>
            }
            traceId={loadError.traceId}
            onRetry={reload}
            onDismiss={() => setErrorDismissed(true)}
          />
        )}
      </>
    );
  }

  const currentIdx = statusIndex(intake.status);
  const isReRecord = intake.status === "re_record";
  const isReady = intake.status === "ready_for_review";
  const isFailed = intake.status === "failed";

  return (
    <>
      <PageHeader
        title={t.title}
        description={t.description}
        breadcrumbs={[
          { label: nav.home, href: "/patient" },
          { label: dict.breadcrumb, href: "/patient/intake" },
          { label: t.breadcrumb },
        ]}
      />

      <div
        className="mx-auto flex max-w-xl flex-col gap-4"
        data-testid="intake-status-page"
      >
        {/* Status list */}
        <section
          className="rounded-lg border border-hairline bg-surface shadow-card overflow-hidden"
          data-testid="status-list"
        >
          {STATUS_STEPS.map((step, index) => {
            const isCurrent = index === currentIdx;
            const isDone = currentIdx >= 0 && index < currentIdx;
            const label = t[step.i18nLabel] as string;
            const desc = t[step.i18nDesc] as string;

            return (
              <div
                key={step.key}
                className={cn(
                  "flex items-start gap-3 px-4 py-3",
                  index < STATUS_STEPS.length - 1 &&
                    "border-b border-hairline-soft",
                  isCurrent && "bg-accent-soft",
                  isDone && "opacity-60",
                )}
                data-testid={`status-row-${step.key}`}
              >
                {/* Step indicator dot */}
                <span
                  className={cn(
                    "mt-1 h-3 w-3 shrink-0 rounded-full",
                    isCurrent && "bg-accent ring-2 ring-accent-soft",
                    isDone && "bg-accent",
                    !isCurrent && !isDone && "bg-hairline",
                  )}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "text-sm font-semibold",
                      isCurrent ? "text-accent-strong" : "text-txt",
                    )}
                    data-testid={`status-label-${step.key}`}
                  >
                    {label}
                  </p>
                  <p className="mt-0.5 text-xs text-txt-muted">{desc}</p>
                </div>
                {isCurrent && (
                  <span
                    className="mt-0.5 shrink-0 text-accent-strong"
                    aria-hidden="true"
                    data-testid={`status-current-${step.key}`}
                  >
                    {"\u25CF"}
                  </span>
                )}
                {isDone && (
                  <span
                    className="mt-0.5 shrink-0 text-accent-strong"
                    aria-hidden="true"
                    data-testid={`status-done-${step.key}`}
                  >
                    {"\u2713"}
                  </span>
                )}
              </div>
            );
          })}

          {/* Failed state - terminal error, not part of the four steps */}
          {isFailed && (
            <div
              className="flex items-start gap-3 border-t border-hairline-soft bg-warn-soft px-4 py-3"
              data-testid="status-row-failed"
            >
              <span
                className="mt-1 h-3 w-3 shrink-0 rounded-full bg-warn-text"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-warn-text">
                  {t.failed}
                </p>
                <p className="mt-0.5 text-xs text-txt-muted">{t.failedDesc}</p>
              </div>
            </div>
          )}
        </section>

        {/* Refresh button */}
        <div className="flex justify-end">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            data-testid="btn-refresh"
          >
            {refreshing ? t.refreshing : t.refresh}
          </Button>
        </div>

        {/* Continue affordance - only when the pre-summary exists */}
        {isReady && preSummary && (
          <div className="flex flex-col gap-2" data-testid="continue-zone">
            <Button
              asChild
              size="lg"
              className="w-full"
              data-testid="btn-continue"
            >
              <Link href={`/patient/intake/${intakeId}/pick`}>
                {t.continue}
              </Link>
            </Button>
          </div>
        )}

        {/* Degraded - ready for review, no pre-summary (raw doctor review) */}
        {isReady && preSummaryMissing && (
          <div
            className="flex flex-col gap-1 rounded-lg border border-hairline bg-surface px-4 py-3 shadow-card"
            data-testid="raw-review-note"
          >
            <p className="text-sm text-txt-muted">{t.rawReviewNote}</p>
          </div>
        )}

        {/* Re-record / type instead affordance */}
        {isReRecord && (
          <div className="flex flex-col gap-2" data-testid="rerecord-zone">
            <Button
              asChild
              size="lg"
              className="w-full"
              data-testid="btn-rerecord"
            >
              <Link href={`/patient/intake/voice`}>{t.reRecordAction}</Link>
            </Button>
            <Button
              asChild
              variant="secondary"
              size="lg"
              className="w-full"
              data-testid="btn-type"
            >
              <Link href={`/patient/intake/text`}>{t.typeInstead}</Link>
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
