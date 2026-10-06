// FEAT-008 / #651 AC-4: the shared stage-chip tone + label map. One map for
// both doctor lists, so a stage looks the same wherever it appears; the
// three-way split mirrors the cases index's existing mapping.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";

import { STAGE_CHIPS, stageChipView } from "./stageChip";

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;

describe("STAGE_CHIPS", () => {
  it("maps the three known stages to distinct tones (#651 AC-4)", () => {
    expect(STAGE_CHIPS.pre_summary.tone).toBe("bg-warn-soft text-warn-text");
    expect(STAGE_CHIPS.prescription_pending.tone).toBe(
      "bg-accent-soft text-accent-strong",
    );
    expect(STAGE_CHIPS.closed.tone).toBe("bg-hairline-soft text-txt-muted");

    const tones = new Set(Object.values(STAGE_CHIPS).map((chip) => chip.tone));
    expect(tones.size).toBe(3);
  });

  it("gives each known stage a label key so labels come from the dictionary", () => {
    expect(STAGE_CHIPS.pre_summary.labelKey).toBe("stagePreSummary");
    expect(STAGE_CHIPS.prescription_pending.labelKey).toBe(
      "stagePrescriptionPending",
    );
    expect(STAGE_CHIPS.closed.labelKey).toBe("stageClosed");
  });
});

describe("stageChipView", () => {
  it("returns label + tone from the map in the active locale", () => {
    expect(stageChipView("pre_summary", t)).toEqual({
      label: t.stagePreSummary,
      tone: "bg-warn-soft text-warn-text",
    });
    expect(stageChipView("closed", t)).toEqual({
      label: t.stageClosed,
      tone: "bg-hairline-soft text-txt-muted",
    });
    expect(stageChipView("pre_summary", hiT).label).toBe(hiT.stagePreSummary);
  });

  it("falls back to a muted chip that renders an unknown stage as itself", () => {
    expect(stageChipView("something_new", t)).toEqual({
      label: "something_new",
      tone: "bg-hairline-soft text-txt-muted",
    });
  });
});
