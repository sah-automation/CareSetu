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

import { useEffect, useState } from "react";

import {
  IconCheck,
  IconDirectory,
  IconHeart,
  IconLock,
  IconPhone,
  IconShield,
} from "@/components/auth/icons";
import { fetchDemoOtp } from "@/lib/auth/api";
import type { OtpFlow } from "./otpState";
import { formatCountdown, OTP_TTL_SECONDS, useOtpFlow } from "./otpState";
import {
  BrandHeader,
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

function CountdownRing({ seconds }: { seconds: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, seconds / OTP_TTL_SECONDS));
  const low = seconds <= 60;
  return (
    <div className={stylesB.ring} aria-hidden="true">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke="var(--hairline)"
          strokeWidth="5"
        />
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke={low ? "var(--danger)" : "var(--accent)"}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - frac)}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <span className={`${stylesB.ringTime} ${low ? stylesB.ringTimeLow : ""}`}>
        {formatCountdown(seconds)}
      </span>
    </div>
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
        <button
          type="button"
          className={stylesB.editLink}
          onClick={flow.backToPhone}
        >
          {t.backToEdit}
        </button>
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

function DoneStep({ flow }: { flow: OtpFlow }) {
  const { t } = flow;
  return (
    <section className={stylesB.section}>
      <div className={stylesB.center}>
        <span className={stylesB.successIcon}>
          <IconCheck size={40} />
        </span>
      </div>
      <h1 className={stylesB.title}>{t.verifiedTitle}</h1>
      <p className={stylesB.sub}>{t.verifiedBody}</p>
      <ul className={stylesB.props}>
        <li>
          <span className={stylesB.propIcon}>
            <IconDirectory size={16} />
          </span>
          {t.valueProps[1]}
        </li>
        <li>
          <span className={stylesB.propIcon}>
            <IconLock size={16} />
          </span>
          {t.valueProps[2]}
        </li>
      </ul>
      <PrimaryButton onClick={flow.goHome}>{t.goHome}</PrimaryButton>
    </section>
  );
}

function AuthenticatedHome({ flow }: { flow: OtpFlow }) {
  const { state, t } = flow;
  const session = state.session;
  return (
    <div className={`${shared.otpProto} ${stylesB.root}`}>
      <BrandHeader t={t} lang={state.lang} onLang={flow.setLang} />
      <main className={stylesB.main}>
        <div className={stylesB.card}>
          <section className={stylesB.section}>
            <div className={stylesB.center}>
              <span className={stylesB.successIcon}>
                <IconCheck size={40} />
              </span>
            </div>
            <h1 className={stylesB.title}>{t.sessionTitle}</h1>
            <p className={stylesB.sub}>{t.sessionBody}</p>
            {session && (
              <p className={stylesB.attempts}>{t.signedInAs(session.phone)}</p>
            )}
            <PrimaryButton onClick={flow.signOut}>{t.signOut}</PrimaryButton>
          </section>
        </div>
      </main>
    </div>
  );
}

export function PatientAuthWizard() {
  const flow = useOtpFlow();
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

  if (!flow.state.hydrated) {
    return null;
  }

  // A stored session lands on the authenticated home on reload; right after a
  // successful verify the stage is still "done", so the folded Done step shows
  // first and "Go to CareSetu home" moves on.
  if (flow.state.session && flow.state.stage !== "done") {
    return <AuthenticatedHome flow={flow} />;
  }

  return (
    <div className={`${shared.otpProto} ${stylesB.root}`}>
      <BrandHeader t={flow.t} lang={flow.state.lang} onLang={flow.setLang} />
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
          {flow.state.stage === "done" && <DoneStep flow={flow} />}
        </div>
      </main>
    </div>
  );
}
