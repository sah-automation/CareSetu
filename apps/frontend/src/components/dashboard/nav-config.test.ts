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
  isNavItemActive,
  sidebarSections,
  sidebarStorageKey,
  splitMobileTabs,
} from "./nav-config";
import type { NavItemDef } from "./nav-config";
import type { Role } from "./types";
import { ROLE_HOME } from "./types";

const ROLES: Role[] = ["patient", "doctor", "partner", "operator"];

// #744: the whole destination tree for a role - top-level and nested - in
// config order. Every contract assertion below walks this one flattening
// instead of hand-threading `children`, so a deeper group needs no new test.
function flatten(items: NavItemDef[]): NavItemDef[] {
  return items.flatMap((item) => [item, ...flatten(item.children ?? [])]);
}

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

  it("keeps every non-home staff entry as Soon except the doctor Cases, Patients and Profile tabs and the operator Observability entry", () => {
    for (const role of ["doctor", "partner", "operator"] as const) {
      for (const item of NAV_CONFIG[role].slice(1)) {
        // #543: Profile joins Cases/Patients as a live doctor tab - each one
        // has a real route behind it, so none may stay dimmed.
        const isLiveDoctorTab =
          role === "doctor" &&
          (item.key === "cases" ||
            item.key === "patients" ||
            item.key === "profile");
        // #708: the operator's Observability entry joins them - the console has
        // a live overview page behind it, so it may not read as coming-soon.
        const isLiveOperatorTab =
          role === "operator" && item.key === "observability";
        expect(item.soon, `${role}/${item.key}`).toBe(
          isLiveDoctorTab || isLiveOperatorTab ? undefined : true,
        );
      }
    }
  });

  it("keeps hrefs unique and absolute within each role, nested destinations included (#744)", () => {
    for (const role of ROLES) {
      // Absolute: every item in the tree, parents and children alike.
      for (const item of flatten(NAV_CONFIG[role])) {
        expect(item.href.startsWith("/"), `${role} ${item.href}`).toBe(true);
      }
      // Unique: no route may serve two distinct destinations. A disclosure
      // parent's own href is its group landing and may equal exactly one of its
      // own children (the page it opens onto) - that single deliberate reuse is
      // pinned by the group-landing test below. Every other collision fails.
      const seen = new Set<string>();
      const claim = (href: string) => {
        expect(seen.has(href), `${role} ${href}`).toBe(false);
        seen.add(href);
      };
      for (const item of NAV_CONFIG[role]) {
        claim(item.href);
        for (const child of item.children ?? []) {
          if (child.href === item.href) continue;
          claim(child.href);
        }
      }
    }
  });

  it("resolves every label key in both locales via the i18n engine, nested labels included (#744)", () => {
    for (const role of ROLES) {
      for (const item of flatten(NAV_CONFIG[role])) {
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

  it("gives every disclosure parent a group landing that is one of its own sub-destinations (#744)", () => {
    // Criterion 2 keys parent highlighting off the parent's own href, so a
    // disclosure parent must carry a real destination (decision 29) and that
    // destination must be one of its pages. Without this the parent would have
    // no route of its own and the prefix match would have nothing to match.
    for (const role of ROLES) {
      for (const item of flatten(NAV_CONFIG[role])) {
        if (!item.children?.length) continue;
        expect(
          item.children.some((child) => child.href === item.href),
          `${role}/${item.key}`,
        ).toBe(true);
      }
    }
  });

  it("keeps center and mobileOverflow slots on top-level destinations only (#744)", () => {
    // The mobile split helper (#746) filters for `center`/`mobileOverflow`. A
    // nested child carrying either flag would be consumed by a mechanism that
    // never walks `children`, dropping a declared sub-destination from every
    // surface - the "destination in one config, missing in the other" failure
    // criterion 1 exists to prevent.
    for (const role of ROLES) {
      for (const item of NAV_CONFIG[role]) {
        for (const child of flatten(item.children ?? [])) {
          expect(child.center, `${role}/${child.key}`).toBeUndefined();
          expect(child.mobileOverflow, `${role}/${child.key}`).toBeUndefined();
        }
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

  it("keeps patient Find live, un-soons Profile & Settings, dims Inbox/Bookings until their phases (PHASE-8.1 T11, #485)", () => {
    const patient = Object.fromEntries(
      NAV_CONFIG.patient.map((item) => [item.key, item]),
    );
    // Find Care is live: /patient/find is a real page, never a dead nav.
    expect(patient.find?.soon).toBeUndefined();
    expect(patient.find?.href).toBe("/patient/find");
    // #524: Profile & Settings un-sooned - /patient/profile is a real route
    // (#522/#523). mobileOverflow pins it to the mobile More sheet; its spot
    // beyond the top-nav's first-five window (after Inbox and Bookings) keeps
    // it out of the desktop top bar, so it stays account-cluster-only there.
    expect(patient["profile-settings"]?.soon).toBeUndefined();
    expect(patient["profile-settings"]?.href).toBe("/patient/profile");
    expect(patient["profile-settings"]?.mobileOverflow).toBe(true);
    // Inbox (Phase 13) and Bookings (Phase 9) are coming-soon - they must
    // render dimmed + non-interactive, so no patient nav item navigates to a
    // dead destination.
    expect(patient.inbox?.soon).toBe(true);
    expect(patient.bookings?.soon).toBe(true);
    // Home / Start / Record stay live (root surfaces with real pages).
    expect(patient.home?.soon).toBeUndefined();
    expect(patient.start?.soon).toBeUndefined();
    expect(patient.record?.soon).toBeUndefined();
  });
});

describe("isNavItemActive (#744)", () => {
  const leaf: NavItemDef = {
    key: "leaf",
    labelKey: "home",
    href: "/x/leaf",
    icon: Home,
  };
  const parent: NavItemDef = {
    key: "group",
    labelKey: "observability",
    href: "/x/group",
    icon: Home,
    children: [leaf],
  };

  it("matches a leaf destination by exact path only", () => {
    expect(isNavItemActive(leaf, "/x/leaf")).toBe(true);
    // A leaf is never a prefix parent: a nested path under it is not "current".
    expect(isNavItemActive(leaf, "/x/leaf/deeper")).toBe(false);
    expect(isNavItemActive(leaf, "/x")).toBe(false);
  });

  it("lights a disclosure parent on its own destination and any nested path", () => {
    expect(isNavItemActive(parent, "/x/group")).toBe(true);
    expect(isNavItemActive(parent, "/x/group/leaf")).toBe(true);
    expect(isNavItemActive(parent, "/x/group/deep/er")).toBe(true);
  });

  it("bounds the parent prefix at a path-segment boundary", () => {
    // The trap this ticket exists to close: a sibling whose href merely shares
    // a string prefix must not light the parent up.
    expect(isNavItemActive(parent, "/x/grouper")).toBe(false);
    expect(isNavItemActive(parent, "/x/group-2")).toBe(false);
    expect(isNavItemActive(parent, "/x/grou")).toBe(false);
  });

  it("never marks a Soon destination current, parent or child", () => {
    const soonLeaf: NavItemDef = { ...leaf, soon: true };
    const soonParent: NavItemDef = { ...parent, soon: true };
    expect(isNavItemActive(soonLeaf, "/x/leaf")).toBe(false);
    expect(isNavItemActive(soonParent, "/x/group/leaf")).toBe(false);
    expect(isNavItemActive(soonParent, "/x/group")).toBe(false);
  });
});

describe("operator Observability group (#744)", () => {
  const parent = NAV_CONFIG.operator.find(
    (item) => item.key === "observability",
  );

  it("is a disclosure parent in its own section, landing on Overview", () => {
    expect(parent?.group).toBe("observability");
    expect(parent?.href).toBe("/operator/observability");
    // The console is live, not a placeholder.
    expect(parent?.soon).toBeUndefined();
    expect(parent?.children?.length).toBeGreaterThan(0);
  });

  it("declares the decision-28 sub-destinations in order", () => {
    // Spec #717 decision 28: Observability holds Overview, Business, Product,
    // Reliability, the four existing AI panels, Security and Settings. #745
    // renders this exact order as the disclosure's sub-menu, so the order is a
    // contract, not an incidental detail.
    expect(parent?.children?.map((child) => child.key)).toEqual([
      "overview",
      "business",
      "product",
      "reliability",
      "cost",
      "usage",
      "quality",
      "health",
      "security",
      "settings",
      "evals",
    ]);
    // #747: no sub-destination is a coming-soon stub any more. Settings is the
    // placeholder shell behind a live page, so the whole sub-menu is clickable.
    expect(
      parent?.children?.filter((child) => child.soon).map((child) => child.key),
    ).toEqual([]);
  });

  it("keeps Settings live as the #747 placeholder shell", () => {
    const settings = parent?.children?.find(
      (child) => child.key === "settings",
    );

    expect(settings?.href).toBe("/operator/observability/settings");
    expect(settings?.soon).toBeUndefined();
  });

  it("keeps the Work entries as they were and adds Observability as a second section", () => {
    const sections = sidebarSections(NAV_CONFIG.operator);

    expect(sections.map((section) => section.labelKey)).toEqual([
      "work",
      "observability",
    ]);
    expect(sections[0].items.map((item) => item.key)).toEqual([
      "home",
      "verifications",
      "disputes",
      "audit",
    ]);
    expect(sections[1].items.map((item) => item.key)).toEqual([
      "observability",
    ]);
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
    // The More tab is permanent for the patient role (#524): the pinned
    // overflow below means hasMore never collapses to a four-column bar.
    expect(hasMore).toBe(true);
    // Inbox stays inside More ahead of the other destinations (it is Soon
    // until Phase 13, but its overflow pin keeps the order). Profile &
    // Settings is now the live overflow entry (#524).
    expect(overflow.map((item) => item.key)).toEqual([
      "inbox",
      "bookings",
      "profile-settings",
    ]);
    expect(
      overflow.find((item) => item.key === "profile-settings")?.soon,
    ).toBeUndefined();
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

  it.each(["doctor", "partner"] as const)(
    "%s fits its entries below the cap without a More sheet",
    (role) => {
      const { tabs, overflow, hasMore } = splitMobileTabs(NAV_CONFIG[role]);

      expect(tabs.map((item) => item.key)).toEqual(
        NAV_CONFIG[role].map((item) => item.key),
      );
      expect(tabs.length).toBeLessThanOrEqual(TABBAR_MAX_DESTINATIONS);
      expect(hasMore).toBe(false);
      expect(overflow).toHaveLength(0);
    },
  );

  // #746: a disclosure parent (an item carrying `children`) is not a flat tab -
  // a tab column cannot expand a group - so the pinned-overflow rule sends it
  // into the More sheet. The operator bar keeps the four Work destinations plus
  // More; the parent and its nine sub-destinations live in the sheet.
  it("pins the operator's disclosure parent into More (#746)", () => {
    const { tabs, overflow, hasMore } = splitMobileTabs(NAV_CONFIG.operator);

    expect(tabs.map((item) => item.key)).toEqual([
      "home",
      "verifications",
      "disputes",
      "audit",
    ]);
    expect(tabs.length).toBeLessThanOrEqual(TABBAR_MAX_DESTINATIONS);
    expect(hasMore).toBe(true);
    expect(overflow.map((item) => item.key)).toEqual(["observability"]);
  });

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

describe("sidebarSections (#538)", () => {
  it("orders the doctor console under Work then Account", () => {
    const sections = sidebarSections(NAV_CONFIG.doctor);

    expect(sections.map((s) => s.labelKey)).toEqual(["work", "account"]);
    expect(sections[0].items.map((item) => item.key)).toEqual([
      "queue",
      "cases",
      "patients",
    ]);
    expect(sections[1].items.map((item) => item.key)).toEqual(["profile"]);
  });

  it("keeps the patient config flat with no section labels", () => {
    const sections = sidebarSections(NAV_CONFIG.patient);

    expect(sections).toEqual([{ labelKey: null, items: NAV_CONFIG.patient }]);
  });

  it("groups by declared membership and preserves config order within a section", () => {
    const synthetic: NavItemDef[] = [
      { key: "b", labelKey: "queue", href: "/b", icon: Home, group: "work" },
      { key: "a", labelKey: "cases", href: "/a", icon: Home, group: "work" },
      {
        key: "c",
        labelKey: "profile",
        href: "/c",
        icon: Home,
        group: "account",
      },
    ];

    const sections = sidebarSections(synthetic);

    expect(sections.map((s) => s.labelKey)).toEqual(["work", "account"]);
    expect(sections[0].items.map((item) => item.key)).toEqual(["b", "a"]);
    expect(sections[1].items.map((item) => item.key)).toEqual(["c"]);
  });

  it("keeps every full-shell role item in a labeled membership (no orphan rows)", () => {
    for (const role of ["doctor", "partner", "operator"] as const) {
      const grouped = sidebarSections(NAV_CONFIG[role]).flatMap(
        (section) => section.items,
      );
      expect(grouped, role).toEqual(NAV_CONFIG[role]);
      expect(
        NAV_CONFIG[role].every((item) => item.group !== undefined),
        `${role} group`,
      ).toBe(true);
      // #744: sub-membership lives in the parent's `children` list alone - a
      // nested item never re-declares its own group, the second hand-maintained
      // list this ticket exists to prevent.
      for (const item of NAV_CONFIG[role]) {
        for (const child of flatten(item.children ?? [])) {
          expect(child.group, `${role}/${child.key}`).toBeUndefined();
        }
      }
    }
  });
});
