// PHASE-2.6 T07 (#198): unit coverage for the cookie-presence proxy.
// ADR-0005 (amended): the guard checks the client-written presence-hint
// cookie's existence only - it never decodes JWT claims. Covered here:
// pass-through with the hint cookie, group-correct redirects without one,
// return-url preservation (path AND query), empty-value cookies treated as
// absent, and the matcher table shape.

import { describe, expect, it } from "vitest";
import { NextRequest, NextResponse } from "next/server";

import { config, proxy } from "./proxy";
import { HINT_COOKIE } from "@/lib/auth/session";

const COOKIE_NAME = HINT_COOKIE;

function makeRequest(path: string, cookie?: string): NextRequest {
  const url = new URL(path, "http://localhost:3000");
  const headers = new Headers();
  if (cookie !== undefined) {
    headers.set("cookie", cookie);
  }
  return new NextRequest(url, { headers });
}

function redirectLocation(response: NextResponse): string {
  const location = response.headers.get("location");
  expect(
    location,
    "expected a redirect response with a Location header",
  ).toBeTruthy();
  const url = new URL(location as string);
  return `${url.pathname}${url.search}`;
}

describe("proxy - signed-in requests pass through", () => {
  it.each([
    "/patient",
    "/patient/record",
    "/doctor",
    "/partner/orders",
    "/operator",
  ])("passes %s through when the session cookie is present", (path) => {
    const response = proxy(makeRequest(path, `${COOKIE_NAME}=some.jwt.value`));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });
});

describe("proxy - patient group redirects to the patient wizard", () => {
  it.each([
    ["/patient", "/login?return=%2Fpatient"],
    ["/patient/find", "/login?return=%2Fpatient%2Ffind"],
    [
      "/patient/bookings?tab=upcoming",
      "/login?return=%2Fpatient%2Fbookings%3Ftab%3Dupcoming",
    ],
  ])("redirects %s to %s", (path, expected) => {
    const response = proxy(makeRequest(path));
    expect(response.status).toBe(307);
    expect(redirectLocation(response)).toBe(expected);
  });
});

describe("proxy - staff partner groups redirect to /staff/login", () => {
  it.each([
    ["/doctor", "/staff/login?return=%2Fdoctor"],
    ["/partner", "/staff/login?return=%2Fpartner"],
    ["/partner/orders/42", "/staff/login?return=%2Fpartner%2Forders%2F42"],
  ])("redirects %s to %s", (path, expected) => {
    const response = proxy(makeRequest(path));
    expect(response.status).toBe(307);
    expect(redirectLocation(response)).toBe(expected);
  });
});

describe("proxy - operator group redirects to /staff/login?role=operator", () => {
  it.each([
    ["/operator", "/staff/login?role=operator&return=%2Foperator"],
    [
      "/operator/audit",
      "/staff/login?role=operator&return=%2Foperator%2Faudit",
    ],
    [
      "/operator/audit?tab=consent",
      "/staff/login?role=operator&return=%2Foperator%2Faudit%3Ftab%3Dconsent",
    ],
  ])("redirects %s to %s", (path, expected) => {
    const response = proxy(makeRequest(path));
    expect(response.status).toBe(307);
    expect(redirectLocation(response)).toBe(expected);
  });
});

describe("proxy - cookie presence is the only signal", () => {
  it("treats an empty-value session cookie as absent", () => {
    const response = proxy(makeRequest("/patient", `${COOKIE_NAME}=`));
    expect(response.status).toBe(307);
    expect(redirectLocation(response)).toBe("/login?return=%2Fpatient");
  });

  it("does not treat an unrelated cookie as a session", () => {
    const response = proxy(makeRequest("/patient", "other=1"));
    expect(response.status).toBe(307);
  });
});

describe("proxy - matcher table", () => {
  it("guards exactly the four app prefixes", () => {
    expect(config.matcher).toEqual([
      "/patient/:path*",
      "/doctor/:path*",
      "/partner/:path*",
      "/operator/:path*",
    ]);
  });
});
