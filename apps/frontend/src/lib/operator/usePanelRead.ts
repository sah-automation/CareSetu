"use client";

// #709 C2b: the one load-state seam every Observability panel page runs on
// (plan-phase14-observability §9.2, blueprint §9.1). The overview and the four
// panel routes - cost, usage, quality, health - each read one C1 endpoint and
// owe the operator the same three states, so the states live here rather than
// being retyped per page.
//
// The closure mirrors the C2a overview page exactly (its `LoadStatus`, its
// retry, its empty rule), for the same reasons that page gives: a failed read
// renders one dismissible banner with a Retry and the API's `trace_id`; a panel
// with nothing in it says so rather than drawing an empty axis. A page that
// re-implemented this would drift from the overview within one release - which
// is why the overview runs on this hook too rather than keeping a copy of it.

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";

/** The three states a panel read can be in. */
export type PanelLoadStatus = "loading" | "ready" | "error";

export interface PanelRead<T> {
  /** The loaded payload, or `null` while in flight or after a failure. */
  data: T | null;
  status: PanelLoadStatus;
  /** The API's trace id for a failed read, for support correlation. */
  errorTraceId: string | undefined;
  /**
   * Whether the failure was an `ApiError` (a response the API chose to send,
   * carrying a trace id) or an unexpected throw (a network failure or a bug,
   * carrying no trace id). Per error-handling-observability §1 these are
   * different classes with different handling: only the expected one may show
   * the API's message, and only an operational failure is worth an alarm. The
   * caller picks the copy; this hook must not flatten the two into one.
   */
  error: { traceId?: string; expected: boolean } | null;
  /** Whether the error banner is currently showing. */
  bannerOpen: boolean;
  /** Re-run the read (the mount effect, and the banner's Retry). */
  reload: () => void;
  /** Hide the banner without leaving the page broken. */
  dismissBanner: () => void;
}

/**
 * Run one observability read and own its loading / ready / error state.
 *
 * `load` is held in a ref rather than an effect dependency because callers pass
 * it inline (`.then` on a fetcher), which is a fresh closure every render. A
 * dependency here would re-fire the read on every render and never settle. The
 * ref keeps `reload` stable, so the mount effect runs exactly once and Retry
 * re-runs the identical read rather than a re-derived one.
 */
export function usePanelRead<T>(load: () => Promise<T>): PanelRead<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<PanelLoadStatus>("loading");
  const [error, setError] = useState<PanelRead<T>["error"]>(null);
  const [bannerOpen, setBannerOpen] = useState(false);

  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  const reload = useCallback(() => {
    setStatus("loading");
    loadRef
      .current()
      .then((loaded) => {
        setData(loaded);
        setStatus("ready");
        setError(null);
        setBannerOpen(false);
      })
      .catch((thrown: unknown) => {
        // An `ApiError` is a response the API chose to send; anything else is a
        // transport failure or a bug. Keeping the distinction is what lets the
        // caller treat an expected 4xx differently from an operational failure.
        setError(
          thrown instanceof ApiError
            ? { traceId: thrown.traceId, expected: true }
            : { expected: false },
        );
        setStatus("error");
        setBannerOpen(true);
      });
  }, []);

  const dismissBanner = useCallback(() => setBannerOpen(false), []);

  // Declared after the ref-sync effect above, so on mount the ref already holds
  // the caller's loader when the first read fires.
  useEffect(() => {
    reload();
  }, [reload]);

  return {
    data,
    status,
    errorTraceId: error?.traceId,
    error,
    bannerOpen,
    reload,
    dismissBanner,
  };
}
