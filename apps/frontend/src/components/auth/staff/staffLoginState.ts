// PHASE-2.6 T10 (#201): client-side validation and error-envelope copy
// mapping for the staff login form (blueprint §9.5). User-visible copy lives
// in the typed dictionaries, keyed on the API's stable SCREAMING_SNAKE codes
// (api-standards §2) - never on raw exception strings or HTTP statuses.

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

// The staff surface is split by role (#302): partners sign in with
// email + password, operators with phone + TOTP. The role is fixed by the
// URL (?role=operator) - never derived from what the user types.
export type StaffLoginRole = "partner" | "operator";

export type StaffLoginFieldError =
  | "phoneInvalid"
  | "emailInvalid"
  | "passwordRequired"
  | "codeRequired"
  | "codeInvalid";

export interface StaffLoginFieldErrors {
  phone?: StaffLoginFieldError;
  email?: StaffLoginFieldError;
  password?: StaffLoginFieldError;
  code?: StaffLoginFieldError;
}

const EMAIL_PATTERN = /^\S+@\S+\.\S+$/;
const PHONE_PATTERN = /^\d{10,15}$/;

const TOTP_PATTERN = /^\d{6}$/;

// Client-side validation first: mirror the Phase 5 server schema's observable
// minimums (well-formed phone or email, non-empty password/TOTP) - nothing
// stricter, so the server stays the authority once it exists.
//
// Mode follows the role passed by the caller (default partner): operator mode
// requires a phone + 6-digit TOTP code, partner mode requires email +
// password. Never derived from field contents - the URL pins the mode.
export function validateStaffLogin(
  values: StaffLoginValues,
  role: StaffLoginRole = "partner",
): StaffLoginFieldErrors {
  const errors: StaffLoginFieldErrors = {};
  const isOperatorMode = role === "operator";

  if (isOperatorMode) {
    // Operator path: phone is required and must be well-formed.
    if (!PHONE_PATTERN.test(values.phone.trim())) {
      errors.phone = "phoneInvalid";
    }
    // Operator path: TOTP code must be exactly 6 digits.
    const code = values.code ?? "";
    if (code.length === 0) {
      errors.code = "codeRequired";
    } else if (!TOTP_PATTERN.test(code)) {
      errors.code = "codeInvalid";
    }
  } else {
    // Partner staff path: email is required and must be well-formed.
    if (!EMAIL_PATTERN.test(values.email.trim())) {
      errors.email = "emailInvalid";
    }
  }

  if (!isOperatorMode && values.password.length === 0) {
    errors.password = "passwordRequired";
  }
  return errors;
}

/**
 * Maps any thrown value onto dictionary copy, keyed on the stable envelope
 * code. The code spellings below are this phase's anticipated IAM codes -
 * Phase 5 owns their final names, and this function is the single place to
 * reconcile them.
 */
export function staffLoginErrorCopy(error: unknown, t: LoginStrings): string {
  if (error instanceof AuthApiError) {
    switch (error.code) {
      case "INVALID_CREDENTIALS":
      case "SESSION_REFUSED":
        return t.invalidCredentials;
      case "ACCOUNT_LOCKED":
        return t.accountLocked;
      default:
        // Includes VALIDATION_ERROR: until Phase 5 ships field-level
        // details[] mapping (ui-blueprint §9.5), a whole-envelope validation
        // failure gets credential-focused copy rather than blaming the system.
        return t.invalidCredentials;
    }
  }
  return t.invalidCredentials;
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
