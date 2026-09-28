"use client";

// #536: the shared verified-login handoff screen. Rendered after a successful
// OTP verify in the patient flow; the doctor flow (#537) consumes the same
// component for active console landings. Confirmation icon, informative copy,
// an indeterminate progress indicator over a single status line, and the
// always-visible "Go to Dashboard" CTA.
//
// #581: the screen is a loading mask and nothing more. It is presentational: no
// countdown, no remaining seconds, no departed flag, no tick, no readiness
// flag, and not one digit on screen or in the accessibility tree. Whether to
// leave, and when, is a consequence of readiness owned by the host (#578's
// hook, wired in #579 and #580); this component only says that the destination
// is opening. The bar slides rather than filling because the code genuinely
// does not know how long the destination will take.

import { IconCheck } from "./icons";
import styles from "./doneScreen.module.css";

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
  /** The status line, constant for the whole life of the screen (doneScreen.*). */
  openingLabel: string;
  /** Always-visible CTA label, e.g. "Go to Dashboard" (doneScreen.*). */
  goToDashboardLabel: string;
  /**
   * The host's single post-login routine: resume the session, then navigate.
   * The once-only guarantee is the host's, held by #578's hook, because
   * readiness lives there and not here.
   */
  onGoToDashboard: () => void;
  /** Optional handoff facts, rendered under the copy. */
  facts?: DoneScreenFact[];
}

export function DoneScreen({
  title,
  body,
  openingLabel,
  goToDashboardLabel,
  onGoToDashboard,
  facts,
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
        {openingLabel}
      </p>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label={openingLabel}
      >
        <div className={styles.progressFill} />
      </div>
      <button type="button" className={styles.cta} onClick={onGoToDashboard}>
        {goToDashboardLabel}
      </button>
    </section>
  );
}
