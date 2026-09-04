"use client";

// PHASE-2.6 T10 (#201): the split-auth staff login card (blueprint section 4.2),
// visually and functionally distinct from the patient OTP wizard.
//
// PHASE-5 T4 (#282): wired to real operator login flow. Submit calls
// POST /v1/auth/operator/login (phone + TOTP). SESSION_MFA_REQUIRED (401)
// surfaces the TOTP input step. On successful auth: create session via
// saveSession, route via postLoginTarget. Phone display stays masked per IAM
// convention. Email + password fields remain for the partner staff login path.

import { useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import { fetchMe, type SessionResult } from "@/lib/auth/api";
import { postLoginTarget } from "@/lib/auth/staff-routing";
import { saveSession } from "@/lib/auth/session";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { operatorLogin } from "@/lib/operator/api";

import {
  staffOperatorErrorCopy,
  validateStaffLogin,
  type StaffLoginFieldError,
} from "./staffLoginState";

type FieldErrors = ReturnType<typeof validateStaffLogin>;
type FieldName = keyof FieldErrors;

interface Notice {
  kind: "phase5" | "envelope";
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
// then route through postLoginTarget. Used by both the password step and the
// TOTP step so a session/route change stays in one place.
async function completeStaffLogin(
  session: SessionResult,
): Promise<{ roles: string[]; phone: string }> {
  const me = await fetchMe(session.jwt);
  saveSession(session, me.phone);
  return { roles: me.roles, phone: me.phone };
}

export function StaffLoginForm() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.login;

  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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

  const phoneRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const totpRef = useRef<HTMLInputElement>(null);

  function errorFor(field: FieldName): StaffLoginFieldError | undefined {
    return fieldErrors[field];
  }

  function applyFieldResult(field: FieldName, errors: FieldErrors) {
    setFieldErrors((prev) => ({ ...prev, [field]: errors[field] }));
  }

  // section 9.5: validate on blur AND on submit; a blur re-checks just that field.
  function handleBlur(field: FieldName) {
    if (field === "code") {
      applyFieldResult(
        field,
        validateStaffLogin({ phone, email, password, code: totpCode }),
      );
    } else {
      applyFieldResult(field, validateStaffLogin({ phone, email, password }));
    }
  }

  // Landing after a successful login: persist the session and route through
  // postLoginTarget. Duplicated nowhere because both the password step and the
  // TOTP step funnel through completeStaffLogin, then this full-page redirect.
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
      const errors = validateStaffLogin({
        phone,
        email,
        password,
        code: totpCode,
      });
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

    // Operator path: phone filled - validate phone + 6-digit TOTP code.
    const rawPhone = phone.trim();
    if (rawPhone.length > 0) {
      const errors = validateStaffLogin({
        phone,
        email,
        password,
        code: totpCode,
      });
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

    // Partner staff path: email + password.
    const errors = validateStaffLogin({ phone, email, password });
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      if (errors.email) {
        emailRef.current?.focus();
      } else {
        passwordRef.current?.focus();
      }
      return;
    }

    // Partner staff login not yet wired - honest placeholder.
    setNotice({ kind: "phase5", message: t.phase5Notice });
  }

  const errorCount = Object.values(fieldErrors).filter(Boolean).length;
  const phoneError = errorFor("phone");
  const emailError = errorFor("email");
  const passwordError = errorFor("password");
  const codeError = errorFor("code");
  const isMfaStep = mfaContext !== null;
  const isOperatorMode = phone.trim().length > 0 && !isMfaStep;

  return (
    <form onSubmit={handleSubmit} noValidate data-testid="staff-login-form">
      {notice ? (
        <div
          role={notice.kind === "phase5" ? "status" : "alert"}
          data-testid={
            notice.kind === "phase5"
              ? "staff-phase5-notice"
              : "staff-login-error"
          }
          className={
            notice.kind === "phase5"
              ? "mb-4 rounded-md border border-hairline bg-surface px-3 py-2 text-sm"
              : "mb-4 rounded-md border border-danger bg-surface px-3 py-2 text-sm text-danger"
          }
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

      {isMfaStep ? (
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

          {isOperatorMode ? (
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
          ) : (
            <>
              <div className="mb-4">
                <label
                  htmlFor="staff-email"
                  className="mb-1 block text-sm font-medium"
                >
                  {t.emailLabel}
                </label>
                <input
                  ref={emailRef}
                  id="staff-email"
                  type="email"
                  autoComplete="username"
                  placeholder={t.emailPlaceholder}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  onBlur={() => handleBlur("email")}
                  aria-invalid={errorFor("email") ? true : undefined}
                  aria-describedby={
                    errorFor("email") ? "staff-email-error" : undefined
                  }
                  className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
                  data-testid="staff-email"
                />
                {emailError ? (
                  <p
                    id="staff-email-error"
                    data-testid="staff-email-error"
                    className="mt-1 text-sm text-danger"
                  >
                    {t[emailError]}
                  </p>
                ) : null}
              </div>

              <div className="mb-4">
                <label
                  htmlFor="staff-password"
                  className="mb-1 block text-sm font-medium"
                >
                  {t.passwordLabel}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    ref={passwordRef}
                    id="staff-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    onBlur={() => handleBlur("password")}
                    aria-invalid={errorFor("password") ? true : undefined}
                    aria-describedby={
                      errorFor("password") ? "staff-password-error" : undefined
                    }
                    className="min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 py-2"
                    data-testid="staff-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    aria-label={showPassword ? t.hidePassword : t.showPassword}
                    data-testid="password-toggle"
                    className="rounded-md border border-hairline px-2 py-1 text-sm"
                  >
                    {showPassword ? t.hidePassword : t.showPassword}
                  </button>
                </div>
                {passwordError ? (
                  <p
                    id="staff-password-error"
                    data-testid="staff-password-error"
                    className="mt-1 text-sm text-danger"
                  >
                    {t[passwordError]}
                  </p>
                ) : null}
                <a
                  href="#"
                  className="mt-1 inline-block text-sm underline"
                  data-testid="forgot-password"
                >
                  {t.forgotPassword}
                </a>
              </div>
            </>
          )}
        </>
      )}

      <button
        type="submit"
        data-testid="staff-submit"
        disabled={loading}
        className="mt-1 w-full rounded-md bg-primary px-4 py-2 font-semibold text-on-accent disabled:opacity-50"
      >
        {isMfaStep ? t.mfaSubmit : t.signIn}
      </button>
    </form>
  );
}
