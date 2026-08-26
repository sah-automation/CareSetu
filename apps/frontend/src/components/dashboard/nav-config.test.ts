// PHASE-2.6 T06 (#197): schema-level suite for the typed nav-config source -
// per-role completeness, bilingual label resolution, and mobile tab-split
// mechanics (five-destination cap, center accent pinning, More overflow).

import { describe, expect, it } from "vitest";
import { Home } from "lucide-react";

import { STRINGS } from "@/lib/i18n/dictionaries";

import {
  NAV_CONFIG,
  TABBAR_CENTER_COLUMN,
  TABBAR_MAX_DESTINATIONS,
  sidebarStorageKey,
  splitMobileTabs,
} from "./nav-config";
import type { NavItemDef } from "./nav-config";
import type { Role } from "./types";
import { ROLE_HOME } from "./types";

const ROLES: Role[] = ["patient", "doctor", "partner", "operator"];

describe("NAV_CONFIG", () => {
  it("ships a config for every role", () => {
    expect(ROLES.map((role) => NAV_CONFIG[role])).toHaveLength(4);
    expect(Object.keys(NAV_CONFIG).sort()).toEqual([...ROLES].sort());
  });

  it.each(ROLES)("%s lands on a live home entry that is never Soon", (role) => {
    const home = NAV_CONFIG[role][0];
    // First destination must be the ROLE_HOME surface from types.ts - the
    // single source public chrome also reads; the two may never drift.
    expect(home.href).toBe(ROLE_HOME[role]);
    expect(home.soon).toBeUndefined();
  });

  it("marks every non-home staff entry as Soon", () => {
    for (const role of ["doctor", "partner", "operator"] as const) {
      for (const item of NAV_CONFIG[role].slice(1)) {
        expect(item.soon, `${role}/${item.key}`).toBe(true);
      }
    }
  });

  it("keeps hrefs unique and absolute within each role", () => {
    for (const role of ROLES) {
      const hrefs = NAV_CONFIG[role].map((item) => item.href);
      for (const href of hrefs) {
        expect(href.startsWith("/"), `${role} ${href}`).toBe(true);
      }
      expect(new Set(hrefs).size).toBe(hrefs.length);
    }
  });

  it("resolves every label key in both locales via the i18n engine", () => {
    for (const role of ROLES) {
      for (const item of NAV_CONFIG[role]) {
        expect(typeof STRINGS.en.nav[item.labelKey], item.labelKey).toBe(
          "string",
        );
        expect(typeof STRINGS.hi.nav[item.labelKey], item.labelKey).toBe(
          "string",
        );
        expect(STRINGS.en.nav[item.labelKey].length).toBeGreaterThan(0);
        expect(STRINGS.hi.nav[item.labelKey].length).toBeGreaterThan(0);
      }
    }
  });

  it("pins exactly one center accent slot, only for the patient tab set", () => {
    for (const role of ROLES) {
      const centers = NAV_CONFIG[role].filter((item) => item.center);
      if (role === "patient") {
        expect(centers.map((item) => item.key)).toEqual(["start"]);
      } else {
        expect(centers).toHaveLength(0);
      }
    }
  });
});

