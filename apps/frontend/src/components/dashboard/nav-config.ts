// PHASE-2.6 T06 (#197): the single typed nav-config source per role
// (blueprint §2.7). One schema - label key, href, icon, soon flag, count slot,
// reserved partner_type filter - drives every nav variant: full-shell sidebar,
// patient desktop top-nav, and both mobile bottom-tab bars. Adding or flipping
// a destination is a one-place change in NAV_CONFIG below.
//
// Visual/interaction spec: finalized PROTO-PHASE-2.6 views shell-light.html +
// shell-full.html; density rules blueprint §2.3-§2.4; per-role IA from §5.1
// (patient tabs, re-ratified five-column per the PROTO-PHASE-3 carry-over fix
// #210), §6.1 (doctor), §7.2 (partner), §8.1 (operator).

import type { ComponentType } from "react";
import {
  Activity,
  BadgeCheck,
  BarChart3,
  Boxes,
  CalendarDays,
  ClipboardList,
  Coins,
  FileText,
  FolderOpen,
  HeartPulse,
  History,
  Home,
  Inbox,
  LayoutDashboard,
  Mic,
  Package,
  Scale,
  ScrollText,
  Search,
  Settings,
  ShieldCheck,
  TrendingUp,
  User,
  Users,
  Wallet,
} from "lucide-react";

import type { Dictionary } from "@/lib/i18n/dictionaries";

import type { Role } from "./types";
import { ROLE_HOME } from "./types";

export type NavIcon = ComponentType<{ size?: number; className?: string }>;

// The live start-visit route for the patient bar's center accent (#197). The
// home services grid's Start visit tile (#504) sources the same constant, so
// the tab bar and the home surface can never point at different routes.
export const PATIENT_START_VISIT_ROUTE = "/patient/intake";

// The live My Record route. The recent-activity card's View all (#506) sources
// the same constant, so the home preview and the tab-bar destination can never
// point at different routes.
export const PATIENT_RECORD_ROUTE = "/patient/record";

// Labels resolve through the i18n engine: the key must exist in BOTH locale
// dictionaries (compile-time via Dictionary typing, runtime via the bilingual
// parity test).
// Only the string-valued nav dictionary keys are label lookups; `sections`
// holds the section-group headings (#538) and is not a NavItemDef label.
export type NavLabelKey = {
  [K in keyof Dictionary["nav"]]: Dictionary["nav"][K] extends string
    ? K
    : never;
}[keyof Dictionary["nav"]];

// #538: the redesigned full-shell sidebar groups its destinations under
// labeled sections (nav.sections.*). Each item declares one via `group`;
// only the full-shell sidebar consumes the grouping metadata - the top-nav
// and mobile tab bar ignore it and keep their config order.
export type NavSectionKey = keyof Dictionary["nav"]["sections"];

// Reserved partner_type filter (§7.1): the partner console is one shell
// type-filtered by account attribute; entries may declare which types see them.
export type PartnerType = "lab" | "chemist";

export interface NavItemDef {
  // Stable identity: testids and React keys derive from it.
  key: string;
  labelKey: NavLabelKey;
  href: string;
  icon: NavIcon;
  // Unbuilt destination: renders dimmed + non-interactive with the Soon badge.
  soon?: boolean;
  // Bottom-tab center accent slot (patient Start Visit, §5.1). Pinned to the
  // middle column of the tab bar; excluded from the desktop top-nav.
  center?: boolean;
  // Always renders inside the mobile More sheet instead of as a tab column;
  // desktop surfaces keep their own placement from this same config. The
  // ratified patient bar (#210) pins every secondary destination this way -
  // otherwise freed bar slots backfill from the remaining config order.
  mobileOverflow?: boolean;
  // Reserved live-count slot: when a number is attached at render time the
  // item shows a count pill (prototype's count-pill convention).
  count?: number;
  partnerTypes?: PartnerType[];
  // #538: sidebar section-group membership (nav.sections.*). Optional additive
  // metadata for the redesigned full-shell sidebar only; the mobile bars and
  // top-nav ignore it.
  group?: NavSectionKey;
  // #744: a disclosure parent's sub-destinations. Sub-membership is declared
  // here ONCE and read by every renderer that has a nested surface (the
  // sidebar disclosure and the mobile More sheet), never re-listed by hand. A
  // parent's own `href` is its group landing - the page the collapsed rail
  // (and the mobile tab) navigate to - and also the prefix that makes the
  // parent read as current while an operator is inside any sub-destination.
  // #745 renders the expanded parent as a disclosure toggle, not a link, so
  // the group's landing is reached through its Overview child there.
  children?: NavItemDef[];
}

