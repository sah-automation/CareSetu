// #531 AC "a valid value in EVERY record-scope surface" + #534: the
// `health_background` record scope must be nameable by the patient client and
// resolvable through the typed EN/HI dictionary in every surface that renders a
// scope. The scope list below is typed as the closed union
// `GrantConsentRequest["record_scope"]`, so a value the union does not carry
// fails `tsc` here - a scope cannot quietly go missing from the wire type while
// every label map still looks complete.

import { describe, expect, it } from "vitest";

import type { GrantConsentRequest } from "./api";
import { STRINGS } from "../i18n/dictionaries";

type RecordScope = GrantConsentRequest["record_scope"];

const RECORD_SCOPES: readonly RecordScope[] = [
  "consultations",
  "prescriptions",
  "lab_results",
  "metrics",
  "health_background",
  "full_record",
];

const SCOPE_LABEL_SURFACES = [
  {
    name: "profileZones.scopeLabels (patient Settings consent list)",
    en: STRINGS.en.profileZones.scopeLabels,
    hi: STRINGS.hi.profileZones.scopeLabels,
  },
  {
    name: "doctorPatients.scopeBadge (doctor patient-detail section)",
    en: STRINGS.en.doctorPatients.scopeBadge,
    hi: STRINGS.hi.doctorPatients.scopeBadge,
  },
] as const;

describe("record-scope surface coverage (#531, #534)", () => {
  it("the grant request union carries health_background", () => {
    // Compile-time: a value outside the union would not typecheck above.
    const healthBackground: RecordScope = "health_background";
    expect(RECORD_SCOPES).toContain(healthBackground);
  });

  it.each(SCOPE_LABEL_SURFACES)(
    "$name labels every scope in both locales",
    ({ en, hi }) => {
      for (const scope of RECORD_SCOPES) {
        expect(en[scope], `en label for ${scope}`).toBeTruthy();
        expect(hi[scope], `hi label for ${scope}`).toBeTruthy();
      }
    },
  );

  it("health_background reads as its own label, not as the full record", () => {
    for (const { en, hi } of SCOPE_LABEL_SURFACES) {
      expect(en.health_background).not.toBe(en.full_record);
      expect(hi.health_background).not.toBe(hi.full_record);
      // A real translation, not the raw snake_case token echoed back.
      expect(en.health_background).not.toBe("health_background");
      expect(hi.health_background).not.toBe("health_background");
    }
  });

  it("the two locales do not silently share one label", () => {
    for (const { name, en, hi } of SCOPE_LABEL_SURFACES) {
      for (const scope of RECORD_SCOPES) {
        expect(hi[scope], `${name} hi label for ${scope}`).not.toBe(en[scope]);
      }
    }
  });
});
