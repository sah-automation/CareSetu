// The shared paise->rupee formatter (lib/money). Moved here from the doctor
// pick card's own suite: the operator Observability console formats money too,
// and a formatter's test belongs with the formatter rather than with whichever
// component happened to need it first.

import { describe, expect, it } from "vitest";

import { formatInrPaise } from "./money";

describe("formatInrPaise", () => {
  it("formats integer paise as a whole-rupee INR amount", () => {
    expect(formatInrPaise(50000)).toBe("\u20B9500");
    expect(formatInrPaise(300)).toBe("\u20B93");
  });

  it("drops a zero budget rather than rendering a dash or a fraction", () => {
    expect(formatInrPaise(0)).toBe("\u20B90");
  });
});
