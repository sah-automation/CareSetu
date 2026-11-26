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
// INTEGRATION POINT (PHASE-3 T10 #219): an Allow writes consent_granted via
// the consent backend (POST /v1/consents) plus an audit event; a denial
// maps to the requesting flow's short-circuit. The sheet now handles the
// grant API call and shows a plain-language receipt; "Not now" explains what
// it leaves unblocked and closes without creating anything.
//
// Keyboard/focus contract (§9.4, #203 AC): focus is trapped while open,
// Escape closes, focus returns to the trigger element. The Radix dialog under
// ui/sheet provides all three; the component suite asserts each in jsdom.

import { useState, type ReactElement } from "react";
import { BadgeCheck, CheckCircle2, Info } from "lucide-react";

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
import { grantConsent, type GrantConsentRequest } from "@/lib/consent/api";

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
  /** Counterparty type for the grant API (doctor | lab | chemist). */
  counterpartyType: GrantConsentRequest["counterparty_type"];
  /** Counterparty identifier for the grant API. */
  counterpartyId: string;
  /** Record scope enum for the grant API. */
  recordScope: GrantConsentRequest["record_scope"];
  /** Single element rendered as the trigger that opens the sheet. */
  children: ReactElement;
  /** Called with the decision after the sheet closes (allow/deny). */
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
  counterpartyType,
  counterpartyId,
  recordScope,
  children,
  onDecision,
}: ConsentSheetProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].consent;
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<
    "prompt" | "loading" | "receipt" | "denied"
  >("prompt");
  const [grantError, setGrantError] = useState<string | null>(null);
  const [grantResult, setGrantResult] = useState<{
    lineageRef: string;
    version: number;
  } | null>(null);

  const settle = async (decision: ConsentDecision) => {
    if (decision === "allow") {
      setPhase("loading");
      setGrantError(null);
      try {
        const result = await grantConsent({
          counterparty_type: counterpartyType,
          counterparty_id: counterpartyId,
          record_scope: recordScope,
        });
        setGrantResult({
          lineageRef: result.lineage_ref,
          version: result.version,
        });
        setPhase("receipt");
        onDecision?.("allow");
      } catch (error) {
        setGrantError(
          error instanceof Error
            ? error.message
            : "Something went wrong. Please try again.",
        );
        setPhase("prompt");
      }
    } else {
      setPhase("denied");
      onDecision?.("deny");
    }
  };

  const closeFromReceipt = () => {
    setOpen(false);
    setPhase("prompt");
    setGrantResult(null);
  };

  const closeFromDenied = () => {
    setOpen(false);
    setPhase("prompt");
  };

  const renderPrompt = () => (
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
              <span data-testid="consent-requester-name">{requesterName}</span>{" "}
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
          disabled={phase === "loading"}
        >
          {phase === "loading" ? "..." : t.allow}
        </Button>
        <Button
          size="lg"
          variant="secondary"
          className="flex-1"
          data-testid="consent-deny"
          onClick={() => settle("deny")}
          disabled={phase === "loading"}
        >
          {t.deny}
        </Button>
      </div>

      {grantError && (
        <p className="text-sm text-danger" role="alert">
          {grantError}
        </p>
      )}

      <SheetClose
        data-testid="consent-log-link"
        className="self-center rounded text-sm font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t.logLink}
      </SheetClose>
    </section>
  );

  const renderReceipt = () => (
    <section className="flex flex-col gap-3" role="status">
      <div className="flex items-center gap-2 text-sm font-medium text-success-text">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span data-testid="consent-receipt-title">{t.grantedNote}</span>
      </div>
      {grantResult && (
        <ul className="space-y-1 text-sm text-txt-sub">
          <li data-testid="consent-receipt-line1">
            {lang === "hi"
              ? `आपने ${requesterName} को ${scope} पढ़ने की अनुमति दी।`
              : `You allowed ${requesterName} to read ${scope.toLowerCase()}.`}
          </li>
          <li data-testid="consent-receipt-line2">
            {lang === "hi"
              ? `यह "${validity}" तक मान्य है।`
              : `It is valid ${validity.toLowerCase()}.`}
          </li>
          <li className="muted" data-testid="consent-receipt-line3">
            {lang === "hi"
              ? `रसीद संदर्भ #${grantResult.lineageRef} v${grantResult.version} · अभी दर्ज हुई`
              : `Receipt ref #${grantResult.lineageRef} v${grantResult.version} · recorded just now`}
          </li>
        </ul>
      )}
      <p className="text-sm text-txt-muted" data-testid="consent-receipt-note">
        {t.deniedNote
          .replace("lab cannot attach", "record cannot be shared")
          .replace("booking", "action")}
      </p>
      <div className="flex gap-3 pt-2">
        <Button
          size="lg"
          variant="secondary"
          className="flex-1"
          onClick={closeFromReceipt}
        >
          {lang === "hi" ? "समझा" : "Got it"}
        </Button>
        <Button size="lg" className="flex-1" onClick={closeFromReceipt}>
          {lang === "hi" ? "अनुमति लॉग खोलें" : "Open consent log"}
        </Button>
      </div>
    </section>
  );

  const renderDenied = () => (
    <section className="flex flex-col gap-3" role="status">
      <div className="flex items-center gap-2 text-sm font-medium text-txt">
        <Info className="h-4 w-4 shrink-0 text-txt-muted" aria-hidden="true" />
        <span data-testid="consent-denied-title">
          {lang === "hi"
            ? "कोई बात नहीं - कुछ साझा नहीं हुआ"
            : "No problem - nothing was shared"}
        </span>
      </div>
      <p className="text-sm text-txt-sub" data-testid="consent-denied-body">
        {lang === "hi"
          ? `अनुमति के बिना ${requesterName} ${scope.toLowerCase()} नहीं पढ़ पाएंगे। यह क्रिया फिर भी होगी - बस रिकॉर्ड संदर्भ के बिना। मन बदले, तो अनुमति लॉग से कभी भी दे सकते हैं।`
          : `Without permission, ${requesterName} cannot read ${scope.toLowerCase()}. The action still proceeds - it simply starts without your record context. Changed your mind? Allow it anytime from your Consent log.`}
      </p>
      <Button size="lg" className="w-full" onClick={closeFromDenied}>
        {lang === "hi" ? "समझा" : "Got it"}
      </Button>
    </section>
  );

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

        {phase === "prompt" && renderPrompt()}
        {phase === "loading" && (
          <section className="flex flex-col items-center gap-4 py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent-border border-t-accent-strong" />
            <p className="text-sm text-txt-sub">
              {lang === "hi"
                ? "अनुमति दर्ज की जा रही है..."
                : "Recording permission..."}
            </p>
          </section>
        )}
        {phase === "receipt" && renderReceipt()}
        {phase === "denied" && renderDenied()}
      </SheetContent>
    </Sheet>
  );
}
