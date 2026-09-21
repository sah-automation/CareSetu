"use client";

// #505: the home "Action required" card (PROTO-2.7 binding, shell-light.html
// `actions.*`). It renders NOTHING when nothing is pending - no empty card, no
// placeholder, and no loading shell (so it can never flash an empty state).
//
// Today the only source is pending patient-consent requests: the existing
// consent log, filtered to status "requested". Each row names the requester and
// the record scope, and its Allow / Not now answer the request through the
// existing consent flows - Allow promotes it (grant-requested), Not now closes
// it (decline). Both reconcile from the server-returned view so the card drops
// the answered row. Rx substitute/refund and booking confirmations are future
// sources and are deliberately not stubbed here.

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  declineConsent,
  fetchConsentLog,
  grantRequestedConsent,
  type ConsentView,
} from "@/lib/consent/api";
import { counterpartyLabel } from "@/lib/consent/consentView";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export function ActionRequiredCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].actions;
  // null = still resolving; [] = nothing readable. Either way the card stays
  // absent until a pending item actually exists.
  const [consents, setConsents] = useState<ConsentView[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchConsentLog()
      .then((log) => {
        if (active) setConsents(log.items);
      })
      .catch((err: unknown) => {
        // Degrade honestly: with nothing readable there is nothing to act on,
        // so the card stays absent - but the failure is logged so it stays
        // distinguishable from true emptiness.
        console.warn(
          "[action-required] consent fetch failed, hiding card:",
          err,
        );
        if (active) setConsents([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const pending = useMemo(
    () => (consents ?? []).filter((c) => c.status === "requested"),
    [consents],
  );

  const answer = useCallback(
    async (consent: ConsentView, decision: "allow" | "deny") => {
      setBusyId(consent.consent_id);
      setFailed(false);
      try {
        const updated =
          decision === "allow"
            ? await grantRequestedConsent(consent.consent_id)
            : await declineConsent(consent.consent_id);
        // Replace from the server-returned view; the answered row is no longer
        // "requested" so it drops out of the pending list.
        setConsents((prev) =>
          prev
            ? prev.map((c) =>
                c.consent_id === updated.consent_id ? updated : c,
              )
            : prev,
        );
      } catch (err: unknown) {
        console.warn("[action-required] consent action failed:", err);
        setFailed(true);
      } finally {
        setBusyId(null);
      }
    },
    [],
  );

  // Completely absent when nothing is pending - asserted as element absence,
  // never merely empty or hidden.
  if (pending.length === 0) return null;

  return (
    <section
      data-testid="action-required"
      className="rounded-lg border border-hairline border-l-4 border-l-warm-mid bg-surface p-4"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h2 className="text-[1.05rem] font-semibold text-txt">{t.title}</h2>
        <span
          data-testid="action-required-count"
          className="rounded-full bg-warm-soft px-2 py-0.5 text-xs font-medium text-warm"
        >
          {pending.length}
        </span>
      </div>

      <div className="space-y-3">
        {pending.map((consent) => (
          <div
            key={consent.consent_id}
            data-testid="action-required-item"
            data-consent-id={consent.consent_id}
            className="space-y-2 border-t border-hairline-soft pt-3 first:border-t-0 first:pt-0"
          >
            <p className="flex flex-wrap items-center gap-2 text-sm text-txt-sub">
              <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong">
                {t.consentBadge}
              </span>
              <span>
                {t.consentRequest(
                  counterpartyLabel(
                    consent.counterparty_type,
                    consent.counterparty_id,
                  ),
                  consent.record_scope,
                )}
              </span>
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                data-testid="action-allow"
                loading={busyId === consent.consent_id}
                disabled={busyId !== null}
                onClick={() => answer(consent, "allow")}
              >
                {t.allow}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                data-testid="action-deny"
                disabled={busyId !== null}
                onClick={() => answer(consent, "deny")}
              >
                {t.deny}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {failed && (
        <p className="mt-2 text-sm text-danger" role="alert">
          {t.actionFailed}
        </p>
      )}
    </section>
  );
}
