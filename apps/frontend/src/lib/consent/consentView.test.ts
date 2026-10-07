// #653: the counterparty label's three-step fallback - the first direct suite
// for consentView, whose step ordering can silently regress: a type-derived
// word reached before the AI id check would label the AI intake row (recorded
// under the doctor type) as a clinician's.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";

import {
  AI_EGRESS_COUNTERPARTY_ID,
  counterpartyInitials,
  counterpartyLabel,
  counterpartyRole,
} from "./consentView";

const en = STRINGS.en.consentLog.counterparty;
const hi = STRINGS.hi.consentLog.counterparty;

const RECORDED_TYPES = ["doctor", "lab", "chemist"] as const;

describe("counterpartyLabel - step one: the resolved display name", () => {
  it("returns the backend-resolved name ahead of type and id", () => {
    expect(counterpartyLabel("doctor", "dv_123", "Dr A Kumar")).toBe(
      "Dr A Kumar",
    );
    expect(counterpartyLabel("lab", "lb_9", "Sunrise Labs")).toBe(
      "Sunrise Labs",
    );
    expect(counterpartyLabel("chemist", "ph_4", "City Pharmacy")).toBe(
      "City Pharmacy",
    );
  });

  // FEAT-002 (#653/#661): the AI id check ahead of the display name is what
  // makes the backend's English brand render bilingually.
  it("keeps the AI pseudo-counterparty on the dictionary brand, whatever display name is attached", () => {
    // The backend resolves intake-ai to the ENGLISH brand (#649); the id
    // check ahead of the display name is what makes that brand bilingual.
    // EN output is identical either way because the wire value equals the
    // English dictionary entry - pinned by the parity test below.
    expect(
      counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID, "Dr A Kumar"),
    ).toBe(en.aiService);
    expect(
      counterpartyLabel(
        "doctor",
        AI_EGRESS_COUNTERPARTY_ID,
        "CareSetu AI Intake Assistant",
        "hi",
      ),
    ).toBe(hi.aiService);
  });

  // FEAT-002: the brand ships in both locales pinned to literals, so the
  // EN+HI requirement cannot regress to a key-presence check alone.
  it("ships the brand identical to the backend wire value, in EN and HI", () => {
    // Cross-tier parity (#661): app.main's AI_INTAKE_COUNTERPARTY_DISPLAY_NAME
    // is pinned to this literal in the backend binding test, so equality here
    // holds both tiers to one brand string.
    expect(en.aiService).toBe("CareSetu AI Intake Assistant");
    expect(hi.aiService).toBe("CareSetu AI इंटेक सहायक");
  });

  it("falls through to step two when the name is absent or empty", () => {
    expect(counterpartyLabel("doctor", "dv_1", null)).toBe(en.doctor);
    expect(counterpartyLabel("doctor", "dv_1", undefined)).toBe(en.doctor);
    expect(counterpartyLabel("doctor", "dv_1", "")).toBe(en.doctor);
  });
});

describe("counterpartyLabel - step two: the type-derived word", () => {
  it("names each counterparty type the product records, in words", () => {
    expect(counterpartyLabel("doctor", "dv_1")).toBe(en.doctor);
    expect(counterpartyLabel("lab", "lb_1")).toBe(en.lab);
    expect(counterpartyLabel("chemist", "ph_1")).toBe(en.chemist);
  });

  it("ships the same words in Hindi", () => {
    expect(counterpartyLabel("doctor", "dv_1", null, "hi")).toBe(hi.doctor);
    expect(counterpartyLabel("lab", "lb_1", null, "hi")).toBe(hi.lab);
    expect(counterpartyLabel("chemist", "ph_1", null, "hi")).toBe(hi.chemist);
  });

  it("reads the AI intake pseudo-counterparty as the branded service, never as a doctor", () => {
    expect(counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID)).toBe(
      en.aiService,
    );
    expect(counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID)).not.toBe(
      en.doctor,
    );
    expect(
      counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID, null, "hi"),
    ).toBe(hi.aiService);
    expect(
      counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID, null, "hi"),
    ).not.toBe(hi.doctor);
  });

  it("checks the AI id before every type branch, whatever type it was recorded under", () => {
    for (const type of RECORDED_TYPES) {
      expect(counterpartyLabel(type, AI_EGRESS_COUNTERPARTY_ID)).toBe(
        en.aiService,
      );
    }
  });
});

