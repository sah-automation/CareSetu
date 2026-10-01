import { describe, expect, it } from "vitest";

import type { DoctorProfileView } from "@/lib/doctor/api";

import {
  ABOUT_LIMITS,
  aboutFromProfile,
  aboutUpdateFromFields,
  invalidAboutFields,
  type AboutFields,
} from "./aboutCardFields";

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 1,
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    clinic_name: "Sunrise Building",
    specialties: ["General Physician"],
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
    consulting_hours: "Mon-Sat mornings, Sat evening clinic after 5",
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

function about(overrides: Partial<AboutFields> = {}): AboutFields {
  return { ...aboutFromProfile(profile()), ...overrides };
}

describe("the About slice", () => {
  it("seeds the prose, both closed selections and the hours", () => {
    expect(aboutFromProfile(profile())).toEqual({
      about: "Twelve years of primary care.",
      languages: ["Hindi", "English"],
      consulting_days: ["Monday", "Saturday"],
      consulting_hours: "Mon-Sat mornings, Sat evening clinic after 5",
    });
  });

  it("sends every field, including the two nullable ones, because the model requires them", () => {
    const body = aboutUpdateFromFields(
      about({ about: "  ", consulting_hours: "" }),
    );

    // `about: null` is how a doctor clears it DELIBERATELY. Omitting the key
    // instead is what #610's model exists to prevent: a client that forgot a field
    // would silently CLEAR the column and the save would still report success.
    expect(body).toEqual({
      about: null,
      languages: ["Hindi", "English"],
      consulting_days: ["Monday", "Saturday"],
      consulting_hours: null,
    });
    expect("about" in body).toBe(true);
    expect("consulting_hours" in body).toBe(true);
  });

  it("copies the selections rather than aliasing the buffer's own arrays", () => {
    const fields = about();
    const body = aboutUpdateFromFields(fields);
    body.languages.push("English" as never);

    // The body is JSON-stringified straight after this, so an alias would let a
    // later edit mutate a request that has already been described as sent.
    expect(fields.languages).toEqual(["Hindi", "English"]);
  });

  it("keeps the hours as prose, byte for byte", () => {
    // Trimmed at the edges and otherwise untouched: no template, no per-day ranges,
    // no slots, because the platform has no booking system.
    expect(
      aboutUpdateFromFields(about({ consulting_hours: "  Mon-Sat mornings  " }))
        .consulting_hours,
    ).toBe("Mon-Sat mornings");
  });

  it("refuses prose over its own bound and nothing else", () => {
    expect(
      invalidAboutFields(about({ about: "x".repeat(ABOUT_LIMITS.about + 1) })),
    ).toEqual(["about"]);
    expect(
      invalidAboutFields(
        about({
          consulting_hours: "y".repeat(ABOUT_LIMITS.consultingHours + 1),
        }),
      ),
    ).toEqual(["consulting_hours"]);
  });

  it("has no rule about the languages or the days", () => {
    // Both are closed selections; an empty one is a state a doctor can hold.
    expect(
      invalidAboutFields(about({ languages: [], consulting_days: [] })),
    ).toEqual([]);
  });
});
