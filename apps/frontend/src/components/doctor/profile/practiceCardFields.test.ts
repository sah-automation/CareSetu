// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
import { describe, expect, it } from "vitest";

import type { DoctorProfileView } from "@/lib/doctor/api";

import {
  invalidPracticeFields,
  practiceFromProfile,
  practiceUpdateFromFields,
  PRACTICE_LIMITS,
  type PracticeFields,
} from "./practiceCardFields";

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 1,
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    clinic_name: "Sunrise Building",
    specialties: ["General Physician", "Dentist"],
    verified: true,
    practice_address: "Main Road, Daltonganj",
    address_line: null,
    landmark: null,
    locality: null,
    city: null,
    pin_code: "822001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: null,
    languages: ["Hindi", "English"],
    experience_years: 12,
    about: "Twelve years of primary care.",
    consultation_fee: null,
    consulting_days: ["Monday", "Saturday"],
    consulting_hours: "Mon-Sat mornings",
    credentials: [],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

function practice(overrides: Partial<PracticeFields> = {}): PracticeFields {
  return { ...practiceFromProfile(profile()), ...overrides };
}

describe("the Practice slice", () => {
  it("seeds the name, the clinic, the selection and the years", () => {
    expect(practiceFromProfile(profile())).toEqual({
      full_name: "Sunrise Clinic",
      clinic_name: "Sunrise Building",
      specialties: ["General Physician", "Dentist"],
      experience_years: "12",
    });
  });

  it("seeds a null name and null years as empty, not as a claim", () => {
    const seeded = practiceFromProfile(
      profile({
        practice_name: null,
        clinic_name: null,
        experience_years: null,
      }),
    );

    // 0 years is a claim about a doctor's career; blank is "not said".
    expect(seeded.full_name).toBe("");
    expect(seeded.clinic_name).toBe("");
    expect(seeded.experience_years).toBe("");
  });

  it("narrows a stored specialty it has no chip for, so the save cannot 422", () => {
    const seeded = practiceFromProfile(
      profile({ specialties: ["Dentist", "Retired Specialty"] }),
    );

    expect(seeded.specialties).toEqual(["Dentist"]);
  });

  it("omits a blank clinic name rather than sending an empty string", () => {
    expect(
      practiceUpdateFromFields(practice({ clinic_name: "   " })).clinic_name,
    ).toBeNull();
  });

  it("sends a cleared years field as null", () => {
    expect(
      practiceUpdateFromFields(practice({ experience_years: "" })),
    ).toMatchObject({ experience_years: null });
  });

  it("refuses a blank name, and says so in one sentence", () => {
    expect(invalidPracticeFields(practice({ full_name: "  " }))).toEqual([
      "full_name",
    ]);
  });

  it("refuses a name and a clinic name over their own bounds", () => {
    expect(
      invalidPracticeFields(
        practice({
          full_name: "x".repeat(PRACTICE_LIMITS.fullName + 1),
          clinic_name: "y".repeat(PRACTICE_LIMITS.clinicName + 1),
        }),
      ),
    ).toEqual(["full_name", "clinic_name"]);
  });

  it("refuses years that are not a whole number inside #606's bound", () => {
    // Non-integer, below, and above are three answers to one question, and the
    // bound is the database's own CHECK rather than a number this surface invented.
    expect(
      invalidPracticeFields(practice({ experience_years: "12.5" })),
    ).toEqual(["experience_years"]);
    expect(invalidPracticeFields(practice({ experience_years: "-1" }))).toEqual(
      ["experience_years"],
    );
    expect(invalidPracticeFields(practice({ experience_years: "61" }))).toEqual(
      ["experience_years"],
    );
    expect(invalidPracticeFields(practice({ experience_years: "60" }))).toEqual(
      [],
    );
    expect(invalidPracticeFields(practice({ experience_years: "0" }))).toEqual(
      [],
    );
  });

  it("names every field it can refuse, in DOM order", () => {
    // The summary counts them and the focus walk takes the first, so the order is
    // the order the controls appear in rather than the order the rules run.
    expect(
      invalidPracticeFields(
        practice({
          full_name: "",
          clinic_name: "y".repeat(PRACTICE_LIMITS.clinicName + 1),
          experience_years: "61",
        }),
      ),
    ).toEqual(["full_name", "clinic_name", "experience_years"]);
  });

  it("has no rule about the specialties, because a chip cannot break one", () => {
    // The only way to change the selection is to tap a member of the closed list,
    // so a validation rule here could only fire on a bug in this module.
    expect(invalidPracticeFields(practice({ specialties: [] }))).toEqual([]);
  });
});
