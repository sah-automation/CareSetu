// #623: one place that turns a backend specialty VALUE into its localized
// label.
//
// Three surfaces render a doctor's declared specialties - the public directory
// browser, the intake pick-a-doctor list and the homepage rail - and each one
// used to carry its own private `value -> camelCase dictionary key` map with
// four entries, over a four-entry `directory.specialties` dictionary. That is
// 16 specialties the backend will happily store and search for which no
// frontend surface could name, and four places to forget to extend.
//
// The doctor-profile dictionary already holds all twenty values in every
// locale, keyed by the backend's own spelling, so the translation already
// existed and the maps were routing around it. This helper is the only
// remaining mapping: value in, localized label out.

import { STRINGS, type Lang } from "@/lib/i18n/dictionaries";

/** Localized name for a backend specialty value.
 *
 * A value the dictionary does not carry falls back to the value itself rather
 * than to a blank chip: a doctor declared in a specialty added to the backend
 * after this locale shipped still has to be findable and still has to be
 * legible, and echoing an English domain value is the honest rendering of that
 * state. Returning the raw value also means an unknown value can never crash a
 * render.
 */
export function specialtyLabel(lang: Lang, value: string): string {
  const labels: Record<string, string> =
    STRINGS[lang].doctorProfile.specialtyLabels;
  return labels[value] ?? value;
}