export const NAV_CONFIG: Record<Role, NavItemDef[]> = {
  patient: [
    { key: "home", labelKey: "home", href: ROLE_HOME.patient, icon: Home },
    { key: "find", labelKey: "find", href: "/patient/find", icon: Search },
    {
      key: "start",
      labelKey: "start",
      href: PATIENT_START_VISIT_ROUTE,
      icon: Mic,
      center: true,
    },
    {
      key: "record",
      labelKey: "record",
      href: PATIENT_RECORD_ROUTE,
      icon: FileText,
    },
    // PHASE-8.1 T11 (#485): Inbox dimmed until Phase 13 (FEAT-019/MOD-010) -
    // no page exists, so a live entry would dead-navigate like Find did.
    {
      key: "inbox",
      labelKey: "inbox",
      href: "/patient/inbox",
      icon: Inbox,
      soon: true,
      mobileOverflow: true,
    },
    {
      key: "bookings",
      labelKey: "bookings",
      href: "/patient/bookings",
      icon: CalendarDays,
      soon: true,
      mobileOverflow: true,
    },
    // #524: Profile & Settings un-sooned - /patient/profile is a real route
    // (#522/#523). mobileOverflow pins it to the mobile More sheet. On
    // desktop it sits past the top-nav's first-five window (after Inbox and
    // Bookings), so it stays reachable only via the account cluster - never
    // a top-nav row.
    {
      key: "profile-settings",
      labelKey: "profileSettings",
      href: "/patient/profile",
      icon: Settings,
      mobileOverflow: true,
    },
  ],
  doctor: [
    // #538: the redesigned sidebar groups the doctor console's practice
    // areas under Work, with Profile alone under Account; Logout is chrome in
    // the sidebar's lower group, never a nav destination.
    {
      key: "queue",
      labelKey: "queue",
      href: "/doctor",
      icon: ClipboardList,
      group: "work",
    },
    // PHASE-8.1 T8 (#483): Cases un-sooned - the open-cases index at
    // /doctor/cases is live; patients/profile stay coming-soon.
    {
      key: "cases",
      labelKey: "cases",
      href: "/doctor/cases",
      icon: FolderOpen,
      group: "work",
    },
    // #541: Patients un-sooned - /doctor/patients is a live destination
    // (list + gated detail read the derived doctor patients API, #539/#540).
    {
      key: "patients",
      labelKey: "patients",
      href: "/doctor/patients",
      icon: Users,
      group: "work",
    },
    // #543: Profile un-sooned - /doctor/profile is the live private
    // projection (#542) plus the consultation-fee editor, so the entry is a
    // real link on the sidebar and the phone tab bar.
    {
      key: "profile",
      labelKey: "profile",
      href: "/doctor/profile",
      icon: User,
      group: "account",
    },
  ],
  partner: [
    {
      key: "orders",
      labelKey: "orders",
      href: ROLE_HOME.partner,
      icon: Package,
      partnerTypes: ["lab", "chemist"],
      group: "work",
    },
    {
      key: "history",
      labelKey: "history",
      href: "/partner/orders",
      icon: History,
      soon: true,
      partnerTypes: ["lab", "chemist"],
      group: "work",
    },
    {
      key: "settlements",
      labelKey: "settlements",
      href: "/partner/settlements",
      icon: Wallet,
      soon: true,
      group: "account",
    },
    {
      key: "profile",
      labelKey: "profile",
      href: "/partner/profile",
      icon: User,
      soon: true,
      group: "account",
    },
  ],
  operator: [
    {
      key: "home",
      labelKey: "home",
      href: ROLE_HOME.operator,
      icon: Home,
      group: "work",
    },
    {
      key: "verifications",
      labelKey: "verifications",
      href: "/operator/verifications",
      icon: BadgeCheck,
      soon: true,
      group: "work",
    },
    {
      key: "disputes",
      labelKey: "disputes",
      href: "/operator/disputes",
      icon: Scale,
      soon: true,
      group: "work",
    },
    {
      key: "audit",
      labelKey: "audit",
      href: "/operator/audit",
      icon: ScrollText,
      soon: true,
      group: "work",
    },
    // #744 (spec #717 decisions 27-29): the console is now its own section and
    // a disclosure parent - its nine sub-destinations are declared here once
    // and read by both the sidebar disclosure (#745) and the mobile More sheet
    // (#746). Overview is the group landing (same route as the parent), the
    // three lenses and the four AI panels have live pages, and Settings is the
    // Batch 2 placeholder shell until it ships - so it stays Soon.
    //
    // Decision 28 says the parent has "no destination of its own"; decision 29
    // and ticket criterion 2 make parent highlighting key off "its own
    // destination". Resolved by giving the parent the console landing route as
    // its href and making Overview a child that points at that same route: the
    // parent's href is a real page (so the collapsed rail and the disclosure
    // header have somewhere to go, and the prefix match has an anchor), while
    // Overview remains the destination an operator reads as current. The
    // duplication is deliberate and pinned by the contract tests.
    {
      key: "observability",
      labelKey: "observability",
      href: "/operator/observability",
      icon: Activity,
      group: "observability",
      children: [
        {
          key: "overview",
          labelKey: "overview",
          href: "/operator/observability",
          icon: LayoutDashboard,
        },
        {
          key: "business",
          labelKey: "business",
          href: "/operator/observability/business",
          icon: TrendingUp,
        },
        {
          key: "product",
          labelKey: "product",
          href: "/operator/observability/product",
          icon: Boxes,
        },
        {
          key: "reliability",
          labelKey: "reliability",
          href: "/operator/observability/reliability",
          icon: ShieldCheck,
        },
        {
          key: "cost",
          labelKey: "cost",
          href: "/operator/observability/cost",
          icon: Coins,
        },
        {
          key: "usage",
          labelKey: "usage",
          href: "/operator/observability/usage",
          icon: BarChart3,
        },
        {
          key: "quality",
          labelKey: "quality",
          href: "/operator/observability/quality",
          icon: BadgeCheck,
        },
        {
          key: "health",
          labelKey: "health",
          href: "/operator/observability/health",
          icon: HeartPulse,
        },
        {
          key: "settings",
          labelKey: "settings",
          href: "/operator/observability/settings",
          icon: Settings,
          soon: true,
        },
      ],
    },
  ],
};

