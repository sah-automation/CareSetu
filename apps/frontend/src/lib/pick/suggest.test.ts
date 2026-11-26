// PHASE-8.1 T11 (#449): suggested-specialty derivation from structured
// symptoms (US-2/US-3). The suggestion is a start-here filter, never a
// verdict - the pick page still offers every specialty chip. Priority:
// child > dental > pregnancy/menstrual > General Physician default.

import { describe, expect, it } from "vitest";

import type { StructuredFields } from "@/lib/intake/api";
import { deriveSpecialtyFromSymptoms } from "./suggest";

function fields(overrides: Partial<StructuredFields> = {}): StructuredFields {
  return {
    chief_complaints: [],
    symptoms: [],
    duration: null,
    ...overrides,
  };
}

describe("deriveSpecialtyFromSymptoms", () => {
  it("suggests Pediatrician for child symptoms", () => {
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ symptoms: ["child has fever since 2 days"] }),
      ),
    ).toBe("Pediatrician");
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ chief_complaints: ["baby not eating"] }),
      ),
    ).toBe("Pediatrician");
  });

  it("suggests Pediatrician before dental/gyn when both match (child priority)", () => {
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ symptoms: ["child has toothache"] }),
      ),
    ).toBe("Pediatrician");
  });

  it("suggests Dentist for dental symptoms", () => {
    expect(
      deriveSpecialtyFromSymptoms(fields({ symptoms: ["toothache"] })),
    ).toBe("Dentist");
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ chief_complaints: ["pain in teeth"] }),
      ),
    ).toBe("Dentist");
  });

  it("suggests Gynecologist for pregnancy and menstrual symptoms", () => {
    expect(
      deriveSpecialtyFromSymptoms(fields({ symptoms: ["irregular periods"] })),
    ).toBe("Gynecologist");
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ chief_complaints: ["pregnant, need checkup"] }),
      ),
    ).toBe("Gynecologist");
  });

  it("defaults to General Physician for unrelated symptoms", () => {
    expect(
      deriveSpecialtyFromSymptoms(fields({ symptoms: ["cough", "cold"] })),
    ).toBe("General Physician");
    expect(
      deriveSpecialtyFromSymptoms(fields({ chief_complaints: ["fever"] })),
    ).toBe("General Physician");
  });

  it("joins chief complaints and symptoms before matching", () => {
    expect(
      deriveSpecialtyFromSymptoms(
        fields({ chief_complaints: ["child"], symptoms: ["sore throat"] }),
      ),
    ).toBe("Pediatrician");
  });

  it("returns a suggestion (General Physician) even with empty fields", () => {
    expect(deriveSpecialtyFromSymptoms(fields({}))).toBe("General Physician");
  });
});