describe("counterpartyLabel - step three: the raw id as last resort", () => {
  it("returns the id only when both the name and the type are absent", () => {
    expect(counterpartyLabel("partner", "pt_abc")).toBe("pt_abc");
    expect(counterpartyLabel("partner", "pt_abc", null, "hi")).toBe("pt_abc");
  });

  it("keeps a non-empty id ahead of the counterparty type", () => {
    expect(counterpartyLabel("partner", "")).toBe("partner");
  });

  it("never lets a counterparty type the product records fall through to the id", () => {
    for (const type of RECORDED_TYPES) {
      const label = counterpartyLabel(type, "opaque-id-9999");
      expect(label).not.toBe("opaque-id-9999");
      expect(label).not.toBe(type);
    }
    expect(counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID)).not.toBe(
      AI_EGRESS_COUNTERPARTY_ID,
    );
  });
});

describe("counterpartyRole - the role in words beside the name (#654)", () => {
  it("names each counterparty type the product records, in words", () => {
    expect(counterpartyRole("doctor", "dv_1")).toBe(en.doctor);
    expect(counterpartyRole("lab", "lb_1")).toBe(en.lab);
    expect(counterpartyRole("chemist", "ph_1")).toBe(en.chemist);
  });

  it("ships the same words in Hindi", () => {
    expect(counterpartyRole("doctor", "dv_1", "hi")).toBe(hi.doctor);
    expect(counterpartyRole("lab", "lb_1", "hi")).toBe(hi.lab);
    expect(counterpartyRole("chemist", "ph_1", "hi")).toBe(hi.chemist);
  });

  it("reads the AI intake pseudo-counterparty as the AI, never as a doctor", () => {
    expect(counterpartyRole("doctor", AI_EGRESS_COUNTERPARTY_ID)).toBe(
      en.aiRole,
    );
    expect(counterpartyRole("doctor", AI_EGRESS_COUNTERPARTY_ID)).not.toBe(
      en.doctor,
    );
    expect(counterpartyRole("doctor", AI_EGRESS_COUNTERPARTY_ID, "hi")).toBe(
      hi.aiRole,
    );
    expect(
      counterpartyRole("doctor", AI_EGRESS_COUNTERPARTY_ID, "hi"),
    ).not.toBe(hi.doctor);
  });

  it("checks the AI id before every type branch, whatever type it was recorded under", () => {
    for (const type of RECORDED_TYPES) {
      expect(counterpartyRole(type, AI_EGRESS_COUNTERPARTY_ID)).toBe(en.aiRole);
    }
  });

  it("returns null for a counterparty type with no word of its own", () => {
    expect(counterpartyRole("partner", "pt_abc")).toBeNull();
    expect(counterpartyRole("partner", "pt_abc", "hi")).toBeNull();
  });

  it("stays the type's own word even when the label resolves to a name", () => {
    expect(counterpartyRole("doctor", "dv_123")).toBe(en.doctor);
    expect(counterpartyLabel("doctor", "dv_123", "Dr A Kumar")).toBe(
      "Dr A Kumar",
    );
  });
});

describe("counterpartyInitials", () => {
  it("derives from whatever the three-step chain produced", () => {
    expect(
      counterpartyInitials(counterpartyLabel("doctor", "dv_1", "Dr A Kumar")),
    ).toBe("DA");
    expect(counterpartyInitials(counterpartyLabel("doctor", "dv_1"))).toBe(
      "DO",
    );
    expect(counterpartyInitials(counterpartyLabel("lab", "lb_1"))).toBe("LA");
    expect(counterpartyInitials(counterpartyLabel("chemist", "ph_1"))).toBe(
      "PH",
    );
    expect(
      counterpartyInitials(
        counterpartyLabel("doctor", AI_EGRESS_COUNTERPARTY_ID),
      ),
    ).toBe("CA");
    expect(counterpartyInitials(counterpartyLabel("partner", "pt_abc"))).toBe(
      "PT",
    );
    expect(
      counterpartyInitials(counterpartyLabel("doctor", "dv_1", null, "hi")),
    ).toBe(counterpartyInitials(hi.doctor));
  });

  it("is unchanged: two words, one word, and padded labels", () => {
    expect(counterpartyInitials("Dr A Kumar")).toBe("DA");
    expect(counterpartyInitials("Doctor")).toBe("DO");
    expect(counterpartyInitials("  Lab Test  ")).toBe("LT");
    expect(counterpartyInitials(hi.aiService)).toBe("CA");
  });
});
