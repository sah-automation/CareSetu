// #623 (FEAT-004, FEAT-005): the frontend's specialty vocabulary cannot drift
// from the backend's, and neither can the labels.
//
// The defect this pins: `DIRECTORIES_SPECIALTIES` listed four of the backend's
// twenty, three components each carried a private four-entry map from a
// specialty value to a camelCase dictionary key, and the pick-a-doctor page
// labelled any specialty outside those four as "General Physician" - so a
// cardiologist was displayed to a patient as a general physician, which is not
// a missing translation but wrong information.
//
// A frontend cannot import a Python enum, so the twenty values are restated
// here. This test is what makes the restatement safe: it reads the backend
// source, so adding a twenty-first `Specialty` member without updating the
// frontend fails the suite instead of shipping another unreachable value.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { DIRECTORIES_SPECIALTIES } from "@/lib/directory/search";
import { specialtyLabel } from "@/lib/directory/specialtyLabel";

const BACKEND_VOCABULARIES = join(
  process.cwd(),
  "..",
  "..",
  "apps",
  "backend",
  "modules",
  "partner",
  "domain",
  "vocabularies.py",
);

/** The twenty values of `class Specialty(StrEnum)`, read off the source. */
function backendSpecialties(): string[] {
  const source = readFileSync(BACKEND_VOCABULARIES, "utf8");
  const body = source
    .split("class Specialty(StrEnum):")[1]
    ?.split("\nclass ")[0];
  expect(body, "the Specialty StrEnum moved or was renamed").toBeDefined();
  return [...(body ?? "").matchAll(/= "([^"]+)"/g)].map((match) => match[1]);
}

describe("frontend/backend specialty vocabulary parity (#623, FEAT-004)", () => {
  it("offers every specialty the backend accepts", () => {
    expect([...DIRECTORIES_SPECIALTIES].sort()).toEqual(
      backendSpecialties().sort(),
    );
  });

  it("carries no duplicate values", () => {
    expect(new Set(DIRECTORIES_SPECIALTIES).size).toBe(
      DIRECTORIES_SPECIALTIES.length,
    );
  });
});

describe("every offered specialty has a label in every locale (#623)", () => {
  it("labels all twenty in English", () => {
    const missing = DIRECTORIES_SPECIALTIES.filter(
      (value) => !(value in STRINGS.en.doctorProfile.specialtyLabels),
    );
    expect(missing).toEqual([]);
  });

  it("labels all twenty in Hindi", () => {
    const missing = DIRECTORIES_SPECIALTIES.filter(
      (value) => !(value in STRINGS.hi.doctorProfile.specialtyLabels),
    );
    expect(missing).toEqual([]);
  });

  it("translates rather than echoes the domain value in Hindi", () => {
    // Identity is correct for a proper noun that is the same in both languages
    // and for the two languages that share orthography; the check is that the
    // map is a real translation table, not a copy of the English block, so a
    // bulk-added row of `value: value` would fail.
    const identical = DIRECTORIES_SPECIALTIES.filter(
      (value) =>
        STRINGS.hi.doctorProfile.specialtyLabels[value] ===
        STRINGS.en.doctorProfile.specialtyLabels[value],
    );
    expect(identical).toEqual([]);
  });

  it("falls back to the raw value for a specialty added after this locale shipped", () => {
    // An unknown value must still render: a doctor declared in a new specialty
    // has to stay findable and legible, and echoing the domain value is the
    // honest rendering of that state.
    expect(specialtyLabel("hi", "Ophthalmologist")).toBe("नेत्र चिकित्सक");
    expect(specialtyLabel("en", "Neuro-Oncologist")).toBe("Neuro-Oncologist");
  });
});
