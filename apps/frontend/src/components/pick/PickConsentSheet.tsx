"use client";

// PHASE-8.1 T11 (#449): the pick-a-doctor consent sheet (US-5/US-6). One
// plain-language sheet reused from the doctor card's Book CTA: it names who
// is asking (the picked doctor, with the verified badge) and what exactly the
// doctor will see (the pre-summary's symptom summary and relevant consented
// history). "Allow" records the pick AND the consent grant as a single atomic
// backend action (POST /v1/intake/{id}/pick-doctor, consent-at-pick MOD-004)
// - there is no second gate. "Not now" closes without recording anything.
// A successful pick reports the backend result to the host page, which swaps
// to the confirmation view.
//
// The sheet mirrors ConsentSheet's anatomy and labels (who/what/how-long +
// verified badge from consent.*), while the pick-specific scope text comes
// from pick.* and the grant mutation is pickDoctor, not ConsentSheet's
// standalone grantConsent - the atomicity would otherwise be broken into two
// calls.

import { useState } from "react";
import { BadgeCheck } from "lucide-react";

import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import type { DirectoryEntry } from "@/lib/directory/search";
import { pickDoctor, type PickDoctorResult } from "@/lib/pick/api";
import { idempotencyKey } from "@/lib/idempotency";

interface PickConsentSheetProps {
  intakeId: number;
  entry: DirectoryEntry;
  /** Practice name already fallen back by the caller, if desired. */
  doctorName: string;
  /** Controlled open state - the page opens it for the picked card. */
  open: boolean;
  /** Called when the sheet closes without a successful pick. */
  onOpenChange: (open: boolean) => void;
  /** Called exactly once after Allow records pick + consent atomically. */
  onPicked: (result: PickDoctorResult) => void;
}

export function PickConsentSheet({
  intakeId,
  entry,
  doctorName,
  open,
  onOpenChange,
  onPicked,
}: PickConsentSheetProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].consent;
  const tp = STRINGS[lang].pick;

  const [phase, setPhase] = useState<"prompt" | "loading" | "error">("prompt");
  const [error, setError] = useState<string | null>(null);
  // Idempotency contract (api-standards A5): one key per pick attempt is
  // minted on first Allow and replayed verbatim on retries, so a failed
  // attempt followed by a retry cannot double-record the pick server-side.
  const [attemptKey, setAttemptKey] = useState<string | null>(null);

  const handleOpenChange = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      setPhase("prompt");
      setError(null);
      setAttemptKey(null);
    }
  };

  const settle = async (allow: boolean) => {
    if (!allow) {
      onOpenChange(false);
      return;
    }
    setPhase("loading");
    setError(null);
    try {
      const key = attemptKey ?? idempotencyKey();
      setAttemptKey(key);
      const result = await pickDoctor(intakeId, entry.partner_id, key);
      onPicked(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : tp.genericError);
      setPhase("prompt");
    }
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="bottom"
        className="mx-auto max-w-lg rounded-t-lg sm:max-w-lg"
      >
        <SheetHeader>
          <SheetTitle data-testid="pick-consent-title">
            {tp.consentTitle}
          </SheetTitle>
        </SheetHeader>

        {phase === "loading" ? (
          <section className="flex flex-col items-center gap-4 py-8">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-border border-t-accent-strong" />
            <p className="text-sm text-txt-sub">{tp.recordingChoice}</p>
          </section>
        ) : (
          <section className="flex flex-col gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                {t.whoLabel}
              </p>
              <div className="mt-1.5 flex items-center gap-2.5">
                <span
                  className="inline-flex items-center gap-1 text-sm font-medium text-txt"
                  data-testid="pick-consent-doctor"
                >
                  {doctorName}
                  <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
                    <BadgeCheck aria-hidden="true" className="h-3 w-3" />
                    {t.verifiedBadge}
                  </span>
                </span>
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                {t.whatLabel}
              </p>
              <SheetDescription className={cn("mt-1 text-sm text-txt")}>
                {tp.consentScope}
              </SheetDescription>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                {t.howLongLabel}
              </p>
              <p className="mt-1 text-sm text-txt-sub">{tp.consentValidity}</p>
            </div>

            {error && (
              <p className="text-sm text-danger" role="alert">
                {error}
              </p>
            )}

            <div className="flex gap-3">
              <Button
                size="lg"
                className="flex-1"
                data-testid="pick-consent-allow"
                onClick={() => void settle(true)}
              >
                {tp.allow}
              </Button>
              <Button
                size="lg"
                variant="secondary"
                className="flex-1"
                data-testid="pick-consent-cancel"
                onClick={() => settle(false)}
              >
                {t.deny}
              </Button>
            </div>

            <SheetClose
              data-testid="pick-consent-close"
              className="self-center rounded text-sm font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t.logLink}
            </SheetClose>
          </section>
        )}
      </SheetContent>
    </Sheet>
  );
}
