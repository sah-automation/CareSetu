// PHASE-2.6 T10 (#201): validation + stable-code error mapping for the staff
// login form (done-verify suite). The mapper is the seam Phase 5's real
// envelopes will flow through; here the codes are synthetic AuthApiErrors.

import { describe, expect, it } from "vitest";

import { AuthApiError } from "@/lib/auth/api";
import { STRINGS } from "@/lib/i18n/dictionaries";

import { staffLoginErrorCopy, validateStaffLogin } from "./staffLoginState";

const t = STRINGS.en.staffAuth.login;

describe("validateStaffLogin", () => {
  it("accepts a well-formed email with any non-empty password", () => {
    expect(
      validateStaffLogin({ email: "dr.sharma@example.com", password: "x" }),
    ).toEqual({});
  });

  it.each([
    ["missing @", "not-an-email"],
    ["missing domain", "user@"],
    ["whitespace-only", "   "],
    ["empty", ""],
  ])("rejects %s as an email", (_label, email) => {
    const errors = validateStaffLogin({ email, password: "secret" });
    expect(errors.email).toBe("emailInvalid");
  });

  it("requires a non-empty password", () => {
    const errors = validateStaffLogin({ email: "a@b.co", password: "" });
    expect(errors.password).toBe("passwordRequired");
  });

  it("reports both fields at once so the summary can count them", () => {
    const errors = validateStaffLogin({ email: "", password: "" });
    expect(Object.keys(errors)).toHaveLength(2);
  });
});

function envelopeError(code: string): AuthApiError {
  return new AuthApiError({
    code,
    message: "envelope message",
    trace_id: "trace-1",
    details: {},
  });
}

describe("staffLoginErrorCopy", () => {
  it("keys INVALID_CREDENTIALS onto the calm invalid-credentials copy", () => {
    expect(staffLoginErrorCopy(envelopeError("INVALID_CREDENTIALS"), t)).toBe(
      t.invalidCredentials,
    );
  });

  it("keys ACCOUNT_LOCKED onto the lockout copy naming the window and reset path", () => {
    const copy = staffLoginErrorCopy(envelopeError("ACCOUNT_LOCKED"), t);
    expect(copy).toBe(t.accountLocked);
    expect(copy).toMatch(/15 minutes/);
  });

  it("maps VALIDATION_ERROR to calm operational copy, never the envelope message", () => {
    // Whole-envelope validation failures cannot be attributed to one field
    // until Phase 5 ships details[] mapping, so they get generic copy.
    const copy = staffLoginErrorCopy(envelopeError("VALIDATION_ERROR"), t);
    expect(copy).toBe(t.genericError);
    expect(copy).not.toBe(t.emailInvalid);
  });

  it("falls back to generic operational copy for unknown codes without leaking the raw code", () => {
    const copy = staffLoginErrorCopy(envelopeError("IAM_SOMETHING_NEW"), t);
    expect(copy).toBe(t.genericError);
    expect(copy).not.toMatch(/IAM_SOMETHING_NEW/);
  });

  it("treats non-envelope throws as operational errors", () => {
    expect(staffLoginErrorCopy(new Error("boom"), t)).toBe(t.genericError);
    expect(staffLoginErrorCopy(undefined, t)).toBe(t.genericError);
  });
});
