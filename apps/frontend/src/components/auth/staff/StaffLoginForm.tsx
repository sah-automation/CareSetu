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
import { STRINGS, type StaffAuthStrings } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { operatorLogin } from "@/lib/operator/api";

import { DoneScreen, type DoneScreenFact } from "../DoneScreen";
import {
  CountdownRing,
  EditLinkButton,
  ErrorMessage,
  FieldLabel,
  GhostButton,
  NoticeMessage,
  OtpInput,
  PrimaryButton,
} from "../otp/shared";
import stepStyles from "../otp/variantB.module.css";
import { usePartnerLoginFlow, type PartnerStage } from "./partnerLoginState";
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
 * partner. #566: the handoff no longer WAITS for this - it renders on the OTP
 * stage and shows the resolved facts once they arrive - so "null" now means
 * "the destination is still in flight", not "there is nothing to show".
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

/**
 * #566: the submit control's label, as a TOTAL function over the four steps.
 *
 * It used to be an inline ternary whose last arm was the phone step's copy, so
 * on the terminal step it fell all the way through to "Get verification code" -
 * a live button under an already-verified partner, reading as an invitation to
 * start signing in again. The fix is an explicit terminal arm, added as a new
 * case rather than by reordering the existing ones, because reordering silently
 * changes what the operator and MFA steps render and those are out of scope.
 *
 * It lives outside the component so every arm is addressable. The control
 * itself is rendered out on the terminal step (that is the stronger fix than
 * disabling it), which would leave the terminal arm as code no test can reach -
 * and an unreachable arm is exactly the kind of thing that rots. Here the
 * mapping is a pure function of (strings, step) and all four arms are asserted.
 */
export function staffSubmitLabel(
  login: StaffAuthStrings["login"],
  step: {
    isMfaStep: boolean;
    isOperatorMode: boolean;
    stage: PartnerStage;
  },
): string {
  if (step.isMfaStep) {
    return login.mfaSubmit;
  }
  if (step.isOperatorMode) {
    return login.signIn;
  }
  if (step.stage === "otp") {
    return login.mfaSubmit;
  }
  if (step.stage === "done") {
    return login.verifiedSubmit;
  }
  return login.getCode;
}

