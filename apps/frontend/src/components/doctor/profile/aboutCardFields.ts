"use client";

// #617: the About section card's editable slice - the doctor's own words, the two
// closed selections and the hours kept as prose (#610).
//
// A sibling of `addressCardFields.ts` (#616) and `practiceCardFields.ts` (#608),
// split per card for the reason all three are: each has its own route, its own body
// and its own save, so one shared editable shape would be a whole-form shape again.
//
// Two rules decide what belongs here:
//
//   1. The field NAMES are the wire names. A 422 arrives with
//      `details.errors[].path` naming the field the server refused, and that path is
//      what maps an error onto an input (api-standards §2, blueprint §9.5). Renaming
//      a key here would make every server error unmappable.
//   2. Nothing here is trimmed to fit a shape. The hours are PROSE with no weekly
//      template, no per-day ranges and no slots, because the platform has no
//      booking system: a structure that invited one would be a promise the server
//      could not keep, and the help text says so where the doctor reads it first.

import type {
  DoctorProfileAboutUpdate,
  DoctorProfileView,
} from "@/lib/doctor/api";

import {
  consultingDaysFromProfile,
  languagesFromProfile,
  type ProfileConsultingDay,
  type ProfileConsultLanguage,
} from "./profileVocabularies";

/**
 * The bounds, in lockstep with `DoctorProfileAboutUpdate`. The hours bound matches
 * the column's retired predecessor so a doctor who typed a long availability note
 * into the old free-text blob can move it across whole.
 */
export const ABOUT_LIMITS = {
  about: 5000,
  consultingHours: 1000,
} as const;

export interface AboutFields {
  about: string;
  /** Two closed selections, each a typed member list rather than free text. */
  languages: ProfileConsultLanguage[];
  consulting_days: ProfileConsultingDay[];
  /** Prose, and deliberately unstructured; see rule 2 above. */
  consulting_hours: string;
}

export type AboutFieldName = "about" | "consulting_hours";

export function aboutFromProfile(profile: DoctorProfileView): AboutFields {
  return {
    about: profile.about ?? "",
    languages: languagesFromProfile(profile),
    consulting_days: consultingDaysFromProfile(profile),
    consulting_hours: profile.consulting_hours ?? "",
  };
}

/** Blank is a value the card clears rather than sends as an empty string. */
function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * The request body. **Every field is sent, including the two nullable ones**, and
 * that is the model's requirement rather than this function's preference: a section
 * save declares the whole card, so omitting `about` would CLEAR the doctor's own
 * words and the save would still report success. `null` is how a doctor clears a
 * field deliberately, which is why blank maps to `null` and not to an absent key.
 */
export function aboutUpdateFromFields(
  fields: AboutFields,
): DoctorProfileAboutUpdate {
  return {
    about: optionalText(fields.about),
    languages: [...fields.languages],
    consulting_days: [...fields.consulting_days],
    consulting_hours: optionalText(fields.consulting_hours),
  };
}

/**
 * The About card's validation pass, run on blur and on submit (§9.5). Two length
 * rules and nothing else.
 *
 * There is deliberately no rule about the languages or the days: both are closed
 * selections, and a member outside a closed list cannot be reached by tapping a
 * chip. A validation rule the doctor cannot break is a rule that only exists to be
 * wrong.
 */
export function invalidAboutFields(fields: AboutFields): AboutFieldName[] {
  const invalid: AboutFieldName[] = [];
  if (fields.about.trim().length > ABOUT_LIMITS.about) {
    invalid.push("about");
  }
  if (fields.consulting_hours.trim().length > ABOUT_LIMITS.consultingHours) {
    invalid.push("consulting_hours");
  }
  return invalid;
}
