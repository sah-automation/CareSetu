// MOD-001 session persistence for the patient PWA (PHASE-2 T9, #60).
// The PWA stores the access JWT and the opaque refresh token issued by
// POST /v1/auth/session so the patient lands authenticated on reload. The
// refresh token is kept for the SMS-independent refresh path (ticket #58);
// no token is ever written to logs.

import type { SessionResult } from "./api";

const JWT_KEY = "caresetu.access_jwt";
const REFRESH_KEY = "caresetu.refresh_token";
const SESSION_KEY = "caresetu.session";

export interface StoredSession {
  jwt: string;
  refresh_token: string;
  jti: string;
  scope: string;
  identity_id: number;
  phone: string;
}

export function saveSession(session: SessionResult, phone: string): void {
  localStorage.setItem(JWT_KEY, session.jwt);
  localStorage.setItem(REFRESH_KEY, session.refresh_token);
  const stored: StoredSession = {
    jwt: session.jwt,
    refresh_token: session.refresh_token,
    jti: session.jti,
    scope: session.scope,
    identity_id: session.identity_id,
    phone,
  };
  localStorage.setItem(SESSION_KEY, JSON.stringify(stored));
}

export function readSession(): StoredSession | null {
  const raw = localStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  localStorage.removeItem(JWT_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(SESSION_KEY);
}
