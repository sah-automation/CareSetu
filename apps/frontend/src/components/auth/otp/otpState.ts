"use client";

// MOD-001 patient auth flow state (PHASE-2 T9, #60), folded from the Variant B
// prototype on `backup/t8-local-history`. The prototype's in-memory mock was
// the behavioural contract; here the same state machine is driven by the live
// /v1/auth endpoints (register -> verify -> session, resend latest-wins).
//
// Resolved decisions it implements (spec #51 §2.4):
//   - single-use = one successful use
//   - 5-attempt budget per challenge; wrong guesses do not kill the OTP
//   - latest-wins resend: a resend invalidates the pending challenge
//   - resend cooldown >= 60 s per phone, measured from last issuance
//   - 10 consecutive failures across challenges -> 15 min phone lockout
//   - +91-only E.164 normalization
//   - Suspended is NOT the lockout; lockout is a temporary counter

import { useEffect, useMemo, useState } from "react";

import { STRINGS, type AuthStrings } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  AuthApiError,
  issueSession,
  registerPhone,
  resendOtp as resendOtpRequest,
  type SessionResult,
  verifyOtp,
} from "@/lib/auth/api";
import {
  clearSession,
  readSession,
  saveSession,
  type StoredSession,
} from "@/lib/auth/session";

export const OTP_TTL_SECONDS = 300;
export const RESEND_COOLDOWN_SECONDS = 60;
export const MAX_ATTEMPTS = 5;
export const LOCKOUT_SECONDS = 900;

export type ChallengeStatus = "idle" | "pending" | "spent" | "locked";
export type Stage = "phone" | "otp" | "done";

export interface OtpState {
  stage: Stage;
  phone: string;
  isExisting: boolean;
  challenge: ChallengeStatus;
  attemptsLeft: number;
  cooldownRemaining: number;
  expiresIn: number;
  lockoutRemaining: number;
  lastNotice: string | null;
  lastError: string | null;
  otpDraft: string;
  verifiedAt: string | null;
  busy: boolean;
  session: StoredSession | null;
  otpSends: number;
  hydrated: boolean;
}

export function initialState(): OtpState {
  return {
    stage: "phone",
    phone: "",
    isExisting: false,
    challenge: "idle",
    attemptsLeft: MAX_ATTEMPTS,
    cooldownRemaining: 0,
    expiresIn: OTP_TTL_SECONDS,
    lockoutRemaining: 0,
    lastNotice: null,
    lastError: null,
    otpDraft: "",
    verifiedAt: null,
    busy: false,
    session: null,
    otpSends: 0,
    hydrated: false,
  };
}

export function normalizePhone(raw: string): string | null {
  let digits = raw.replace(/[^0-9]/g, "");
  if (digits.startsWith("91") && digits.length === 12) {
    digits = digits.slice(2);
  }
  if (digits.length === 10 && /^[6-9]/.test(digits)) {
    return `+91${digits}`;
  }
  return null;
}

export function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(Math.max(0, totalSeconds) / 60);
  const s = Math.max(0, totalSeconds) % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// The wizard's bilingual copy lives in the app-wide typed dictionaries
// (`@/lib/i18n/dictionaries`, PHASE-2.6 T03 #194) under the auth.* surface;
// this flow reads its locale from LangContext instead of wizard-local state.

export interface OtpFlow {
  state: OtpState;
  t: AuthStrings;
  submitPhone: (raw: string) => void;
  submitOtp: () => void;
  resendOtp: () => void;
  setOtpDraft: (digits: string) => void;
  backToPhone: () => void;
  signOut: () => void;
}

function errorString(error: unknown, t: AuthStrings): string {
  if (error instanceof AuthApiError) {
    switch (error.code) {
      case "PHONE_INVALID":
      case "VALIDATION_ERROR":
        return t.badPhone;
      case "SMS_DELIVERY_FAILED":
        return t.smsFailed;
      default:
        return t.networkError;
    }
  }
  return t.networkError;
}

export function useOtpFlow(): OtpFlow {
  const { lang } = useLang();
  const [state, setState] = useState<OtpState>(initialState);

  // Hydration gate: render nothing until we know whether a session is stored,
  // so a signed-in reload never flashes the auth form. The server and the
  // first client render both see hydrated=false; the effect flips it once.
  useEffect(() => {
    const stored = readSession();
    // The set-state-in-effect rule is intentionally suspended here - this is
    // the canonical Next.js SSR/client-mismatch guard.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, session: stored ?? s.session, hydrated: true }));
  }, []);

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
        const next: OtpState = {
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

  return useMemo<OtpFlow>(() => {
    const t = STRINGS[lang].auth;

    const flow: OtpFlow = {
      state,
      t,
      submitPhone: (raw: string) => {
        const phone = normalizePhone(raw);
        if (phone === null) {
          setState((s) => ({ ...s, lastError: t.badPhone, lastNotice: null }));
          return;
        }
        setState((s) => ({ ...s, busy: true }));
        void registerPhone(phone)
          .then((result) => {
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
              const lockoutSeconds = result.lockout_remaining_seconds ?? 0;
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
              isExisting: result.is_existing,
              challenge: "pending",
              attemptsLeft: result.attempts_left ?? MAX_ATTEMPTS,
              cooldownRemaining:
                result.cooldown_remaining_seconds ?? RESEND_COOLDOWN_SECONDS,
              expiresIn: result.expires_in_seconds ?? OTP_TTL_SECONDS,
              otpDraft: "",
              busy: false,
              lastError: null,
              lastNotice: result.is_existing ? t.duplicateNotice : null,
              otpSends: s.otpSends + 1,
            }));
          })
          .catch((error: unknown) => {
            setState((s) => ({
              ...s,
              busy: false,
              lastError: errorString(error, t),
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
        void verifyOtp(s.phone, s.otpDraft)
          .then((result) => {
            if (result.outcome === "verified") {
              return issueSession(s.phone)
                .then((sessionResult) => {
                  const stored = toStoredSession(sessionResult, s.phone);
                  saveSession(sessionResult, s.phone);
                  setState((prev) => ({
                    ...prev,
                    stage: "done",
                    challenge: "spent",
                    otpDraft: "",
                    busy: false,
                    lastError: null,
                    lastNotice: null,
                    verifiedAt: new Date().toISOString(),
                    session: stored,
                  }));
                })
                .catch((error: unknown) => {
                  setState((prev) => ({
                    ...prev,
                    busy: false,
                    lastError: errorString(error, t),
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
              lastError: errorString(error, t),
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
        void resendOtpRequest(s.phone)
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
              lastError: null,
              lastNotice: t.notRegistered,
            }));
          })
          .catch((error: unknown) => {
            setState((prev) => ({
              ...prev,
              busy: false,
              lastError: errorString(error, t),
            }));
          });
      },
      setOtpDraft: (digits: string) => {
        const clean = digits.replace(/[^0-9]/g, "").slice(0, 6);
        setState((s) => ({ ...s, otpDraft: clean, lastError: null }));
      },
      backToPhone: () =>
        setState((s) => ({
          ...initialState(),
          isExisting: s.isExisting,
          hydrated: true,
        })),
      signOut: () => {
        clearSession();
        setState((s) => ({ ...initialState(), hydrated: true }));
      },
    };

    return flow;
  }, [state, lang]);
}

function toStoredSession(session: SessionResult, phone: string): StoredSession {
  return {
    jwt: session.jwt,
    refresh_token: session.refresh_token,
    jti: session.jti,
    scope: session.scope,
    identity_id: session.identity_id,
    phone,
  };
}
