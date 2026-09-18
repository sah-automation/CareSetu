"use client";

// PHASE-2.6 T10 (#201): the split-auth staff login card (blueprint section 4.2),
// visually and functionally distinct from the patient OTP wizard.
//
// PHASE-5 T4 (#282): wired to real operator login flow. Submit calls
// POST /v1/auth/operator/login (phone + TOTP). SESSION_MFA_REQUIRED (401)
// surfaces the TOTP input step. On successful auth: create session via
// saveSession, route via postLoginTarget. Phone display stays masked per IAM
// convention.
//
// PHASE-5 T7 (#467): partner mode is phone + SMS-code for real, reusing the
// patient wizard's interaction pattern (phone step -> code step, countdown,
// resend, demo OTP read-back banner) over the ADR-0016 partner routes. The
// dead email/password fields and the Phase-5 notice are gone from the partner
// card (ADR-0016 superseded email/password for partners). The operator branch
// is untouched.
//
// #302: the mode is fixed by the caller's role prop (default "partner",
// "operator" via ?role=operator) - fields never swap while the user types.

import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import { fetchMe, type SessionResult } from "@/lib/auth/api";
import { postLoginTarget } from "@/lib/auth/staff-routing";
import { saveSession } from "@/lib/auth/session";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { operatorLogin } from "@/lib/operator/api";

import { formatCountdown } from "../otp/otpState";
import { usePartnerLoginFlow } from "./partnerLoginState";
import {
  staffOperatorErrorCopy,
  validateStaffLogin,
  type StaffLoginRole,
} from "./staffLoginState";

type FieldErrors = ReturnType<typeof validateStaffLogin>;
type FieldName = keyof FieldErrors;

interface Notice {
  kind: "envelope";
  message: string;
  /** Short trace rendered alongside envelope errors only (section 9.5). */
  traceId?: string;
}

function maskPhone(phone: string): string {
  if (phone.length <= 4) return phone;
  const visible = phone.slice(-4);
  const masked = "X".repeat(phone.length - 4);
  return masked + visible;
}

// Shared post-auth landing: fetch the /v1/me profile, persist the session,
// then route through postLoginTarget. Used by the TOTP step and the partner
// OTP flow so a session/route change stays in one place.
async function completeStaffLogin(
  session: SessionResult,
): Promise<{ roles: string[]; phone: string }> {
  const me = await fetchMe(session.jwt);
  saveSession(session, me.phone);
  return { roles: me.roles, phone: me.phone };
}

