// MOD-001 auth HTTP surface client for the patient PWA (PHASE-2 T9, #60).
// Thin fetch wrapper over the backend's /v1/auth endpoints and the protected
// GET /v1/me session read (PHASE-2.6 T05, #196); the response shapes mirror
// the facade result models in modules/iam/facade.py and app/main.py exactly.

export interface RegisterResult {
  outcome: "sent" | "cooldown" | "locked" | "suspended";
  phone_e164: string;
  identity_id: number;
  challenge_id: number | null;
  is_existing: boolean;
  flow: "register" | "login";
  expires_in_seconds: number | null;
  cooldown_remaining_seconds: number | null;
  attempts_left: number | null;
  lockout_remaining_seconds: number | null;
}

export interface VerifyResult {
  outcome: "verified" | "wrong_code" | "expired" | "spent" | "locked";
  phone_e164: string;
  identity_id: number | null;
  attempts_left: number | null;
  lockout_remaining_seconds: number | null;
}

export interface ResendResult {
  outcome: "sent" | "cooldown" | "locked" | "suspended" | "no_identity";
  phone_e164: string;
  challenge_id: number | null;
  expires_in_seconds: number | null;
  cooldown_remaining_seconds: number | null;
  lockout_remaining_seconds: number | null;
  attempts_left: number | null;
}

export interface SessionResult {
  jwt: string;
  jti: string;
  scope: string;
  identity_id: number;
  expires_in_seconds: number;
  refresh_token: string;
}

// Partner phone-OTP login (ADR-0016, F014-T02 #462): the staff login page's
// partner mode. The phone step calls /v1/auth/partner/login; outcome shapes
// mirror the patient surface plus the partner-only ``no_account`` refusal.
export interface PartnerLoginResult {
  outcome: "sent" | "no_account" | "cooldown" | "locked" | "suspended";
  phone_e164: string;
  challenge_id: number | null;
  expires_in_seconds: number | null;
  cooldown_remaining_seconds: number | null;
  attempts_left: number | null;
  lockout_remaining_seconds: number | null;
}

// Partner phone-OTP verify (F014-T03 #463): consuming the challenge marks the
// identity phone-verified silently - no patient role, no patient event. The
// code step of the staff login page renders these outcomes exactly as on the
// patient surface.
export interface PartnerVerifyResult {
  outcome: "verified" | "wrong_code" | "expired" | "spent" | "locked";
  phone_e164: string;
  identity_id: number | null;
  attempts_left: number | null;
  lockout_remaining_seconds: number | null;
}

export interface MeResult {
  subject_id: string;
  roles: string[];
  phone: string;
}

export interface DemoOtpResult {
  code: string | null;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  trace_id: string;
  details: Record<string, unknown>;
}

export class AuthApiError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly traceId: string;

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "AuthApiError";
    this.code = envelope.code;
    this.details = envelope.details;
    this.traceId = envelope.trace_id;
  }
}

const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function post<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
    });
  } catch {
    throw new AuthApiError({
      code: "NETWORK_ERROR",
      message: "Could not reach the CareSetu API",
      trace_id: "",
      details: {},
    });
  }

  if (!response.ok) {
    let envelope: ErrorEnvelope;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      throw new AuthApiError({
        code: "UNEXPECTED_ERROR",
        message: "The API answered with an unreadable response",
        trace_id: "",
        details: {},
      });
    }
    throw new AuthApiError(envelope);
  }

  return (await response.json()) as T;
}

export function registerPhone(phone: string): Promise<RegisterResult> {
  return post<RegisterResult>("/v1/auth/register", { phone });
}

export function verifyOtp(phone: string, otp: string): Promise<VerifyResult> {
  return post<VerifyResult>("/v1/auth/verify", { phone, otp });
}

export function resendOtp(phone: string): Promise<ResendResult> {
  return post<ResendResult>("/v1/auth/resend", { phone });
}

export function issueSession(phone: string): Promise<SessionResult> {
  return post<SessionResult>("/v1/auth/session", { phone });
}

export function issuePartnerSession(phone: string): Promise<SessionResult> {
  return post<SessionResult>("/v1/auth/partner/session", { phone });
}

export function partnerLogin(phone: string): Promise<PartnerLoginResult> {
  return post<PartnerLoginResult>("/v1/auth/partner/login", { phone });
}

export function partnerVerify(
  phone: string,
  otp: string,
): Promise<PartnerVerifyResult> {
  return post<PartnerVerifyResult>("/v1/auth/partner/verify", { phone, otp });
}

export async function fetchMe(jwt: string): Promise<MeResult> {
  const response = await fetch(`${API_BASE_URL}/v1/me`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  if (!response.ok) {
    throw new Error(`GET /v1/me returned ${response.status}`);
  }
  return (await response.json()) as MeResult;
}

export async function fetchDemoOtp(phone: string): Promise<string | null> {
  try {
    const response = await fetch(
      `${API_BASE_URL}/v1/auth/dev/otp?phone=${encodeURIComponent(phone)}`,
    );
    if (!response.ok) {
      return null;
    }
    const body = (await response.json()) as DemoOtpResult;
    return typeof body.code === "string" ? body.code : null;
  } catch {
    return null;
  }
}
