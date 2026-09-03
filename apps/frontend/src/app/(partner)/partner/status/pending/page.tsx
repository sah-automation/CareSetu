"use client";

// PHASE-2.6 T10 (#201) / PHASE-5 FE T3 (#281): partner "pending / under
// verification" state screen (blueprint s4.4). Lives inside the partner route
// group, so the session guard (/partner/:path*) and the full AppShell wrap it
// automatically; any post-login landing while the application is pending
// arrives here instead of the channel home.
//
// Reads GET /v1/partner/me + GET /v1/partner/me/verification to show
// verification round state, submitted-at timestamp, and partner identity.
// Polls every 10s while status is "Under Verification" and stops when the
// operator decides (approve -> redirect, reject -> redirect to rejected screen).

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchPartnerMe,
  fetchPartnerVerification,
  type PartnerMeView,
  type PartnerVerificationStatusView,
} from "@/lib/partner/api";
import { ApiError } from "@/lib/api-errors";

const POLL_INTERVAL_MS = 10_000;

type LoadStatus = "loading" | "ready" | "error";

function formatSubmittedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

export default function PartnerStatusPendingPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.pending;
  const router = useRouter();

  const [partner, setPartner] = useState<PartnerMeView | null>(null);
  const [verification, setVerification] =
    useState<PartnerVerificationStatusView | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([fetchPartnerMe(), fetchPartnerVerification()])
      .then(([me, ver]) => {
        setPartner(me);
        setVerification(ver);
        setStatus("ready");
        setBannerOpen(false);

        // Redirect when operator has decided
        if (me.status === "Active") {
          router.replace("/partner");
        } else if (me.status === "Rejected") {
          router.replace("/partner/status/rejected");
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

  // Poll while status is "Under Verification"
  useEffect(() => {
    if (partner?.status === "Under Verification") {
      pollRef.current = setInterval(load, POLL_INTERVAL_MS);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [partner?.status, load]);

  return (
    <div className="mx-auto w-full max-w-xl">
      <PageHeader title={t.headerTitle} />
      <section
        className="rounded-lg border border-hairline bg-surface p-6 text-center shadow-card"
        data-testid="partner-pending-card"
        aria-labelledby="partner-pending-title"
      >
        {status === "loading" && !partner ? (
          <div data-testid="partner-pending-loading" className="space-y-3">
            <div className="mx-auto h-10 w-10 animate-pulse rounded-full bg-hairline-soft" />
            <div className="mx-auto h-5 w-32 animate-pulse rounded bg-hairline-soft" />
            <div className="mx-auto h-6 w-56 animate-pulse rounded bg-hairline-soft" />
            <dl className="mx-auto mt-4 max-w-sm space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex justify-between gap-4">
                  <dt className="h-4 w-24 animate-pulse rounded bg-hairline-soft" />
                  <dd className="h-4 w-32 animate-pulse rounded bg-hairline-soft" />
                </div>
              ))}
            </dl>
          </div>
        ) : (
          <>
            <p className="text-4xl" aria-hidden="true">
              ⏳
            </p>
            <span
              className="mt-2 inline-block rounded-full bg-warn-soft px-2 py-0.5 text-xs font-semibold text-warn-text"
              data-testid="partner-status-badge"
            >
              {t.badge}
            </span>
            <h1 id="partner-pending-title" className="mt-3 text-xl font-bold">
              {t.title}
            </h1>

            <dl className="mx-auto mt-4 max-w-sm space-y-1 text-left text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-txt-muted">{t.submittedLabel}</dt>
                <dd className="text-right font-medium">
                  {formatSubmittedAt(partner?.created_at) ||
                    t.detailPlaceholder}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-txt-muted">{t.applicationLabel}</dt>
                <dd className="text-right font-medium">
                  {partner
                    ? `${partner.partner_type
                        .charAt(0)
                        .toUpperCase()}${partner.partner_type.slice(1)}`
                    : t.detailPlaceholder}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-txt-muted">{t.verifyingLabel}</dt>
                <dd className="text-right font-medium">
                  {verification?.decision_reason || t.detailPlaceholder}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-txt-muted">{t.windowLabel}</dt>
                <dd className="text-right font-medium">{t.windowValue}</dd>
              </div>
            </dl>

            <div
              role="note"
              data-testid="partner-pending-note"
              className="mt-4 rounded-md border border-hairline bg-page-bg px-3 py-2 text-left text-sm"
            >
              {t.infoBanner}
            </div>

            <a
              href="#"
              className="mt-4 inline-block rounded-md border border-hairline px-4 py-2 text-sm"
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