describe("splitMobileTabs", () => {
  it("shapes the ratified five-column patient bar with Start Visit centered", () => {
    const { tabs, overflow, hasMore } = splitMobileTabs(NAV_CONFIG.patient);

    // Ratified carry-over fix (#210): Home | Find | Start(center) | Record |
    // More - four destination columns plus the More chrome trigger; Inbox
    // folds into the More sheet instead of taking a sixth column.
    expect(tabs.map((item) => item.key)).toEqual([
      "home",
      "find",
      "start",
      "record",
    ]);
    expect(tabs.length + (hasMore ? 1 : 0)).toBe(TABBAR_MAX_DESTINATIONS);
    expect(tabs[TABBAR_CENTER_COLUMN]?.key).toBe("start");
    expect(tabs.filter((item) => item.center)).toHaveLength(1);
    // Inbox stays reachable inside More, ahead of the Soon destinations.
    expect(overflow.map((item) => item.key)).toEqual([
      "inbox",
      "bookings",
      "profile-settings",
    ]);
    // PHASE-3 T7 (#216): the record screen un-sooned its nav slot - Record is
    // now a live destination on every surface via this one config entry.
    expect(
      NAV_CONFIG.patient.find((item) => item.key === "record")?.soon,
    ).toBeUndefined();
  });

  it("pins mobileOverflow destinations into More even when everything fits", () => {
    const synthetic: NavItemDef[] = [
      { key: "dest-0", labelKey: "home", href: "/x/0", icon: Home },
      { key: "dest-1", labelKey: "home", href: "/x/1", icon: Home },
      {
        key: "pinned",
        labelKey: "home",
        href: "/x/pinned",
        icon: Home,
        mobileOverflow: true,
      },
    ];

    const { tabs, overflow, hasMore } = splitMobileTabs(synthetic);

    expect(tabs.map((item) => item.key)).toEqual(["dest-0", "dest-1"]);
    expect(hasMore).toBe(true);
    expect(overflow.map((item) => item.key)).toEqual(["pinned"]);
  });

  it.each(["doctor", "partner", "operator"] as const)(
    "%s fits its entries below the cap without a More sheet",
    (role) => {
      const { tabs, overflow, hasMore } = splitMobileTabs(NAV_CONFIG[role]);

      expect(tabs.map((item) => item.key)).toEqual(
        NAV_CONFIG[role].map((item) => item.key),
      );
      expect(tabs).toHaveLength(4);
      expect(hasMore).toBe(false);
      expect(overflow).toHaveLength(0);
    },
  );

  it("keeps the first five destinations visible and pushes the rest into More", () => {
    const synthetic: NavItemDef[] = Array.from({ length: 7 }, (_, i) => ({
      key: `dest-${i}`,
      labelKey: "home",
      href: `/x/${i}`,
      icon: Home,
    }));

    const { tabs, overflow, hasMore } = splitMobileTabs(synthetic);

    expect(tabs.map((item) => item.key)).toEqual([
      "dest-0",
      "dest-1",
      "dest-2",
      "dest-3",
      "dest-4",
    ]);
    expect(hasMore).toBe(true);
    expect(overflow.map((item) => item.key)).toEqual(["dest-5", "dest-6"]);
  });

  it("keeps the center slot pinned when a centered config overflows", () => {
    const synthetic: NavItemDef[] = [
      ...Array.from({ length: 6 }, (_, i) => ({
        key: `dest-${i}`,
        labelKey: "home" as const,
        href: `/x/${i}`,
        icon: Home,
      })),
      {
        key: "mid",
        labelKey: "home",
        href: "/x/mid",
        icon: Home,
        center: true,
      },
    ];

    const { tabs, overflow, hasMore } = splitMobileTabs(synthetic);

    expect(tabs).toHaveLength(TABBAR_MAX_DESTINATIONS);
    expect(tabs[TABBAR_CENTER_COLUMN]?.key).toBe("mid");
    expect(hasMore).toBe(true);
    expect(overflow).toHaveLength(2);
  });

  it("renders no More column when everything fits", () => {
    const synthetic: NavItemDef[] = Array.from({ length: 5 }, (_, i) => ({
      key: `dest-${i}`,
      labelKey: "home",
      href: `/x/${i}`,
      icon: Home,
    }));

    const { tabs, overflow, hasMore } = splitMobileTabs(synthetic);

    expect(tabs).toHaveLength(5);
    expect(hasMore).toBe(false);
    expect(overflow).toHaveLength(0);
  });
});

describe("sidebar collapse persistence key", () => {
  it("namespaces the stored preference by role", () => {
    expect(sidebarStorageKey("operator")).toBe("caresetu.sidebar.operator");
    expect(sidebarStorageKey("doctor")).toBe("caresetu.sidebar.doctor");
  });
});