export function StaffLoginForm({
  role = "partner",
  returnTarget,
  onTerminalChange,
}: {
  role?: StaffLoginRole;
  /** `?return=` deep-link target, bounded to the staff groups; see staff-routing. */
  returnTarget?: string | null;
  /**
   * #566: reports that the sign-in flow has reached its terminal step, so a
   * host can retire its own sign-in chrome. The verified handoff brings its own
   * `h1`, so a host heading left in place would put two on one screen. Pass a
   * stable callback (a `useState` setter does); it is read in an effect, never
   * during render.
   */
  onTerminalChange?: (terminal: boolean) => void;
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
  // #551: the single post-login resume seam. Started once the partner session
  // exists and awaited by BOTH the countdown and the CTA, so the countdown
  // starts only after the session-resume call succeeds and a fast CTA click
  // cannot navigate before identity lands in state. `landedRef` keeps the
  // routine idempotent, so a click during the countdown and the tick at zero
  // cannot both navigate. #566: keyed on the session, not on the resolved
  // destination, so it is an independent signal rather than a mirror of
  // `landing` - the countdown gate is the conjunction of the two, not this
  // alone.
  const resumeRef = useRef<Promise<void> | null>(null);
  const landedRef = useRef(false);
  const [resumeSettled, setResumeSettled] = useState(false);

  // #566: the flow is terminal the moment the OTP stage hands over to the
  // handoff - the session is minted before the stage advances, and the
  // operator and MFA paths never reach this stage at all. The handoff renders
  // on the stage ALONE: keying it on anything else (the resolved destination, or
  // a latch the routing exits set) is the blank card this ticket reports.
  const flowTerminal = partner.state.stage === "done";

  useEffect(() => {
    onTerminalChange?.(flowTerminal);
  }, [flowTerminal, onTerminalChange]);

  const phoneRef = useRef<HTMLInputElement>(null);
  const totpRef = useRef<HTMLInputElement>(null);

  const resumeOnce = useCallback((): Promise<void> => {
    resumeRef.current ??= resumeSession();
    return resumeRef.current;
  }, [resumeSession]);

  // Resume the saved session in-flow (same no-reload seam as the patient flow,
  // #496) as soon as the partner session exists, then release the countdown.
  // Never a hard page reload on this path (AC-3). #566: keyed on the session
  // rather than on the resolved destination, so it runs concurrently with the
  // destination reads instead of after them - which is what lets the handoff be
  // on screen while they are still in flight. `resumeOnce` is idempotent by
  // ref, so this stays the one call site.
  useEffect(() => {
    if (partner.state.session === null) {
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
  }, [partner.state.session, resumeOnce]);

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
        // #566: the handoff renders on the STAGE, not on the resolved
        // destination. Destination resolution is no longer a render
        // precondition: while the three post-login reads are in flight the
        // handoff is already up, reporting a pending state and holding its
        // countdown back until there is genuinely somewhere to count down to.
        // This is what the patient flow's terminal step already does, and what
        // the partner flow's old `landing !== null` wrapper did not: that
        // wrapper returned null for the whole window, which is the blank card
        // with a live submit button that was reported.
        //
        // #537 still holds: the countdown owns the auto-redirect and "Go to
        // Dashboard" routes through the same resume-then-navigate routine, both
        // with the framework router rather than a hard reload.
        //
        // AC-6 is carried by the routing, not by a second render condition: a
        // pending or rejected partner's route read resolves to a `location.
        // replace` that swaps the document, and the countdown and CTA below both
        // no-op while `landing` is null, so no console destination is ever
        // engaged for them. A render-level latch here would mean editing the
        // three exit branches, which the ticket freezes.
        <DoneScreen
          title={t.verifiedTitle}
          body={t.verifiedBody}
          openingLabel={doneScreenT.openingDashboard}
          openingInLabel={doneScreenT.openingIn}
          goToDashboardLabel={doneScreenT.goToDashboard}
          // The conjunction, and it is load-bearing: the session-resume seam
          // is one call, the destination is a three-read chain, and the
          // countdown must not be released by either one alone.
          resumePending={!resumeSettled || landing === null}
          onGoToDashboard={landOnConsole}
          facts={landingFacts}
        />
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
            // Partner code step: countdown, code input, resend, back. Built
            // from the shared atoms the patient wizard renders for the same
            // interaction, so the two surfaces cannot drift (#572). The atoms
            // carry the treatment; the step carries only the state.
            //
            // `mb-4` stays, and is the one Tailwind utility left here: it is
            // the block margin the phone step above already uses, and the
            // status lines below are a sibling group, not part of this
            // section's gap.
            <div className={`mb-4 ${stepStyles.section}`}>
              <div className={stepStyles.center}>
                <div>
                  <p
                    className={stepStyles.sub}
                    data-testid="partner-code-expires"
                  >
                    {t.codeExpires}
                  </p>
                  <CountdownRing
                    seconds={partner.state.expiresIn}
                    testId="partner-countdown"
                  />
                </div>
              </div>
              <p className={stepStyles.sub} data-testid="partner-code-hint">
                {t.codeHint} <strong>{partner.state.phone}</strong>
              </p>
              <FieldLabel>
                {t.codeLabel}
                <OtpInput
                  value={partner.state.otpDraft}
                  onChange={partner.setOtpDraft}
                  disabled={partnerBlocked}
                  testId="partner-otp"
                />
              </FieldLabel>
              <div className={stepStyles.resendRow}>
                <GhostButton
                  onClick={partner.resendOtp}
                  disabled={
                    partnerBlocked || partner.state.cooldownRemaining > 0
                  }
                  testId="partner-resend"
                >
                  {t.resend}
                </GhostButton>
                <EditLinkButton
                  onClick={partner.backToPhone}
                  disabled={partner.state.busy}
                  testId="partner-edit-number"
                >
                  {t.backToEdit}
                </EditLinkButton>
              </div>
            </div>
          )}

          {/* The step's status lines. No atom owns these - they are the
          wizard's attempts treatment on hand-marked elements, and the
          lockout deliberately has no stage guard so it renders on both. */}
          <div className={stepStyles.section}>
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
              <p className={stepStyles.attempts} data-testid="partner-lockout">
                {t.lockout(Math.ceil(partner.state.lockoutRemaining / 60))}
              </p>
            )}
            {partner.state.stage === "otp" &&
              partner.state.cooldownRemaining > 0 &&
              partner.state.challenge !== "locked" && (
                <p
                  className={stepStyles.attempts}
                  data-testid="partner-resend-cooldown"
                >
                  {t.resendIn(partner.state.cooldownRemaining)}
                </p>
              )}
            {partner.state.stage === "otp" &&
              partner.state.challenge === "pending" && (
                <p
                  className={stepStyles.attempts}
                  data-testid="partner-attempts"
                >
                  {partner.state.attemptsLeft > 0
                    ? t.attemptsLeft(partner.state.attemptsLeft)
                    : t.noAttempts}
                </p>
              )}
            <ErrorMessage
              message={partner.state.lastError}
              testId="partner-error"
            />
            <NoticeMessage
              message={partner.state.lastNotice}
              testId="partner-notice"
            />
            {partner.state.stage === "otp" &&
              partner.demoOtp !== null &&
              partner.state.otpSends > 0 && (
                // The notice treatment, not the error one, and still a live
                // region: the code arrives asynchronously, so the announcement
                // is the only thing that reaches a screen reader.
                <NoticeMessage
                  message={t.demoOtp(partner.demoOtp)}
                  role="status"
                  testId="partner-demo-banner"
                />
              )}
          </div>
        </>
      )}

      {/* #566: the submit control is gated on the same terminal-ness as the
      handoff, so no orphan button can render beneath an in-flight handoff -
      rendering it out rather than merely disabling it. Its label is a total
      function of the step (see `staffSubmitLabel`), so the terminal step has its
      own copy instead of falling through to the phone step's "Get verification
      code". */}
      {flowTerminal ? null : (
        <PrimaryButton
          type="submit"
          testId="staff-submit"
          disabled={isOperatorMode || isMfaStep ? loading : partnerBlocked}
        >
          {staffSubmitLabel(t, {
            isMfaStep,
            isOperatorMode,
            stage: partner.state.stage,
          })}
        </PrimaryButton>
      )}
    </form>
  );
}
