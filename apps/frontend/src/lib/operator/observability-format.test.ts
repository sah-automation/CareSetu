// #709 C2b: the Observability console's shared figure formatters. The C2a
// overview page and all four C2b panels render rates, durations and rupees
// through these, so the two rules they encode are pinned once here.

import { describe, expect, it } from "vitest";

import {
  DASH,
  formatDuration,
  formatMoney,
  formatPct,
  rupeesFromPaise,
} from "./observability-format";

describe("formatPct", () => {
  it("drops a trailing zero but keeps a real decimal", () => {
    expect(formatPct(95)).toBe("95%");
    expect(formatPct(2.6)).toBe("2.6%");
    expect(formatPct(99.96)).toBe("100%");
  });

  it("renders an unmeasured rate as an em dash, never as zero", () => {
    expect(formatPct(null)).toBe(DASH);
    expect(formatPct(null)).not.toBe("0%");
  });
});

describe("formatDuration", () => {
  it("reads in seconds past a second and whole milliseconds below that", () => {
    expect(formatDuration(4200)).toBe("4.2s");
    expect(formatDuration(900)).toBe("900ms");
    expect(formatDuration(1000)).toBe("1s");
  });

  it("renders an unmeasured duration as an em dash", () => {
    expect(formatDuration(null)).toBe(DASH);
  });
});

describe("money", () => {
  it("formats paise as whole rupees", () => {
    expect(formatMoney(125000)).toBe("₹1,250");
  });

  it("divides paise to rupees for a chart axis", () => {
    expect(rupeesFromPaise(125000)).toBe(1250);
    expect(rupeesFromPaise(0)).toBe(0);
  });
});
