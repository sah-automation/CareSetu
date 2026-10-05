"use client";

// #617: the Practice section card's editable slice - its fields, their bounds, the
// mapper that turns the shared profile answer into them, and the validation pass
// that mirrors the server's own rules (#608).
//
// A sibling of `addressCardFields.ts` (#616) and for the same reasons, and a
// sibling rather than a key in one shared `sectionFields` because the practice
// slice and the about slice are two different writes: each card has its own route,
// its own body and its own save, and folding them into one shape would put two
// independently saving cards back into a form that can no longer save either.
//
// Three rules decide what belongs here:
//
//   1. The field NAMES are the wire names. A 422 arrives with
//      `details.errors[].path` naming the field the server refused, and that path
//      is what maps an error onto an input (api-standards §2, blueprint §9.5).
//      Renaming a key here would make every server error unmappable.
//   2. Numeric inputs stay STRINGS while editing, so a doctor can clear one
//      mid-edit. Only the submit path converts, and it converts an empty field to
//      `null` rather than to `0` - "years of experience" left blank is a doctor who
//      has not said, and 0 is a claim about their career.
//   3. A bound the client does not mirror is a bound the doctor learns about only
//      from the server, so every `max_length` in `doctor_profile_models.py` is
//      mirrored here. The one bound deliberately NOT mirrored is a selection's
//      length: the backend has none either, because the closed list already is the
//      bound.

import type {
  DoctorProfilePracticeUpdate,
  DoctorProfileView,
} from "@/lib/doctor/api";

import {
  specialtiesFromProfile,
  type ProfileSpecialty,
} from "./profileVocabularies";

/**
 * The per-field bounds, in lockstep with `DoctorProfilePracticeUpdate`: the name and
 * the clinic name are the profile's two String(120) columns, and the experience
 * bound is #606's 0..60 CHECK.
 */
export const PRACTICE_LIMITS = {
  fullName: 120,
  clinicName: 120,
  experienceYears: { min: 0, max: 60 },
} as const;

export interface PracticeFields {
  full_name: string;
  clinic_name: string;
  /** A closed selection, so it is a typed member list rather than free text. */
  specialties: ProfileSpecialty[];
  /** A string while editing so the field can be cleared; see rule 2 above. */
  experience_years: string;
}

/** The fields the Practice card's validation pass can name. */
export type PracticeFieldName =
  | "full_name"
  | "clinic_name"
  | "experience_years";

export function practiceFromProfile(
  profile: DoctorProfileView,
): PracticeFields {
  return {
    full_name: profile.practice_name ?? "",
    clinic_name: profile.clinic_name ?? "",
    specialties: specialtiesFromProfile(profile),
    experience_years:
      profile.experience_years == null ? "" : String(profile.experience_years),
  };
}

/** Blank is a value the card omits rather than sends as an empty string. */
function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * The request body. `full_name` is trimmed but never emptied by this function: the
 * field is `min_length=1`, and a blank name is a refusal the validation pass states
 * in one sentence, not something to send and let the server refuse.
 */
export function practiceUpdateFromFields(
  fields: PracticeFields,
): DoctorProfilePracticeUpdate {
  const years = fields.experience_years.trim();
  return {
    full_name: fields.full_name.trim(),
    clinic_name: optionalText(fields.clinic_name),
    specialties: [...fields.specialties],
    experience_years: years === "" ? null : Number(years),
  };
}

/**
 * The client-side validation pass, run on blur and on submit (§9.5). Returns the
 * fields that need attention, in DOM order, so the summary can count them and the
 * focus walk can take the first. WHEN it runs is `useSectionValidation`'s business.
 *
 * Two rules, and both are ones the client can state in a sentence: a name is not
 * blank, and years are a whole number inside #606's bound. The closed specialties
 * need no rule here, because the only way to change the selection is to tap a chip -
 * a value outside the list is not reachable, and the server's member-by-member walk
 * is there for a client that is not this one.
 */
export function invalidPracticeFields(
  fields: PracticeFields,
): PracticeFieldName[] {
  const invalid: PracticeFieldName[] = [];
  const name = fields.full_name.trim();
  if (name.length === 0 || name.length > PRACTICE_LIMITS.fullName) {
    invalid.push("full_name");
  }
  if (fields.clinic_name.trim().length > PRACTICE_LIMITS.clinicName) {
    invalid.push("clinic_name");
  }
  const years = fields.experience_years.trim();
  if (years !== "") {
    const parsed = Number(years);
    if (
      !Number.isInteger(parsed) ||
      parsed < PRACTICE_LIMITS.experienceYears.min ||
      parsed > PRACTICE_LIMITS.experienceYears.max
    ) {
      invalid.push("experience_years");
    }
  }
  return invalid;
}
