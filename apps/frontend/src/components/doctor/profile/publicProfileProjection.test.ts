// #618 AC 1 + AC 5: the pure projection behind the live preview. The suite is
// about one thing above all - which fields may come from a TYPED value and which
// may only come from the API projection - because that split is what stops the
// preview from showing a doctor a tick they typed.

import { describe, expect, it } from "vitest";

import type { DoctorProfileView } from "@/lib/doctor/api";

import {
  draftFromProfile,
  projectPublicProfile,
  type PublicProfileDraft,
} from "./publicProfileProjection";

function view(overrides: Partial<DoctorProfileView> = {}): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Dr. Rakesh Sharma",
    clinic_name: "Sharma Clinic",
    specialties: ["General Physician", "Pediatrician"],
    verified: true,
    practice_address: "Main Road",
    address_line: null,
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "826001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["English", "Hindi"],
    experience_years: 12,
    about: "Twelve years in general practice.",
    consultation_fee: 30000,
    consulting_days: ["Monday", "Tuesday"],
    consulting_hours: "9am-5pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
      {
        credential_type: "qualification_certificate",
        status: "expired",
        expires_at: "2020-01-01T00:00:00Z",
      },
    ],
    notification_preferences: {},
    ...overrides,
  };
}

/** A draft, with the slices MERGED rather than replaced. The two publishing
 * sections are what a test here varies independently - a doctor editing their
 * name has not cleared their specialties, and a fixture that made them do so
 * would be testing a state no sequence of keystrokes produces. */
function draft(
  overrides: Partial<{
    practice: Partial<PublicProfileDraft["practice"]>;
    address: Partial<PublicProfileDraft["address"]>;
  }> = {},
): PublicProfileDraft {
  return {
    practice: {
      practiceName: "Dr. Rakesh Sharma",
      specialties: [],
      ...overrides.practice,
    },
    address: { locality: "Daltonganj", ...overrides.address },
  };
}

describe("draftFromProfile", () => {
  it("seeds from the saved projection, with a blank rather than a null field", () => {
    // The buffer's own convention: an editor holds strings, and a value the
    // doctor has not said is an empty string rather than a missing key.
    expect(
      draftFromProfile(
        view({ practice_name: null, locality: null, specialties: [] }),
      ),
    ).toEqual({
      practice: { practiceName: "", specialties: [] },
      address: { locality: "" },
    });
  });
});

