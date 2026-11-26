// MOD-001 session persistence for the patient PWA (PHASE-2 T9, #60).
// The PWA stores the access JWT and the opaque refresh token issued by
// POST /v1/auth/session so the patient lands authenticated on reload. The
// refresh token is kept for the SMS-independent refresh path (ticket #58);
// no token is ever written to logs. saveSession/clearSession also maintain
// the secret-free `caresetu_authed` presence-hint cookie that the edge
// guard reads (ADR-0005 amendment).

import type { SessionResult } from "./api";

const JWT_KEY = "caresetu.access_jwt";
const REFRESH_KEY = "caresetu.refresh_token";
const SESSION_KEY = "caresetu.session";
const SELECTED_ROLE_KEY = "caresetu.selected_role";

// Presence-only hint cookie (ADR-0005 amendment) so the src/proxy.ts edge
// guard sees a first-party cookie on THIS origin: the backend's own
// Set-Cookie lands on the API origin and never reaches the frontend on split
// deployments (Vercel frontend -> Render backend), where SameSite rules drop
// it entirely. Secret-free value; a fixed long window instead of the JWT TTL
// because the refresh path rotates tokens without a new TTL payload - and a
// lapsed hint only costs one client-side redirect, since AuthContext's
// /v1/me validation is the real gate.
export const HINT_COOKIE = "caresetu_authed";
const HINT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

export function hintCookieString(secure: boolean): string {
  const attributes = `Path=/; Max-Age=${HINT_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
  return `${HINT_COOKIE}=1; ${attributes}${secure ? "; Secure" : ""}`;
}

function writeHintCookie(): void {
  document.cookie = hintCookieString(window.location.protocol === "https:");
}

function expireHintCookie(): void {
  document.cookie = `${HINT_COOKIE}=; Path=/; Max-Age=0`;
}

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
  writeHintCookie();
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
  localStorage.removeItem(SELECTED_ROLE_KEY);
  expireHintCookie();
}

export function readSelectedRole(): string | null {
  return localStorage.getItem(SELECTED_ROLE_KEY);
}

export function saveSelectedRole(role: string): void {
  localStorage.setItem(SELECTED_ROLE_KEY, role);
}

export function clearSelectedRole(): void {
  localStorage.removeItem(SELECTED_ROLE_KEY);
}
