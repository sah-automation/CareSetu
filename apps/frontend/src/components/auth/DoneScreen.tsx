"use client";

// #536: the shared verified-login handoff screen. Rendered after a successful
// OTP verify in the patient flow; the doctor flow (#537) consumes the same
// component for active console landings. Confirmation icon, informative copy,
// a real countdown with a progress indicator, and the always-visible "Go to
// Dashboard" CTA.
//
// #551: the countdown is a real 5-second tick, per #529 solution point 1 - a
// long-enough-to-read confirmation and a short-enough-not-to-feel-slow
// redirect. It starts ONLY once the host reports the session-resume call has
// settled (`resumePending` flips false), so no digit ever runs ahead of the
// session the redirect depends on, and it fires the host's navigation routine
// at zero. The host owns that routine: the countdown and the CTA call the same
// `onGoToDashboard`, which is idempotent, so a click mid-countdown cannot
// double-navigate and a fast click still waits for the resume seam.

import { useCallback, useEffect, useRef, useState } from "react";

import { IconCheck } from "./icons";
import styles from "./doneScreen.module.css";

/**
 * Seconds the shared handoff counts down before it asks the host to navigate.
 * One named constant: the screen owns the tick, so no host repeats the number.
 */
export const DONE_SCREEN_COUNTDOWN_SECONDS = 5;

/** A handoff fact row (doctor practice, specialty, destination). */
export interface DoneScreenFact {
  /** Short field label, e.g. "Practice" (doneScreen.*). */
  label: string;
  /** Value from already-fetched data, never inline copy. */
  value: string;
}

export interface DoneScreenProps {
  /** Verified heading, e.g. "Identity verified" (host-supplied from auth.*). */
  title: string;
  /** Informative body copy under the heading (host-supplied). */
  body: string;
  /** Progress line shown while the resume seam is in flight (doneScreen.*). */
  openingLabel: string;
  /** Countdown line once the resume seam settled, e.g. "... in 3". */
  openingInLabel: (secondsLeft: number) => string;
  /** Always-visible CTA label, e.g. "Go to Dashboard" (doneScreen.*). */
  goToDashboardLabel: string;
  /**
   * True while the host's session-resume call is still in flight. The
   * countdown is held at full duration until this flips false, so the
   * auto-redirect begins only after the resume call succeeds.
   */
  resumePending: boolean;
  /**
   * The host's single post-login routine: resume the session, then navigate.
   * Called by the countdown at zero and by the CTA; it must be idempotent.
   */
  onGoToDashboard: () => void;
  /** Optional handoff facts, rendered under the copy. */
  facts?: DoneScreenFact[];
}

export function DoneScreen({
  title,
  body,
  openingLabel,
  openingInLabel,
  goToDashboardLabel,
  resumePending,
  onGoToDashboard,
  facts,
}: DoneScreenProps) {
  const [secondsLeft, setSecondsLeft] = useState(DONE_SCREEN_COUNTDOWN_SECONDS);
  const [departed, setDeparted] = useState(false);
  // Refs, not state, for the once-only guard and the latest host callback: the
  // guard must survive a StrictMode double-invoke of the effects below, and a
  // fresh inline callback identity must not re-arm the auto-redirect.
  const departedRef = useRef(false);
  const goRef = useRef(onGoToDashboard);

  useEffect(() => {
    goRef.current = onGoToDashboard;
  }, [onGoToDashboard]);

  const depart = useCallback(() => {
    if (departedRef.current) {
      return;
    }
    departedRef.current = true;
    setDeparted(true);
    goRef.current();
  }, []);

  // The tick. Held back while the resume seam is in flight, and cleared on
  // teardown so no state update lands after unmount.
  useEffect(() => {
    if (resumePending || departed) {
      return;
    }
    const tick = window.setInterval(() => {
      setSecondsLeft((remaining) => Math.max(0, remaining - 1));
    }, 1000);
    return () => {
      window.clearInterval(tick);
    };
  }, [resumePending, departed]);

  // The auto-redirect: exactly once, at zero, after the resume seam settled.
  useEffect(() => {
    if (resumePending || departed || secondsLeft > 0) {
      return;
    }
    depart();
  }, [resumePending, departed, secondsLeft, depart]);

  const progressLine = resumePending
    ? openingLabel
    : openingInLabel(secondsLeft);
  const elapsedPercent = (secondsLeft / DONE_SCREEN_COUNTDOWN_SECONDS) * 100;

  return (
    <section className={styles.section}>
      <div className={styles.center}>
        <span className={styles.successIcon} aria-hidden="true">
          <IconCheck size={40} />
        </span>
      </div>
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.body}>{body}</p>
      {facts && facts.length > 0 ? (
        <dl className={styles.facts}>
          {facts.map((fact) => (
            <div key={fact.label} className={styles.fact}>
              <dt className={styles.factLabel}>{fact.label}</dt>
              <dd className={styles.factValue}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p className={styles.progress} role="status">
        {progressLine}
      </p>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label={openingLabel}
        aria-valuemin={0}
        aria-valuemax={DONE_SCREEN_COUNTDOWN_SECONDS}
        aria-valuenow={secondsLeft}
        aria-valuetext={progressLine}
      >
        <div
          className={styles.progressFill}
          style={{ width: `${elapsedPercent}%` }}
        />
      </div>
      <button type="button" className={styles.cta} onClick={depart}>
        {goToDashboardLabel}
      </button>
    </section>
  );
}
