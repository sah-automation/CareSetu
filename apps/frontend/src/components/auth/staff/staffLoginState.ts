// PHASE-2.6 T10 (#201): client-side validation and error-envelope copy
// mapping for the staff login form (blueprint §9.5). User-visible copy lives
// in the typed dictionaries, keyed on the API's stable SCREAMING_SNAKE codes
// (api-standards §2) - never on raw exception strings or HTTP statuses.
//
// PHASE-5 T7 (#467): partner mode became phone → SMS-code (ADR-0016) and no
// longer validates email/password on the client; the phone/code correctness
// for that mode lives in the partner OTP flow hook (partnerLoginState.ts).
// validateStaffLogin now guards the operator TOTP branch only.

import { ApiError } from "@/lib/api-errors";
import { AuthApiError } from "@/lib/auth/api";
import type { StaffAuthStrings } from "@/lib/i18n/dictionaries";

export type LoginStrings = StaffAuthStrings["login"];

export interface StaffLoginValues {
  phone: string;
  email: string;
  password: string;
  code?: string;
}

// The staff surface is split by role (#302): partners sign in with phone +
// SMS code, operators with phone + TOTP. The role is fixed by the URL
// (?role=operator) - never derived from what the user types.
export type StaffLoginRole = "partner" | "operator";

export type StaffLoginFieldError =
  | "phoneInvalid"
  | "codeRequired"
  | "codeInvalid";

export interface StaffLoginFieldErrors {
  phone?: StaffLoginFieldError;
  code?: StaffLoginFieldError;
}

const PHONE_PATTERN = /^\d{10,15}$/;

const TOTP_PATTERN = /^\d{6}$/;

// Client-side validation first: mirror the operator schema's observable
// minimums (well-formed phone, non-empty TOTP) - nothing stricter, so the
// server stays the authority. Operator mode requires a phone + 6-digit TOTP
// code. Partner mode validates nothing here: its phone/code correctness
// comes from the OTP flow hook (partnerPhoneInvalid / 6-digit gate). Never
// derived from field contents - the URL pins the mode.
export function validateStaffLogin(
  values: StaffLoginValues,
  role: StaffLoginRole = "partner",
): StaffLoginFieldErrors {
  const errors: StaffLoginFieldErrors = {};
  if (role !== "operator") {
    return errors;
  }
  if (!PHONE_PATTERN.test(values.phone.trim())) {
    errors.phone = "phoneInvalid";
  }
  const code = values.code ?? "";
  if (code.length === 0) {
    errors.code = "codeRequired";
  } else if (!TOTP_PATTERN.test(code)) {
    errors.code = "codeInvalid";
  }
  return errors;
}

/**
 * Maps the partner OTP flow's AuthApiError throws (from `lib/auth/api`, the
 * transport layer for /v1/auth/partner/*) onto calm dictionary copy. The
 * partner refusal OUTCOMES (cooldown/locked/suspended/no_account/wrong/...)
 * arrive as 200 envelopes handled by the flow itself, so this mapper only
 * sees transport-level codes - a network drop, an unreadable body, a failed
 * SMS issue, or a session mint refusal. The raw SCREAMING_SNAKE code is
 * never shown to users (api-standards section 2).
 */
export function partnerLoginErrorCopy(error: unknown, t: LoginStrings): string {
  if (error instanceof AuthApiError) {
    switch (error.code) {
      case "PHONE_INVALID":
      case "VALIDATION_ERROR":
        return t.phoneInvalid;
      case "SMS_DELIVERY_FAILED":
        return t.smsFailed;
      default:
        return t.networkError;
    }
  }
  return t.networkError;
}

/**
 * Maps the operator-login HTTP client's ApiError (api-errors.ts, distinct from
 * AuthApiError) onto the same dictionary copy used by the staff login card.
 * SESSION_MFA_REQUIRED is handled by the caller as a state transition, never
 * rendered as free copy here. All other codes - and non-envelope throws - fall
 * back to the credential-focused copy; the raw SCREAMING_SNAKE code is never
 * shown to users (api-standards section 2).
 */
export function staffOperatorErrorCopy(
  error: unknown,
  t: LoginStrings,
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "INVALID_CREDENTIALS":
      case "SESSION_REFUSED":
        return t.invalidCredentials;
      case "ACCOUNT_LOCKED":
        return t.accountLocked;
      case "INVALID_OPERATOR_CODE":
        return t.invalidOperatorCode;
      default:
        return t.invalidCredentials;
    }
  }
  return t.invalidCredentials;
}
