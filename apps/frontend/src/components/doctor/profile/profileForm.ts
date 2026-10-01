// #615: the shape the profile page's editable sections share, lifted out of the
// page body when the page became a shell.
//
// What lives here is only what the section components need to render a field:
// the form's own keys, the names the validation pass names a bad field by, and the
// input bounds the controls mirror. The request builder (`updateFromForm`), the
// validation pass (`invalidFields`) and the buffer's seeding (`formFromProfile`)
// deliberately stay on the page, because the brief scopes them there as what is
// specific to this surface's whole-form write - the section-write clients that
// will replace that write belong to the section tickets.
//
// `LIMITS` is the frontend's mirror of `doctor_profile_models.py`. A bound that
// is not mirrored here is a bound the doctor only learns about from the server,
// so keep it in lockstep with the model.

/** The per-field bounds the controls mirror, in lockstep with the backend model. */
export const LIMITS = {
  practiceName: 120,
  practiceAddress: 1000,
  about: 5000,
  experienceYears: { min: 0, max: 60 },
  languages: 20,
  languageNameLength: 50,
} as const;

/**
 * The fields the validation pass can name. The coordinate fields are gone from
 * both lists: #615 removed the inputs, and the server-written position travels in
 * the whole-form write unedited rather than through a field the doctor is shown.
 */
export type ProfileFieldName =
  | "practice_name"
  | "practice_address"
  | "experience_years"
  | "languages"
  | "about";

/**
 * Every value stays a string while editing so a field can be cleared mid-edit;
 * only the submit path converts to the typed request body.
 *
 * The two coordinate fields are the exception to "editable": #615 removed their
 * inputs and no component renders them, because the backend derives the practice
 * position from the declared PIN code (#609). They are carried here unedited only
 * because the transitional request builder still declares them - a transitional
 * state, not a field the doctor owns.
 */
export interface ProfileForm {
  practice_name: string;
  practice_address: string;
  /** Server-written, never client-written. @see the note on `ProfileForm`. */
  practice_latitude: string;
  /** Server-written, never client-written. @see the note on `ProfileForm`. */
  practice_longitude: string;
  experience_years: string;
  languages: string;
  about: string;
  notifications: Record<string, boolean>;
}

/**
 * The canonical notification-key vocabulary this page renders as toggles, because
 * the backend keeps preferences as a dict capped at 20 entries with 50-character
 * keys. A key the server already holds that this list does not know is carried
 * through untouched on save, so a save never silently drops a stored preference.
 */
export const NOTIFICATION_KEYS = [
  "new_consultations",
  "record_shared",
  "pre_summary_ready",
  "case_updates",
  "credential_status",
] as const;

export type NotificationKey = (typeof NOTIFICATION_KEYS)[number];

export const MAX_NOTIFICATION_ENTRIES = 20;
export const MAX_NOTIFICATION_KEY_LENGTH = 50;
