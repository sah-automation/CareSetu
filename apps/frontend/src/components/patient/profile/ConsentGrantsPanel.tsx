"use client";

// #548: the Settings-zone consent grants panel. Settings answers "who can see
// my records" and gives the patient a way out: it lists the live granted
// consents and revokes them.
//
// Scope-agnostic by construction. A `health_background` grant is not a special
// case here - it arrives as `record_scope` like any other and is revoked the
// same way - because a grant the patient cannot take back from Settings is a
// grant they can only ask support to undo. Anything that is not `granted` is
// not access the patient currently holds, so it is not listed.
//
// Revocation is confirmed before it is sent (it cannot be un-done by the
// patient) and a failure keeps both the grant and the sheet, so a retry is one
// tap rather than a re-read of the list.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchConsentLog,
  revokeConsent,
  type ConsentView,
} from "@/lib/consent/api";
import {
  counterpartyInitials,
  counterpartyLabel,
} from "@/lib/consent/consentView";
import {
  REVOCATION_NOTICE_CLASS,
  REVOCATION_NOTICE_MS,
} from "@/lib/consent/revocationNotice";

export function ConsentGrantsPanel() {
  const { lang } = useLang();
  const t = STRINGS[lang].profileZones;
  const [grants, setGrants] = useState<ConsentView[] | null>(null);
  const [loadFailure, setLoadFailure] = useState<{ traceId?: string } | null>(
    null,
  );
  const [target, setTarget] = useState<ConsentView | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeFailure, setRevokeFailure] = useState<{
    traceId?: string;
  } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setLoadFailure(null);
    try {
      const log = await fetchConsentLog();
      setGrants(log.items.filter((item) => item.status === "granted"));
    } catch (err) {
      // Keep whatever list is already on screen: a transient failure must not
      // erase grants the patient is reading.
      setLoadFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current !== null) clearTimeout(toastTimer.current);
    },
    [],
  );

  function flash(message: string) {
    setToast(message);
    if (toastTimer.current !== null) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), REVOCATION_NOTICE_MS);
  }

  async function confirmRevoke() {
    if (target === null) return;
    setRevoking(true);
    setRevokeFailure(null);
    try {
      await revokeConsent(target.consent_id);
      const id = target.consent_id;
      setGrants((current) =>
        current === null
          ? current
          : current.filter((item) => item.consent_id !== id),
      );
      setTarget(null);
      flash(t.consentRevokeDone);
    } catch (err) {
      // Sheet stays open with the grant intact so the tap can be retried.
      setRevokeFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setRevoking(false);
    }
  }

  const targetName =
    target === null
      ? ""
      : counterpartyLabel(target.counterparty_type, target.counterparty_id);

  return (
    <div data-testid="ps-consents">
      <p className="text-sm font-medium text-txt">{t.consentHeading}</p>
      <p className="mt-0.5 text-xs text-txt-muted">{t.consentSub}</p>

      {grants === null && !loadFailure && (
        <p
          className="mt-3 text-sm text-txt-muted"
          data-testid="ps-consent-loading"
        >
          {t.consentLoading}
        </p>
      )}

      {loadFailure !== null && (
        <div
          role="alert"
          data-testid="ps-consent-failed"
          className="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          <span>
            {t.consentLoadFailed}
            {loadFailure.traceId && (
              <span className="ml-1 font-mono text-xs">
                ({loadFailure.traceId})
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-md border border-danger-border px-2 py-1 text-xs font-medium text-danger"
            data-testid="ps-consent-retry"
          >
            {t.consentRetry}
          </button>
        </div>
      )}

      {grants !== null && grants.length === 0 && loadFailure === null && (
        <p
          className="mt-3 text-sm text-txt-muted"
          data-testid="ps-consent-empty"
        >
          {t.consentEmpty}
        </p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {grants?.map((grant) => {
          const name = counterpartyLabel(
            grant.counterparty_type,
            grant.counterparty_id,
          );
          const labels = t.scopeLabels as Record<string, string | undefined>;
          const scope = labels[grant.record_scope] ?? t.consentScopeOther;
          return (
            <li
              key={grant.consent_id}
              data-testid={`ps-consent-${grant.consent_id}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-hairline bg-surface px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong"
                >
                  {counterpartyInitials(name)}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-txt">
                    {name}
                  </p>
                  <p
                    className="text-xs text-txt-muted"
                    data-testid={`ps-consent-scope-${grant.consent_id}`}
                  >
                    {scope}
                  </p>
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                // The visible label is the same on every row, so name the row in
                // the accessible name: N identical "Revoke access" buttons are
                // indistinguishable to anyone navigating by control.
                aria-label={`${t.consentRevoke} - ${name}`}
                data-testid={`ps-consent-revoke-${grant.consent_id}`}
                onClick={() => {
                  setRevokeFailure(null);
                  setTarget(grant);
                }}
              >
                {t.consentRevoke}
              </Button>
            </li>
          );
        })}
      </ul>

      <Sheet
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) setTarget(null);
        }}
      >
        <SheetContent side="bottom" data-testid="ps-consent-sheet">
          <SheetHeader>
            <SheetTitle>{t.consentRevokeTitle}</SheetTitle>
            <SheetDescription>
              {t.consentRevokeBody(targetName)}
            </SheetDescription>
          </SheetHeader>
          {revokeFailure !== null && (
            <p
              role="alert"
              data-testid="ps-consent-revoke-failed"
              className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {t.consentRevokeFailed}
              {revokeFailure.traceId && (
                <span className="ml-1 font-mono text-xs">
                  ({revokeFailure.traceId})
                </span>
              )}
            </p>
          )}
          <SheetFooter className="mt-4 flex-row gap-2">
            <Button
              type="button"
              onClick={() => void confirmRevoke()}
              disabled={revoking}
              loading={revoking}
              data-testid="ps-consent-confirm"
            >
              {t.consentRevokeConfirm}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setTarget(null)}
              data-testid="ps-consent-cancel"
            >
              {t.consentRevokeCancel}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {toast && (
        <div
          role="status"
          data-testid="ps-consent-toast"
          className={REVOCATION_NOTICE_CLASS}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
