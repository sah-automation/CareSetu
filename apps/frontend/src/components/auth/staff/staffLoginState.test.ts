// PHASE-2.6 T10 (#201): validation + stable-code error mapping for the staff
// login form (done-verify suite). The mapper is the seam Phase 5's real
// envelopes will flow through.
//
// PHASE-5 T7 (#467): partner staff sign-in is phone + SMS-code (ADR-0016), so
// validateStaffLogin no longer guards partner email/password fields - the
// partner flow hook (partnerLoginState.ts) owns phone/code correctness for
// that mode. The validator now guards the operator TOTP branch only, and the
// AuthApiError mapper covers the partner flow's transport-level throws.

import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { AuthApiError } from "@/lib/auth/api";
import { STRINGS } from "@/lib/i18n/dictionaries";

import {
  partnerLoginErrorCopy,
  staffOperatorErrorCopy,
  validateStaffLogin,
} from "./staffLoginState";

const t = STRINGS.en.staffAuth.login;

describe("validateStaffLogin", () => {
  describe("partner mode", () => {
    it("does not validate fields client-side - the OTP flow owns phone/code correctness", () => {
      expect(
        validateStaffLogin(
          { phone: "123", email: "", password: "", code: "1" },
          "partner",
        ),
      ).toEqual({});
    });

    it("never reports email or password errors after the email/password removal (#467)", () => {
      const errors = validateStaffLogin(
        { phone: "", email: "", password: "" },
        "partner",
      );
      expect(Object.keys(errors)).toHaveLength(0);
    });
  });

  describe("operator mode", () => {
    it("accepts a well-formed phone number with a 6-digit TOTP code", () => {
      expect(
        validateStaffLogin(
          { phone: "9876543210", email: "", password: "", code: "123456" },
          "operator",
        ),
      ).toEqual({});
    });

    it.each([
      ["too short", "123"],
      ["letters", "abcdefghij"],
      ["with spaces", "987 654 3210"],
    ])("rejects %s as a phone number", (_label, phone) => {
      const errors = validateStaffLogin(
        { phone, email: "", password: "", code: "123456" },
        "operator",
      );
      expect(errors.phone).toBe("phoneInvalid");
    });

    it("requires a 6-digit TOTP code", () => {
      const errors = validateStaffLogin(
        { phone: "9876543210", email: "", password: "", code: "" },
        "operator",
      );
      expect(errors.code).toBe("codeRequired");
    });

    it.each([
      ["too short", "123"],
      ["too long", "1234567"],
      ["letters", "abcdef"],
      ["with spaces", "123 456"],
    ])("rejects %s as a TOTP code", (_label, code) => {
      const errors = validateStaffLogin(
        { phone: "9876543210", email: "", password: "", code },
        "operator",
      );
      expect(errors.code).toBe("codeInvalid");
    });

    it("does not require email or password", () => {
      expect(
        validateStaffLogin(
          { phone: "9876543210", email: "", password: "", code: "123456" },
          "operator",
        ),
      ).toEqual({});
    });
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

describe("partnerLoginErrorCopy", () => {
  it("keys PHONE_INVALID onto the phone validation copy", () => {
    expect(partnerLoginErrorCopy(envelopeError("PHONE_INVALID"), t)).toBe(
      t.phoneInvalid,
    );
  });

  it("keys VALIDATION_ERROR onto the phone validation copy without leaking the envelope message", () => {
    const copy = partnerLoginErrorCopy(envelopeError("VALIDATION_ERROR"), t);
    expect(copy).toBe(t.phoneInvalid);
    expect(copy).not.toBe("envelope message");
  });

  it("keys SMS_DELIVERY_FAILED onto the SMS failure copy", () => {
    expect(partnerLoginErrorCopy(envelopeError("SMS_DELIVERY_FAILED"), t)).toBe(
      t.smsFailed,
    );
  });

  it("keys NETWORK_ERROR onto the network copy", () => {
    expect(partnerLoginErrorCopy(envelopeError("NETWORK_ERROR"), t)).toBe(
      t.networkError,
    );
  });

  it("falls back to network copy for unknown codes without leaking the raw code", () => {
    const copy = partnerLoginErrorCopy(envelopeError("IAM_SOMETHING_NEW"), t);
    expect(copy).toBe(t.networkError);
    expect(copy).not.toMatch(/IAM_SOMETHING_NEW/);
  });

  it("treats non-envelope throws as network errors", () => {
    expect(partnerLoginErrorCopy(new Error("boom"), t)).toBe(t.networkError);
    expect(partnerLoginErrorCopy(undefined, t)).toBe(t.networkError);
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

  it("keys SESSION_REFUSED onto the invalid-credentials copy", () => {
    // SESSION_REFUSED (409) is emitted when the phone is unknown or the
    // identity is not Active - the user should be guided to check their input,
    // not told the system failed.
    expect(staffOperatorErrorCopy(operatorError("SESSION_REFUSED"), t)).toBe(
      t.invalidCredentials,
    );
  });

  it("never leaks a raw operator code to users - falls back to credential-focused copy", () => {
    const copy = staffOperatorErrorCopy(
      operatorError("IAM_OPERATOR_UNKNOWN_CODE"),
      t,
    );
    expect(copy).toBe(t.invalidCredentials);
    expect(copy).not.toMatch(/IAM_OPERATOR_UNKNOWN_CODE/);
  });

  it("treats non-envelope throws as credential-focused operational errors", () => {
    expect(staffOperatorErrorCopy(new Error("boom"), t)).toBe(
      t.invalidCredentials,
    );
    expect(staffOperatorErrorCopy(undefined, t)).toBe(t.invalidCredentials);
  });
});
