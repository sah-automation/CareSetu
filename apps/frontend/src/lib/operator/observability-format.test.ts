// #709 C2b: the Observability console's shared figure formatters. The C2a
// overview page and all four C2b panels render rates, durations and rupees
// through these, so the two rules they encode are pinned once here.

import { describe, expect, it } from "vitest";

import {
  DASH,
  formatDuration,
  formatMoney,
  formatPct,
  formatUnitCost,
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

// #737: a unit cost is a RATE, not a price. `formatMoney` is right for a bill -
// every CareSetu price is a whole-rupee amount - and wrong here: AI costs about
// 10 paise per request, so the whole-rupee formatter reports "₹10" for 10.42.
// The last case below is the limit this admits, stated rather than papered over.
describe("formatUnitCost", () => {
  it("keeps paise precision the whole-rupee price formatter drops", () => {
    expect(formatUnitCost(1041.6667)).toBe("₹10.42");
    expect(formatUnitCost(1096.4912)).toBe("₹10.96");
    expect(formatUnitCost(2500000)).toBe("₹25,000.00");
  });

  it("shows a sub-rupee cost as a fraction, where the price rule showed nothing", () => {
    // 40 paise is ₹0.40: the whole-rupee rule renders that as "₹0", which reads
    // as free. Two decimals is as fine as the currency goes - a cost below one
    // paisa still reads as "₹0.00", which is the formatter's documented limit.
    expect(formatUnitCost(40)).toBe("₹0.40");
    expect(formatUnitCost(40)).not.toBe(formatMoney(40));
    expect(formatUnitCost(0.4)).toBe("₹0.00");
  });
});
