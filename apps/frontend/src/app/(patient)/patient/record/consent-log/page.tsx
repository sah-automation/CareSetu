"use client";

// PHASE-3 T9 (#218): Consent log screen (blueprint section 5.5, binding
// prototype prototype/phase-3/consent-log.html). The patient's control panel
// for sharing: every consent interaction with expandable receipts, inline
// revoke with confirmation, and the egress slice showing what has left the
// record. Pending requests sort above everything; revoked grants stay visible
// with plainly stated stop-forward copy. Fully bilingual EN/HI.

import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  fetchConsentLog,
  revokeConsent,
  fetchEgressLog,
  type ConsentView,
  type EgressLogEntry,
} from "@/lib/consent/api";
import {
  counterpartyLabel,
  counterpartyInitials,
} from "@/lib/consent/consentView";

type LoadStatus = "loading" | "ready" | "error";

const BADGE_TONE: Record<string, string> = {
  requested: "bg-warn-soft text-warn-text",
  granted: "bg-accent-soft text-accent-strong",
  revoked: "bg-hairline-soft text-txt-muted",
};

const BADGE_KEY: Record<
  string,
  keyof (typeof STRINGS)["en"]["consentLog"]["badge"]
> = {
  requested: "requested",
  granted: "active",
  revoked: "revoked",
};

