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
  BadgeCheck,
  CalendarDays,
  ClipboardList,
  FileText,
  FolderOpen,
  History,
  Home,
  Inbox,
  Mic,
  Package,
  Scale,
  ScrollText,
  Search,
  Settings,
  User,
  Users,
  Wallet,
} from "lucide-react";

import type { Dictionary } from "@/lib/i18n/dictionaries";

import type { Role } from "./types";
import { ROLE_HOME } from "./types";

export type NavIcon = ComponentType<{ size?: number; className?: string }>;

// Labels resolve through the i18n engine: the key must exist in BOTH locale
// dictionaries (compile-time via Dictionary typing, runtime via the bilingual
// parity test).
export type NavLabelKey = keyof Dictionary["nav"];

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
}

export const NAV_CONFIG: Record<Role, NavItemDef[]> = {
  patient: [
    { key: "home", labelKey: "home", href: ROLE_HOME.patient, icon: Home },
    { key: "find", labelKey: "find", href: "/patient/find", icon: Search },
    {
      key: "start",
      labelKey: "start",
      href: "/patient/intake",
      icon: Mic,
      center: true,
    },
    {
      key: "record",
      labelKey: "record",
      href: "/patient/record",
      icon: FileText,
    },
    {
      key: "inbox",
      labelKey: "inbox",
      href: "/patient/inbox",
      icon: Inbox,
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
    {
      key: "profile-settings",
      labelKey: "profileSettings",
      href: "/patient/profile",
      icon: Settings,
      soon: true,
      mobileOverflow: true,
    },
  ],
  doctor: [
    { key: "queue", labelKey: "queue", href: "/doctor", icon: ClipboardList },
    {
      key: "cases",
      labelKey: "cases",
      href: "/doctor/cases",
      icon: FolderOpen,
      soon: true,
    },
    {
      key: "patients",
      labelKey: "patients",
      href: "/doctor/patients",
      icon: Users,
      soon: true,
    },
    {
      key: "profile",
      labelKey: "profile",
      href: "/doctor/profile",
      icon: User,
      soon: true,
    },
  ],
  partner: [
    {
      key: "orders",
      labelKey: "orders",
      href: ROLE_HOME.partner,
      icon: Package,
      partnerTypes: ["lab", "chemist"],
    },
    {
      key: "history",
      labelKey: "history",
      href: "/partner/orders",
      icon: History,
      soon: true,
      partnerTypes: ["lab", "chemist"],
    },
    {
      key: "settlements",
      labelKey: "settlements",
      href: "/partner/settlements",
      icon: Wallet,
      soon: true,
    },
    {
      key: "profile",
      labelKey: "profile",
      href: "/partner/profile",
      icon: User,
      soon: true,
    },
  ],
  operator: [
    { key: "home", labelKey: "home", href: ROLE_HOME.operator, icon: Home },
    {
      key: "verifications",
      labelKey: "verifications",
      href: "/operator/verifications",
      icon: BadgeCheck,
      soon: true,
    },
    {
      key: "disputes",
      labelKey: "disputes",
      href: "/operator/disputes",
      icon: Scale,
      soon: true,
    },
    {
      key: "audit",
      labelKey: "audit",
      href: "/operator/audit",
      icon: ScrollText,
      soon: true,
    },
  ],
};

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
  const pinnedOverflow = items.filter(
    (item) => item.mobileOverflow && !item.center,
  );
  const regular = items.filter((item) => !item.center && !item.mobileOverflow);
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

// Collapse preference persists per role (spec decision 6): the storage key is
// namespaced so each full-density role remembers its own sidebar choice.
export function sidebarStorageKey(role: Role): string {
  return `caresetu.sidebar.${role}`;
}