// #744: the one active-state predicate every nav renderer shares (sidebar row,
// collapsed-rail row, bottom tab). An item is current when the path equals its
// own destination. A disclosure parent (an item carrying children) is ALSO
// current when the path sits beneath its own destination, so a group never
// looks inactive while the operator is inside it. The prefix match is bounded
// at a path-segment boundary: a sibling whose href merely begins with the same
// string ("/operator/observability" vs "/operator/observability-archive") must
// not light the parent up. Soon entries are never current.
export function isNavItemActive(item: NavItemDef, pathname: string): boolean {
  if (item.soon) return false;
  if (pathname === item.href) return true;
  return Boolean(item.children?.length) && pathname.startsWith(`${item.href}/`);
}

// Bottom-tab bar capacity: up to five destination columns; the optional More
// trigger is chrome, not a destination, so it takes one extra column only
// when a config overflows (§2.4 "up to 5 primary destinations").
export const TABBAR_MAX_DESTINATIONS = 5;
// Middle column of a 5-column bar - where the center accent sits.
export const TABBAR_CENTER_COLUMN = 2;

export interface MobileTabSplit {
  // Rendered columns in order. When `center` exists it sits at
  // min(TABBAR_CENTER_COLUMN, regular length); otherwise config order.
  tabs: NavItemDef[];
  // Destinations beyond the bar; rendered inside the More sheet.
  overflow: NavItemDef[];
  // Whether the bar must render the trailing More trigger.
  hasMore: boolean;
}

