"use client";

// #616: the Address card's editable slice - its fields, their bounds, the mapper
// that turns the shared profile answer into them, and the validation pass that
// mirrors the server's own rules.
//
// It is a sibling of `profileForm.ts` rather than a key in it, on purpose. That
// module is the *whole-form* write's editable shape, and this card does not
// belong to that write: it has its own route, its own body, and its own save.
// Folding these fields into the whole-form shape would put the address back into
// a form that can no longer save them.
//
// Two rules decide what belongs here:
//
//   1. The field NAMES are the wire names. #609's refusal arrives as a 422 whose
//      `details.errors[].path` is `pin_code`, and that path is what maps an error
//      onto an input (api-standards §2, ui-blueprint §9.5). The slice keys are
//      therefore the backend model's field names, not prettier ones - renaming
//      them here would make every server error unmappable.
//   2. No coordinate field, at any level. The practice position is derived from
//      `pin_code` by the server (ADR-0022) and the backend model refuses a body
//      that carries one; a slice that held one would put the field back within
//      reach of a save.

import type {
  DoctorProfileAddressUpdate,
  DoctorProfileView,
} from "@/lib/doctor/api";

/**
 * The per-part bounds, in lockstep with `DoctorProfileAddressUpdate`: the parts
 * are the profile's String(200)/String(120) columns (#606). A bound the client
 * does not mirror is one the doctor learns about only from the server.
 */
export const ADDRESS_LIMITS = {
  addressLine: 200,
  landmark: 200,
  locality: 120,
  city: 120,
} as const;

/**
 * #603's own rule, mirrored client-side: an Indian PIN code is exactly six ASCII
 * digits, and the backend reports malformed and unlisted as two machine reasons
 * inside one PIN-keyed envelope. So the client refuses only what it can state in
 * one sentence - "six digits" - and leaves the unlisted case to the server, which
 * is the only side that has the centroid table.
 */
export const PIN_CODE_PATTERN = /^\d{6}$/;

export interface AddressFields {
  address_line: string;
  landmark: string;
  locality: string;
  city: string;
  pin_code: string;
  /**
   * The two derived rows (AC 2). Declared read-only and always seeded empty:
   * neither the profile projection nor the address write's answer carries a
   * district or a region, and #603's `PinCentroid` deliberately holds only the
   * position. They are fields rather than a constant so the card renders exactly
   * the shape the criterion asks for, and the client never invents a value the
   * server did not send.
   */
  district: string;
  state: string;
}

/** The one field the server can refuse, named the way the server names it. */
export type AddressFieldName = "pin_code";

export function addressFromProfile(profile: DoctorProfileView): AddressFields {
  return {
    address_line: profile.address_line ?? "",
    landmark: profile.landmark ?? "",
    locality: profile.locality ?? "",
    city: profile.city ?? "",
    pin_code: profile.pin_code ?? "",
    district: "",
    state: "",
  };
}

/** Blank is a value the card omits rather than sends as an empty string. */
function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * The request body. The PIN code is NOT trimmed-to-empty and is not defaulted:
 * it is the one required part, because without it the server has nothing to
 * resolve and cannot produce a position. The validation pass has already refused
 * an unusable one, so this only has to state the shape honestly.
 */
export function addressUpdateFromFields(
  fields: AddressFields,
): DoctorProfileAddressUpdate {
  return {
    address_line: optionalText(fields.address_line),
    landmark: optionalText(fields.landmark),
    locality: optionalText(fields.locality),
    city: optionalText(fields.city),
    pin_code: fields.pin_code.trim(),
  };
}

/**
 * The client-side validation pass (ui-blueprint §9.5: validate on blur and on
 * submit). Returns the fields that need attention, in DOM order, so the summary
 * can count them and the focus walk can take the first.
 *
 * One rule only, because one rule is all the client can state: the PIN code's
 * shape. Everything else about a PIN - whether this well-formed code is one the
 * platform can place - is the server's answer to give, and answering it here
 * would mean shipping the centroid table to the browser.
 */
export function invalidAddressFields(
  fields: AddressFields,
): AddressFieldName[] {
  const invalid: AddressFieldName[] = [];
  if (!PIN_CODE_PATTERN.test(fields.pin_code.trim())) {
    invalid.push("pin_code");
  }
  return invalid;
}
