// MOD-003 (FEAT-002 record / FEAT-018 metrics), #549: the health-background
// form's pure value handling (see form.ts). These are the two places the zone
// could quietly lose or invent a patient's own health data, so they are pinned
// on their own rather than only through the component: a blank textarea line
// must not become an empty list entry a doctor would read, and an implausible
// or unreadable measurement must be refused against the field it belongs to.

import { describe, expect, it } from "vitest";

import {
  BLOOD_GROUP_MAX_LENGTH,
  HEIGHT_CM_MAX,
  HEIGHT_CM_MIN,
  WEIGHT_KG_MAX,
  WEIGHT_KG_MIN,
  entriesToText,
  normalizeBloodGroup,
  parseMeasurement,
  textToEntries,
} from "./form";

describe("the entry-list round-trip", () => {
  it("renders a stored list as one entry per line", () => {
    expect(entriesToText(["Asthma", "Diabetes"])).toBe("Asthma\nDiabetes");
  });

  it("keeps a stored entry's own line order", () => {
    expect(textToEntries(entriesToText(["A", "B", "C"]))).toEqual([
      "A",
      "B",
      "C",
    ]);
  });

  it("drops blank lines instead of storing an empty entry", () => {
    // A doctor reading a blank bullet would take it as a real (if empty)
    // condition, so a trailing newline must not become a list item.
    expect(textToEntries("Asthma\n\n\n")).toEqual(["Asthma"]);
    expect(textToEntries("\n\n")).toEqual([]);
    expect(textToEntries("")).toEqual([]);
  });

  it("trims the padding a paste or a stray space leaves behind", () => {
    expect(textToEntries("  Asthma \n\t Diabetes  ")).toEqual([
      "Asthma",
      "Diabetes",
    ]);
  });

  it("round-trips an empty list without inventing an entry", () => {
    expect(textToEntries(entriesToText([]))).toEqual([]);
  });
});

describe("normalizeBloodGroup", () => {
  it("treats an untouched box as not recorded", () => {
    expect(normalizeBloodGroup("")).toBeNull();
    expect(normalizeBloodGroup("   ")).toBeNull();
  });

  it("keeps what the patient typed, trimmed", () => {
    expect(normalizeBloodGroup("  B+  ")).toBe("B+");
    expect(normalizeBloodGroup("O negative")).toBe("O negative");
  });

  it("caps the label at the length the API accepts", () => {
    const tooLong = "A".repeat(BLOOD_GROUP_MAX_LENGTH + 5);
    expect(normalizeBloodGroup(tooLong)).toHaveLength(BLOOD_GROUP_MAX_LENGTH);
  });
});

describe("parseMeasurement", () => {
  it("accepts both values and sends them as an instant", () => {
    const parsed = parseMeasurement({
      heightCm: "170",
      weightKg: "68.5",
      recordedAt: "2026-09-26T10:00",
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.heightCm).toBe(170);
    expect(parsed.value.weightKg).toBe(68.5);
    expect(Number.isNaN(Date.parse(parsed.value.recordedAt))).toBe(false);
  });

  it("accepts a weigh-in with no height", () => {
    const parsed = parseMeasurement({
      heightCm: "",
      weightKg: "68.5",
      recordedAt: "2026-09-26T10:00",
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.heightCm).toBeNull();
    expect(parsed.value.weightKg).toBe(68.5);
  });

  it("refuses a timestamp with neither value", () => {
    // The API rejects it, and a bare timestamp is not a measurement - so the
    // complaint is about the values, not about the date the patient did supply.
    const parsed = parseMeasurement({
      heightCm: "",
      weightKg: "  ",
      recordedAt: "2026-09-26T10:00",
    });

    expect(parsed).toEqual({
      ok: false,
      field: "values",
      reason: "value-required",
    });
  });

  it("refuses a height the API would reject, naming the height field", () => {
    expect(
      parseMeasurement({
        heightCm: "900",
        weightKg: "68.5",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "height", reason: "height-out-of-range" });

    expect(
      parseMeasurement({
        heightCm: "10",
        weightKg: "68.5",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "height", reason: "height-out-of-range" });
  });

  it("refuses a weight the API would reject, naming the weight field", () => {
    expect(
      parseMeasurement({
        heightCm: "170",
        weightKg: "0",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "weight", reason: "weight-out-of-range" });

    expect(
      parseMeasurement({
        heightCm: "170",
        weightKg: "900",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "weight", reason: "weight-out-of-range" });
  });

  it("accepts the exact bounds the API accepts, because its CHECKs are inclusive", () => {
    // One either side of the edge is the whole contract: an off-by-one here
    // would refuse a legitimate measurement, or accept one the API rejects,
    // and neither shows up in the out-of-range tests above.
    for (const heightCm of [String(HEIGHT_CM_MIN), String(HEIGHT_CM_MAX)]) {
      expect(
        parseMeasurement({
          heightCm,
          weightKg: "68.5",
          recordedAt: "2026-09-26T10:00",
        }),
      ).toMatchObject({ ok: true });
    }
    for (const weightKg of [String(WEIGHT_KG_MIN), String(WEIGHT_KG_MAX)]) {
      expect(
        parseMeasurement({
          heightCm: "170",
          weightKg,
          recordedAt: "2026-09-26T10:00",
        }),
      ).toMatchObject({ ok: true });
    }
  });

  it("refuses a value that is not a number, naming the box it is in", () => {
    // The dangerous case is a stray non-numeric value in ONE box while the
    // other is fine: treating it as "not recorded" would save the measurement
    // with that reading silently missing.
    expect(
      parseMeasurement({
        heightCm: "tall",
        weightKg: "68.5",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "height", reason: "value-not-a-number" });

    expect(
      parseMeasurement({
        heightCm: "170",
        weightKg: "heavy",
        recordedAt: "2026-09-26T10:00",
      }),
    ).toEqual({ ok: false, field: "weight", reason: "value-not-a-number" });
  });

  it("refuses a missing or unreadable measurement date", () => {
    expect(
      parseMeasurement({ heightCm: "170", weightKg: "", recordedAt: "" }),
    ).toEqual({
      ok: false,
      field: "recordedAt",
      reason: "recorded-at-required",
    });

    // A date the control could not have meant is a different mistake from a
    // missing one, so it gets its own complaint rather than the same message.
    expect(
      parseMeasurement({
        heightCm: "170",
        weightKg: "",
        recordedAt: "sometime last week",
      }),
    ).toEqual({
      ok: false,
      field: "recordedAt",
      reason: "recorded-at-invalid",
    });
  });
});