export function StaffLoginForm({
  role = "partner",
}: {
  role?: StaffLoginRole;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.login;

  const isOperatorMode = role === "operator";
  const partner = usePartnerLoginFlow();

  const [phone, setPhone] = useState("");
  const [totpCode, setTotpCode] = useState("");
  // Set once SESSION_MFA_REQUIRED is seen: masked display number (never raw
  // PII) plus the raw number retained only for the TOTP verification request.
  const [mfaContext, setMfaContext] = useState<{
    masked: string;
    raw: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [attemptedSubmit, setAttemptedSubmit] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [partnerPhone, setPartnerPhone] = useState("");

  const phoneRef = useRef<HTMLInputElement>(null);
  const totpRef = useRef<HTMLInputElement>(null);

  // Partner landing: once the OTP flow has minted a partner session, persist
  // and route through the same save path as the operator flow. A failed
  // landing surfaces the envelope notice on the (now inert) code card instead
  // of stranding the caller silently.
  useEffect(() => {
    if (!partner.state.session) {
      return;
    }
    void landAfterLogin(partner.state.session).catch((error: unknown) =>
      setNotice(envelopeNotice(error)),
    );
    // Single-fire on mint - landAfterLogin closes over the render-stable
    // helpers that land a signed-in caller exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partner.state.session]);

  function errorFor(field: FieldName): FieldErrors[FieldName] | undefined {
    return fieldErrors[field];
  }

  function applyFieldResult(field: FieldName, errors: FieldErrors) {
    setFieldErrors((prev) => ({ ...prev, [field]: errors[field] }));
  }

  // section 9.5: validate on blur AND on submit; a blur re-checks just that field.
  function handleBlur(field: FieldName) {
    applyFieldResult(
      field,
      validateStaffLogin(
        { phone, email: "", password: "", code: totpCode },
        role,
      ),
    );
  }

  // Landing after a successful login: persist the session and route through
  // postLoginTarget. Used by the TOTP step and (via the effect above) the
  // partner code step.
  async function landAfterLogin(session: SessionResult) {
    const me = await completeStaffLogin(session);
    window.location.replace(
      postLoginTarget({ surface: "staff", roles: me.roles }),
    );
  }

  // Map any thrown value onto calm dictionary copy, reusing the operator
  // envelope mapper. The envelope retains its own trace id for the notice.
  function envelopeNotice(error: unknown): Notice {
    return {
      kind: "envelope",
      message: staffOperatorErrorCopy(error, t),
      traceId: error instanceof ApiError ? error.traceId : undefined,
    };
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setAttemptedSubmit(true);
    setNotice(null);

    // TOTP re-verification step (SESSION_MFA_REQUIRED fallback): phone already
    // submitted, now verify the TOTP code.
    if (mfaContext !== null) {
      const errors = validateStaffLogin(
        { phone, email: "", password: "", code: totpCode },
        role,
      );
      if (errors.code) {
        setFieldErrors({ code: errors.code });
        totpRef.current?.focus();
        return;
      }
      const trimmedCode = totpCode.trim();
      setLoading(true);
      operatorLogin({ phone: mfaContext.raw, code: trimmedCode })
        .then((session) => landAfterLogin(session))
        .catch((error: unknown) => setNotice(envelopeNotice(error)))
        .finally(() => setLoading(false));
      return;
    }

    // Operator path: role pinned by the caller (URL ?role=operator), not by
    // what the user typed. Validate phone + 6-digit TOTP code.
    if (isOperatorMode) {
      const errors = validateStaffLogin(
        { phone, email: "", password: "", code: totpCode },
        role,
      );
      setFieldErrors(errors);
      if (errors.phone || errors.code) {
        if (errors.phone) {
          phoneRef.current?.focus();
        } else {
          totpRef.current?.focus();
        }
        return;
      }
      setLoading(true);
      const rawPhone = phone.trim();
      operatorLogin({ phone: rawPhone, code: totpCode.trim() })
        .then((session) => landAfterLogin(session))
        .catch((error: unknown) => {
          if (
            error instanceof ApiError &&
            error.code === "SESSION_MFA_REQUIRED"
          ) {
            setMfaContext({ masked: maskPhone(rawPhone), raw: rawPhone });
            setTotpCode("");
            setFieldErrors({});
            setNotice(null);
            setTimeout(() => totpRef.current?.focus(), 0);
          } else {
            setNotice(envelopeNotice(error));
          }
        })
        .finally(() => setLoading(false));
      return;
    }

    // Partner path: phone -> SMS code. The step decides which action runs:
    // the phone step requests the code, the code step verifies it.
    if (partner.state.stage === "phone") {
      partner.submitPhone(partnerPhone);
    } else {
      partner.submitOtp();
    }
  }

  const errorCount = Object.values(fieldErrors).filter(Boolean).length;
  const phoneError = errorFor("phone");
  const codeError = errorFor("code");
  const isMfaStep = mfaContext !== null;

  const partnerBlocked =
    partner.state.busy || partner.state.challenge === "locked";

  return (
    <form onSubmit={handleSubmit} noValidate data-testid="staff-login-form">
      {notice ? (
        <div
          role="alert"
          data-testid="staff-login-error"
          className="mb-4 rounded-md border border-danger bg-surface px-3 py-2 text-sm text-danger"
        >
          {notice.message}
          {notice.traceId ? (
            <span className="mt-1 block font-mono text-xs opacity-75">
              {notice.traceId}
            </span>
          ) : null}
        </div>
      ) : null}

      {attemptedSubmit && errorCount > 0 ? (
        <div
          role="alert"
          data-testid="staff-form-summary"
          className="mb-4 rounded-md border border-danger bg-surface px-3 py-2 text-sm text-danger"
        >
          {t.summaryTitle(errorCount)}
        </div>
      ) : null}

      {isOperatorMode ? (
        isMfaStep ? (
          <>
            <p
              data-testid="mfa-phone-display"
              className="mb-4 text-sm text-on-surface"
            >
              {mfaContext.masked}
            </p>

            <div className="mb-4">
              <label
                htmlFor="staff-mfa"
                className="mb-1 block text-sm font-medium"
              >
                {t.mfaCodeLabel}
              </label>
              <input
                ref={totpRef}
                id="staff-mfa"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(event) => setTotpCode(event.target.value)}
                aria-invalid={codeError ? true : undefined}
                aria-describedby={codeError ? "staff-mfa-error" : undefined}
                className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
                data-testid="mfa-input"
              />
              {codeError ? (
                <p
                  id="staff-mfa-error"
                  data-testid="mfa-code-error"
                  className="mt-1 text-sm text-danger"
                >
                  {t[codeError]}
                </p>
              ) : null}
              <p className="mt-1 text-xs opacity-80">{t.mfaHelp}</p>
            </div>
          </>
        ) : (
          <>
            <div className="mb-4">
              <label
                htmlFor="staff-phone"
                className="mb-1 block text-sm font-medium"
              >
                {t.phoneLabel}
              </label>
              <input
                ref={phoneRef}
                id="staff-phone"
                type="tel"
                autoComplete="tel"
                placeholder={t.phonePlaceholder}
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                onBlur={() => handleBlur("phone")}
                aria-invalid={errorFor("phone") ? true : undefined}
                aria-describedby={
                  errorFor("phone") ? "staff-phone-error" : undefined
                }
                className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
                data-testid="staff-phone"
              />
              {phoneError ? (
                <p
                  id="staff-phone-error"
                  data-testid="staff-phone-error"
                  className="mt-1 text-sm text-danger"
                >
                  {t[phoneError]}
                </p>
              ) : null}
            </div>

            <div className="mb-4">
              <label
                htmlFor="staff-totp"
                className="mb-1 block text-sm font-medium"
              >
                {t.mfaCodeLabel}
              </label>
              <input
                ref={totpRef}
                id="staff-totp"
                inputMode="numeric"
                maxLength={6}
                placeholder="000000"
                value={totpCode}
                onChange={(event) => setTotpCode(event.target.value)}
                onBlur={() => handleBlur("code")}
                aria-invalid={codeError ? true : undefined}
                aria-describedby={codeError ? "staff-totp-error" : undefined}
                className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
                data-testid="staff-totp"
              />
              {codeError ? (
                <p
                  id="staff-totp-error"
                  data-testid="staff-totp-error"
                  className="mt-1 text-sm text-danger"
                >
                  {t[codeError]}
                </p>
              ) : null}
              <p className="mt-1 text-xs opacity-80">{t.mfaHelp}</p>
            </div>
          </>
        )
      ) : partner.state.stage === "done" ? null : (
        <>
          {/* Partner phone step: collect the number, request the SMS code. */}
          {partner.state.stage === "phone" ? (
            <div className="mb-4">
              <label
                htmlFor="staff-partner-phone"
                className="mb-1 block text-sm font-medium"
              >
                {t.phoneLabel}
              </label>
              <input
                id="staff-partner-phone"
                type="tel"
                inputMode="numeric"
                autoComplete="tel"
                placeholder={t.phonePlaceholder}
                value={partnerPhone}
                onChange={(event) => setPartnerPhone(event.target.value)}
                disabled={partner.state.challenge === "locked"}
                aria-invalid={partner.state.lastError ? true : undefined}
                aria-describedby={
                  partner.state.lastError ? "partner-error" : undefined
                }
                className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
                data-testid="partner-phone"
              />
            </div>
          ) : (
            <>
              {/* Partner code step: countdown, code input, resend, back. */}
              <div className="mb-4 text-center">
                <p
                  className="text-xs opacity-80"
                  data-testid="partner-code-expires"
                >
                  {t.codeExpires}
                </p>
                <p
                  className="text-lg font-semibold"
                  data-testid="partner-countdown"
                >
                  {formatCountdown(partner.state.expiresIn)}
                </p>
                <p
                  className="text-sm text-on-surface"
                  data-testid="partner-code-hint"
                >
                  {t.codeHint} <strong>{partner.state.phone}</strong>
                </p>
              </div>

              <div className="mb-4">
                <label
                  htmlFor="staff-partner-otp"
                  className="mb-1 block text-sm font-medium"
                >
                  {t.codeLabel}
                </label>
                <input
                  id="staff-partner-otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={partner.state.otpDraft}
                  onChange={(event) => partner.setOtpDraft(event.target.value)}
                  disabled={partnerBlocked}
                  aria-invalid={partner.state.lastError ? true : undefined}
                  aria-describedby={
                    partner.state.lastError ? "partner-error" : undefined
                  }
                  className="w-full rounded-md border border-hairline bg-surface px-3 py-2 tracking-[0.5em]"
                  data-testid="partner-otp"
                />
              </div>

              <div className="mb-4 flex items-center gap-3">
                <button
                  type="button"
                  onClick={partner.resendOtp}
                  disabled={
                    partnerBlocked || partner.state.cooldownRemaining > 0
                  }
                  className="rounded-md border border-hairline px-3 py-1.5 text-sm disabled:opacity-50"
                  data-testid="partner-resend"
                >
                  {t.resend}
                </button>
                <button
                  type="button"
                  onClick={partner.backToPhone}
                  disabled={partner.state.busy}
                  className="text-sm underline"
                  data-testid="partner-edit-number"
                >
                  {t.backToEdit}
                </button>
              </div>
            </>
          )}

          {partner.state.stage === "phone" &&
            partner.state.cooldownRemaining > 0 && (
              <p
                className="mb-2 text-sm text-on-surface"
                data-testid="partner-cooldown"
              >
                {t.resendIn(partner.state.cooldownRemaining)}
              </p>
            )}
          {partner.state.challenge === "locked" && (
            <p
              className="mb-2 text-sm text-danger"
              data-testid="partner-lockout"
            >
              {t.lockout(Math.ceil(partner.state.lockoutRemaining / 60))}
            </p>
          )}
          {partner.state.stage === "otp" &&
            partner.state.cooldownRemaining > 0 &&
            partner.state.challenge !== "locked" && (
              <p
                className="mb-2 text-sm text-on-surface"
                data-testid="partner-resend-cooldown"
              >
                {t.resendIn(partner.state.cooldownRemaining)}
              </p>
            )}
          {partner.state.stage === "otp" &&
            partner.state.challenge === "pending" && (
              <p
                className="mb-2 text-sm text-on-surface"
                data-testid="partner-attempts"
              >
                {partner.state.attemptsLeft > 0
                  ? t.attemptsLeft(partner.state.attemptsLeft)
                  : t.noAttempts}
              </p>
            )}
          {partner.state.lastError ? (
            <p
              role="alert"
              className="mb-2 text-sm text-danger"
              data-testid="partner-error"
            >
              {partner.state.lastError}
            </p>
          ) : null}
          {partner.state.lastNotice ? (
            <p
              className="mb-2 text-sm text-on-surface"
              data-testid="partner-notice"
            >
              {partner.state.lastNotice}
            </p>
          ) : null}
          {partner.state.stage === "otp" &&
            partner.demoOtp !== null &&
            partner.state.otpSends > 0 && (
              <div
                role="status"
                data-testid="partner-demo-banner"
                className="mb-2 rounded-md border border-hairline bg-surface px-3 py-2 text-sm"
              >
                {t.demoOtp(partner.demoOtp)}
              </div>
            )}
        </>
      )}

      <button
        type="submit"
        data-testid="staff-submit"
        disabled={isOperatorMode || isMfaStep ? loading : partnerBlocked}
        className="mt-1 w-full rounded-md bg-primary px-4 py-2 font-semibold text-on-accent disabled:opacity-50"
      >
        {isMfaStep
          ? t.mfaSubmit
          : isOperatorMode
            ? t.signIn
            : partner.state.stage === "otp"
              ? t.mfaSubmit
              : t.getCode}
      </button>
    </form>
  );
}
