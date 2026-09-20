"use client";

// PHASE-5 T7 (#467): partner phone-OTP login flow state for the staff login
// card, mirroring the patient auth wizard's interaction pattern (otpState.ts)
// while driving the ADR-0016 partner routes instead:
// /v1/auth/partner/login -> /v1/auth/partner/verify -> /v1/auth/partner/session.
//
// The shared OTP machine semantics are unchanged: latest-wins resend, >= 60 s
// cooldown, 5-attempt budget, 5-minute TTL, 15-minute phone lockout
// (SMS-cost failures only). The partner-only ``no_account`` refusal points
// back to registration and never mints anything, and a successful verify is
// silent for the patient lifecycle - no patient role, no patient event, no
// patient session (the mint calls issuePartnerSession, never issueSession).
//
// Refusals render exactly as on the patient surface: cooldown / locked with
// the matching countdown, suspended, and wrong/expired/spent on the code step.

import { useEffect, useMemo, useState } from "react";

import {
  fetchDemoOtp,
  issuePartnerSession,
  partnerLogin,
  partnerVerify,
  type SessionResult,
} from "@/lib/auth/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

import {
  LOCKOUT_SECONDS,
  MAX_ATTEMPTS,
  normalizePhone,
  OTP_TTL_SECONDS,
  RESEND_COOLDOWN_SECONDS,
} from "../otp/otpState";
import { partnerLoginErrorCopy } from "./staffLoginState";

export type PartnerStage = "phone" | "otp" | "done";
export type PartnerChallengeStatus = "idle" | "pending" | "spent" | "locked";

export interface PartnerOtpState {
  stage: PartnerStage;
  /** E.164 phone the challenge was issued for (normalized server-style). */
  phone: string;
  challenge: PartnerChallengeStatus;
  attemptsLeft: number;
  cooldownRemaining: number;
  expiresIn: number;
  lockoutRemaining: number;
  lastNotice: string | null;
  lastError: string | null;
  otpDraft: string;
  busy: boolean;
  /** Partner-scoped session minted after a verified code; drives the landing. */
  session: SessionResult | null;
  otpSends: number;
}

export interface PartnerOtpFlow {
  state: PartnerOtpState;
  /** Demo-only OTP read-back, non-null only when NEXT_PUBLIC_DEMO_MODE=true. */
  demoOtp: string | null;
  submitPhone: (raw: string) => void;
  submitOtp: () => void;
  resendOtp: () => void;
  setOtpDraft: (digits: string) => void;
  backToPhone: () => void;
}

function partnerInitialState(): PartnerOtpState {
  return {
    stage: "phone",
    phone: "",
    challenge: "idle",
    attemptsLeft: MAX_ATTEMPTS,
    cooldownRemaining: 0,
    expiresIn: OTP_TTL_SECONDS,
    lockoutRemaining: 0,
    lastNotice: null,
    lastError: null,
    otpDraft: "",
    busy: false,
    session: null,
    otpSends: 0,
  };
}

