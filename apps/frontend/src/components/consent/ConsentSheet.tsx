"use client";

// PHASE-2.6 T12 (#203): the reusable consent-moment bottom sheet (blueprint
// §5.10, finalized PROTO-PHASE-2.6 view consent-sheet.html). One anatomy for
// every care action that needs record access: who is asking (name + verified
// badge), the specific plain-language scope of what they will see (never
// blanket wording), a per-action validity statement, and Allow / Not-now.
//
// Decision semantics (#203 AC): Allow reports "allow", Not-now reports
// "deny" - the host decides what proceeds or stays blocked. The sheet never
// re-prompts on its own: it only ever opens from its trigger, and hosts pair
// it with lib/consent/consentGate for session-scoped dismissal memory.
//
// INTEGRATION POINT (later phase): an Allow must write consent_granted via
// the consent backend (MOD-004 check_consent / FEAT-002) plus an audit event;
// a denial maps to the requesting flow's short-circuit. No write exists this
// phase - hosts receive onDecision and keep local state only.
//
// Keyboard/focus contract (§9.4, #203 AC): focus is trapped while open,
// Escape closes, focus returns to the trigger element. The Radix dialog under
// ui/sheet provides all three; the component suite asserts each in jsdom.

import { useState, type ReactElement } from "react";
import { BadgeCheck } from "lucide-react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ConsentDecision = "allow" | "deny";

export interface ConsentSheetProps {
  /** Plain name of who is asking, shown with the verified badge. */
  requesterName: string;
  /** One-line context of how the request reaches the patient. */
  requesterContext?: string;
  /** Credential-verified requester; false hides the badge. */
  verified?: boolean;
  /** Specific plain-language scope of what they will see. */
  scope: string;
  /** Per-action validity statement. */
  validity: string;
  /** Single element rendered as the trigger that opens the sheet. */
  children: ReactElement;
  onDecision?: (decision: ConsentDecision) => void;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]!.toUpperCase())
    .join("");
}

const labelClass =
  "text-xs font-semibold uppercase tracking-wide text-txt-muted";

export function ConsentSheet({
  requesterName,
  requesterContext,
  verified = true,
  scope,
  validity,
  children,
  onDecision,
}: ConsentSheetProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].consent;
  const [open, setOpen] = useState(false);

  // INTEGRATION POINT (later phase): persist the decision here before
  // reporting it - grant -> consent_granted + audit event, denial ->
  // requesting-flow short-circuit. Local state only until that phase.
  const settle = (decision: ConsentDecision) => {
    setOpen(false);
    onDecision?.(decision);
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent
        side="bottom"
        className="mx-auto max-w-lg rounded-t-lg sm:max-w-lg"
      >
        <SheetHeader>
          <SheetTitle data-testid="consent-title">{t.title}</SheetTitle>
        </SheetHeader>

        <section className="flex flex-col gap-4">
          <div>
            <p className={labelClass}>{t.whoLabel}</p>
            <div className="mt-1.5 flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong"
              >
                {initials(requesterName)}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-txt">
                  <span data-testid="consent-requester-name">
                    {requesterName}
                  </span>{" "}
                  {verified && (
                    <span
                      data-testid="consent-verified-badge"
                      className="ml-1 inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text"
                    >
                      <BadgeCheck aria-hidden="true" className="h-3 w-3" />
                      {t.verifiedBadge}
                    </span>
                  )}
                </p>
                {requesterContext && (
                  <p className="text-xs text-txt-muted">{requesterContext}</p>
                )}
              </div>
            </div>
          </div>

          <div>
            <p className={labelClass}>{t.whatLabel}</p>
            <SheetDescription className={cn("mt-1 text-sm text-txt")}>
              {scope}
            </SheetDescription>
          </div>

          <div>
            <p className={labelClass}>{t.howLongLabel}</p>
            <p className="mt-1 text-sm text-txt-sub">{validity}</p>
          </div>

          <div className="flex gap-3">
            <Button
              size="lg"
              className="flex-1"
              data-testid="consent-allow"
              onClick={() => settle("allow")}
            >
              {t.allow}
            </Button>
            <Button
              size="lg"
              variant="secondary"
              className="flex-1"
              data-testid="consent-deny"
              onClick={() => settle("deny")}
            >
              {t.deny}
            </Button>
          </div>

          {/* §5.10: every sheet links to Record > Consent log; revocation
              lives there. The destination page arrives in a later phase. */}
          <SheetClose
            data-testid="consent-log-link"
            className="self-center rounded text-sm font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t.logLink}
          </SheetClose>
        </section>
      </SheetContent>
    </Sheet>
  );
}
