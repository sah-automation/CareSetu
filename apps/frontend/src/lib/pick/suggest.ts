// PHASE-8.1 T11 (#449): derive a suggested specialty from the patient's
// structured fields. The suggestion appears as a start-here filter on the
// pick-a-doctor screen - never blocking full choice (US-2/US-3). Priority:
// child keywords > dental > pregnancy/menstrual > General Physician default.

import type { StructuredFields } from "@/lib/intake/api";
import type { Specialty } from "@/lib/directory/search";

const CHILD_RE =
  /\b(child|children|baby|infant|kid|toddler|बच्च[ाेे]|बच्चे|शिशु)\b/i;

const DENTAL_RE =
  /\b(tooth|teeth|dental|toothache|gum|decayed|cavity|दां?त|डेंटल)\b/i;

const PREGNANCY_RE =
  /\b(pregnant|pregnancy|menstruation|menstrual|period|periods|miscarriage|abortion|gestation|गर्भ|पीरियड|मासिक|गर्भवती|प्रेगनेंसी)\b/i;

function joinText(
  fields: Pick<StructuredFields, "chief_complaints" | "symptoms">,
): string {
  return [...fields.chief_complaints, ...fields.symptoms].join(" ");
}

/**
 * Derive a suggested specialty from the intake's structured fields.
 * Always returns a specialty - an unrelated or empty chief complaint
 * falls back to General Physician (brief T11 US-2 "otherwise General
 * Physician"), shown as a start-here filter, never a verdict.
 *
 * Priority: child > dental > pregnancy/menstrual > General Physician.
 */
export function deriveSpecialtyFromSymptoms(
  fields: Pick<StructuredFields, "chief_complaints" | "symptoms">,
): Specialty {
  const text = joinText(fields);

  if (CHILD_RE.test(text)) return "Pediatrician";
  if (DENTAL_RE.test(text)) return "Dentist";
  if (PREGNANCY_RE.test(text)) return "Gynecologist";
  // Default suggestion when nothing specific matches (US-2)
  return "General Physician";
}
