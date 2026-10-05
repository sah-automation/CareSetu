"use client";

// #615: the consultation-fee editor, lifted out of the page's `FeeEditor` as the
// page's last section component.
//
// It keeps the fee's OWN save rather than joining the declared band's section
// writes, because the fee is not part of any of them: it goes through the
// unchanged `PATCH /v1/partner/consultation-fee` route against the same partner
// record, and the landing page's editor used the same path. Folding it in would
// mean re-declaring the fee on a profile section body that has no such field -
// the one save button per write is what keeps each write honest about what it
// carries.
//
// The per-attempt idempotency key is the editor's own, not the page's, and it is
// the same discipline the photo picker uses: one key per attempt, so a retry of
// the same amount cannot be written twice, and a new amount mints a new one.

import { useRef, useState, type FormEvent } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { idempotencyKey } from "@/lib/idempotency";
import { useLang } from "@/lib/i18n/LangContext";
import { updateConsultationFee } from "@/lib/partner/api";
import { formatFeePaise } from "@/components/pick/DoctorPickCard";
import { ProfileField, fieldClassName } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import type { SectionFailure } from "./ProfileSectionShell";

export interface ConsultationFeeCardProps {
  feePaise: number | null;
  onFeeSaved: (feePaise: number | null) => void;
}

export function ConsultationFeeCard({
  feePaise,
  onFeeSaved,
}: ConsultationFeeCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  const [feeInput, setFeeInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const [failure, setFailure] = useState<SectionFailure | null>(null);
  const attemptKey = useRef<string | null>(null);

  function changeFeeInput(value: string) {
    setFeeInput(value);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    attemptKey.current = null;
  }

  async function saveFee() {
    const rupees = Number(feeInput);
    if (!Number.isFinite(rupees) || rupees < 0) {
      setInvalid(true);
      return;
    }
    setSaving(true);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    const key = attemptKey.current ?? idempotencyKey();
    attemptKey.current = key;
    try {
      // The unchanged fee path: the same PATCH route the landing used, against
      // the same partner record. The reply is a partner view without the fee,
      // so the parent's local projection is the source of truth for the value.
      await updateConsultationFee(Math.round(rupees * 100), key);
      attemptKey.current = null;
      setSaved(true);
      onFeeSaved(Math.round(rupees * 100));
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setSaving(true);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    const key = idempotencyKey();
    try {
      await updateConsultationFee(null, key);
      setFeeInput("");
      setSaved(true);
      onFeeSaved(null);
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      id={PROFILE_ANCHORS.fee}
      data-testid="fee-editor"
      // The editor validates the amount itself so a bad entry is named in the
      // form instead of being swallowed by a native bubble.
      noValidate
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void saveFee();
      }}
    >
      <Card>
        <CardHeader>
          {/* shadcn's CardTitle is a div, so the heading element is nested inside
              it rather than styled by ARIA - the page's outline keeps real
              headings to skip between. */}
          <CardTitle>
            <h2 className="text-sm font-semibold text-txt">{t.feeHeading}</h2>
          </CardTitle>
          <p className="text-sm text-txt-muted">{t.feeHelp}</p>
        </CardHeader>
        <CardContent>
          {feePaise !== null && (
            <p className="text-sm text-txt" data-testid="fee-current">
              {formatFeePaise(feePaise)}
            </p>
          )}

          <div className="flex flex-wrap items-end gap-2">
            <div className="w-40">
              <ProfileField id="profile-fee" label={t.feeFieldLabel}>
                <input
                  id="profile-fee"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="1"
                  value={feeInput}
                  onChange={(event) => changeFeeInput(event.target.value)}
                  aria-invalid={invalid}
                  placeholder={t.feeFieldPlaceholder}
                  className={fieldClassName(invalid)}
                  data-testid="fee-input"
                />
              </ProfileField>
            </div>
            <Button
              type="submit"
              size="sm"
              disabled={saving || feeInput === ""}
              loading={saving}
              data-testid="fee-save"
            >
              {t.saveFee}
            </Button>
            {feePaise !== null && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={saving}
                onClick={() => void handleClear()}
                data-testid="fee-clear"
              >
                {t.clearFee}
              </Button>
            )}
          </div>

          {saved && (
            <p className="mt-2 text-sm text-success" data-testid="fee-message">
              {t.feeSaved}
            </p>
          )}
          {invalid && (
            <p
              className="mt-2 text-sm text-danger"
              role="alert"
              data-testid="fee-invalid"
            >
              {t.feeInvalid}
            </p>
          )}
        </CardContent>
      </Card>
      {failure && (
        <ErrorBanner
          message={t.feeSaveFailed}
          traceId={failure.traceId}
          onRetry={() => void saveFee()}
          onDismiss={() => setFailure(null)}
        />
      )}
    </form>
  );
}
