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

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api-errors";
import { ROLE_HOME } from "@/components/dashboard/types";
import { fetchMe, type SessionResult } from "@/lib/auth/api";
import {
  fetchPartnerRouteState,
  isDoctorConsoleLanding,
  postLoginTarget,
} from "@/lib/auth/staff-routing";
import { useAuth } from "@/lib/auth/AuthContext";
import { saveSession } from "@/lib/auth/session";
import { fetchDoctorProfile } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { operatorLogin } from "@/lib/operator/api";

import { DoneScreen, type DoneScreenFact } from "../DoneScreen";
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

/**
 * The resolved landing of an Active doctor partner, plus the practice facts
 * the verified handoff shows (US-3). Null until the landing has resolved;
 * non-null only for a doctor-console landing, never for a pending or rejected
 * partner.
 */
interface DoctorLanding {
  /** The post-login destination the countdown and the CTA both route to. */
  target: string;
  practiceName: string | null;
  specialty: string | null;
}

// The handoff's practice facts come from the private doctor-profile projection
// the batch already ships (#542) - the same partner record, no new endpoint.
// The read is best-effort: a failure degrades to a handoff without the
// practice line (logged, never silently dropped) instead of stranding the
// login on a blank card.
async function readPracticeIdentity(): Promise<{
  practiceName: string | null;
  specialty: string | null;
}> {
  try {
    const profile = await fetchDoctorProfile();
    return {
      practiceName: profile.practice_name,
      specialty: profile.specialty,
    };
  } catch (error) {
    console.error(
      "[staff-login] practice details unreadable; handoff without them",
      error,
    );
    return { practiceName: null, specialty: null };
  }
}

