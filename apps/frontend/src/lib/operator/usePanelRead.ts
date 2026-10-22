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
 *
 * `key` names WHAT the read is about - a window, a scope, a provider. When it
 * changes the read is about something else, so the old payload is DROPPED and
 * the read re-run: a figure from the previous window sitting behind a loading
 * skeleton is a figure an operator could still read, and the page would then
 * show yesterday's spend under today's title.
 */
export function usePanelRead<T>(
  load: () => Promise<T>,
  key?: string,
): PanelRead<T> {
  /**
   * The payload, together with the key it was read for. A payload belongs to
   * the key it was asked about, so the two travel together: a payload read for
   * another key is not this page's data, and the read exposes `null` rather
   * than a figure from the wrong window.
   */
  const [loaded, setLoaded] = useState<{
    key: string | undefined;
    data: T;
  } | null>(null);
  const [status, setStatus] = useState<PanelLoadStatus>("loading");
  const [error, setError] = useState<PanelRead<T>["error"]>(null);
  const [bannerOpen, setBannerOpen] = useState(false);

  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  /**
   * Which read is allowed to land. Every reload takes a number; only the
   * newest one may write. Without this, switching a window twice quickly
   * leaves the slower first response to land last and overwrite the newer
   * figures with the older ones.
   */
  const generationRef = useRef(0);

  /**
   * The key the current read is about. Held in a ref because `reload` is
   * stable and must not close over a changing key.
   */
  const keyRef = useRef(key);

  const reload = useCallback(() => {
    const generation = ++generationRef.current;
    setStatus("loading");
    loadRef
      .current()
      .then((payload) => {
        if (generation !== generationRef.current) return;
        setLoaded({ key: keyRef.current, data: payload });
        setStatus("ready");
        setError(null);
        setBannerOpen(false);
      })
      .catch((thrown: unknown) => {
        // A read that was superseded is not a failure of the page: the read
        // that replaced it owns the state now.
        if (generation !== generationRef.current) return;
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

  // A change of key is a change of question: the read is re-run for the new
  // key, and the payload read for the old one stops being this page's data
  // (see the `loaded` state above) - so no figure from the previous window is
  // on screen while the new one loads.
  const keyChangedRef = useRef(false);
  useEffect(() => {
    if (keyRef.current === key) return;
    keyRef.current = key;
    keyChangedRef.current = true;
  }, [key]);

  // Run the read when the key changes or on mount. A mounted read always
  // starts on mount; a key change also needs a fresh read for the new window.
  useEffect(() => {
    if (keyChangedRef.current) {
      keyChangedRef.current = false;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [key, reload]);

  return {
    data: loaded !== null && loaded.key === key ? loaded.data : null,
    status,
    errorTraceId: error?.traceId,
    error,
    bannerOpen,
    reload,
    dismissBanner,
  };
}

/**
 * A read that belongs to a key - a window, a scope - and re-runs when that key
 * changes.
 *
 * The same seam as `usePanelRead`, named for the one thing it adds: the read
 * is ABOUT something that can change under the operator's hands, and the page
 * says so with one read rather than one read per window.
 */
export function useKeyedRead<T>(
  load: () => Promise<T>,
  key: string,
): PanelRead<T> {
  return usePanelRead(load, key);
}
