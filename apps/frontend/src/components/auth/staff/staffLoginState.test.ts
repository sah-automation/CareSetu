// PHASE-2.6 T10 (#201): validation + stable-code error mapping for the staff
// login form (done-verify suite). The mapper is the seam Phase 5's real
// envelopes will flow through; here the codes are synthetic AuthApiErrors.

import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { AuthApiError } from "@/lib/auth/api";
import { STRINGS } from "@/lib/i18n/dictionaries";

import {
  staffLoginErrorCopy,
  staffOperatorErrorCopy,
  validateStaffLogin,
} from "./staffLoginState";

const t = STRINGS.en.staffAuth.login;

describe("validateStaffLogin", () => {
  it("accepts a well-formed email with any non-empty password", () => {
    expect(
      validateStaffLogin({
        phone: "",
        email: "dr.sharma@example.com",
        password: "x",
      }),
    ).toEqual({});
  });

  it.each([
    ["missing @", "not-an-email"],
    ["missing domain", "user@"],
    ["whitespace-only", "   "],
    ["empty", ""],
  ])("rejects %s as an email", (_label, email) => {
    const errors = validateStaffLogin({ phone: "", email, password: "secret" });
    expect(errors.email).toBe("emailInvalid");
  });

  it("requires a non-empty password", () => {
    const errors = validateStaffLogin({
      phone: "",
      email: "a@b.co",
      password: "",
    });
    expect(errors.password).toBe("passwordRequired");
  });

  it("reports both fields at once so the summary can count them", () => {
    const errors = validateStaffLogin({ phone: "", email: "", password: "" });
    expect(Object.keys(errors)).toHaveLength(2);
  });

  it("accepts a well-formed phone number with a 6-digit TOTP code", () => {
    expect(
      validateStaffLogin({
        phone: "9876543210",
        email: "",
        password: "",
        code: "123456",
      }),
    ).toEqual({});
  });

  it.each([
    ["too short", "123"],
    ["letters", "abcdefghij"],
    ["with spaces", "987 654 3210"],
  ])("rejects %s as a phone number", (_label, phone) => {
    const errors = validateStaffLogin({
      phone,
      email: "",
      password: "secret",
      code: "123456",
    });
    expect(errors.phone).toBe("phoneInvalid");
  });

  it("requires a 6-digit TOTP code in operator mode", () => {
    const errors = validateStaffLogin({
      phone: "9876543210",
      email: "",
      password: "",
      code: "",
    });
    expect(errors.code).toBe("codeRequired");
  });

  it.each([
    ["too short", "123"],
    ["too long", "1234567"],
    ["letters", "abcdef"],
    ["with spaces", "123 456"],
  ])("rejects %s as a TOTP code", (_label, code) => {
    const errors = validateStaffLogin({
      phone: "9876543210",
      email: "",
      password: "",
      code,
    });
    expect(errors.code).toBe("codeInvalid");
  });

  it("does not require password in operator mode", () => {
    const errors = validateStaffLogin({
      phone: "9876543210",
      email: "",
      password: "",
      code: "123456",
    });
    expect(errors.password).toBeUndefined();
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

function operatorError(code: string): ApiError {
  return new ApiError({
    code,
    message: "envelope message",
    trace_id: "trace-1",
    details: {},
  });
}

describe("staffOperatorErrorCopy", () => {
  it("keys INVALID_CREDENTIALS onto the calm invalid-credentials copy", () => {
    expect(
      staffOperatorErrorCopy(operatorError("INVALID_CREDENTIALS"), t),
    ).toBe(t.invalidCredentials);
  });

  it("keys ACCOUNT_LOCKED onto the lockout copy", () => {
    expect(staffOperatorErrorCopy(operatorError("ACCOUNT_LOCKED"), t)).toBe(
      t.accountLocked,
    );
  });

  it("never leaks a raw operator code to users - falls back to generic copy", () => {
    const copy = staffOperatorErrorCopy(
      operatorError("IAM_OPERATOR_UNKNOWN_CODE"),
      t,
    );
    expect(copy).toBe(t.genericError);
    expect(copy).not.toMatch(/IAM_OPERATOR_UNKNOWN_CODE/);
  });

  it("treats non-envelope throws as operational errors", () => {
    expect(staffOperatorErrorCopy(new Error("boom"), t)).toBe(t.genericError);
    expect(staffOperatorErrorCopy(undefined, t)).toBe(t.genericError);
  });
});
