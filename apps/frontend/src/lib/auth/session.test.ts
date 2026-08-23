// Unit coverage for the session persistence module (PHASE-2 T9, #60) and
// its `caresetu_authed` presence-hint cookie (ADR-0005 amendment, live
// 307-bounce fix after PR #190). Covered here: hint-cookie attribute string
// (with and without Secure), saveSession writing both localStorage and the
// hint cookie, and clearSession expiring both.

import { afterEach, describe, expect, it } from "vitest";

import {
  clearSession,
  HINT_COOKIE,
  hintCookieString,
  saveSession,
} from "./session";

function readHintCookie(): string | null {
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${HINT_COOKIE}=`));
  return match ?? null;
}

function expireHintCookie(): void {
  document.cookie = `${HINT_COOKIE}=; Path=/; Max-Age=0`;
}

afterEach(() => {
  expireHintCookie();
  localStorage.clear();
});

describe("hintCookieString", () => {
  it("carries the fixed long window, path, and SameSite=Lax without Secure", () => {
    const cookie = hintCookieString(false);
    expect(cookie.startsWith(`${HINT_COOKIE}=1;`)).toBe(true);
    expect(cookie).toContain("Path=/");
    expect(cookie).toContain("Max-Age=");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).not.toContain("Secure");
  });

  it("adds Secure for https origins", () => {
    const cookie = hintCookieString(true);
    expect(cookie.startsWith(`${HINT_COOKIE}=1;`)).toBe(true);
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("; Secure");
  });

  it("never carries token material - the value is the literal 1", () => {
    expect(hintCookieString(false)).toMatch(new RegExp(`^${HINT_COOKIE}=1;`));
  });
});

describe("saveSession / clearSession hint-cookie maintenance", () => {
  const session = {
    jwt: "test.jwt.value",
    refresh_token: "refresh-token-value",
    jti: "jti-1",
    scope: "patient",
    identity_id: 42,
    expires_in_seconds: 900,
  };

  it("sets a readable first-party hint cookie on saveSession", () => {
    saveSession(session, "+919000000001");
    expect(readHintCookie()).toBe(`${HINT_COOKIE}=1`);
  });

  it("expires the hint cookie on clearSession", () => {
    saveSession(session, "+919000000001");
    expect(readHintCookie()).toBe(`${HINT_COOKIE}=1`);
    clearSession();
    expect(readHintCookie()).toBeNull();
  });

  it("clears localStorage alongside the hint cookie", () => {
    saveSession(session, "+919000000001");
    expect(localStorage.getItem("caresetu.session")).not.toBeNull();
    clearSession();
    expect(localStorage.getItem("caresetu.session")).toBeNull();
    expect(localStorage.getItem("caresetu.access_jwt")).toBeNull();
    expect(localStorage.getItem("caresetu.refresh_token")).toBeNull();
  });
});
