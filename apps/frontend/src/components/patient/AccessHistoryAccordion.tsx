"use client";

// MOD-011 (access-history ledger) / FEAT-003 (patient trust view): #669 the
// "Who accessed my record" accordion, extracted from the record page so the
// record page's mobile privacy mirror and desktop rail (and, in #671, the
// homepage rail) compose one component. It owns its own access-history
// fetch state, the latest-five inline slice, the expand/collapse details, and
// the consent-log footer entry point; `zone` swaps the testid set so a test
// can scope copy to the mobile card or the rail. The mobile copy renders the
// shared ErrorBanner (which owns `error-banner`); the rail renders a lighter
// inline error so desktop users still get Retry without duplicating testids.
//
// The record page mounts both zones (Tailwind toggles which is visible), so a
// per-patient module store shares one fetch across mounts: one request, one
// retry, and identical state in both copies - exactly the single state the
// page held before the extraction. The store is dropped when its last listener
// unmounts, so a fresh mount refetches.

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useSyncExternalStore } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { ApiError } from "@/lib/api-errors";
import { fetchAccessHistory, type AccessHistoryEntry } from "@/lib/audit/api";
import { counterpartyLabel, counterpartyRole } from "@/lib/consent/consentView";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { formatOccurredAt } from "@/lib/record/timelineView";

// PROTO-3.1 (#511): only the 5 most recent rows render inline; the badge shows
// the full count and the consent-log link routes to the complete audit.
const ACCESS_MOST_RECENT_COUNT = 5;

type LoadStatus = "loading" | "ready" | "error";

interface AccessHistoryState {
  status: LoadStatus;
  entries: AccessHistoryEntry[] | null;
  traceId: string | undefined;
  bannerOpen: boolean;
}

const INITIAL_STATE: AccessHistoryState = {
  status: "loading",
  entries: null,
  traceId: undefined,
  bannerOpen: false,
};

class AccessHistoryStore {
  private state: AccessHistoryState = INITIAL_STATE;
  private listeners = new Set<() => void>();
  private started = false;

  constructor(private readonly patientId: number) {}

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    if (!this.started) this.load();
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0) {
        // Deferred so a transient mount/unmount/mount (StrictMode, or a
        // same-tick remount) reuses the store instead of refetching; a real
        // navigation unmounts, the microtask drops the store, and the next
        // mount starts a fresh fetch.
        queueMicrotask(() => {
          if (
            this.listeners.size === 0 &&
            stores.get(this.patientId) === this
          ) {
            stores.delete(this.patientId);
          }
        });
      }
    };
  };

  getSnapshot = (): AccessHistoryState => this.state;

  private setState(patch: Partial<AccessHistoryState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  load = (): void => {
    this.started = true;
    this.setState({ status: "loading" });
    fetchAccessHistory(this.patientId)
      .then((data) => {
        // Newest-first by accessed_at for a stable reading order.
        const sorted = [...data.entries].sort(
          (a, b) =>
            new Date(b.accessed_at).getTime() -
            new Date(a.accessed_at).getTime(),
        );
        this.setState({ entries: sorted, status: "ready", bannerOpen: false });
      })
      .catch((error: unknown) => {
        this.setState({
          traceId: error instanceof ApiError ? error.traceId : undefined,
          status: "error",
          bannerOpen: true,
        });
      });
  };

  retry = (): void => this.load();

  dismiss = (): void => this.setState({ bannerOpen: false });
}

const stores = new Map<number, AccessHistoryStore>();

function getStore(patientId: number): AccessHistoryStore {
  let store = stores.get(patientId);
  if (!store) {
    store = new AccessHistoryStore(patientId);
    stores.set(patientId, store);
  }
  return store;
}

function useAccessHistory(patientId: number): {
  status: LoadStatus;
  entries: AccessHistoryEntry[] | null;
  traceId: string | undefined;
  bannerOpen: boolean;
  onRetry: () => void;
  onDismiss: () => void;
} {
  const store = useMemo(() => getStore(patientId), [patientId]);
  const state = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );
  return {
    status: state.status,
    entries: state.entries,
    traceId: state.traceId,
    bannerOpen: state.bannerOpen,
    onRetry: store.retry,
    onDismiss: store.dismiss,
  };
}

export type AccessHistoryZone = "mobile" | "rail";

export type AccessHistoryAccordionProps = {
  patientId: number;
  zone: AccessHistoryZone;
};