export function usePartnerLoginFlow(): PartnerOtpFlow {
  const { lang } = useLang();
  const [state, setState] = useState<PartnerOtpState>(partnerInitialState);

  // Demo-mode OTP read-back banner (DEPLOY-4, #118), gated exactly like the
  // patient wizard: inert unless NEXT_PUBLIC_DEMO_MODE is inlined as "true".
  const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const [demoOtp, setDemoOtp] = useState<string | null>(null);

  useEffect(() => {
    if (!demoMode || state.stage !== "otp" || state.otpSends < 1) {
      return;
    }
    setDemoOtp(null);
    let cancelled = false;
    void fetchDemoOtp(state.phone).then((code) => {
      if (!cancelled) {
        setDemoOtp(code);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [demoMode, state.stage, state.otpSends, state.phone]);

  // Shared 1-second countdown ticker, mirroring the patient flow.
  useEffect(() => {
    const id = setInterval(() => {
      setState((s) => {
        const cooldownRemaining = Math.max(0, s.cooldownRemaining - 1);
        const lockoutRemaining = Math.max(0, s.lockoutRemaining - 1);
        const expiresIn = Math.max(0, s.expiresIn - 1);
        let challenge =
          s.challenge === "pending" && expiresIn <= 0 ? "spent" : s.challenge;
        if (challenge === "locked" && lockoutRemaining <= 0) {
          challenge = "idle";
        }
        const next: PartnerOtpState = {
          ...s,
          cooldownRemaining,
          lockoutRemaining,
          expiresIn,
          challenge,
        };
        if (
          next.cooldownRemaining === s.cooldownRemaining &&
          next.lockoutRemaining === s.lockoutRemaining &&
          next.expiresIn === s.expiresIn &&
          next.challenge === s.challenge
        ) {
          return s;
        }
        return next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  return useMemo<PartnerOtpFlow>(() => {
    const t = STRINGS[lang].staffAuth.login;

    const flow: PartnerOtpFlow = {
      state,
      demoOtp,
      submitPhone: (raw: string) => {
        const phone = normalizePhone(raw);
        if (phone === null) {
          setState((s) => ({
            ...s,
            lastError: t.phoneInvalid,
            lastNotice: null,
          }));
          return;
        }
        setState((s) => ({ ...s, busy: true }));
        void partnerLogin(phone)
          .then((result) => {
            if (result.outcome === "no_account") {
              setState((s) => ({
                ...s,
                phone,
                busy: false,
                lastError: t.noAccount,
                lastNotice: null,
              }));
              return;
            }
            if (result.outcome === "cooldown") {
              const cooldown = result.cooldown_remaining_seconds ?? 0;
              setState((s) => ({
                ...s,
                phone,
                cooldownRemaining: cooldown,
                busy: false,
                lastError: null,
                lastNotice: null,
              }));
              return;
            }
            if (result.outcome === "locked") {
              const lockoutSeconds =
                result.lockout_remaining_seconds ?? LOCKOUT_SECONDS;
              setState((s) => ({
                ...s,
                phone,
                challenge: "locked",
                lockoutRemaining: lockoutSeconds,
                busy: false,
                lastError: null,
                lastNotice: null,
              }));
              return;
            }
            if (result.outcome === "suspended") {
              setState((s) => ({
                ...s,
                phone,
                busy: false,
                lastError: t.suspendedNotice,
                lastNotice: null,
              }));
              return;
            }
            setState((s) => ({
              ...s,
              phone,
              stage: "otp",
              challenge: "pending",
              attemptsLeft: result.attempts_left ?? MAX_ATTEMPTS,
              cooldownRemaining:
                result.cooldown_remaining_seconds ?? RESEND_COOLDOWN_SECONDS,
              expiresIn: result.expires_in_seconds ?? OTP_TTL_SECONDS,
              otpDraft: "",
              busy: false,
              lastError: null,
              lastNotice: null,
              otpSends: s.otpSends + 1,
            }));
          })
          .catch((error: unknown) => {
            setState((s) => ({
              ...s,
              busy: false,
              lastError: partnerLoginErrorCopy(error, t),
              lastNotice: null,
            }));
          });
      },
      submitOtp: () => {
        const s = state;
        if (s.lockoutRemaining > 0) {
          setState((prev) => ({
            ...prev,
            lastError: t.lockout(Math.ceil(s.lockoutRemaining / 60)),
          }));
          return;
        }
        if (s.challenge !== "pending") {
          setState((prev) => ({ ...prev, lastError: t.expiredOrUsed }));
          return;
        }
        if (s.otpDraft.length !== 6) {
          setState((prev) => ({ ...prev, lastError: t.shortCode }));
          return;
        }
        setState((prev) => ({ ...prev, busy: true }));
        void partnerVerify(s.phone, s.otpDraft)
          .then((result) => {
            if (result.outcome === "verified") {
              return issuePartnerSession(s.phone)
                .then((sessionResult) => {
                  setState((prev) => ({
                    ...prev,
                    stage: "done",
                    challenge: "spent",
                    otpDraft: "",
                    busy: false,
                    lastError: null,
                    lastNotice: null,
                    session: sessionResult,
                  }));
                })
                .catch((error: unknown) => {
                  setState((prev) => ({
                    ...prev,
                    busy: false,
                    lastError: partnerLoginErrorCopy(error, t),
                  }));
                });
            }
            if (result.outcome === "wrong_code") {
              const attemptsLeft = result.attempts_left ?? s.attemptsLeft - 1;
              setState((prev) => ({
                ...prev,
                attemptsLeft,
                otpDraft: "",
                busy: false,
                lastError: t.wrongCode(attemptsLeft),
              }));
              return;
            }
            if (result.outcome === "expired" || result.outcome === "spent") {
              setState((prev) => ({
                ...prev,
                challenge: "spent",
                otpDraft: "",
                busy: false,
                lastError: t.expiredOrUsed,
              }));
              return;
            }
            const lockoutSeconds =
              result.lockout_remaining_seconds ?? s.lockoutRemaining;
            setState((prev) => ({
              ...prev,
              challenge: "locked",
              lockoutRemaining: lockoutSeconds,
              otpDraft: "",
              busy: false,
              lastError: t.lockout(Math.ceil(lockoutSeconds / 60)),
            }));
          })
          .catch((error: unknown) => {
            setState((prev) => ({
              ...prev,
              busy: false,
              lastError: partnerLoginErrorCopy(error, t),
            }));
          });
      },
      resendOtp: () => {
        const s = state;
        if (s.lockoutRemaining > 0) {
          setState((prev) => ({
            ...prev,
            lastError: t.lockout(Math.ceil(s.lockoutRemaining / 60)),
          }));
          return;
        }
        if (s.cooldownRemaining > 0) {
          setState((prev) => ({
            ...prev,
            lastError: t.resendEarly(s.cooldownRemaining),
          }));
          return;
        }
        if (s.stage !== "otp") return;
        setState((prev) => ({ ...prev, busy: true }));
        void partnerLogin(s.phone)
          .then((result) => {
            if (result.outcome === "sent") {
              setState((prev) => ({
                ...prev,
                challenge: "pending",
                attemptsLeft: result.attempts_left ?? MAX_ATTEMPTS,
                cooldownRemaining:
                  result.cooldown_remaining_seconds ?? RESEND_COOLDOWN_SECONDS,
                expiresIn: result.expires_in_seconds ?? OTP_TTL_SECONDS,
                otpDraft: "",
                busy: false,
                lastError: null,
                lastNotice: t.latestWins,
                otpSends: prev.otpSends + 1,
              }));
              return;
            }
            if (result.outcome === "cooldown") {
              const cooldown =
                result.cooldown_remaining_seconds ?? s.cooldownRemaining;
              setState((prev) => ({
                ...prev,
                cooldownRemaining: cooldown,
                busy: false,
                lastError: t.resendEarly(cooldown),
                lastNotice: null,
              }));
              return;
            }
            if (result.outcome === "locked") {
              const lockoutSeconds =
                result.lockout_remaining_seconds ?? s.lockoutRemaining;
              setState((prev) => ({
                ...prev,
                challenge: "locked",
                lockoutRemaining: lockoutSeconds,
                busy: false,
                lastError: t.lockout(Math.ceil(lockoutSeconds / 60)),
                lastNotice: null,
              }));
              return;
            }
            if (result.outcome === "suspended") {
              setState((prev) => ({
                ...prev,
                challenge: "spent",
                busy: false,
                lastError: t.suspendedNotice,
                lastNotice: null,
              }));
              return;
            }
            setState((prev) => ({
              ...prev,
              stage: "phone",
              phone: "",
              challenge: "idle",
              busy: false,
              lastError: t.noAccount,
              lastNotice: null,
            }));
          })
          .catch((error: unknown) => {
            setState((prev) => ({
              ...prev,
              busy: false,
              lastError: partnerLoginErrorCopy(error, t),
            }));
          });
      },
      setOtpDraft: (digits: string) => {
        const clean = digits.replace(/[^0-9]/g, "").slice(0, 6);
        setState((s) => ({ ...s, otpDraft: clean, lastError: null }));
      },
      backToPhone: () => setState(partnerInitialState()),
    };

    return flow;
  }, [state, lang, demoOtp]);
}
