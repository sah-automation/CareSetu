"use client";

// #578: the one place the verified-login handoff decides when to leave. The
// partner login and the patient login both host the same handoff screen, and
// the only thing either of them knows that the screen does not is whether its
// destination is in hand - so the decision lives here, and the two flows just
// report readiness and hand over a routine that navigates.
//
// The hold this replaces was five seconds and did two jobs: a confirmation beat
// (real) and a delay (not). Only the first survives, as a sub-second minimum
// dwell, and it is measured from readiness rather than from mount so a flow
// that was slow to become ready is not also made to wait afterwards.
//
// This is the only definition of that dwell in the codebase. Tuning it, or
// removing it, is a one-line change here and nowhere else (#577 story 34).

import { useCallback, useEffect, useRef } from "react";

/**
 * The confirmation beat, in milliseconds: long enough that a handoff whose
 * destination is ready almost at once reads as a confirmation rather than a
 * flicker, short enough that it is never felt as a wait.
 */
export const HANDOFF_MINIMUM_DWELL_MS = 500;

/**
 * Own the whole navigation decision for a verified-login handoff. Given whether
 * the flow is ready and the routine that actually navigates, this leaves at
 * most once: not at all until the flow is ready, then after the minimum dwell
 * measured from that readiness, or at once if the caller has already asked to
 * go. Returns that "ask to go" callback, which the handoff's "Go to Dashboard"
 * button is wired to.
 *
 * @param ready Whether the flow's destination is in hand.
 * @param navigate The routine that leaves the handoff. Hosts pass an inline
 *   closure, so it must not be treated as a per-render input.
 */
export function useHandoffNavigation(
  ready: boolean,
  navigate: () => void,
): () => void {
  // What "leave" means is not a per-render input, and what "ready" is worth is
  // a boolean, so neither is listed as an effect dependency. The routine is
  // held here instead: an inline closure arrives as a fresh identity every
  // render, and re-arming the timer on each one would restart the dwell
  // forever - the button would do nothing and the flow would never navigate.
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const readyRef = useRef(ready);
  readyRef.current = ready;

  // The once-only latch is a ref rather than state because these hosts run
  // under StrictMode, where a state update in an effect is applied twice. A ref
  // survives that, and the countdown this replaces latched the same way.
  const departedRef = useRef(false);
  // Whether the caller has asked to go before readiness, which is what turns
  // the dwell into no wait at all once the flow is finally ready.
  const askedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The returned callback outlives the effect that armed the timer, so "is
  // there still a handoff on the page" is held here rather than inferred from
  // the timer. The flag is set in the effect body as well as cleared in its
  // cleanup, because StrictMode mounts, unmounts and remounts an effect, and a
  // flag that only ever got cleared would strand the second mount.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const depart = useCallback(() => {
    if (departedRef.current || !mountedRef.current) return;
    departedRef.current = true;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    navigateRef.current();
  }, []);

  const goNow = useCallback(() => {
    if (departedRef.current) return;
    askedRef.current = true;
    // With nowhere to go to, the ask is remembered rather than obeyed, and the
    // readiness effect below honours it the moment there is somewhere to go.
    if (!readyRef.current) return;
    depart();
  }, [depart]);

  useEffect(() => {
    if (!ready || departedRef.current) return;
    const timer = setTimeout(
      () => {
        timerRef.current = null;
        depart();
      },
      askedRef.current ? 0 : HANDOFF_MINIMUM_DWELL_MS,
    );
    timerRef.current = timer;
    return () => {
      // The host going away is the only thing that cancels a pending leave. If
      // it does, the handoff is off the page and nothing may still navigate.
      clearTimeout(timer);
      if (timerRef.current === timer) timerRef.current = null;
    };
  }, [ready, depart]);

  return goNow;
}
