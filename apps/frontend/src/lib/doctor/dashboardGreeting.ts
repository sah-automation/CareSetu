// #678: the greeting helpers for the doctor console landing - which part of the
// day it is, the doctor's own name in first-name form with honorifics stripped,
// and the localized date line that sits under the greeting.
//
// Pure functions on purpose: the time-of-day decision and the honorific strip
// are the two places a greeting spec can go vague, so each lives behind a seam
// that a focused test drives with explicit dates and names instead of fake
// timers at the page seam.

import type { Dictionary, Lang } from "@/lib/i18n/dictionaries";

export type GreetingPart = "morning" | "afternoon" | "evening";

/** Which part of the day `now` is in: morning before noon, afternoon until 5pm, evening after. */
export function greetingPart(now: Date): GreetingPart {
  const hour = now.getHours();
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}

/**
 * The locale's greeting word for `now` - the one ternary that turns a
 * `GreetingPart` into its copy. The page and its tests both go through this
 * seam, so the part-to-word mapping has exactly one home; switching the
 * afternoon and evening strings is caught where the mapping lives, not
 * re-derived silently in a test.
 */
export function greetingTimeText(
  t: Dictionary["doctorConsole"],
  now: Date,
): string {
  const part = greetingPart(now);
  return part === "morning"
    ? t.greetingMorning
    : part === "afternoon"
      ? t.greetingAfternoon
      : t.greetingEvening;
}

// Leading honorifics a doctor's own name may carry ("Dr. Anil Kumar",
// "डॉ. अनिल कुमार"). Each is matched only when followed by a period or
// whitespace, so a real name that merely begins with these letters ("Drishya",
// "Modern Care") is never eaten. English and Devanagari both, so the strip
// works in either script a doctor's profile was typed in.
const LEADING_HONORIFIC =
  /^\s*(?:dr|doctor|prof|professor|mr|mrs|ms|डॉ|डॉक्टर|प्रो|प्रोफेसर|श्री|श्रीमती|सुश्री)[.\s]+/i;

/**
 * The doctor's own name in first-name form: the first spoken token of
 * `practice_name` with any leading honorific stripped.
 *
 * Returns null for a missing, blank, or honorific-only name, so the greeting
 * falls back to the name-free form rather than greeting a doctor by their own
 * title or by nothing at all.
 */
export function greetingFirstName(
  practiceName: string | null | undefined,
): string | null {
  if (practiceName == null) return null;
  const trimmed = practiceName.trim();
  if (trimmed.length === 0) return null;
  const stripped = trimmed.replace(LEADING_HONORIFIC, "").trim();
  if (stripped.length === 0) return null;
  return stripped.split(/\s+/)[0] || null;
}

/** Today's date line under the greeting, in the active locale's long form. */
export function formatGreetingDate(now: Date, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(now);
}
