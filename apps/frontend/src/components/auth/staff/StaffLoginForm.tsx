"use client";

// PHASE-2.6 T10 (#201): the split-auth staff login card (blueprint §4.2),
// visually and functionally distinct from the patient OTP wizard - email +
// password here, no phone step, and deliberately NO role picker (the role
// derives server-side from the account at sign-in, never chosen by hand).
//
// Pages only this phase: submitting never fakes success - it names Phase 5
// honestly and nothing leaves the browser. `staffLoginErrorCopy` (pure,
// suite-tested on stable codes) is the seam Phase 5's real envelopes plug
// into; when that happens an envelope notice renders its short trace_id per
// ui-blueprint §9.5. The MFA step renders only while enrollment is indicated
// by local state - which nothing sets until Phase 5 wires TOTP - and its
// input stays disabled even then.

import { useRef, useState } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

import {
  validateStaffLogin,
  type StaffLoginFieldError,
} from "./staffLoginState";

type FieldErrors = ReturnType<typeof validateStaffLogin>;
type FieldName = keyof FieldErrors;

interface Notice {
  kind: "phase5" | "envelope";
  message: string;
  /** Short trace rendered alongside envelope errors only (§9.5). */
  traceId?: string;
}

export interface StaffLoginFormProps {
  /**
   * Local stand-in for the Phase 5 session flag ("account has MFA enrolled").
   * Nothing sets it this phase; it exists so the slot's rendering rule and
   * its inertness are provable in isolation.
   */
  mfaEnrolled?: boolean;
}

export function StaffLoginForm({ mfaEnrolled = false }: StaffLoginFormProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.login;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  // Per-field errors accumulate from blur checks; the summary block above the
  // form appears only once a submit has been attempted (§9.5).
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [attemptedSubmit, setAttemptedSubmit] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  function errorFor(field: FieldName): StaffLoginFieldError | undefined {
    return fieldErrors[field];
  }

  function applyFieldResult(field: FieldName, errors: FieldErrors) {
    setFieldErrors((prev) => ({ ...prev, [field]: errors[field] }));
  }

  // §9.5: validate on blur AND on submit; a blur re-checks just that field.
  function handleBlur(field: FieldName) {
    applyFieldResult(field, validateStaffLogin({ email, password }));
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setAttemptedSubmit(true);
    setNotice(null);

    const errors = validateStaffLogin({ email, password });
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      // Failed submit announces the count via the summary block and moves
      // focus to the first invalid field.
      if (errors.email) {
        emailRef.current?.focus();
      } else {
        passwordRef.current?.focus();
      }
      return;
    }

    // Honest submit: staff auth lands in Phase 5. No request, no fake
    // success state - the banner says exactly that.
    setNotice({ kind: "phase5", message: t.phase5Notice });
  }

  const errorCount = Object.values(fieldErrors).filter(Boolean).length;
  const emailError = errorFor("email");
  const passwordError = errorFor("password");

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

      <div className="mb-4">
        <label htmlFor="staff-email" className="mb-1 block text-sm font-medium">
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
          aria-describedby={errorFor("email") ? "staff-email-error" : undefined}
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

      {/* Conditional post-password MFA step: renders ONLY while the account
          is flagged enrolled (nothing sets that until Phase 5), and its input
          stays disabled - the step is a slot, never functional this phase. */}
      {mfaEnrolled ? (
        <div
          aria-disabled="true"
          data-testid="mfa-slot"
          className="mb-4 opacity-60"
        >
          <label htmlFor="staff-mfa" className="mb-1 block text-sm font-medium">
            {t.mfaCodeLabel}
          </label>
          <input
            id="staff-mfa"
            inputMode="numeric"
            maxLength={6}
            disabled
            className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
            data-testid="mfa-input"
          />
          <p className="mt-1 text-xs opacity-80">{t.mfaHelp}</p>
        </div>
      ) : null}

      <button
        type="submit"
        data-testid="staff-submit"
        className="mt-1 w-full rounded-md bg-primary px-4 py-2 font-semibold text-on-accent"
      >
        {t.signIn}
      </button>
    </form>
  );
}