function formatDateTime(iso: string, locale: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function formatMetaDate(
  iso: string,
  locale: string,
  kind: string,
  t: (typeof STRINGS)["en"]["consentLog"],
): string {
  const date = formatDateTime(iso, locale);
  const prefix = kind === "requested" ? t.metaRequested : t.metaGranted;
  return `${prefix} ${date}`;
}

function receiptLine(
  event: { kind: string; version: number; occurred_at: string },
  locale: string,
  t: (typeof STRINGS)["en"]["consentLog"],
): string {
  const date = formatDateTime(event.occurred_at, locale);
  const versionSuffix = event.version > 1 ? ` v${event.version}` : "";
  switch (event.kind) {
    case "requested":
      return t.receiptRequested.replace("{date}", date) + versionSuffix;
    case "granted":
      return t.receiptGranted.replace("{date}", date) + versionSuffix;
    case "revoked":
      return t.receiptRevoked.replace("{date}", date) + versionSuffix;
    default:
      return `${event.kind} ${date}${versionSuffix}.`;
  }
}

export default function ConsentLogPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].consentLog;
  const locale = lang === "hi" ? "hi-IN" : "en-IN";

  const [status, setStatus] = useState<LoadStatus>("loading");
  const [consents, setConsents] = useState<ConsentView[]>([]);
  const [egress, setEgress] = useState<EgressLogEntry[]>([]);
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);

  // Revoke sheet state
  const [revokeTarget, setRevokeTarget] = useState<ConsentView | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([fetchConsentLog(), fetchEgressLog()])
      .then(([log, egressLog]) => {
        setConsents(log.items);
        setEgress(egressLog.items);
        setStatus("ready");
        setBannerOpen(false);
      })
      .catch((error: unknown) => {
        setErrorTraceId(error instanceof ApiError ? error.traceId : undefined);
        setStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Sort: pending (requested) first, then by updated_at descending
  const sortedConsents = useMemo(() => {
    return [...consents].sort((a, b) => {
      const aPending = a.status === "requested" ? 0 : 1;
      const bPending = b.status === "requested" ? 0 : 1;
      if (aPending !== bPending) return aPending - bPending;
      return (
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    });
  }, [consents]);

  const pendingConsents = useMemo(
    () => sortedConsents.filter((c) => c.status === "requested"),
    [sortedConsents],
  );

  const historyConsents = useMemo(
    () => sortedConsents.filter((c) => c.status !== "requested"),
    [sortedConsents],
  );

  const handleRevoke = useCallback(async () => {
    if (!revokeTarget) return;
    setRevoking(true);
    try {
      const updated = await revokeConsent(revokeTarget.consent_id);
      setConsents((prev) =>
        prev.map((c) => (c.consent_id === updated.consent_id ? updated : c)),
      );
      setRevokeTarget(null);
      setToast(t.revokeConfirm.done);
      setTimeout(() => setToast(null), 3500);
    } catch {
      // Error stays silent; the sheet remains open for retry
    } finally {
      setRevoking(false);
    }
  }, [revokeTarget, t.revokeConfirm.done]);

  return (
    <>
      <PageHeader
        title={t.title}
        description={t.description}
        breadcrumbs={[
          {
            label: STRINGS[lang].record.title,
            href: "/patient/record",
          },
          { label: t.title },
        ]}
      />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadError}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {status === "loading" ? (
        <div className="space-y-3" data-testid="consent-log-loading">
          {[0, 1, 2].map((row) => (
            <div
              key={row}
              className="h-24 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60"
            />
          ))}
        </div>
      ) : status === "error" ? null : consents.length === 0 ? (
        <EmptyState title={t.empty.title} body={t.empty.body} />
      ) : (
        <>
          {/* Pending requests - always above everything */}
          {pendingConsents.length > 0 && (
            <section data-testid="pending-section">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                {t.pendingHeading}
              </h2>
              <div className="space-y-2">
                {pendingConsents.map((c) => (
                  <ConsentCard
                    key={c.consent_id}
                    consent={c}
                    t={t}
                    locale={locale}
                    onRevoke={setRevokeTarget}
                  />
                ))}
              </div>
            </section>
          )}

          {/* History - active and revoked grants */}
          {historyConsents.length > 0 && (
            <section
              className={pendingConsents.length > 0 ? "mt-6" : ""}
              data-testid="history-section"
            >
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-txt-muted">
                {t.historyHeading}
              </h2>
              <div className="space-y-2">
                {historyConsents.map((c) => (
                  <ConsentCard
                    key={c.consent_id}
                    consent={c}
                    t={t}
                    locale={locale}
                    onRevoke={setRevokeTarget}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Egress slice */}
          {egress.length > 0 && (
            <section
              className={sortedConsents.length > 0 ? "mt-6" : ""}
              data-testid="egress-section"
            >
              <h2 className="text-base font-semibold text-txt">
                {t.egress.heading}
              </h2>
              <p className="mb-3 text-sm text-txt-muted">
                {t.egress.description}
              </p>
              <div className="overflow-x-auto rounded-lg border border-hairline">
                <table
                  className="w-full text-left text-sm"
                  data-testid="egress-table"
                >
                  <thead>
                    <tr className="border-b border-hairline bg-hairline-soft/40">
                      <th className="px-3 py-2 font-medium text-txt-muted">
                        {t.egress.th.when}
                      </th>
                      <th className="px-3 py-2 font-medium text-txt-muted">
                        {t.egress.th.what}
                      </th>
                      <th className="px-3 py-2 font-medium text-txt-muted">
                        {t.egress.th.to}
                      </th>
                      <th className="px-3 py-2 font-medium text-txt-muted">
                        {t.egress.th.via}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {egress.map((entry) => (
                      <tr
                        key={entry.egress_id}
                        className="border-b border-hairline last:border-0"
                      >
                        <td className="whitespace-nowrap px-3 py-2">
                          {formatDateTime(entry.disclosed_at, locale)}
                        </td>
                        <td className="px-3 py-2">{entry.record_scope}</td>
                        <td className="px-3 py-2">
                          {counterpartyLabel(
                            entry.counterparty_type,
                            entry.counterparty_id,
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-txt-muted">
                          {entry.lineage_ref}
                          {entry.version > 1 ? ` v${entry.version}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {/* Revoke confirmation sheet */}
      <Sheet
        open={revokeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRevokeTarget(null);
        }}
      >
        <SheetContent side="bottom" data-testid="revoke-sheet">
          <SheetHeader>
            <SheetTitle>{t.revokeConfirm.title}</SheetTitle>
            <SheetDescription>{t.revokeConfirm.body}</SheetDescription>
          </SheetHeader>
          <SheetFooter className="mt-4 flex-row gap-2 sm:gap-2">
            <button
              type="button"
              onClick={handleRevoke}
              disabled={revoking}
              className={cn(
                "flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
                "bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50",
              )}
              data-testid="revoke-confirm"
            >
              {revoking ? "..." : t.revokeConfirm.confirm}
            </button>
            <button
              type="button"
              onClick={() => setRevokeTarget(null)}
              className="flex-1 rounded-lg border border-hairline bg-surface px-4 py-2.5 text-sm font-medium text-txt-sub transition-colors hover:bg-hairline-soft"
              data-testid="revoke-cancel"
            >
              {t.revokeConfirm.cancel}
            </button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Toast */}
      {toast && (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-txt px-4 py-2 text-sm text-on-txt shadow-lg"
          data-testid="toast"
        >
          {toast}
        </div>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  ConsentCard - one row in the pending or history list                       */
/* -------------------------------------------------------------------------- */

interface ConsentCardProps {
  consent: ConsentView;
  t: (typeof STRINGS)["en"]["consentLog"];
  locale: string;
  onRevoke: (consent: ConsentView) => void;
}

function ConsentCard({ consent, t, locale, onRevoke }: ConsentCardProps) {
  const label = counterpartyLabel(
    consent.counterparty_type,
    consent.counterparty_id,
  );
  const initials = counterpartyInitials(label);
  const badgeKey = BADGE_KEY[consent.status] ?? "requested";
  const badgeLabel = t.badge[badgeKey];
  const badgeClass = BADGE_TONE[consent.status] ?? BADGE_TONE.requested;

  // Build meta line
  const metaParts: string[] = [];
  metaParts.push(`#${consent.lineage_ref}`);
  if (consent.version > 1) metaParts.push(`v${consent.version}`);
  metaParts.push(
    formatMetaDate(
      consent.status === "requested" ? consent.created_at : consent.updated_at,
      locale,
      consent.status === "requested" ? "requested" : "granted",
      t,
    ),
  );

  return (
    <div
      className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
      data-testid={`consent-${consent.consent_id}`}
    >
      {/* Header row: avatar + name + badge */}
      <div className="flex items-start gap-2">
        <span
          aria-hidden="true"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong"
        >
          {initials}
        </span>
        <div className="min-w-0 flex-1">
          <strong className="text-base">{label}</strong>
        </div>
        <span
          className={cn(
            "ml-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            badgeClass,
          )}
        >
          {badgeLabel}
        </span>
      </div>

      {/* Scope */}
      <p className="mt-2 text-sm text-txt-sub">{consent.record_scope}</p>

      {/* Meta */}
      <p className="mt-1 text-xs text-txt-muted">
        {metaParts.join(" \u00b7 ")}
      </p>

      {/* Expandable receipt timeline */}
      {consent.events.length > 0 && (
        <details className="mt-2" data-testid={`receipt-${consent.consent_id}`}>
          <summary className="cursor-pointer text-sm font-medium text-accent-strong hover:underline">
            {t.viewReceipt}
          </summary>
          <ul className="mt-2 space-y-1 border-l-2 border-hairline pl-3">
            {consent.events.map((event, idx) => (
              <li key={idx} className="text-sm text-txt-sub">
                {receiptLine(event, locale, t)}
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Actions */}
      {consent.status === "requested" && (
        <div className="mt-3 flex gap-2">
          {/* T10 mount point: Allow/Decline buttons for the grant-moment
              sheet. Clean mount for T10 to wire up. */}
          <span
            className="flex-1"
            data-testid={`t10-mount-${consent.consent_id}`}
          />
        </div>
      )}

      {consent.status === "granted" && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => onRevoke(consent)}
            className="rounded-lg border border-danger-border bg-danger-soft px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger-soft/80"
            data-testid={`revoke-${consent.consent_id}`}
          >
            {t.revoke}
          </button>
        </div>
      )}

      {/* Stop-forward copy for revoked grants */}
      {consent.status === "revoked" && (
        <p
          className="mt-3 rounded-md bg-hairline-soft/60 px-3 py-2 text-xs text-txt-muted"
          data-testid={`stop-forward-${consent.consent_id}`}
        >
          {t.stopForward}
        </p>
      )}
    </div>
  );
}
