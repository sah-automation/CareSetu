"use client";

// PHASE-2.6 T10 (#201) / PHASE-5 FE T3 (#281): partner "rejected with reason"
// state screen (blueprint s4.4, FEAT-014 scenario 2). Same group placement as
// the pending screen - session guard + full AppShell come from the partner
// layout.
//
// Reads GET /v1/partner/me + GET /v1/partner/rejection-reason to show the
// specific rejection reason. The appeal CTA calls POST /v1/partner/appeal and
// on success routes back to /partner/status/pending (the partner re-enters
// the verification queue).

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchPartnerMe,
  fetchRejectionReason,
  appealRejection,
  type PartnerMeView,
  type RejectionReasonView,
} from "@/lib/partner/api";
import { ApiError } from "@/lib/api-errors";

type LoadStatus = "loading" | "ready" | "error";

const POLL_INTERVAL_MS = 10_000;

export default function PartnerStatusRejectedPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.rejected;
  const router = useRouter();

  const [partner, setPartner] = useState<PartnerMeView | null>(null);
  const [rejection, setRejection] = useState<RejectionReasonView | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);
  const [appealPending, setAppealPending] = useState(false);
  const [appealDone, setAppealDone] = useState(false);
  const [appealError, setAppealError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([fetchPartnerMe(), fetchRejectionReason()])
      .then(([me, reason]) => {
        setPartner(me);
        setRejection(reason);
        setStatus("ready");
        setBannerOpen(false);

        // Redirect when the operator moves the application out of Rejected.
        if (me.status === "Active") {
          router.replace("/partner");
        } else if (me.status === "Under Verification") {
          router.replace("/partner/status/pending");
        }
      })
      .catch((error: unknown) => {
        setErrorTraceId(error instanceof ApiError ? error.traceId : undefined);
        setStatus("error");
        setBannerOpen(true);
      });
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while the application stays Rejected (operator may reconsider and
  // move it back into the verification queue).
  useEffect(() => {
    if (partner?.status === "Rejected") {
      pollRef.current = setInterval(load, POLL_INTERVAL_MS);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [partner?.status, load]);

  const handleAppeal = useCallback(async () => {
    setAppealPending(true);
    setAppealError(null);
    try {
      await appealRejection();
      setAppealDone(true);
      // Redirect to pending screen after a brief moment so the user sees
      // the success message.
      setTimeout(() => router.replace("/partner/status/pending"), 1500);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Something went wrong. Please try again.";
      setAppealError(message);
    } finally {
      setAppealPending(false);
    }
  }, [router]);

  return (
    <div className="mx-auto w-full max-w-xl">
      <PageHeader title={t.headerTitle} />
      <section
        className="rounded-lg border border-hairline bg-surface p-6 text-center shadow-card"
        data-testid="partner-rejected-card"
        aria-labelledby="partner-rejected-title"
      >
        {status === "loading" && !partner ? (
          <div data-testid="partner-rejected-loading" className="space-y-3">
            <div className="mx-auto h-5 w-20 animate-pulse rounded-full bg-hairline-soft" />
            <div className="mx-auto h-6 w-56 animate-pulse rounded bg-hairline-soft" />
            <div className="mt-4 h-16 animate-pulse rounded-md bg-hairline-soft" />
            <div className="mt-3 h-4 w-48 animate-pulse rounded bg-hairline-soft" />
          </div>
        ) : (
          <>
            <span
              className="inline-block rounded-full bg-danger-soft px-2 py-0.5 text-xs font-semibold text-danger"
              data-testid="partner-status-badge"
            >
              {t.badge}
            </span>
            <h1 id="partner-rejected-title" className="mt-3 text-xl font-bold">
              {t.title}
            </h1>

            <div
              role="alert"
              data-testid="partner-rejection-reason"
              className="mt-4 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-left text-sm"
            >
              <p>
                <strong>{t.reasonHeading}</strong>{" "}
                {rejection?.rejection_reason || t.reasonPlaceholder}
              </p>
            </div>

            <p className="mt-3 text-sm text-txt-sub">{t.fixNote}</p>

            {appealDone ? (
              <p
                role="status"
                data-testid="partner-appeal-success"
                className="mt-3 rounded-md border border-success-border bg-success-soft px-3 py-2 text-left text-sm text-success-text"
              >
                {t.appealSuccess}
              </p>
            ) : null}

            {appealError ? (
              <p
                role="alert"
                data-testid="partner-appeal-error"
                className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-left text-sm text-danger"
              >
                {appealError}
              </p>
            ) : null}

            <button
              type="button"
              onClick={handleAppeal}
              disabled={appealPending || appealDone}
              data-testid="partner-resubmit-cta"
              className="mt-4 w-full rounded-md bg-accent px-4 py-2 font-semibold text-on-accent disabled:opacity-50"
            >
              {appealPending ? t.appealProcessing : t.resubmitCta}
            </button>
            <a
              href="#"
              className="mt-2 inline-block text-sm underline"
              data-testid="partner-help-link"
            >
              {t.helpCta}
            </a>
          </>
        )}
      </section>

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadError}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}
    </div>
  );
}