function weaveCenter(
  center: NavItemDef | undefined,
  regular: NavItemDef[],
): NavItemDef[] {
  if (!center) return [...regular];
  const at = Math.min(TABBAR_CENTER_COLUMN, regular.length);
  return [...regular.slice(0, at), center, ...regular.slice(at)];
}

export function splitMobileTabs(items: NavItemDef[]): MobileTabSplit {
  const center = items.find((item) => item.center);
  // #746: the pinned-overflow rule now also covers disclosure parents. A tab
  // column is a single flat destination and cannot expand a group, so an item
  // carrying `children` is pinned into the More sheet exactly like a
  // `mobileOverflow` destination - where the group (and every sub-destination)
  // renders. This is what makes adding nine sub-destinations change what fits
  // on the operator bar: the parent leaves the bar for the More sheet.
  const pinnedOverflow = items.filter(
    (item) => (item.mobileOverflow || isGroupParent(item)) && !item.center,
  );
  const regular = items.filter(
    (item) => !item.center && !item.mobileOverflow && !isGroupParent(item),
  );
  const capacity = center
    ? TABBAR_MAX_DESTINATIONS - 1
    : TABBAR_MAX_DESTINATIONS;

  if (pinnedOverflow.length === 0 && regular.length <= capacity) {
    return { tabs: weaveCenter(center, regular), overflow: [], hasMore: false };
  }
  return {
    tabs: weaveCenter(center, regular.slice(0, capacity)),
    overflow: [...pinnedOverflow, ...regular.slice(capacity)],
    hasMore: true,
  };
}

// #746: an item is a disclosure parent (a group) when it carries
// sub-destinations. A group is not a flat destination - a tab column cannot
// expand it - so it is pinned into the More sheet, and the sheet grows a nested
// branch to render it. Naming the rule here keeps it one expression.
export function isGroupParent(item: NavItemDef): boolean {
  return Boolean(item.children?.length);
}

// #746: whether a configuration declares disclosure groups. When it does, the
// mobile More sheet renders the full grouped navigation (mirroring the sidebar)
// rather than the flat overflow list, so every destination - parents and
// sub-destinations alike - is reachable from the sheet. A config with no
// nesting keeps the sheet as the overflow list it has always been.
export function hasNestedDestinations(items: NavItemDef[]): boolean {
  return items.some(isGroupParent);
}

// Collapse preference persists per role (spec decision 6): the storage key is
// namespaced so each full-density role remembers its own sidebar choice.
export function sidebarStorageKey(role: Role): string {
  return `caresetu.sidebar.${role}`;
}

// #538: order full-shell nav items into the redesigned sidebar's labeled
// section groups. Group order follows NAV_CONFIG order (which lists Work
// entries ahead of Account for every full role), ungrouped items render last
// without a header. Only the sidebar consumes this: the mobile bars and
// top-nav keep their flat config order.
export interface SidebarSection {
  labelKey: NavSectionKey | null;
  items: NavItemDef[];
}

export function sidebarSections(items: NavItemDef[]): SidebarSection[] {
  const grouped = new Map<NavSectionKey | null, NavItemDef[]>();
  const order: (NavSectionKey | null)[] = [];
  for (const item of items) {
    const group = item.group ?? null;
    if (!grouped.has(group)) {
      grouped.set(group, []);
      order.push(group);
    }
    grouped.get(group)!.push(item);
  }
  return order.map((key) => ({ labelKey: key, items: grouped.get(key)! }));
}
