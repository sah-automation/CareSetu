// PHASE-3 T9 (#218): presentation helpers for consent log view models.
// Pure functions for rendering consent data - separated from the HTTP client
// to keep api.ts focused on transport concerns.
//
// #653: counterpartyLabel is the one three-step fallback chain that keeps an
// opaque counterparty id from ever being the only thing a patient is shown.
// #654: counterpartyRole is the role in words printed beside that label on a
// consent card - a separate bilingual field, never concatenated into the name.

import { STRINGS, type Lang } from "@/lib/i18n/dictionaries";

/**
 * The AI intake pseudo-counterparty id, exactly as the AI egress path records
 * it (backend: `modules/intake/adapters/__init__.py`'s
 * `AI_EGRESS_COUNTERPARTY_ID`). It is recorded under the `doctor` counterparty
 * type, so this id check must run before the type branch - otherwise a machine
 * disclosure would render as a clinician's.
 */
export const AI_EGRESS_COUNTERPARTY_ID = "intake-ai";

/** The counterparty types that get a word of their own at step two. */
const TYPE_LABEL_KEYS: Record<string, "doctor" | "lab" | "chemist"> = {
  doctor: "doctor",
  lab: "lab",
  chemist: "chemist",
};

/**
 * Resolve the label a patient sees for one consent counterparty, in three
 * steps:
 *
 * 1. the display name the backend resolved - an enrichment of the id, absent
 *    when nothing could name the counterparty;
 * 2. a type-derived word (Doctor / Lab / Pharmacy), guarded by the AI intake
 *    id check above so the pseudo-counterparty reads as the branded service it
 *    is instead of as a doctor;
 * 3. the raw id, only when both are absent - a last resort kept so a
 *    counterparty never renders as a blank avatar and a blank name, and
 *    unreachable in practice for every counterparty type the product records.
 *
 * The result is a single label: counterpartyInitials derives from it and
 * nothing downstream keeps a second source of truth.
 */
export function counterpartyLabel(
  counterpartyType: string,
  counterpartyId: string,
  counterpartyDisplayName?: string | null,
  lang: Lang = "en",
): string {
  if (counterpartyDisplayName) return counterpartyDisplayName;
  const t = STRINGS[lang].consentLog.counterparty;
  if (counterpartyId === AI_EGRESS_COUNTERPARTY_ID) return t.aiService;
  const typeKey = TYPE_LABEL_KEYS[counterpartyType];
  if (typeKey) return t[typeKey];
  return counterpartyId || counterpartyType;
}

/**
 * Derive initials (up to 2 chars) from a display label for the avatar circle.
 */
export function counterpartyInitials(label: string): string {
  const parts = label.trim().split(/\s+/);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/**
 * #654: the role in words a consent card prints beside the resolved name -
 * "Dr A Kumar" plus "Doctor" reads better than a parenthesised concatenation,
 * and a paren reads worse still in Hindi. Two separate fields, both bilingual.
 *
 * The AI intake pseudo-counterparty gets its own role rather than the doctor
 * word its recorded type would imply, so a machine disclosure never reads as a
 * clinician's. Returns null for a counterparty type the product records no
 * word for, so a surface renders no role segment rather than a wrong one.
 */
export function counterpartyRole(
  counterpartyType: string,
  counterpartyId: string,
  lang: Lang = "en",
): string | null {
  const t = STRINGS[lang].consentLog.counterparty;
  if (counterpartyId === AI_EGRESS_COUNTERPARTY_ID) return t.aiRole;
  const typeKey = TYPE_LABEL_KEYS[counterpartyType];
  return typeKey ? t[typeKey] : null;
}
