// PHASE-5 (#293): shared badge maps + statusKey() normalizer tests.
// statusKey() must normalize every backend status value to a stable lowercase
// key, and the badge maps must key consistently so lookups land.

import { describe, expect, it } from "vitest";

import { STATUS_BADGE, TYPE_BADGE, statusKey } from "./badges";

describe("statusKey", () => {
  it("maps Title Case backend statuses to stable lowercase keys", () => {
    expect(statusKey("Under Verification")).toBe("under_verification");
  });

  it("passes lowercase backend statuses through unchanged", () => {
    expect(statusKey("verified")).toBe("verified");
    expect(statusKey("rejected")).toBe("rejected");
  });

  it("covers every backend status value", () => {
    const backendStatuses = ["Under Verification", "verified", "rejected"];
    const keys = backendStatuses.map(statusKey);
    expect(keys).toEqual(["under_verification", "verified", "rejected"]);
    expect(Object.keys(STATUS_BADGE).sort()).toEqual(
      Array.from(new Set(keys)).sort(),
    );
  });

  it("is case-insensitive against lowercase lookups", () => {
    for (const key of Object.keys(STATUS_BADGE)) {
      expect(STATUS_BADGE[statusKey(key)]).toBeDefined();
    }
  });
});

describe("STATUS_BADGE", () => {
  it("provides a style for every status key", () => {
    expect(STATUS_BADGE).toEqual({
      under_verification: "bg-warn-soft text-warn-text",
      verified: "bg-success-soft text-success-text",
      rejected: "bg-danger-soft text-danger",
    });
  });
});

describe("TYPE_BADGE", () => {
  it("provides a style for every partner type", () => {
    expect(TYPE_BADGE).toEqual({
      doctor: "bg-accent-soft text-accent-strong",
      lab: "bg-success-soft text-success-text",
      chemist: "bg-warm-soft text-txt-sub",
    });
  });
});
