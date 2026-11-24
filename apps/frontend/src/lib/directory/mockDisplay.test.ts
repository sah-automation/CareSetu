// PHASE-6 card redesign (#965): mock display stand-ins. Pins the
// determinism contract the visual-testing story relies on: same partner_id
// always yields the same rating/template/distance, a spread of ids produces
// visibly different values inside the declared ranges, and every per-type
// template carries the keys the three directory variants render.

import { describe, expect, it } from "vitest";

import type { ProviderType } from "./links";
import {
  getMockCardData,
  getMockProfileDistance,
  getMockRating,
} from "./mockDisplay";

const PROVIDER_TYPES: ProviderType[] = ["doctor", "lab", "chemist"];

describe("getMockRating", () => {
  it("returns the same rating for the same partner_id", () => {
    expect(getMockRating(42)).toEqual(getMockRating(42));
  });

  it("keeps every rating inside the 4.5-4.9 range with a positive count", () => {
    for (let partnerId = 1; partnerId <= 50; partnerId += 1) {
      const { stars, reviewCount } = getMockRating(partnerId);
      expect(stars).toBeGreaterThanOrEqual(4.5);
      expect(stars).toBeLessThanOrEqual(4.9);
      expect(Number.isInteger(stars * 10)).toBe(true);
      expect(Number.isInteger(reviewCount)).toBe(true);
      expect(reviewCount).toBeGreaterThan(0);
    }
  });

  it("does not make every card look identical across ids", () => {
    const stars = new Set<number>();
    const counts = new Set<number>();
    for (let partnerId = 1; partnerId <= 30; partnerId += 1) {
      const rating = getMockRating(partnerId);
      stars.add(rating.stars);
      counts.add(rating.reviewCount);
    }
    expect(stars.size).toBeGreaterThan(1);
    expect(counts.size).toBeGreaterThan(1);
  });
});

describe("getMockCardData", () => {
  it("returns the same template for the same partner_id and type", () => {
    expect(getMockCardData(7, "doctor")).toEqual(getMockCardData(7, "doctor"));
  });

  it.each(PROVIDER_TYPES)(
    "carries the expected template keys for %s",
    (type) => {
      const template = getMockCardData(11, type);
      expect(Object.keys(template).sort()).toEqual([
        "credentials",
        "facts",
        "highlightRibbon",
        "tags",
        "videoBadge",
      ]);
      expect(template.facts.length).toBeGreaterThan(0);
      for (const fact of template.facts) {
        expect(typeof fact.label).toBe("string");
        expect(fact.label.length).toBeGreaterThan(0);
        expect(typeof fact.icon).toBe("string");
      }
      expect(template.tags).toHaveLength(2);
      expect(template.tags[0].variant).toBe("accent");
      expect(template.tags[1].variant).toBe("muted");
    },
  );

  it("gives doctors MD/BDS credentials and never labs or chemists", () => {
    for (let partnerId = 1; partnerId <= 20; partnerId += 1) {
      const doctor = getMockCardData(partnerId, "doctor");
      expect(["MD", "BDS"]).toContain(doctor.credentials);
      expect(getMockCardData(partnerId, "lab").credentials).toBeNull();
      expect(getMockCardData(partnerId, "chemist").credentials).toBeNull();
    }
  });

  it("keeps the video badge doctor-only", () => {
    for (let partnerId = 1; partnerId <= 20; partnerId += 1) {
      expect(getMockCardData(partnerId, "lab").videoBadge).toBe(false);
      expect(getMockCardData(partnerId, "chemist").videoBadge).toBe(false);
    }
    const badges = new Set<boolean>();
    for (let partnerId = 1; partnerId <= 20; partnerId += 1) {
      badges.add(getMockCardData(partnerId, "doctor").videoBadge);
    }
    expect(badges).toEqual(new Set([true, false]));
  });

  it("varies templates across ids so cards are visually distinct", () => {
    const seen = new Set<string>();
    for (let partnerId = 1; partnerId <= 30; partnerId += 1) {
      seen.add(JSON.stringify(getMockCardData(partnerId, "doctor")));
    }
    expect(seen.size).toBeGreaterThan(1);
  });
});

describe("getMockProfileDistance", () => {
  it("returns the same distance for the same partner_id", () => {
    expect(getMockProfileDistance(3)).toBe(getMockProfileDistance(3));
  });

  it("formats as 'x.x km away' inside the mock range", () => {
    for (let partnerId = 1; partnerId <= 50; partnerId += 1) {
      const distance = getMockProfileDistance(partnerId);
      expect(distance).toMatch(/^\d\.\d km away$/);
      const km = Number(distance.split(" ")[0]);
      expect(km).toBeGreaterThanOrEqual(0.3);
      expect(km).toBeLessThanOrEqual(4.7);
    }
  });

  it("does not give every provider the same distance", () => {
    const distances = new Set<string>();
    for (let partnerId = 1; partnerId <= 30; partnerId += 1) {
      distances.add(getMockProfileDistance(partnerId));
    }
    expect(distances.size).toBeGreaterThan(1);
  });
});
