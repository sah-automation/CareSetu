"use client";

// #617: the Notification section card's editable slice - the five switches, the
// total map over them, and the pass that has nothing to check (#610).
//
// A sibling of `addressCardFields.ts` (#616), `practiceCardFields.ts` (#608) and
// `aboutCardFields.ts` (#610), split per card for the reason all four are: each has
// its own route, its own body and its own save.
//
// One rule decides what belongs here:
//
//   1. The five keys are NAMES, not values. `notification_preferences` is the only
//      wire path this card can be refused on - the backend reports an unknown key
//      against the dict itself - so the slice holds no field called
//      `notification_preferences` and the copy never speaks about a key.

import type {
  DoctorProfileNotificationUpdate,
  DoctorProfileView,
} from "@/lib/doctor/api";

/**
 * The five things a doctor can be notified about, mirroring #602's
 * `NotificationPreferenceKey`.
 *
 * This list MOVED here from the retired `profileForm.ts`, and it moved because its
 * home was wrong rather than its contents: until #610 the only named list of these
 * five anywhere in the repository was this TypeScript tuple, which is why the
 * server's "preferences" had no vocabulary and no pre-condition to enforce against.
 * #610 declared the owning copy on the server. This remains the copy the page
 * RENDERS, and the two are kept in step by the suite that asserts every key here is
 * a member of the backend enum - which is the only direction that can be checked
 * from here, since the browser cannot import Python.
 */
export const NOTIFICATION_KEYS = [
  "new_consultations",
  "record_shared",
  "pre_summary_ready",
  "case_updates",
  "credential_status",
] as const;

export type NotificationKey = (typeof NOTIFICATION_KEYS)[number];

/**
 * The card's slice is a TOTAL map over the five, not the stored dict.
 *
 * A total map is what makes rendering and submitting both a plain lookup with no
 * membership test: a key the row has never held starts `false` because the doctor
 * never chose it, and the submitted body always carries all five - which is what
 * makes a save mean "these are my five toggles" rather than "here is one more
 * change". A doctor who turns every switch off submits five falses and ends up with
 * no toggles, and that is a real answer rather than an absent one.
 *
 * The stored dict's other keys are deliberately NOT held here. `require_notification_
 * preferences` refuses a key outside the five, so echoing one back would make every
 * save a 422; the promise that such a stored key survives a save is now the server's
 * MERGE to keep (`merge_notification_preferences`), and the card sees its result in
 * the projection that merge returns.
 */
export interface NotificationFields {
  preferences: Record<NotificationKey, boolean>;
}

export type NotificationFieldName = "notification_preferences";

/**
 * Seed the five from the projection. A value is read as a boolean or treated as
 * absent: the projection is typed `Record<string, boolean>` but the wire is not this
 * module's to trust, and `Boolean("false")` is the exact opposite of what such a
 * value says - the same reason the backend carries a stored preference through
 * verbatim instead of narrowing it (see `merge_notification_preferences`).
 */
export function notificationsFromProfile(
  profile: DoctorProfileView,
): NotificationFields {
  const stored = profile.notification_preferences;
  const seeded = {} as Record<NotificationKey, boolean>;
  for (const key of NOTIFICATION_KEYS) {
    const value = stored[key];
    seeded[key] = typeof value === "boolean" ? value : false;
  }
  return { preferences: seeded };
}

/**
 * The request body: exactly the five toggles, nothing else.
 *
 * Stated as a rebuild over `NOTIFICATION_KEYS` rather than a spread of the slice so
 * the guarantee is structural - a sixth key cannot get into the body even if a future
 * field is added to the slice by mistake. The backend refuses one anyway; this makes
 * it impossible to send rather than merely refused.
 */
export function notificationsUpdateFromFields(
  fields: NotificationFields,
): DoctorProfileNotificationUpdate {
  const preferences: Record<string, boolean> = {};
  for (const key of NOTIFICATION_KEYS) {
    preferences[key] = fields.preferences[key];
  }
  return { notification_preferences: preferences };
}

/**
 * The Notification card's validation pass, which is empty.
 *
 * Not an oversight: there is nothing on this card a doctor can enter that the
 * vocabulary does not already hold. Every control is a switch over a key the five
 * name, and every value is a boolean by construction, so a rule here could only
 * fire on a bug in this module. The function exists anyway, so the card's save path
 * has the same three steps as its siblings' and a rule added later has somewhere to
 * live - and because `useSectionValidation` is what runs it, this card's blur and
 * submit behaviour cannot drift from theirs'.
 */
export function invalidNotificationFields(
  _fields: NotificationFields,
): NotificationFieldName[] {
  return [];
}
