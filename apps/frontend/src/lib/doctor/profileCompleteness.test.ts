// #678: focused unit suite for profileCompleteness, the shared projection
// behind the dashboard's profile-status card and getting-started checklist.

import { describe, expect, it } from "vitest";

import type { DoctorProfileView } from "@/lib/doctor/api";
import { profileCompleteness } from "./profileCompleteness";

function view(overrides: Partial<DoctorProfileView> = {}): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: "doctor/7/photo-1.enc",
    practice_name: "Dr. Anil Kumar",
    clinic_name: null,
    specialties: [],
    verified: false,
    practice_address: "Main Road, Daltonganj",
    address_line: "Main Road, Daltonganj",
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "822001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["Hindi", "English"],
    experience_years: null,
    about: null,
    consultation_fee: null,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

describe("profileCompleteness (#678)", () => {
  it("reports every field missing on an empty profile", () => {
    expect(profileCompleteness(view())).toEqual({
      verified: false,
      fee: false,
      about: false,
      clinic: false,
    });
  });

  it("reports each field present when the profile has it", () => {
    const profile = view({
      verified: true,
      consultation_fee: 500,
      about: "  General physician with 10 years in practice.  ",
      clinic_name: "Sunrise Clinic",
    });
    expect(profileCompleteness(profile)).toEqual({
      verified: true,
      fee: true,
      about: true,
      clinic: true,
    });
  });

  it("treats whitespace-only free text as missing", () => {
    const profile = view({ about: "   ", clinic_name: " " });
    expect(profileCompleteness(profile).about).toBe(false);
    expect(profileCompleteness(profile).clinic).toBe(false);
  });
});
