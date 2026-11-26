// PHASE-2.6 T07 (#198): unit coverage for the shared `return` param contract.

import { describe, expect, it } from "vitest";

import { PATIENT_HOME, RETURN_PARAM, sanitizeReturnTarget } from "./return-url";

describe("RETURN_PARAM", () => {
  it("is the param name the proxy and entry surfaces share", () => {
    expect(RETURN_PARAM).toBe("return");
  });
});

describe("sanitizeReturnTarget", () => {
  it.each([
    [null, PATIENT_HOME],
    [undefined, PATIENT_HOME],
    ["", PATIENT_HOME],
    ["/patient/bookings", "/patient/bookings"],
    ["/patient/record?tab=all", "/patient/record?tab=all"],
  ])("resolves %p to %p", (raw, expected) => {
    expect(sanitizeReturnTarget(raw)).toBe(expected);
  });

  it.each([
    "https://evil.example/phish",
    "http://evil.example",
    "//evil.example",
    "/\\evil.example",
    "\\evil.example",
    "patient/relative",
  ])("falls back to %s for the off-site target %p", (raw) => {
    expect(sanitizeReturnTarget(raw)).toBe(PATIENT_HOME);
  });
});