export function StaffLoginForm({
  role = "partner",
  returnTarget,
}: {
  role?: StaffLoginRole;
  /** `?return=` deep-link target, bounded to the staff groups; see staff-routing. */
  returnTarget?: string | null;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.login;

  const isOperatorMode = role === "operator";
  const partner = usePartnerLoginFlow();
  const router = useRouter();
  const { resumeSession } = useAuth();

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
  // #537/#551: the resolved doctor-console landing for an Active partner
  // after verify, shown on the shared done screen. Null until the landing has
  // resolved; non-null only for a console landing (pending/rejected, an
  // unreadable status and every non-console landing route immediately).
  const [landing, setLanding] = useState<DoctorLanding | null>(null);
  // #551: the single post-login resume seam. Started once the landing resolves
  // and awaited by BOTH the countdown and the CTA, so the countdown starts
  // only after the session-resume call succeeds and a fast CTA click cannot
  // navigate before identity lands in state. `landedRef` keeps the routine
  // idempotent, so a click during the countdown and the tick at zero cannot
  // both navigate.
  const resumeRef = useRef<Promise<void> | null>(null);
  const landedRef = useRef(false);
  const [resumeSettled, setResumeSettled] = useState(false);

  const phoneRef = useRef<HTMLInputElement>(null);
  const totpRef = useRef<HTMLInputElement>(null);

  const resumeOnce = useCallback((): Promise<void> => {
    resumeRef.current ??= resumeSession();
    return resumeRef.current;
  }, [resumeSession]);

  // Resume the saved session in-flow (same no-reload seam as the patient flow,
  // #496) once the landing is known, then release the countdown. Never a hard
  // page reload on this path (AC-3).
  useEffect(() => {
    if (partner.state.stage !== "done" || landing === null) {
      return;
    }
    let cancelled = false;
    void resumeOnce().then(() => {
      if (!cancelled) {
        setResumeSettled(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [partner.state.stage, landing, resumeOnce]);

  // The countdown at zero and the always-visible CTA share this one routine.
  const landOnConsole = useCallback(() => {
    if (landedRef.current || landing === null) {
      return;
    }
    landedRef.current = true;
    void resumeOnce().then(() => router.replace(landing.target));
  }, [landing, resumeOnce, router]);

  // The immediate active-partner landing that shows no done screen: same
  // resume-then-navigate ordering, so it too never mounts a route before the
  // session is in state.
  const landOn = useCallback(
    async (target: string) => {
      if (landedRef.current) {
        return;
      }
      landedRef.current = true;
      await resumeOnce();
      router.replace(target);
    },
    [resumeOnce, router],
  );

  // Partner landing: once the OTP flow has minted a partner session, resolve
  // the post-login destination and branch (#537). A failed landing surfaces
  // the envelope notice on the (now inert) code card instead of stranding the
  // caller silently.
  useEffect(() => {
    if (!partner.state.session) {
      return;
    }
    void landPartnerAfterLogin(partner.state.session).catch((error: unknown) =>
      setNotice(envelopeNotice(error)),
    );
    // Single-fire on mint - landPartnerAfterLogin closes over the
    // render-stable helpers that land a signed-in caller exactly once.
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
  // partner code step. For a partner session, the partner's own status drives
  // the landing (§4.4): pending / under verification -> waiting screen,
  // rejected -> rejection screen, active -> normal role routing (an active
  // doctor lands on the doctor console, #475). When the visitor arrived via a
  // staff deep link, the sanitized ?return= target is threaded through so they
  // land back on it (F014-T09b) - partner state still beats it.
  async function landAfterLogin(session: SessionResult) {
    const me = await completeStaffLogin(session);
    window.location.replace(
      postLoginTarget({
        surface: "staff",
        roles: me.roles,
        returnTarget,
        ...(await fetchPartnerRouteState(me.roles)),
      }),
    );
  }

  // #537: variant for the partner plan only. Resolves the routing output first
  // (same matrix; postLoginTarget is mocked in tests) but DEPENDS on it for
  // the branch, so it is split from the operator path that keeps the hard
  // reload (out of scope). An ACTIVE DOCTOR partner (partnerState undefined,
  // doctor type) whose resolved target IS a console landing hands that target
  // to the done screen and moves there via the framework router once the
  // session resumes (AC-1). Every other landing routes on immediately and
  // never sees the done screen (AC-2): pending and rejected to their status
  // screens exactly as before, and an active doctor bound for some other
  // surface (a ?return= deep link outside the console) to that target.
  async function landPartnerAfterLogin(session: SessionResult) {
    const me = await completeStaffLogin(session);
    const routeState = await fetchPartnerRouteState(me.roles);
    const target = postLoginTarget({
      surface: "staff",
      roles: me.roles,
      returnTarget,
      ...routeState,
    });
    if (
      routeState.partnerType !== "doctor" ||
      routeState.partnerState !== undefined
    ) {
      window.location.replace(target);
      return;
    }
    if (!isDoctorConsoleLanding(target)) {
      // Active doctor, not a console landing: no console-branded handoff, so
      // route straight on - still the no-hard-reload active path.
      await landOn(target);
      return;
    }
    setLanding({ target, ...(await readPracticeIdentity()) });
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

  const doneScreenT = STRINGS[lang].doneScreen;
  // US-3: the doctor handoff says which practice the caller is signing in to
  // and where they are headed. The practice name and specialty are the values
  // already fetched after the partner read; the labels are dictionary copy, and
  // a fact with no value (unset practice name, unreadable profile) is dropped
  // rather than rendered blank.
  const landingFacts: DoneScreenFact[] = [];
  if (landing !== null) {
    if (landing.practiceName) {
      landingFacts.push({
        label: doneScreenT.practiceLabel,
        value: landing.practiceName,
      });
    }
    if (landing.specialty) {
      landingFacts.push({
        label: doneScreenT.specialtyLabel,
        value: landing.specialty,
      });
    }
    landingFacts.push({
      label: doneScreenT.destinationLabel,
      value:
        landing.target === ROLE_HOME.doctor
          ? doneScreenT.consoleDestination
          : landing.target,
    });
  }

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
              className="mb-4 text-sm text-txt-sub"
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
      ) : partner.state.stage === "done" ? (
        landing !== null ? (
          // #537: ACTIVE doctor console landing. The destination resolved
          // before this renders; the countdown owns the auto-redirect and
          // "Go to Dashboard" routes through the same resume-then-navigate
          // routine, both with the framework router.
          <DoneScreen
            title={t.verifiedTitle}
            body={t.verifiedBody}
            openingLabel={doneScreenT.openingDashboard}
            openingInLabel={doneScreenT.openingIn}
            goToDashboardLabel={doneScreenT.goToDashboard}
            resumePending={!resumeSettled}
            onGoToDashboard={landOnConsole}
            facts={landingFacts}
          />
        ) : null
      ) : (
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
                  className="text-sm text-txt-sub"
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
                className="mb-2 text-sm text-txt-sub"
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
                className="mb-2 text-sm text-txt-sub"
                data-testid="partner-resend-cooldown"
              >
                {t.resendIn(partner.state.cooldownRemaining)}
              </p>
            )}
          {partner.state.stage === "otp" &&
            partner.state.challenge === "pending" && (
              <p
                className="mb-2 text-sm text-txt-sub"
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
              className="mb-2 text-sm text-txt-sub"
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
