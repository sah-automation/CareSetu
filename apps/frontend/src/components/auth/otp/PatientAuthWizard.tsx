"use client";

// MOD-001 patient auth wizard (PHASE-2 T9, #60), folded from the Variant B
// prototype's ``OtpPrototype`` + ``variantB``. Step one collects the phone and
// calls the live register endpoint, step two verifies the OTP with the
// countdown ring / resend cooldown / attempts-left / lockout states, and a
// successful verify stores the session so the patient lands on the
// authenticated home - the protected patient view. Prototype-only chrome
// (mock OTP hint, state strip, demo toggles) is gone; the only demo surface
// left is the build-flag-gated OTP read-back banner (DEPLOY-4, #118), which
// is inert unless NEXT_PUBLIC_DEMO_MODE is inlined as "true" at build time.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  IconCheck,
  IconHeart,
  IconPhone,
  IconShield,
} from "@/components/auth/icons";
import { DoneScreen } from "@/components/auth/DoneScreen";
import { fetchDemoOtp } from "@/lib/auth/api";
import { useAuth } from "@/lib/auth/AuthContext";
import { useLang } from "@/lib/i18n/LangContext";
import { STRINGS, type DoneScreenStrings } from "@/lib/i18n/dictionaries";
import type { OtpFlow } from "./otpState";
import { useOtpFlow } from "./otpState";
import {
  BrandHeader,
  CountdownRing,
  EditLinkButton,
  ErrorMessage,
  FieldLabel,
  GhostButton,
  NoticeMessage,
  OtpInput,
  PhoneInput,
  PrimaryButton,
} from "./shared";
import shared from "./otpShared.module.css";
import stylesB from "./variantB.module.css";

function StepDots({ flow }: { flow: OtpFlow }) {
  const { state, t } = flow;
  const steps = [t.stepPhone, t.stepVerify, t.stepDone];
  const current = state.stage === "phone" ? 0 : state.stage === "otp" ? 1 : 2;
  return (
    <ol className={stylesB.steps}>
      {steps.map((label, i) => (
        <li
          key={label}
          className={`${stylesB.step} ${
            i < current
              ? stylesB.stepDone
              : i === current
                ? stylesB.stepCurrent
                : ""
          }`}
        >
          <span className={stylesB.stepNum}>
            {i < current ? <IconCheck size={14} /> : i + 1}
          </span>
          <span className={stylesB.stepLabel}>{label}</span>
        </li>
      ))}
    </ol>
  );
}

function PhoneStep({ flow }: { flow: OtpFlow }) {
  const { state, t } = flow;
  const [phoneDraft, setPhoneDraft] = useState(
    state.phone.replace(/^\+91/, ""),
  );
  return (
    <section className={stylesB.section}>
      <h1 className={stylesB.title}>{t.verify}</h1>
      <ul className={stylesB.props}>
        <li>
          <span className={stylesB.propIcon}>
            <IconShield size={16} />
          </span>
          {t.valueProps[0]}
        </li>
        <li>
          <span className={stylesB.propIcon}>
            <IconHeart size={16} />
          </span>
          {t.valueProps[1]}
        </li>
        <li>
          <span className={stylesB.propIcon}>
            <IconPhone size={16} />
          </span>
          {t.valueProps[2]}
        </li>
      </ul>
      <div className={stylesB.field}>
        <FieldLabel>{t.phoneLabel}</FieldLabel>
        <PhoneInput
          value={phoneDraft}
          onChange={setPhoneDraft}
          placeholder={t.phonePlaceholder}
        />
      </div>
      <NoticeMessage message={state.lastNotice} />
      <ErrorMessage message={state.lastError} />
      {state.cooldownRemaining > 0 && state.challenge !== "locked" && (
        <p className={stylesB.attempts}>
          {t.resendIn(state.cooldownRemaining)}
        </p>
      )}
      {state.challenge === "locked" && (
        <p className={stylesB.attempts}>
          {t.lockout(Math.ceil(state.lockoutRemaining / 60))}
        </p>
      )}
      <PrimaryButton
        onClick={() => flow.submitPhone(phoneDraft)}
        disabled={state.busy || state.challenge === "locked"}
      >
        {t.getCode}
      </PrimaryButton>
    </section>
  );
}

function OtpStep({ flow }: { flow: OtpFlow }) {
  const { state, t } = flow;
  const lockout = state.challenge === "locked" || state.lockoutRemaining > 0;
  const blocked = lockout || state.busy;
  return (
    <section className={stylesB.section}>
      <h1 className={stylesB.title}>{t.verify}</h1>
      <div className={stylesB.center}>
        <div>
          <p className={stylesB.sub}>{t.codeExpires}</p>
          <CountdownRing seconds={state.expiresIn} />
        </div>
      </div>
      <p className={stylesB.sub}>
        {t.codeHint} <strong>{state.phone}</strong>
      </p>
      <NoticeMessage message={state.lastNotice} />
      <OtpInput
        value={state.otpDraft}
        onChange={flow.setOtpDraft}
        autoFocus
        disabled={blocked}
      />
      <div className={stylesB.resendRow}>
        <GhostButton
          onClick={flow.resendOtp}
          disabled={blocked || state.cooldownRemaining > 0}
        >
          {t.resend}
        </GhostButton>
        <EditLinkButton onClick={flow.backToPhone}>
          {t.backToEdit}
        </EditLinkButton>
      </div>
      {state.cooldownRemaining > 0 && !lockout && (
        <p className={stylesB.attempts}>
          {t.resendIn(state.cooldownRemaining)}
        </p>
      )}
      {state.challenge === "pending" && state.attemptsLeft > 0 && (
        <p className={stylesB.attempts}>{t.attemptsLeft(state.attemptsLeft)}</p>
      )}
      {state.challenge === "pending" && state.attemptsLeft === 0 && (
        <p className={stylesB.attempts}>{t.noAttempts}</p>
      )}
      <ErrorMessage message={state.lastError} />
      <PrimaryButton
        onClick={flow.submitOtp}
        disabled={blocked}
        pending={state.otpDraft.length !== 6}
      >
        {t.verify}
      </PrimaryButton>
    </section>
  );
}

