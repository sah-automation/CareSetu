"use client";

// #536: the shared verified-login handoff screen. Rendered after a successful
// OTP verify in the patient flow (this ticket); the doctor flow (#537)
// consumes the same component for Active landings. Confirmation icon,
// informative copy, an always-visible "Go to Dashboard" CTA, and the opening
// progress cue - "Opening your dashboard..." over three animated dots.
//
// The dots ride the host's own redirect timing: there is deliberately no fixed
// numeric countdown, because the session-resume -> navigate window varies with
// server/network latency. An honest indeterminate cue, never fake digits. The
// host owns the auto-redirect (after session resume resolves) and passes
// onGoToDashboard for the manual, immediate path.

import { IconCheck } from "./icons";
import styles from "./doneScreen.module.css";

export interface DoneScreenProps {
  /** Verified heading, e.g. "Identity verified" (host-supplied from auth.*). */
  title: string;
  /** Informative body copy under the heading (host-supplied). */
  body: string;
  /** Progress cue label, e.g. "Opening your dashboard" (doneScreen.*). */
  openingLabel: string;
  /** Always-visible CTA label, e.g. "Go to Dashboard" (doneScreen.*). */
  goToDashboardLabel: string;
  /** Immediate manual navigation; the host routes to its post-login target. */
  onGoToDashboard: () => void;
}

export function DoneScreen({
  title,
  body,
  openingLabel,
  goToDashboardLabel,
  onGoToDashboard,
}: DoneScreenProps) {
  return (
    <section className={styles.section}>
      <div className={styles.center}>
        <span className={styles.successIcon} aria-hidden="true">
          <IconCheck size={40} />
        </span>
      </div>
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.body}>{body}</p>
      <p className={styles.progress} role="status">
        {openingLabel}
        <span className={styles.dots} aria-hidden="true">
          <span className={styles.dot} />
          <span className={styles.dot} />
          <span className={styles.dot} />
        </span>
      </p>
      <button type="button" className={styles.cta} onClick={onGoToDashboard}>
        {goToDashboardLabel}
      </button>
    </section>
  );
}
