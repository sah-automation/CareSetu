"use client";

// #605: the reusable section shell for the doctor profile page's independently
// saving sections. It owns presentation and the save lifecycle, and nothing else:
// the title, the help text, the dirty hint, its own save button, its own
// pending state, its own saved confirmation and its own error presentation with
// a retry action (blueprint §9.1 - an in-place mutation spins inside the
// triggering button and never takes over the page, and a card-scoped failure
// renders a quiet retry link in place).
//
// What it deliberately does NOT own is validation or transport. Both stay with
// the section that knows them, which is what keeps the shell reusable: the
// notification section saves through a different route, and a read-only band
// needs a shell with no save affordance at all. So `onSave` is a callback into
// whoever owns the attempt and reports how it went, and the retry action is
// that same callback again - which is also what keeps the per-attempt
// idempotency key honest: the key lives with the section's request builder, a
// retry re-enters the same attempt and therefore reuses the same key, and only
// an edit mints a new one.

import type { ReactNode } from "react";
import { useRef, useState } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * A failed mutation, carrying the API trace id when the failure came from the
 * API so support can correlate it (ErrorBanner falls back to a client id).
 */
export interface SectionFailure {
  traceId?: string;
}

/**
 * How one attempt went, reported by the section that owns it. `declined` is the
 * section's own validation refusing the attempt: nothing was written, so the
 * shell says nothing either and the section renders its own field-level message.
 */
export type SectionSaveResult =
  | { status: "saved" }
  | { status: "declined" }
  | { status: "failed"; failure: SectionFailure };

/** Everything a saving section hands the shell, copy and state included. */
export interface ProfileSectionSave {
  onSave: () => Promise<SectionSaveResult>;
  label: string;
  savedLabel: string;
  unsavedLabel: string;
  failureMessage: string;
  /**
   * The section's buffer latches its dirty flag: the doctor has touched this
   * section, and no later server answer may overwrite them. The shell owns what
   * that means to a doctor, which is the hint beside the save button.
   */
  dirty: boolean;
  /**
   * A signal that changes on every edit, which is how the shell learns that the
   * section moved underneath the result it is showing. The page used to clear
   * its own saved and failure state inside each mutator; once the mutator lives
   * in a reusable buffer, this is the shell's only signal that it must too.
   *
   * `dirty` and `edits` are required together because neither is meaningful
   * alone: a section that reports the first and not the second latches its hint
   * on forever and can never outdate a confirmation.
   */
  edits: number;
  /**
   * Required rather than defaulted: several sections share a page, so each has to
   * name its own hooks rather than collide on a shared default.
   */
  buttonTestId: string;
  savedTestId: string;
  unsavedTestId: string;
}

export interface ProfileSectionShellProps {
  title: string;
  help?: string;
  /** The section's own fields, its chips, its read-only rows. */
  children: ReactNode;
  /**
   * Omit for a section with nothing to save: the shell then renders no button,
   * no footer, no confirmation, no form element and no dirty state at all.
   */
  save?: ProfileSectionSave;
  /**
   * The in-page anchor this section answers to, rendered as the `id` on whichever
   * element the shell returns.
   *
   * #615 added this to a landed sibling's contract. The page's sticky anchor-chip
   * index (#615) needs a target per section, and the alternative - wrapping every
   * section in a second element to hang the `id` on - would give each section two
   * headings and two landmarks, which is exactly the accessibility floor biting.
   * Optional, so every existing caller is unaffected.
   */
  anchorId?: string;
  testId?: string;
}

export function ProfileSectionShell({
  title,
  help,
  children,
  save,
  anchorId,
  testId,
}: ProfileSectionShellProps) {
  const { dirty, edits } = save ?? { dirty: false, edits: 0 };
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<SectionSaveResult | null>(null);

  // Adjusting state during render, which is React's documented way to reset when
  // a prop changes - an effect here would show one commit of a confirmation that
  // no longer describes anything. An edit that lands *before* the reply never
  // gets here, so a save still reports itself saved for what it actually sent.
  const lastEdits = useRef(edits);
  if (edits !== lastEdits.current) {
    lastEdits.current = edits;
    setResult(null);
  }

  async function attempt() {
    if (save == null || pending) return;
    setPending(true);
    setResult(null);
    try {
      setResult(await save.onSave());
    } catch {
      // The section classifies its own failures, so a throw reaching here is a
      // classification it never made. It is still presented as a failed attempt
      // rather than left to escape the submit handler as an unhandled rejection.
      setResult({ status: "failed", failure: {} });
    } finally {
      setPending(false);
    }
  }

  const saved = result?.status === "saved";
  const failure = result?.status === "failed" ? result.failure : null;
  // The dirty flag latches for the rest of the session by design, so it cannot
  // be rendered beside a confirmation without claiming the section is saved and
  // unsaved at once. The confirmation wins, which means a doctor who keeps typing
  // across an attempt sees "saved" for the fields that attempt actually sent and
  // no hint for the keystrokes after it - the behaviour the profile page suite
  // pins in "keeps in-progress typing when a save's own reply lands after it".
  // Narrowing the confirmation to only the covered edits would be a behaviour
  // change, so it is left for a ticket that says it wants one.
  const unsaved = dirty && !saved;

  const body = (
    <>
      <CardHeader>
        {/* shadcn's CardTitle is a div, so the heading element is nested inside
            it rather than styled by ARIA: the page's own outline still gets a
            real h2 to skip between, which role="heading" only imitates. */}
        <CardTitle>
          <h2 className="text-sm font-semibold text-txt">{title}</h2>
        </CardTitle>
        {help && <CardDescription>{help}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
      {save != null && (
        <CardFooter className="flex flex-wrap items-center gap-2">
          <Button
            type="submit"
            size="sm"
            disabled={pending}
            loading={pending}
            data-testid={save.buttonTestId}
          >
            {save.label}
          </Button>
          {unsaved && (
            <span
              className="text-xs text-txt-muted"
              data-testid={save.unsavedTestId}
            >
              {save.unsavedLabel}
            </span>
          )}
          {saved && (
            <p className="text-sm text-success" data-testid={save.savedTestId}>
              {save.savedLabel}
            </p>
          )}
        </CardFooter>
      )}
      {save != null && failure != null && (
        <ErrorBanner
          message={save.failureMessage}
          traceId={failure.traceId}
          onRetry={() => void attempt()}
          onDismiss={() => setResult(null)}
        />
      )}
    </>
  );

  // A saving section is a form, because the shell's button is its submit button
  // and one submit path is what makes the retry and the button the same attempt.
  // A read-only section is not a form: it has nothing to submit.
  if (save == null) {
    return (
      <Card id={anchorId} data-testid={testId}>
        {body}
      </Card>
    );
  }

  return (
    <form
      // The section owns its own validation pass and renders one message for the
      // offending fields, so the browser's constraint bubbles must not preempt
      // the submit (and silently swallow the attempt).
      noValidate
      id={anchorId}
      data-testid={testId}
      onSubmit={(event) => {
        event.preventDefault();
        void attempt();
      }}
    >
      <Card>{body}</Card>
    </form>
  );
}