function DoneStep({
  flow,
  doneScreenT,
  resumePending,
  onGoToDashboard,
}: {
  flow: OtpFlow;
  doneScreenT: DoneScreenStrings;
  resumePending: boolean;
  onGoToDashboard: () => void;
}) {
  const { t } = flow;
  return (
    <DoneScreen
      title={t.verifiedTitle}
      body={t.verifiedBody}
      openingLabel={doneScreenT.openingDashboard}
      openingInLabel={doneScreenT.openingIn}
      goToDashboardLabel={doneScreenT.goToDashboard}
      resumePending={resumePending}
      onGoToDashboard={onGoToDashboard}
    />
  );
}

export function PatientAuthWizard({
  returnTo = "/patient",
}: {
  // Post-auth destination (PHASE-2.6 T07 #198): the sanitized `return`
  // target from the login surface; defaults to the patient app home.
  returnTo?: string;
}) {
  const flow = useOtpFlow();
  // Locale is app-wide state now (PHASE-2.6 T03, #194): the wizard reads and
  // toggles it through LangContext instead of wizard-local state.
  const { lang, setLang } = useLang();
  const router = useRouter();
  // #496: the session-resume seam resolves the freshly-persisted login session
  // in-flow, so the post-login surface hydrates without a reload.
  const { resumeSession } = useAuth();
  const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const [demoOtp, setDemoOtp] = useState<string | null>(null);

  useEffect(() => {
    if (!demoMode || flow.state.stage !== "otp" || flow.state.otpSends < 1) {
      return;
    }
    setDemoOtp(null);
    let cancelled = false;
    void fetchDemoOtp(flow.state.phone).then((code) => {
      if (!cancelled) {
        setDemoOtp(code);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [demoMode, flow.state.stage, flow.state.otpSends, flow.state.phone]);

  // Redirect to the return target if already authenticated (session exists
  // from reload)
  useEffect(() => {
    if (
      flow.state.hydrated &&
      flow.state.session &&
      flow.state.stage !== "done"
    ) {
      router.replace(returnTo);
    }
  }, [
    flow.state.hydrated,
    flow.state.session,
    flow.state.stage,
    returnTo,
    router,
  ]);

  // #551: one post-login routine for BOTH the countdown and the CTA. The
  // session-resume seam is started once and awaited by whichever signal
  // arrives first, so a fast "Go to Dashboard" click goes through the same
  // resume-then-navigate ordering as the auto path - identity/roles land in
  // state BEFORE the post-login route mounts, because a patient surface that
  // mounted identity-less makes the Provider remount that applies identity
  // reset an in-progress completion wizard and wipe its draft (#496). A reload
  // is never needed; the seam is best-effort by design, since
  // resumeSession never rejects. `landedRef` keeps it idempotent, so a click
  // during the countdown and the tick at zero cannot both navigate.
  const resumeRef = useRef<Promise<void> | null>(null);
  const landedRef = useRef(false);
  const [resumeSettled, setResumeSettled] = useState(false);

  const resumeOnce = useCallback((): Promise<void> => {
    resumeRef.current ??= resumeSession();
    return resumeRef.current;
  }, [resumeSession]);

  // Start the resume once the flow is done; the countdown is released (and
  // only the countdown drives the auto-redirect) after it settles.
  useEffect(() => {
    if (flow.state.stage !== "done" || !flow.state.session) {
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
  }, [flow.state.stage, flow.state.session, resumeOnce]);

  const landOnReturnTarget = useCallback(() => {
    if (landedRef.current) {
      return;
    }
    landedRef.current = true;
    void resumeOnce().then(() => router.replace(returnTo));
  }, [resumeOnce, router, returnTo]);

  if (!flow.state.hydrated) {
    return null;
  }

  // While redirect is in-flight, render nothing
  if (flow.state.session && flow.state.stage !== "done") {
    return null;
  }

  return (
    <div className={`${shared.otpProto} ${stylesB.root}`}>
      <BrandHeader t={flow.t} lang={lang} onLang={setLang} />
      <nav aria-label={flow.t.stepProgress}>
        <StepDots flow={flow} />
      </nav>
      <main className={stylesB.main}>
        <div className={stylesB.card}>
          {flow.state.stage === "otp" && demoMode && demoOtp !== null && (
            <div className={stylesB.demoBanner} role="status">
              Demo OTP: {demoOtp}
            </div>
          )}
          {flow.state.stage === "phone" && <PhoneStep flow={flow} />}
          {flow.state.stage === "otp" && <OtpStep flow={flow} />}
          {flow.state.stage === "done" && (
            <DoneStep
              flow={flow}
              doneScreenT={STRINGS[lang].doneScreen}
              resumePending={!resumeSettled}
              onGoToDashboard={landOnReturnTarget}
            />
          )}
        </div>
      </main>
    </div>
  );
}