describe("projectPublicProfile", () => {
  it("renders the declared fields the doctor is typing", () => {
    const projected = projectPublicProfile(
      view(),
      draft({
        practice: { practiceName: "  Dr. R. Sharma  ", specialties: [] },
      }),
    );

    // A trimmed name, because the wire name is trimmed: showing the raw buffer
    // would show a patient whitespace the API will not serve.
    expect(projected.practice_name).toBe("Dr. R. Sharma");
  });

  it("publishes the FIRST selected specialty, the way the backend does", () => {
    // `get_provider_profile` takes `specialties[0]` of the filtered selection, so
    // a preview that joined the list or showed the last member would show a
    // patient something the real surface cannot show.
    const projected = projectPublicProfile(
      view(),
      draft({
        practice: {
          practiceName: "Dr. Rakesh Sharma",
          specialties: ["Paediatrics", "General Physician"],
        },
      }),
    );

    expect(projected.specialty).toBe("Paediatrics");
  });

  it("shows no specialty row once the doctor clears the whole selection", () => {
    const projected = projectPublicProfile(view(), draft());

    expect(projected.specialty).toBeNull();
  });

  it("reads the service area from the DECLARED locality, never the platform area", () => {
    // The public projection serves the declared locality (#612); `area` on the
    // private view is the platform's service-area vocabulary and is explicitly not
    // a doctor-facing fact, so a preview built on it would show a place the doctor
    // never named.
    const projected = projectPublicProfile(
      view({ locality: "Medininagar", area: "Daltonganj" }),
      draft({ address: { locality: "Medininagar" } }),
    );

    expect(projected.area).toBe("Medininagar");
  });

  it("renders an unsaid field as absent rather than as a blank row", () => {
    const projected = projectPublicProfile(
      view(),
      draft({
        practice: { practiceName: "   ", specialties: [] },
        address: { locality: "  " },
      }),
    );

    expect(projected.practice_name).toBeNull();
    expect(projected.area).toBeNull();
  });

  it("takes the verified marker from the API projection and nothing a doctor typed", () => {
    // AC 5, and the property #613's and #619's own criteria depend on: no string
    // in the draft can reach `verified`, because the draft has no such field.
    expect(
      projectPublicProfile(view({ verified: false }), draft()).verified,
    ).toBe(false);
    expect(
      projectPublicProfile(view({ verified: true }), draft()).verified,
    ).toBe(true);
  });

  it("carries each credential's own status rather than asserting every one verified", () => {
    const projected = projectPublicProfile(view(), draft());

    // `get_provider_profile` hardcodes `status="verified"` for every credential it
    // returns, because the visibility gate already proved all of them valid. The
    // private projection carries the real status, so passing it through DIVERGES
    // from what a patient is served today: the preview can show a doctor an
    // unticked credential the public page will tick.
    //
    // That divergence is deliberate and it is the safer direction. Hardcoding
    // `verified` here too would be a second derivation site that can disagree with
    // the server's - the exact failure ADR-0011 exists to prevent - and it would
    // teach a doctor that an expired credential is fine. The preview reports the
    // truth; the public surface stops lying when #619 reads real status off the
    // projection. What the renderer must never do is invent a tick from a typed
    // value, and no path to a typed value exists for either field.
    expect(projected.credentials).toEqual([
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
      {
        credential_type: "qualification_certificate",
        status: "expired",
        expires_at: "2020-01-01T00:00:00Z",
      },
    ]);
  });

  it("identifies the same partner the public page would serve", () => {
    const projected = projectPublicProfile(view(), draft());

    expect(projected.partner_id).toBe(7);
    expect(projected.partner_type).toBe("doctor");
  });

  it("carries every field the public projection can carry, and nothing else", () => {
    // #619 (FEAT-005, MOD-002): the projection and the public payload are one
    // contract - a field the patient can read has to be here, and a field here is a
    // field a patient can read. #619 widened both sides, so this list is what stops
    // the two drifting apart again: a field added to one and not the other renders
    // nothing on the public page while looking perfectly served here.
    const projected = projectPublicProfile(view(), draft());

    expect(Object.keys(projected).sort()).toEqual([
      "about",
      "address_line",
      "area",
      "city",
      "clinic_name",
      "consulting_days",
      "consulting_hours",
      "credentials",
      "experience_years",
      "landmark",
      "languages",
      "locality",
      "partner_id",
      "partner_type",
      "pin_code",
      "practice_name",
      "specialties",
      "specialty",
      "verified",
    ]);
  });

  it("passes the saved declared band through, and takes only the drafted fields from the draft", () => {
    // #619 (FEAT-005): the rule this file exists to hold, now that the band is
    // here. A value the doctor is TYPING lives in the draft; a value they SAVED
    // lives in the private projection. The About card's text is saved, so a doctor
    // who has not touched it still sees it - and the converse, that no keystroke
    // can reach a field the draft does not carry, is structural: there is no path.
    //
    // The split is not even, and the test says so rather than asserting a tidier
    // story: the two cards that publish into the draft own the practice name, the
    // specialty selection and the locality, and everything else in the band is a
    // saved fact. `specialties` and `locality` are asserted BELOW as draft-owned
    // precisely because the band comment used to claim otherwise.
    const projected = projectPublicProfile(view(), draft());

    expect(projected.about).toBe("Twelve years in general practice.");
    expect(projected.clinic_name).toBe("Sharma Clinic");
    expect(projected.languages).toEqual(["English", "Hindi"]);
    expect(projected.consulting_hours).toBe("9am-5pm");
    expect(projected.experience_years).toBe(12);
    expect(projected.address_line).toBeNull();
    expect(projected.landmark).toBeNull();
    expect(projected.city).toBe("Daltonganj");
    expect(projected.pin_code).toBe("826001");
  });

  it("lets a keystroke reach the declared fields the publishing cards own", () => {
    // The other half of the split above, stated as its own assertion: the draft
    // really does drive the declared band for the sections that publish. A preview
    // that ignored these would be claiming to be live about the two cards a doctor
    // is most likely to be editing while they watch it.
    const projected = projectPublicProfile(
      view(),
      draft({
        practice: {
          practiceName: "Asha R. Verma",
          specialties: ["Pediatrician"],
        },
        address: { locality: "Medininagar" },
      }),
    );

    expect(projected.specialties).toEqual(["Pediatrician"]);
    expect(projected.locality).toBe("Medininagar");
    expect(projected.area).toBe("Medininagar");
    // The representative the narrow surfaces read still comes from the same
    // selection's first member, so the hero and the band cannot disagree.
    expect(projected.specialty).toBe("Pediatrician");
    // And the saved facts did not move, because nobody edited them.
    expect(projected.clinic_name).toBe("Sharma Clinic");
  });

  it("keeps the declared band out of reach of every derived marker", () => {
    // Nothing in the band may be read as, or promoted into, a verification. The
    // projection has exactly one verified field and it comes from the API answer;
    // a doctor who declares twelve years of experience does not become verified,
    // because nobody checked those twelve years.
    const projected = projectPublicProfile(
      view({ verified: false, experience_years: 12, about: "Twelve years." }),
      draft(),
    );

    expect(projected.verified).toBe(false);
    expect(projected.experience_years).toBe(12);
  });
});
