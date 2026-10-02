// #623 (FEAT-004): a directory href states which filter it is pre-seeding.
//
// The defect this pins: `directoryHref(type, query)` had one positional text
// parameter, so a homepage chip for a doctor's specialty sent
// `/directory?type=doctor&q=Cardiologist`. `q` is the backend's free-text
// search over practice name, clinic name and area; `specialty` is the
// closed-vocabulary membership filter. A specialty sent as free text therefore
// searched three columns instead of the one that matters, so the chip both
// matched the wrong set and left the specialty filter control unset.
//
// The options bag makes the two indistinguishable by accident, and the tests
// below pin the parameter each filter actually lands in.

import { describe, expect, it } from "vitest";

import {
  DIRECTORY_ROUTE,
  directoryHref,
  providerProfileHref,
  type ProviderType,
} from "./links";

const SPECIALTIES = [
  "General Physician",
  "Pediatrician",
  "Gynecologist",
  "Dentist",
  "General Surgeon",
  "Orthopedic Surgeon",
  "Ophthalmologist",
  "ENT Specialist",
  "Dermatologist",
  "Psychiatrist",
  "Cardiologist",
  "Neurologist",
  "Gastroenterologist",
  "Urologist",
  "Nephrologist",
  "Pulmonologist",
  "Endocrinologist",
  "Oncologist",
  "Ayurvedic Practitioner",
  "Homeopathy Practitioner",
] as const;

function params(href: string): URLSearchParams {
  const query = href.split("?")[1];
  return new URLSearchParams(query ?? "");
}

describe("directoryHref pre-seeds the filter it names (#623, FEAT-004)", () => {
  it("sends a specialty as the specialty filter, never as free text", () => {
    for (const specialty of SPECIALTIES) {
      const search = params(directoryHref("doctor", { specialty }));
      expect(search.get("specialty")).toBe(specialty);
      expect(search.get("q")).toBeNull();
      expect(search.get("type")).toBe("doctor");
    }
  });

  it("percent-encodes a specialty with a space in it", () => {
    // "General Physician" and "ENT Specialist" both carry a space; an
    // unencoded one splits into two query params and the filter matches nothing.
    const href = directoryHref("doctor", { specialty: "ENT Specialist" });
    expect(href).toBe("/directory?type=doctor&specialty=ENT+Specialist");
    expect(params(href).get("specialty")).toBe("ENT Specialist");
  });

  it("sends a lab or chemist service keyword as free text", () => {
    // Not specialties: "Blood test" matches no member of the closed vocabulary,
    // so the membership filter would return nothing for it.
    for (const keyword of ["Blood test", "X-ray", "Full body checkup"]) {
      const search = params(directoryHref("lab", { q: keyword }));
      expect(search.get("q")).toBe(keyword);
      expect(search.get("specialty")).toBeNull();
    }
  });

  it("carries both filters together when both are given", () => {
    const search = params(
      directoryHref("doctor", { q: "Pahar", specialty: "Cardiologist" }),
    );
    expect(search.get("q")).toBe("Pahar");
    expect(search.get("specialty")).toBe("Cardiologist");
  });

  it("omits a filter left undefined instead of sending an empty param", () => {
    const search = params(directoryHref("doctor", { specialty: undefined }));
    expect(search.get("specialty")).toBeNull();
    expect(search.has("specialty")).toBe(false);
  });

  it("keeps the bare route for a type-only tile and for no preset at all", () => {
    expect(directoryHref()).toBe(DIRECTORY_ROUTE);
    expect(directoryHref("chemist")).toBe(`${DIRECTORY_ROUTE}?type=chemist`);
  });
});

describe("the directory route family is untouched by #623", () => {
  it("keeps one variant route per provider type", () => {
    const types: ProviderType[] = ["doctor", "lab", "chemist"];
    expect(types.map((type) => directoryHref(type))).toEqual([
      "/directory?type=doctor",
      "/directory?type=lab",
      "/directory?type=chemist",
    ]);
  });

  it("keeps the public profile href shape", () => {
    expect(providerProfileHref(42)).toBe("/providers/42");
  });
});
