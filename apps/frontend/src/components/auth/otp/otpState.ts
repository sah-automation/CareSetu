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

export type Lang = "en" | "hi";
export type ChallengeStatus = "idle" | "pending" | "spent" | "locked";
export type Stage = "phone" | "otp" | "done";

export interface OtpState {
  lang: Lang;
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
    lang: "en",
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

export interface I18n {
  brand: string;
  tagline: string;
  phoneLabel: string;
  phonePlaceholder: string;
  getCode: string;
  verify: string;
  resend: string;
  backToEdit: string;
  codeLabel: string;
  codeHint: string;
  codeExpires: string;
  resendIn: (s: number) => string;
  attemptsLeft: (n: number) => string;
  noAttempts: string;
  wrongCode: (n: number) => string;
  badPhone: string;
  shortCode: string;
  lockout: (m: number) => string;
  resendEarly: (s: number) => string;
  expiredOrUsed: string;
  latestWins: string;
  duplicateNotice: string;
  verifiedTitle: string;
  verifiedBody: string;
  goHome: string;
  welcome: string;
  stepPhone: string;
  stepVerify: string;
  stepDone: string;
  stepProgress: string;
  valueProps: string[];
  networkError: string;
  smsFailed: string;
  suspendedNotice: string;
  notRegistered: string;
  sessionTitle: string;
  sessionBody: string;
  signedInAs: (phone: string) => string;
  signOut: string;
}

export const STRINGS: Record<Lang, I18n> = {
  en: {
    brand: "CareSetu",
    tagline: "Your health, connected",
    phoneLabel: "Mobile number",
    phonePlaceholder: "10-digit mobile number",
    getCode: "Get verification code",
    verify: "Verify & continue",
    resend: "Resend code",
    backToEdit: "Edit number",
    codeLabel: "Verification code",
    codeHint: "6-digit code sent by SMS to",
    codeExpires: "Code expires in",
    resendIn: (s) => `Resend in ${s}s`,
    attemptsLeft: (n) => `${n} ${n === 1 ? "attempt" : "attempts"} left`,
    noAttempts: "No attempts left. Request a new code.",
    wrongCode: (n) =>
      `Wrong code. ${n} ${n === 1 ? "attempt" : "attempts"} left.`,
    badPhone: "Enter a valid 10-digit Indian mobile number.",
    shortCode: "Enter the full 6-digit code.",
    lockout: (m) =>
      `Too many failed attempts. Verification locked for ${m} min.`,
    resendEarly: (s) => `Cooldown active. Resend in ${s}s.`,
    expiredOrUsed:
      "This code has expired or was already used. Request a new one.",
    latestWins: "A new code was sent. The previous code is no longer valid.",
    duplicateNotice:
      "This number is already registered - verifying logs you in.",
    verifiedTitle: "Identity verified",
    verifiedBody: "Your number is verified and your session is ready.",
    goHome: "Go to CareSetu home",
    welcome: "One verified identity for your entire health journey.",
    stepPhone: "Phone",
    stepVerify: "Verify",
    stepDone: "Done",
    stepProgress: "Sign in progress",
    valueProps: [
      "One stable identity - no duplicate accounts",
      "Your record stays yours, shared only with your consent",
      "Works in English and Hindi",
    ],
    networkError: "Could not reach the server. Check your connection.",
    smsFailed: "We could not send the code. Try again in a moment.",
    suspendedNotice:
      "This number is suspended. Contact support for assistance.",
    notRegistered:
      "This number was never registered. Go back and get a code first.",
    sessionTitle: "You're signed in",
    sessionBody: "Your identity is verified and your health journey is ready.",
    signedInAs: (phone) => `Signed in as ${phone}`,
    signOut: "Sign out",
  },
  hi: {
    brand: "सेतु",
    tagline: "आपका स्वास्थ्य, जुड़ा हुआ",
    phoneLabel: "मोबाइल नंबर",
    phonePlaceholder: "10 अंकों का मोबाइल नंबर",
    getCode: "वेरिफिकेशन कोड पाएँ",
    verify: "सत्यापित करें",
    resend: "कोड फिर से भेजें",
    backToEdit: "नंबर बदलें",
    codeLabel: "वेरिफिकेशन कोड",
    codeHint: "SMS से भेजा गया 6 अंकों का कोड",
    codeExpires: "कोड समाप्त होने में",
    resendIn: (s) => `${s}s में फिर से भेजें`,
    attemptsLeft: (n) => `${n} प्रयास शेष`,
    noAttempts: "कोई प्रयास नहीं बचा। नया कोड माँगें।",
    wrongCode: (n) => `गलत कोड। ${n} प्रयास शेष।`,
    badPhone: "सही 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें।",
    shortCode: "पूरा 6 अंकों का कोड दर्ज करें।",
    lockout: (m) => `बहुत अधिक गलत प्रयास। ${m} मिनट के लिए लॉक किया गया।`,
    resendEarly: (s) => `कूलडाउन सक्रिय। ${s}s में फिर से भेजें।`,
    expiredOrUsed: "यह कोड समाप्त या उपयोग हो चुका है। नया कोड माँगें।",
    latestWins: "नया कोड भेजा गया। पुराना कोड अब मान्य नहीं है।",
    duplicateNotice: "यह नंबर पहले से पंजीकृत है - सत्यापन से आप लॉग इन होंगे।",
    verifiedTitle: "पहचान सत्यापित",
    verifiedBody: "आपका नंबर सत्यापित हो गया और सत्र तैयार है।",
    goHome: "सेतु होम पर जाएँ",
    welcome: "आपकी पूरी स्वास्थ्य यात्रा के लिए एक स्थिर पहचान।",
    stepPhone: "फ़ोन",
    stepVerify: "सत्यापन",
    stepDone: "पूर्ण",
    stepProgress: "साइन इन प्रगति",
    valueProps: [
      "एक स्थिर पहचान - कोई डुप्लीकेट खाता नहीं",
      "आपका रिकॉर्ड आपका है, केवल आपकी सहमति से साझा",
      "हिंदी और अंग्रेज़ी दोनों में",
    ],
    networkError: "सर्वर से संपर्क नहीं हो सका। अपना कनेक्शन जाँचें।",
    smsFailed: "कोड भेजा नहीं जा सका। कुछ देर में फिर कोशिश करें।",
    suspendedNotice: "यह नंबर निलंबित है। सहायता के लिए संपर्क करें।",
    notRegistered: "यह नंबर पंजीकृत नहीं था। वापस जाकर पहले कोड माँगें।",
    sessionTitle: "आप साइन इन हैं",
    sessionBody: "आपकी पहचान सत्यापित है और स्वास्थ्य यात्रा तैयार है।",
    signedInAs: (phone) => `${phone} से साइन इन`,
    signOut: "साइन आउट",
  },
};

export interface OtpFlow {
  state: OtpState;
  t: I18n;
  submitPhone: (raw: string) => void;
  submitOtp: () => void;
  resendOtp: () => void;
  setOtpDraft: (digits: string) => void;
  setLang: (lang: Lang) => void;
  backToPhone: () => void;
  goHome: () => void;
  signOut: () => void;
}

function errorString(error: unknown, t: I18n): string {
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
    const t = STRINGS[state.lang];

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
      setLang: (lang: Lang) => setState((s) => ({ ...s, lang })),
      backToPhone: () =>
        setState((s) => ({
          ...initialState(),
          lang: s.lang,
          isExisting: s.isExisting,
          hydrated: true,
        })),
      goHome: () => setState((s) => ({ ...s, stage: "phone" })),
      signOut: () => {
        clearSession();
        setState((s) => ({ ...initialState(), lang: s.lang, hydrated: true }));
      },
    };

    return flow;
  }, [state]);
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
