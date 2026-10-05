// #618: the projection the live preview renders. One pure function, from what
// the doctor has TYPED to the exact shape the public profile surface consumes -
// so the preview runs on the same field names, the same null-means-absent rule
// and the same first-specialty representative the backend publishes.
//
// The rule this file exists to hold is which fields a typed value may reach:
//
//   - DECLARED fields (name, specialties, locality) come from the draft, because
//     they are what the doctor is editing and the preview is here to show them.
//   - DERIVED fields (`verified`, every credential's `status`) come from the API
//     projection and from nowhere else (ADR-0011, FEAT-005). `verified` is
//     derived server-side from activation state plus credential dates and is
//     never stored, so a client that recomputed it - or worse, let a typed value
//     reach it - would be a second derivation site that can disagree with the
//     only one that counts. There is no `verified` key on the draft, so there is
//     nothing for a keystroke to write into.
//
// The two REPRESENTATIVE values mirror `get_provider_profile` exactly: the
// specialty is the FIRST member of the filtered selection, and the service area
// is the DECLARED locality rather than the platform's `area` vocabulary (#612).
// A preview that disagreed with either would show a doctor something the real
// surface cannot show.
//
// Credentials are the one place the preview deliberately does NOT mirror it, and
// the direction is the safe one. `get_provider_profile` returns
// `status="verified"` for every credential it serves, because the visibility gate
// already proved them all valid - so hardcoding the same word here would be a
// second derivation site that can disagree with the server's, and it would show a
// doctor an expired credential as ticked. The preview reports each credential's
// real status and so can differ from the public page on that one field. The
// renderer still invents no tick: a typed value cannot reach either field.
//
// #619 widened the projection with the DECLARED band, so this file now carries it
// too - and the split above is unchanged by that. The band is where the two hosts
// differ most, so it is worth being exact about which of its fields a keystroke
// reaches. `practice_name`, `specialty`, `area` and `locality` DO come from the
// draft, because the doctor is editing them in the cards that publish today, and a
// preview that ignored them would be lying about the two sections it claims to be
// live. Every other declared field is a saved fact passed through from the private
// projection, so a doctor typing in the About or Languages card does not move the
// preview until that section publishes into the draft - which is the honest version
// of "live". The preview shows the saved profile plus the fields that are actually
// being typed, and never claims to show a sentence that has not been saved.
//
// The band is also where the shared renderer is least forgiving, which is why it is
// the band with the loudest rules: a declared field that reached a solid-edged band
// would read as platform-vouched, so the band component refuses to put a tick on
// any of it regardless of how plausible the value looks.

import { declaredText, type ProviderProfile } from "@/lib/directory/profile";

import type { DoctorProfileView } from "@/lib/doctor/api";

import type { AddressFields } from "./addressCardFields";
import type { PracticeFields } from "./practiceCardFields";

/** The sections whose edits reach the preview. Extend per declared band. */
const PUBLIC_PROFILE_SECTIONS = ["practice", "address"] as const;

export type PublicProfileSection = (typeof PUBLIC_PROFILE_SECTIONS)[number];

/**
 * What the doctor has typed so far, one slice per publishing section.
 *
 * Strings, not nulls: these are editor buffers, and the section edit buffer's own
 * convention is that an unsaid field is `""`. The null-vs-absent decision belongs
 * to the projection below, where it is one rule rather than one per field.
 */
export interface PublicProfileDraft {
  practice: { practiceName: string; specialties: string[] };
  address: { locality: string };
}

/** The draft a saved projection seeds, before a doctor has touched anything. */
export function draftFromProfile(
  profile: DoctorProfileView,
): PublicProfileDraft {
  return {
    practice: {
      practiceName: profile.practice_name ?? "",
      specialties: [...profile.specialties],
    },
    address: { locality: profile.locality ?? "" },
  };
}

/**
 * What the Practice card publishes when the doctor types there. A mapping rather
 * than the card's slice itself, because the two slices use different vocabularies
 * on purpose: the card's keys are the wire names a 422 refusal arrives with, and
 * the draft's are the projection's field names. Copying one over the other would
 * invite renaming one to match the other.
 *
 * Declared as a function of the card's fields so the card's change handler reads as
 * "publish what I now hold", which is the whole contract.
 */
export function practiceDraftFromFields(
  fields: Pick<PracticeFields, "full_name" | "specialties">,
): PublicProfileDraft["practice"] {
  return {
    practiceName: fields.full_name,
    specialties: [...fields.specialties],
  };
}

/** What the Address card publishes when the doctor types there. */
export function addressDraftFromFields(
  fields: Pick<AddressFields, "locality">,
): PublicProfileDraft["address"] {
  return { locality: fields.locality };
}

/**
 * The projection both hosts render.
 *
 * `profile` is the API answer and `draft` is the typed state; nothing but the
 * declared fields reads the draft, and nothing derived reads the draft at all.
 */
export function projectPublicProfile(
  profile: DoctorProfileView,
  draft: PublicProfileDraft,
): ProviderProfile {
  return {
    partner_id: profile.partner_id,
    practice_name: declaredText(draft.practice.practiceName),
    // The doctor console is the only host that has a doctor to preview, and the
    // public projection's `partner_type` is a closed vocabulary - so this states
    // the member rather than widening the draft with a field nobody can type.
    partner_type: "doctor",
    specialty: draft.practice.specialties[0] ?? null,
    area: declaredText(draft.address.locality),
    // ADR-0011: the stored, server-derived indicator. Read, never recomputed, and
    // unreachable from the draft.
    verified: profile.verified,
    credentials: profile.credentials.map((credential) => ({
      credential_type: credential.credential_type,
      status: credential.status,
      expires_at: credential.expires_at,
    })),
    // #619: the rest of the DECLARED band, passed through from the private
    // projection the server already serves. These are saved facts rather than
    // typed ones, so they read the API answer - the two sections that publish into
    // the draft today (`practice`, `address`) are the two whose declared fields are
    // already handled above, and the rule that will keep this list honest as the
    // other sections gain editors is the same one: a field only moves to the draft
    // when a card publishes it.
    clinic_name: profile.clinic_name,
    specialties: [...draft.practice.specialties],
    languages: [...profile.languages],
    consulting_days: [...profile.consulting_days],
    consulting_hours: profile.consulting_hours,
    about: profile.about,
    experience_years: profile.experience_years,
    address_line: profile.address_line,
    landmark: profile.landmark,
    locality: declaredText(draft.address.locality),
    city: profile.city,
    pin_code: profile.pin_code,
  };
}
