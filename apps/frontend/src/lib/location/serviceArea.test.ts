// #501: the single-city service-area model. The enum holds the launch
// beachhead only and is the source of truth for a service area; the display
// label is keyed by that id in the locale dictionaries. A persisted value that
// names a known area localizes, any other value is free text shown verbatim,
// and nothing saved falls back to the beachhead.

import { describe, expect, it } from "vitest";

import {
  DEFAULT_SERVICE_AREA,
  SERVICE_AREAS,
  asServiceArea,
  resolveServiceArea,
  serviceAreaLabel,
} from "./serviceArea";

const EN_LABELS = { Daltonganj: "Daltonganj" } as const;
const HI_LABELS = { Daltonganj: "डालटनगंज" } as const;

describe("service-area model (#501)", () => {
  it("serves exactly the launch beachhead today", () => {
    expect(SERVICE_AREAS).toEqual(["Daltonganj"]);
    expect(DEFAULT_SERVICE_AREA).toBe("Daltonganj");
    expect(SERVICE_AREAS).toContain(DEFAULT_SERVICE_AREA);
  });

  it("recognizes a known area, trimmed, and rejects free text", () => {
    expect(asServiceArea("Daltonganj")).toBe("Daltonganj");
    expect(asServiceArea("  Daltonganj  ")).toBe("Daltonganj");
    expect(asServiceArea("Bishrampur")).toBeNull();
    expect(asServiceArea(null)).toBeNull();
    expect(asServiceArea(undefined)).toBeNull();
    expect(asServiceArea("   ")).toBeNull();
  });

  it("selects the persisted known area, else the beachhead", () => {
    expect(resolveServiceArea("Daltonganj")).toBe("Daltonganj");
    expect(resolveServiceArea("Bishrampur")).toBe("Daltonganj");
    expect(resolveServiceArea(null)).toBe("Daltonganj");
    expect(resolveServiceArea(undefined)).toBe("Daltonganj");
    expect(resolveServiceArea("   ")).toBe("Daltonganj");
  });

  it("localizes a known area by its dictionary key", () => {
    expect(serviceAreaLabel("Daltonganj", EN_LABELS)).toBe("Daltonganj");
    expect(serviceAreaLabel("  Daltonganj  ", HI_LABELS)).toBe("डालटनगंज");
  });

  it("shows a free-text area verbatim, and the localized beachhead when empty", () => {
    expect(serviceAreaLabel("Bishrampur", HI_LABELS)).toBe("Bishrampur");
    expect(serviceAreaLabel(null, HI_LABELS)).toBe("डालटनगंज");
    expect(serviceAreaLabel(undefined, HI_LABELS)).toBe("डालटनगंज");
    expect(serviceAreaLabel("   ", HI_LABELS)).toBe("डालटनगंज");
  });
});
