// PHASE-2.6 T13 (#204): client-side profile draft state backing the
// first-login profile-completion wizard, the Home nudge cards, and the §5.9
// gating matrix (blueprint §5.9; prototype profile-completion.html is the
// binding visual/copy spec).
//
// Gating matrix (source of truth - blueprint §5.9):
//   - OTP identity gates login only. Browsing Find Care and viewing My
//     Record are NEVER gated.
//   - Name + age + gender gate care actions (intake submission, booking).
//   - Area/address gates medicine-delivery checkout only.
//
// INTEGRATION POINT (later phase): the draft lives client-side only -
// localStorage here, a server-side profile write (gap G5) later. Nothing in
// this module may pretend persistence beyond the device exists. The language
// field records profile-language intent per spec #191 D1: asked explicitly
// in wizard step 1, defaulting to "en" until set.

import type { Lang } from "@/lib/i18n/dictionaries";

const DRAFT_STORAGE_KEY = "caresetu.profile.draft";

export const MIN_AGE = 1;
export const MAX_AGE = 120;

export type GenderId = "female" | "male" | "other";

export interface ProfileDraft {
  // Step 1 - required basics (language per D1).
  name: string;
  /** Raw input value; validity is judged by parseAge, never trusted directly. */
  age: string;
  gender: "" | GenderId;
  language: Lang;
  // Step 2 - skippable chronic-interest toggles.
  trackBp: boolean;
  trackSugar: boolean;
  // Step 3 - skippable photo/area/emergency contact.
  /** File name only this phase - no upload exists yet (integration point). */
  photoFileName: string;
  area: string;
  emergencyContact: string;
}

export function initialDraft(): ProfileDraft {
  return {
    name: "",
    age: "",
    gender: "",
    language: "en",
    trackBp: false,
    trackSugar: false,
    photoFileName: "",
    area: "",
    emergencyContact: "",
  };
}

// --- Field predicates -------------------------------------------------------
// One predicate per collectable item; validation and the completion meter
// both derive from these so garbage input can never advance the meter.

function hasText(value: string): boolean {
  return value.trim().length > 0;
}

/** Parses the raw age input to a plausible whole-number age, or null. */
export function parseAge(raw: string): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const n = Number.parseInt(raw.trim(), 10);
  return n >= MIN_AGE && n <= MAX_AGE ? n : null;
}

export interface Step1Errors {
  nameRequired: boolean;
  ageRequired: boolean;
  ageInvalid: boolean;
  genderRequired: boolean;
}

export function step1Errors(draft: ProfileDraft): Step1Errors {
  const trimmed = draft.age.trim();
  return {
    nameRequired: !hasText(draft.name),
    ageRequired: trimmed.length === 0,
    ageInvalid: trimmed.length > 0 && parseAge(draft.age) === null,
    genderRequired: draft.gender === "",
  };
}

/** Basics complete = the care-action gate's requirement (name+age+gender). */
export function basicsComplete(draft: ProfileDraft): boolean {
  const errors = step1Errors(draft);
  return (
    !errors.nameRequired &&
    !errors.ageRequired &&
    !errors.ageInvalid &&
    !errors.genderRequired
  );
}

/** Delivery gate's requirement: a non-empty area/address. */
export function areaComplete(draft: ProfileDraft): boolean {
  return hasText(draft.area);
}

function trackingChosen(draft: ProfileDraft): boolean {
  return draft.trackBp || draft.trackSugar;
}

function photoPresent(draft: ProfileDraft): boolean {
  return hasText(draft.photoFileName);
}

function emergencyPresent(draft: ProfileDraft): boolean {
  return hasText(draft.emergencyContact);
}

// --- Completion meter -------------------------------------------------------

/** The seven collectable items the meter counts; each is worth one share. */
function completenessItems(draft: ProfileDraft): boolean[] {
  return [
    hasText(draft.name),
    parseAge(draft.age) !== null,
    draft.gender !== "",
    trackingChosen(draft),
    photoPresent(draft),
    areaComplete(draft),
    emergencyPresent(draft),
  ];
}

/** Draft completeness as a whole percentage, 0-100. */
export function profileCompleteness(draft: ProfileDraft): number {
  const items = completenessItems(draft);
  const filled = items.filter(Boolean).length;
  return Math.round((100 * filled) / items.length);
}

// --- Gating matrix ----------------------------------------------------------

/** Patient actions whose gating the matrix answers for. */
export type PatientAction =
  | "findCare"
  | "viewRecord"
  | "intake"
  | "booking"
  | "medicineCheckout";

/**
 * What blocks an action right now: "basics" (name+age+gender), "area", or
 * null when nothing does. Browse actions always answer null.
 */
export type ProfileGate = "basics" | "area";

export function evaluateGate(
  action: PatientAction,
  draft: ProfileDraft,
): ProfileGate | null {
  switch (action) {
    case "findCare":
    case "viewRecord":
      return null;
    case "intake":
    case "booking":
      return basicsComplete(draft) ? null : "basics";
    case "medicineCheckout":
      return areaComplete(draft) ? null : "area";
  }
}

// --- Nudge groups -----------------------------------------------------------
// Skipped items resurface on Home as gentle dismissible cards - one card per
// still-missing group, never a modal (§5.9).

export type NudgeGroup = "basics" | "tracking" | "photo" | "area" | "emergency";

export function missingNudgeGroups(draft: ProfileDraft): NudgeGroup[] {
  const groups: Array<[NudgeGroup, boolean]> = [
    ["basics", !basicsComplete(draft)],
    ["tracking", !trackingChosen(draft)],
    ["photo", !photoPresent(draft)],
    ["area", !areaComplete(draft)],
    ["emergency", !emergencyPresent(draft)],
  ];
  return groups.filter(([, missing]) => missing).map(([group]) => group);
}

// --- Nudge dismissal memory -------------------------------------------------
// Dismissing a Home nudge card hides just that card for the current page
// session (mirrors lib/consent/consentGate's session-scoped convention).
// Deliberately in-memory and never durable: a later visit gets its gentle
// reminder again - dismissal is not a "never ask me again" preference.

const dismissedNudges = new Set<NudgeGroup>();

export function dismissNudge(group: NudgeGroup): void {
  dismissedNudges.add(group);
}

export function isNudgeDismissed(group: NudgeGroup): boolean {
  return dismissedNudges.has(group);
}

// Test isolation only: the store is process-global.
export function __resetNudgeDismissalsForTests(): void {
  dismissedNudges.clear();
}

// --- Persistence ------------------------------------------------------------

export function saveDraft(draft: ProfileDraft): void {
  window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
}

/** Stored draft when readable; a fresh initial draft otherwise. */
export function loadDraft(): ProfileDraft {
  const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
  if (!raw) return initialDraft();
  try {
    const parsed = JSON.parse(raw) as Partial<ProfileDraft> | null;
    if (!parsed || typeof parsed !== "object") return initialDraft();
    // Merge over the initial draft so fields added later default cleanly.
    return { ...initialDraft(), ...parsed };
  } catch {
    // Observable, never silent - but no PHI: the raw value stays unlogged.
    console.warn("[profile-draft] stored draft unreadable, starting fresh");
    return initialDraft();
  }
}
