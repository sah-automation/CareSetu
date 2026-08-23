// PHASE-2.6 T10 (#201): client-side validation and error-envelope copy
// mapping for the staff login form (blueprint §9.5). User-visible copy lives
// in the typed dictionaries, keyed on the API's stable SCREAMING_SNAKE codes
// (api-standards §2) - never on raw exception strings or HTTP statuses.

import { AuthApiError } from "@/lib/auth/api";
import type { StaffAuthStrings } from "@/lib/i18n/dictionaries";

export type LoginStrings = StaffAuthStrings["login"];

export interface StaffLoginValues {
  email: string;
  password: string;
}

export type StaffLoginFieldError = "emailInvalid" | "passwordRequired";

export interface StaffLoginFieldErrors {
  email?: StaffLoginFieldError;
  password?: StaffLoginFieldError;
}

const EMAIL_PATTERN = /^\S+@\S+\.\S+$/;

// Client-side validation first: mirror the Phase 5 server schema's observable
// minimums (well-formed email, non-empty password) - nothing stricter, so the
// server stays the authority once it exists.
export function validateStaffLogin(
  values: StaffLoginValues,
): StaffLoginFieldErrors {
  const errors: StaffLoginFieldErrors = {};
  if (!EMAIL_PATTERN.test(values.email.trim())) {
    errors.email = "emailInvalid";
  }
  if (values.password.length === 0) {
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
        return t.invalidCredentials;
      case "ACCOUNT_LOCKED":
        return t.accountLocked;
      default:
        // Includes VALIDATION_ERROR: until Phase 5 ships field-level
        // details[] mapping (ui-blueprint §9.5), a whole-envelope validation
        // failure gets calm operational copy rather than wrongly blaming one
        // specific field.
        return t.genericError;
    }
  }
  return t.genericError;
}
