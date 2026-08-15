// MOD-001 auth HTTP surface client for the patient PWA (PHASE-2 T9, #60).
// Thin fetch wrapper over the backend's /v1/auth endpoints; the response
// shapes mirror the facade result models in modules/iam/facade.py exactly.

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

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "AuthApiError";
    this.code = envelope.code;
    this.details = envelope.details;
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