export function AccessHistoryAccordion({
  patientId,
  zone,
}: AccessHistoryAccordionProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].record;
  const {
    status: accessStatus,
    entries: accessHistory,
    traceId: accessTraceId,
    bannerOpen: accessBannerOpen,
    onRetry,
    onDismiss,
  } = useAccessHistory(patientId);

  const isMobile = zone === "mobile";
  const listId = isMobile ? "access-history-list" : "access-history-rail-list";
  const loadingId = isMobile ? "access-loading" : "access-loading-rail";
  const entryPrefix = isMobile ? "access-entry-" : "access-entry-rail-";
  const keyPrefix = isMobile ? "entry" : "rail";
  const consentLinkId = isMobile
    ? "access-consent-log-link"
    : "access-consent-log-link-rail";
  const hasEntries =
    accessStatus === "ready" && !!accessHistory && accessHistory.length > 0;

  return (
    <section
      data-testid={isMobile ? "access-history" : "access-history-rail"}
      className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
    >
      <div className="flex items-center justify-between gap-2">
        {/* <h2> keeps the existing heading role on mobile; the rail uses a
              <strong> so the two zone copies never duplicate a heading
              level. */}
        {isMobile ? (
          <h2 className="text-base font-semibold text-txt">
            {t.accessHistory.heading}
          </h2>
        ) : (
          <strong className="text-base font-semibold text-txt">
            {t.accessHistory.heading}
          </strong>
        )}
        {hasEntries && (
          <span className="rounded-full bg-hairline-soft px-2 py-0.5 text-xs font-medium text-txt-muted">
            {accessHistory.length}
          </span>
        )}
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer list-none text-sm text-txt-muted">
          <span className="flex items-center justify-between gap-2">
            {t.accessAccordionHint}
            <span aria-hidden="true" className="text-txt-muted">
              ▾
            </span>
          </span>
        </summary>
        <div className="mt-3">
          {accessBannerOpen &&
            (isMobile ? (
              <ErrorBanner
                message={t.accessHistory.loadError}
                traceId={accessTraceId}
                onRetry={onRetry}
                onDismiss={onDismiss}
              />
            ) : (
              <p
                className="mb-2 flex items-center justify-between gap-2 text-sm text-danger"
                data-testid="access-rail-error"
              >
                <span>{t.accessHistory.loadError}</span>
                <button
                  type="button"
                  onClick={onRetry}
                  data-testid="access-rail-retry"
                  className="shrink-0 rounded-md border border-danger-border px-2 py-1 text-xs font-medium text-danger hover:bg-danger-soft/60"
                >
                  Retry
                </button>
              </p>
            ))}
          {accessStatus === "loading" ? (
            <ul className="space-y-2" data-testid={loadingId}>
              {[0, 1, 2].map((row) => (
                <li
                  key={row}
                  className="h-10 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60"
                />
              ))}
            </ul>
          ) : accessStatus === "error" ||
            accessHistory === null ? null : accessHistory.length === 0 ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-txt">
                {t.accessHistory.emptyTitle}
              </p>
              <p className="text-sm text-txt-muted">
                {t.accessHistory.emptyBody}
              </p>
            </div>
          ) : (
            <ul className="space-y-2" data-testid={listId}>
              {accessHistory
                .slice(0, ACCESS_MOST_RECENT_COUNT)
                .map((entry, index) => {
                  // #670: one labeling voice with the consent log - the shared
                  // three-step fallback (resolved name -> role word -> raw id).
                  // A denied row never shows a resolved name: the refused
                  // identity is not disclosed on the record owner's behalf.
                  const displayName = entry.denied
                    ? null
                    : entry.actor_display_name;
                  const label = counterpartyLabel(
                    entry.actor_type ?? "",
                    String(entry.actor_id),
                    displayName,
                    lang,
                  );
                  const role = counterpartyRole(
                    entry.actor_type ?? "",
                    String(entry.actor_id),
                    lang,
                  );
                  const scope = entry.scope
                    ? `, ${t.accessHistory.scopePrefix}${entry.scope}`
                    : "";
                  return (
                    <li
                      key={`${keyPrefix}-${entry.actor_id}-${entry.accessed_at}-${index}`}
                      data-testid={`${entryPrefix}${index}`}
                    >
                      <div>
                        <span className="flex items-start gap-2">
                          <strong className="text-[0.9375rem] text-txt">
                            {label}
                          </strong>
                          {entry.denied && (
                            <span className="ml-auto shrink-0 rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium text-danger">
                              {t.accessHistory.deniedLabel}
                            </span>
                          )}
                        </span>
                        {/* The role word is its own muted line, only when the
                            label did not already fall back to it (#654/#670). */}
                        {role !== null && role !== label && (
                          <p className="mt-0.5 text-xs text-txt-muted">
                            {role}
                          </p>
                        )}
                        <p className="mt-0.5 text-[0.8125rem] text-txt-muted">
                          {formatOccurredAt(entry.accessed_at, lang)}
                          {scope}
                        </p>
                        {entry.denied && entry.denial_reason ? (
                          <p className="mt-0.5 text-xs text-txt-muted">
                            {t.accessHistory.deniedReasonPrefix}
                            {entry.denial_reason}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
            </ul>
          )}
        </div>
      </details>

      {/* "Open consent log" is a permanent entry point at the bottom of the
          section, visible without expanding the audit (prototype posture). */}
      <footer className="mt-3">
        <Link
          href="/patient/record/consent-log"
          data-testid={consentLinkId}
          className="inline-flex items-center gap-1 text-xs font-medium tracking-wide text-accent-strong hover:underline"
        >
          {t.openConsentLog}
          <ChevronRight size={14} aria-hidden="true" />
        </Link>
      </footer>
    </section>
  );
}
