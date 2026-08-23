import { describe, it, expect, beforeEach } from "vitest";

import {
  clearDenied,
  hasBeenDenied,
  markDenied,
  __resetConsentGateForTests,
} from "./consentGate";

describe("consentGate", () => {
  beforeEach(() => {
    __resetConsentGateForTests();
  });

  it("reports nothing denied before any denial is marked", () => {
    expect(hasBeenDenied("lab-booking.history")).toBe(false);
  });

  it("remembers a denial per request key", () => {
    markDenied("lab-booking.history");

    expect(hasBeenDenied("lab-booking.history")).toBe(true);
  });

  it("keeps request keys isolated - one denial never marks another", () => {
    markDenied("lab-booking.history");

    expect(hasBeenDenied("chemist-fill.rx")).toBe(false);
  });

  it("repeat denials of the same key stay a single standing mark", () => {
    markDenied("lab-booking.history");
    markDenied("lab-booking.history");

    expect(hasBeenDenied("lab-booking.history")).toBe(true);
  });

  it("a later Allow clears the standing denial", () => {
    markDenied("lab-booking.history");

    clearDenied("lab-booking.history");

    expect(hasBeenDenied("lab-booking.history")).toBe(false);
  });

  it("clearing one key leaves other denials untouched", () => {
    markDenied("lab-booking.history");
    markDenied("chemist-fill.rx");

    clearDenied("lab-booking.history");

    expect(hasBeenDenied("lab-booking.history")).toBe(false);
    expect(hasBeenDenied("chemist-fill.rx")).toBe(true);
  });
});
