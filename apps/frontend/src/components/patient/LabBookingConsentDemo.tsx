"use client";

// PHASE-2.6 T12 (#203): the single demo integration point proving the full
// trigger -> sheet -> decision -> block-or-proceed loop end-to-end against
// local state, on a patient surface behind an explicit "demo care action"
// affordance so real surfaces stay unpolluted. Grant/revoke writes remain
// later-phase integration points (see ConsentSheet header); denial memory is
// session-scoped via lib/consent/consentGate - a returning visit within this
// page session sees the standing denial instead of a fresh prompt.

import { useState } from "react";
import { CheckCircle2, Info } from "lucide-react";

import {
  ConsentSheet,
  type ConsentDecision,
} from "@/components/consent/ConsentSheet";
import { Button } from "@/components/ui/button";
import {
  markDenied,
  clearDenied,
  hasBeenDenied,
} from "@/lib/consent/consentGate";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export const DEMO_CONSENT_REQUEST_KEY = "demo.lab-booking.history";

export function LabBookingConsentDemo() {
  const { lang } = useLang();
  const t = STRINGS[lang].consent;
  // Session-scoped memory, seeded from the gate once per mount and kept in
  // step with every decision: a returning visit within this page session
  // sees the standing denial instead of a fresh prompt, and an Allow clears it.
  const [standingDenial, setStandingDenial] = useState(() =>
    hasBeenDenied(DEMO_CONSENT_REQUEST_KEY),
  );
  const [outcome, setOutcome] = useState<ConsentDecision | null>(null);

  const handleDecision = (decision: ConsentDecision) => {
    if (decision === "deny") {
      markDenied(DEMO_CONSENT_REQUEST_KEY);
      setStandingDenial(true);
    } else {
      clearDenied(DEMO_CONSENT_REQUEST_KEY);
      setStandingDenial(false);
    }
    setOutcome(decision);
  };

  const showAllowOutcome = outcome === "allow";
  const showDenyOutcome = outcome === "deny" || standingDenial;

  return (
    <section
      aria-labelledby="consent-demo-title"
      data-testid="consent-demo-card"
      className="rounded-lg border border-hairline bg-surface p-5 shadow-card"
    >
      <p className="mb-2 inline-flex rounded-full bg-warn-soft px-2.5 py-0.5 text-xs font-semibold text-warn-text">
        {t.demo.badge}
      </p>
      <h2 id="consent-demo-title" className="text-base font-semibold text-txt">
        {t.demo.cardTitle}
      </h2>
      <p className="mt-1 text-sm text-txt-sub">{t.demo.cardBody}</p>

      <div className="mt-4">
        <ConsentSheet
          requesterName={t.demo.requesterName}
          requesterContext={t.demo.requesterContext}
          scope={t.demo.scope}
          validity={t.demo.validity}
          onDecision={handleDecision}
        >
          <Button size="lg" data-testid="consent-demo-trigger">
            {t.demo.cta}
          </Button>
        </ConsentSheet>
      </div>

      {showAllowOutcome && (
        <p
          role="status"
          data-testid="consent-demo-outcome-allow"
          className="mt-4 flex items-start gap-2 rounded-md bg-success-soft px-3 py-2 text-sm font-medium text-success-text"
        >
          <CheckCircle2
            aria-hidden="true"
            className="mt-0.5 h-4 w-4 shrink-0"
          />
          {t.grantedNote} {t.demo.allowedProceed}
        </p>
      )}
      {showDenyOutcome && (
        <p
          role="status"
          data-testid="consent-demo-outcome-deny"
          className="mt-4 flex items-start gap-2 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          {standingDenial && outcome === null && (
            <span className="font-medium">{t.demo.standingDenial} </span>
          )}
          {t.deniedNote}
        </p>
      )}
    </section>
  );
}
