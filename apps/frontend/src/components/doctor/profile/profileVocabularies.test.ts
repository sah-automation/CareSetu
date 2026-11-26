// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// @vitest-environment node

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";

import {
  CONSULTING_DAYS,
  CONSULT_LANGUAGES,
  knownMembers,
  SPECIALTIES,
  specialtiesFromProfile,
  vocabularySlug,
  type ProfileSpecialty,
} from "./profileVocabularies";
import { NOTIFICATION_KEYS } from "./notificationCardFields";
import type { DoctorProfileView } from "@/lib/doctor/api";

// The three closed vocabularies are DOMAIN lists (#602), and this file's whole
// reason for existing is that a list the client cannot see is a list whose
// members a doctor guesses at. A frontend copy of a domain list is therefore a
// promise that can rot silently: add a specialty to the backend and this page
// goes on refusing to offer it, with nothing failing. So the FIRST assertion here
// reads the backend source and checks the two agree - the one direction that can
// be checked from TypeScript, since the browser cannot import Python.

const BACKEND_SOURCE = fileURLToPath(
  new URL(
    "../../../../../backend/modules/partner/domain/vocabularies.py",
    import.meta.url,
  ),
);

/** The members of one `StrEnum` in the backend, as their wire values. */
function backendEnumValues(enumName: string): string[] {
  const source = readFileSync(BACKEND_SOURCE, "utf8");
  const body = new RegExp(
    `class ${enumName}\\(StrEnum\\):\\n([\\s\\S]*?)(?=\\n\\n|\\nclass |\\n_)`,
  ).exec(source);
  if (body?.[1] == null) {
    throw new Error(`${enumName} is not a StrEnum in vocabularies.py`);
  }
  const values = [...body[1].matchAll(/=\s*"([^"]+)"/g)].map(
    (match) => match[1],
  );
  // Every member of a domain enum is a wire value, and the docstrings in that file
  // contain `#:` prose rather than assignments, so an empty read is a parse that
  // found the class and lost it - which must fail loudly rather than pass as
  // "the two lists agree because one is empty".
  if (values.length === 0) {
    throw new Error(`${enumName} parsed to zero members in vocabularies.py`);
  }
  return values;
}

describe("the closed vocabularies stay in step with the domain", () => {
  it("offers exactly the specialties #602 declares", () => {
    expect([...SPECIALTIES]).toEqual(backendEnumValues("Specialty"));
  });

  it("offers exactly the consulting languages #602 declares", () => {
    expect([...CONSULT_LANGUAGES]).toEqual(
      backendEnumValues("ConsultLanguage"),
    );
  });

  it("offers exactly the consulting days #602 declares", () => {
    expect([...CONSULTING_DAYS]).toEqual(backendEnumValues("ConsultingDay"));
  });

  // #610 moved the owning copy of these five to the backend, so the pair can now
  // drift the same way the other three can. Before #610 this direction was
  // uncheckable, which is precisely why the server's copy had to exist.
  it("renders exactly the notification keys #610 declares", () => {
    expect([...NOTIFICATION_KEYS]).toEqual(
      backendEnumValues("NotificationPreferenceKey"),
    );
  });
});

describe("both locales label every member", () => {
  const cases: [string, readonly string[], Record<string, string>][] = [
    ["specialties", SPECIALTIES, STRINGS.en.doctorProfile.specialtyLabels],
    ["languages", CONSULT_LANGUAGES, STRINGS.en.doctorProfile.languageLabels],
    ["days", CONSULTING_DAYS, STRINGS.en.doctorProfile.dayLabels],
  ];

  for (const [name, vocabulary, labels] of cases) {
    it(`labels all ${vocabulary.length} ${name} in English`, () => {
      expect(Object.keys(labels).sort()).toEqual([...vocabulary].sort());
    });
  }

  // Parity is the mechanical half; this is the half that catches a label written
  // as the English value pasted into the Hindi map, which no key-set comparison
  // can see and which ships a doctor a chip labelled "General Physician" in a
  // Hindi page.
  it("gives every Hindi label real Hindi copy rather than the wire value", () => {
    const hi = STRINGS.hi.doctorProfile;
    for (const [name, vocabulary] of [
      ["specialty", SPECIALTIES],
      ["language", CONSULT_LANGUAGES],
      ["day", CONSULTING_DAYS],
    ] as const) {
      const labels =
        name === "specialty"
          ? hi.specialtyLabels
          : name === "language"
            ? hi.languageLabels
            : hi.dayLabels;
      for (const value of vocabulary) {
        expect(
          labels[value as keyof typeof labels],
          `${name} label for ${value}`,
        ).not.toBe(value);
      }
    }
  });
});

describe("knownMembers", () => {
  it("keeps declared order and drops what it has no chip for", () => {
    const selection: ProfileSpecialty[] = knownMembers<ProfileSpecialty>(
      ["Dentist", "Ayurvedic Practitioner"],
      SPECIALTIES,
    );

    // Order is what the stored selection and every later membership match read,
    // so a narrowing that sorted or reversed would change what a save writes.
    expect(selection).toEqual(["Dentist", "Ayurvedic Practitioner"]);
  });

  it("returns an empty selection rather than inventing a default member", () => {
    // #602 returns an empty tuple for an empty selection: a doctor who has not
    // decided their days yet is not making a mistake.
    expect(knownMembers([], CONSULTING_DAYS)).toEqual([]);
  });

  it("seeds a stored value the vocabulary does not know out of the selection", () => {
    const profile = {
      languages: ["Hindi", "Klingon", "English"],
    } as unknown as DoctorProfileView;

    // An unknown value has no chip and no label, so keeping it would render an
    // unlabelled chip or 422 the save; dropping it here is the declared outcome.
    expect(knownMembers(profile.languages, CONSULT_LANGUAGES)).toEqual([
      "Hindi",
      "English",
    ]);
  });

  it("does not mutate the array it was handed", () => {
    const stored = ["Hindi", "Klingon"];
    knownMembers(stored, CONSULT_LANGUAGES);

    // The projection's own array, which the source still holds and every other
    // section reads from it.
    expect(stored).toEqual(["Hindi", "Klingon"]);
  });
});

describe("specialtiesFromProfile", () => {
  it("narrows the projection's own selection to the renderable members", () => {
    const profile = {
      specialties: ["Pediatrician", "Retired Specialty"],
    } as unknown as DoctorProfileView;

    expect(specialtiesFromProfile(profile)).toEqual(["Pediatrician"]);
  });
});

describe("vocabularySlug", () => {
  it("is stable across both locales because it reads the machine value", () => {
    // A chip's accessible name is its label, which differs per locale; the slug is
    // how a test finds a chip without knowing what it is called.
    expect(vocabularySlug("General Physician")).toBe("general-physician");
    expect(vocabularySlug("ENT Specialist")).toBe("ent-specialist");
    expect(vocabularySlug("Ayurvedic Practitioner")).toBe(
      "ayurvedic-practitioner",
    );
  });

  it("produces a slug for every member, with no empties to collide", () => {
    const all: readonly string[] = [
      ...SPECIALTIES,
      ...CONSULT_LANGUAGES,
      ...CONSULTING_DAYS,
    ];
    const slugs = all.map(vocabularySlug);

    // Two members sharing a slug would make one chip's test hook name the other,
    // and the failure would look like a selection bug rather than a naming one.
    expect(new Set(slugs).size).toBe(slugs.length);
    expect(slugs.every((slug) => slug.length > 0)).toBe(true);
  });
});
