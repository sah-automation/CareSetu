// #709 C2b: the Observability console's shared figure formatters. The C2a
// overview page and all four C2b panels render rates, durations and rupees
// through these, so the two rules they encode are pinned once here.

import { describe, expect, it } from "vitest";

import {
  DASH,
  formatAge,
  formatCount,
  formatDuration,
  formatMarginPercent,
  formatMoney,
  formatPct,
  formatRate,
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

// #738: the second percentage scale. The backend stores `success_rate` and
// `error_rate` as FRACTIONS - "0.8750" means 87.5% of calls succeeded - while
// `cap_consumed_pct` arrives already on the 0-100 scale. Two formatters, one per
// scale, so neither can be used for the other's field.
describe("formatRate", () => {
  it("scales a fraction the backend sent", () => {
    expect(formatRate(0.875)).toBe("87.5%");
    expect(formatRate(0.1818)).toBe("18.2%");
    expect(formatRate(1)).toBe("100%");
  });

  it("reads very differently from the percentage-scale formatter it must not be confused with", () => {
    // The failure this exists to prevent: a provider that is 87.5% healthy
    // reported as "0.9%".
    expect(formatRate(0.875)).not.toBe(formatPct(0.875));
    expect(formatPct(0.875)).toBe("0.9%");
  });

  it("renders an unmeasured rate as an em dash, never as zero", () => {
    expect(formatRate(null)).toBe(DASH);
    expect(formatRate(null)).not.toBe("0%");
  });
});

describe("formatCount", () => {
  it("groups in the console's own convention", () => {
    expect(formatCount(1234)).toBe("1,234");
    expect(formatCount(1200000)).toBe("12,00,000");
    expect(formatCount(0)).toBe("0");
  });
});

// #737: a margin percentage is either a figure or a REASON. The zero is the
// failure this exists to prevent: "0% gross margin" reads as "the AI costs
// nothing", which is a claim about the business, not a fact about the data.
describe("formatMarginPercent", () => {
  const REASONS = {
    revenueNotCaptured: "revenue not captured",
    revenueZero: "revenue was zero in this period",
  };

  it("prints the figure when there is one", () => {
    expect(
      formatMarginPercent({ value: 97.5, reason: null, detail: null }, REASONS),
    ).toBe("97.5%");
  });

  it("names the reason instead of printing a zero", () => {
    expect(
      formatMarginPercent(
        { value: null, reason: "revenue_not_captured", detail: null },
        REASONS,
      ),
    ).toBe("revenue not captured");
    expect(
      formatMarginPercent(
        { value: null, reason: "revenue_zero", detail: null },
        REASONS,
      ),
    ).toBe("revenue was zero in this period");
  });

  it("never prints a zero margin, whatever the read says", () => {
    for (const reason of ["revenue_not_captured", "revenue_zero"] as const) {
      expect(
        formatMarginPercent({ value: null, reason, detail: null }, REASONS),
      ).not.toBe("0%");
    }
  });

  it("falls back to the dash when there is neither a figure nor a reason", () => {
    expect(
      formatMarginPercent({ value: null, reason: null, detail: null }, REASONS),
    ).toBe(DASH);
  });
});

describe("formatAge", () => {
  const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

  it("reads in the operator queue's register", () => {
    expect(formatAge(ago(30_000))).toBe("< 1m");
    expect(formatAge(ago(5 * 60_000))).toBe("5m");
    expect(formatAge(ago(3 * 3_600_000))).toBe("3h");
    expect(formatAge(ago(26 * 3_600_000))).toBe("1 day");
    expect(formatAge(ago(72 * 3_600_000))).toBe("3 days");
  });
});
