"use client";

// #617: the frontend's mirror of the three closed practice vocabularies the
// domain owns (#602), plus the one rule each of them needs on this side.
//
// #602 declared them in `modules/partner/domain/vocabularies.py` as `StrEnum`s
// and REFUSES a value outside the list. Until now the doctor Profile page was the
// only place a member of any of them was named, and it named none of them: the
// specialty chip row printed the wire strings and the language field was a
// free-text box parsed by commas, so a doctor was typing at a vocabulary rather
// than choosing from one. This module is the client's copy of the three lists,
// and it exists for the same reason the backend's exists: a closed list the client
// cannot see is a list whose members a doctor guesses at.
//
// Three rules, and each of them is a decision about what the client is NOT allowed
// to do:
//
//   1. **The values are the domain's values, verbatim.** `Specialty.MONTH` is
//      "General Physician", not a slug - the wire carries the display-ready string
//      and the column is keyed on it, so a client that invented its own spelling
//      would be refused by `require_specialties`. No aliases, no normalisation.
//   2. **A selection is narrowed to members on the way IN, not on the way out.**
//      `knownMembers` is what keeps a stored value this client does not know from
//      reaching a toggle group: an unknown value has no chip to render, so
//      leaving it in the selection would either drop it silently at save time or
//      render an unlabelled chip. Narrowing drops it explicitly, at the seam where
//      it becomes a decision, rather than letting the save 422 on it.
//   3. **An empty selection is a state the doctor can hold**, for all three. A
//      doctor who has not decided their consulting days yet is not making a
//      mistake, and the domain agrees (`require_consulting_days` returns an empty
//      tuple for an empty selection). So nothing here invents a default member.
//
// The labels are NOT here. A value is a machine key and a label is copy, so the
// labels live in `dictionaries.ts` beside every other bilingual string, and
// `labelFor` here is what maps a member onto one.
//
// #602 owns the canonical lists. If you add a member there, add it here and add
// its label to both locales, or the selection the domain will accept is one this
// page cannot offer.

import type { DoctorProfileView } from "@/lib/doctor/api";

/** The closed `Specialty` pick-list (FEAT-004). Mirrors #602's `Specialty`. */
export const SPECIALTIES = [
  "General Physician",
  "Pediatrician",
  "Gynecologist",
  "Dentist",
  "General Surgeon",
  "Orthopedic Surgeon",
  "Ophthalmologist",
  "ENT Specialist",
  "Dermatologist",
  "Psychiatrist",
  "Cardiologist",
  "Neurologist",
  "Gastroenterologist",
  "Urologist",
  "Nephrologist",
  "Pulmonologist",
  "Endocrinologist",
  "Oncologist",
  "Ayurvedic Practitioner",
  "Homeopathy Practitioner",
] as const;

export type ProfileSpecialty = (typeof SPECIALTIES)[number];

/**
 * The closed `ConsultLanguage` list (FEAT-005): the Eighth Schedule's languages
 * plus English. Mirrors #602's `ConsultLanguage`.
 */
export const CONSULT_LANGUAGES = [
  "Assamese",
  "Bengali",
  "Bodo",
  "Dogri",
  "English",
  "Gujarati",
  "Hindi",
  "Kannada",
  "Kashmiri",
  "Konkani",
  "Maithili",
  "Malayalam",
  "Manipuri",
  "Marathi",
  "Nepali",
  "Odia",
  "Punjabi",
  "Sanskrit",
  "Santali",
  "Sindhi",
  "Tamil",
  "Telugu",
  "Urdu",
] as const;

export type ProfileConsultLanguage = (typeof CONSULT_LANGUAGES)[number];

/** The closed seven-day list (FEAT-005). Mirrors #602's `ConsultingDay`. */
export const CONSULTING_DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export type ProfileConsultingDay = (typeof CONSULTING_DAYS)[number];

/**
 * Narrow a stored multi-valued selection to the members this client can render.
 *
 * The wire is not this module's to trust: a row can hold a value that predates a
 * vocabulary change, and such a value has no label here. It is dropped rather than
 * rendered unlabelled - a chip whose text is a raw wire string is exactly what
 * this ticket replaces - and dropping it is a declared outcome, not a silent one:
 * a doctor who saves this card has therefore declared the selection they can see.
 * Order is preserved, because the doctor's declared order is what the stored
 * selection and every later membership match read.
 */
export function knownMembers<V extends string>(
  selection: readonly string[],
  vocabulary: readonly V[],
): V[] {
  const members = new Set<string>(vocabulary);
  return selection.filter((value): value is V => members.has(value));
}

/**
 * Seed one closed selection from the profile projection.
 *
 * A named function per field rather than three call sites of `knownMembers`,
 * because the narrow V to V[] is what each card's slice actually needs and because
 * the argument ORDER is the mistake worth naming: pass the vocabulary as the
 * vocabulary and the seed is total, pass it reversed and every member is unknown and
 * every selection silently empties. Passing it the other way round is NOT a compile
 * error - both sides are string arrays at the boundary - which is the reason these
 * three exist instead of being inlined.
 */
export function specialtiesFromProfile(
  profile: DoctorProfileView,
): ProfileSpecialty[] {
  return knownMembers(profile.specialties, SPECIALTIES);
}

export function languagesFromProfile(
  profile: DoctorProfileView,
): ProfileConsultLanguage[] {
  return knownMembers(profile.languages, CONSULT_LANGUAGES);
}

export function consultingDaysFromProfile(
  profile: DoctorProfileView,
): ProfileConsultingDay[] {
  return knownMembers(profile.consulting_days, CONSULTING_DAYS);
}

/**
 * A stable, locale-independent handle for one vocabulary member.
 *
 * Used only for test hooks and for nothing the doctor can see, and it exists for
 * one reason: a chip's accessible name is its LABEL, which differs between the
 * two locales, so a test that finds a chip by name is a test that has to be
 * written twice and breaks when a translation is reworded. The slug is derived
 * from the machine value - which is stable, and is what the wire carries - so a
 * test can assert "the Hindi chip is pressed" without knowing what "Hindi" is
 * called in the active locale.
 */
export function vocabularySlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
