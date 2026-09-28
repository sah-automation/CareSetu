"use client";

// PHASE-2.6 T06 (#197): full-shell desktop sidebar (blueprint §2.3 right).
// Responsiveness is pure CSS - `hidden lg:flex` removes the sidebar from the
// layout entirely below the lg breakpoint, where the bottom tab bar takes
// over; the retired JS viewport-collapse / icon-rail mechanics are gone. The
// only collapse control is the user's own toggle, persisted per role by the
// AppShell (spec decision 6).
//
// #538: doctor-chrome redesign of the full-shell sidebar. Sections: nav items
// group under labeled sections (nav.sections.*, driven by NavItemDef.group);
// the active item carries a left accent indicator; the collapsed icon rail
// shows hover label flyouts (with the open-cases count pill on the Cases
// flyout) rendered as a viewport-fixed tooltip so the aside's overflow never
// clips them. These are additions to the shared chrome - the light patient
// shell never renders a sidebar, and the mobile bottom-tab bars are untouched.
//
// #574: the collapse control is brand-header chrome, not a footer row - a
// compact icon control on the header's trailing edge, 44px tall in both states
// and centred in the collapsed rail. It used to sit under Logout in one
// undivided stack, which read a navigation control as one more nav item and
// paired it with sign-out; the footer now holds Log out alone inside the
// divider it already had. Both of its accessible names come from the string
// dictionary (nav.collapseSidebar / nav.expandSidebar) rather than being
// hardcoded English, so they exist in both locales per blueprint §9.2.

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft, ChevronRight, LogOut } from "lucide-react";

import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import { NAV_CONFIG, sidebarSections } from "./nav-config";
import {
  ActiveIndicator,
  CountPill,
  NavItemLink,
  SoonBadge,
} from "./NavItemLink";
import type { NavItemDef, SidebarSection } from "./nav-config";
import type { Role } from "./types";

interface SidebarProps {
  role: Role;
  collapsed: boolean;
  onToggleCollapse: () => void;
  // Render-time nav override: the AppShell attaches the open-cases count to
  // the doctor Cases item here (#483). Defaults to the static NAV_CONFIG.
  items?: NavItemDef[];
}

export function Sidebar({
  role,
  collapsed,
  onToggleCollapse,
  items,
}: SidebarProps) {
  const navItems = items ?? NAV_CONFIG[role];
  const sections = sidebarSections(navItems);
  const { logout } = useAuth();
  const { lang } = useLang();
  const strings = STRINGS[lang].nav;

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col overflow-y-auto border-r border-hairline bg-surface transition-[width] duration-200 lg:flex",
        collapsed ? "w-16" : "w-60",
      )}
      data-collapsed={collapsed || undefined}
      data-testid="sidebar"
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center overflow-hidden border-b border-hairline",
          // Expanded: the wordmark leads and the control trails it. Collapsed:
          // the wordmark is gone, and a 44px control left on `px-4` would sit
          // 12px off-centre in the 64px rail - so the row centres it instead,
          // the same shape the collapsed footer uses.
          collapsed ? "justify-center px-0" : "justify-between px-4",
        )}
        data-testid="sidebar-brand"
      >
        {!collapsed && (
          <span className="text-base font-semibold whitespace-nowrap text-accent">
            CareSetu
          </span>
        )}
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={
            collapsed ? strings.expandSidebar : strings.collapseSidebar
          }
          data-testid="sidebar-toggle"
          // Compact means narrower, never smaller to hit: `w-full` goes, the
          // 44px box stays (blueprint §9.4 line 597, touch targets).
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded text-txt-sub hover:bg-accent-soft hover:text-txt"
        >
          {collapsed ? (
            <ChevronRight size={20} className="shrink-0" />
          ) : (
            <ChevronLeft size={20} className="shrink-0" />
          )}
        </button>
      </div>

      <nav className="flex-1 space-y-4 p-2" data-testid="sidebar-nav">
        {sections.map((section) => (
          <SidebarSectionGroup
            key={section.labelKey ?? "ungrouped"}
            section={section}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* Sign-out alone, inside the divider this footer already had (#574). */}
      <div
        className="shrink-0 border-t border-hairline-soft p-2"
        data-testid="sidebar-footer"
      >
        <button
          type="button"
          onClick={logout}
          aria-label={strings.logOut}
          data-testid="sidebar-logout"
          className={cn(
            "flex min-h-11 w-full items-center gap-3 rounded px-3 text-sm font-medium text-txt-sub hover:bg-danger-soft hover:text-danger",
            collapsed && "justify-center px-0",
          )}
        >
          <LogOut size={20} className="shrink-0" />
          {!collapsed && (
            <span className="min-w-0 truncate">{strings.logOut}</span>
          )}
        </button>
      </div>
    </aside>
  );
}

function SidebarSectionGroup({
  section,
  collapsed,
}: {
  section: SidebarSection;
  collapsed: boolean;
}) {
  const { lang } = useLang();
  const label = section.labelKey
    ? STRINGS[lang].nav.sections[section.labelKey]
    : null;

  return (
    <div className="space-y-1">
      {!collapsed && label && (
        <p className="px-3 pt-2 text-[11px] font-semibold tracking-wide text-txt-muted uppercase">
          {label}
        </p>
      )}
      {section.items.map((item) =>
        collapsed ? (
          <CollapsedNavItem key={item.key} item={item} />
        ) : (
          <NavItemLink key={item.key} item={item} variant="sidebar" />
        ),
      )}
    </div>
  );
}

// #538: collapsed icon-only state. The label (plus Soon badge and count pill)
// only enters the DOM while the item is hovered - the old rail never leaked
// labels into the collapsed tree. The flyout is `position: fixed` so the
// aside's `overflow-y-auto` cannot clip it; the sidebar is `sticky top-0`, so
// the captured rect stays valid while the page scrolls. The mouse (and focus)
// handlers live on the item root (onMouseEnter/onMouseLeave are non-bubbling),
// with the anchor-level hover only driving the fixed flyout placement.
//
// Blueprint §9.4 "Labeled controls" is a hard floor, and a hover-only tooltip
// is not a name: a `role="tooltip"` nothing references is never announced. So
// every collapsed control carries its own accessible name (the link's
// `aria-label` is the item's own localized label; the Soon affordance carries
// the same label as screen-reader-only text, because `aria-label` is
// prohibited on a role-less span), and the visual flyout is wired to the
// control with `aria-describedby` so its text (label, Soon badge, open count)
// rides along as the description. Focus still opens the flyout for sighted
// keyboard users, but it is no longer what names the control.
function CollapsedNavItem({ item }: { item: NavItemDef }) {
  const pathname = usePathname();
  const { lang } = useLang();
  const [flyoutOpen, setFlyoutOpen] = useState(false);
  const [flyoutTop, setFlyoutTop] = useState(0);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const flyoutId = useId();

  const label = STRINGS[lang].nav[item.labelKey];
  const Icon = item.icon;
  const active = !item.soon && pathname === item.href;

  function openFlyout() {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (rect) {
      setFlyoutTop(rect.top + rect.height / 2);
    }
    setFlyoutOpen(true);
  }

  const handlers = {
    onMouseEnter: openFlyout,
    onMouseLeave: () => setFlyoutOpen(false),
    // Sighted keyboard users hit the icon rail with Tab, so focus mirrors the
    // hover state and surfaces the same visual flyout.
    onFocus: openFlyout,
    onBlur: () => setFlyoutOpen(false),
  };

  const anchor = (
    <span
      ref={anchorRef}
      // Decorative: the name comes from the control (aria-label below), never
      // from the glyph.
      aria-hidden="true"
      className={cn(
        "relative flex h-11 w-11 shrink-0 items-center justify-center rounded",
        active
          ? "bg-accent-soft text-accent-strong"
          : "text-txt-sub hover:bg-accent-soft hover:text-txt",
      )}
    >
      {active && <ActiveIndicator />}
      <Icon size={20} className="shrink-0" />
    </span>
  );

  const flyout = (
    <div
      id={flyoutId}
      role="tooltip"
      style={{ top: flyoutTop }}
      className="fixed left-16 z-50 flex -translate-y-1/2 items-center gap-2 rounded-md border border-hairline bg-surface px-3 py-2 text-sm whitespace-nowrap text-txt shadow-card"
      data-testid="sidebar-flyout"
    >
      {/* The count pill keeps its bare number as its own text: an aria-label
          here would replace the value-bearing text and announce nothing
          useful. It reaches AT through the flyout's description instead. */}
      <span
        className={cn(
          "min-w-0 truncate",
          active && "font-semibold text-accent-strong",
        )}
      >
        {label}
      </span>
      {item.soon && <SoonBadge />}
      {typeof item.count === "number" && !item.soon && (
        <CountPill count={item.count} />
      )}
    </div>
  );

  const body = (
    <div className="relative flex w-11 items-center justify-center">
      {anchor}
      {flyoutOpen && flyout}
    </div>
  );

  if (item.soon) {
    return (
      <span
        aria-disabled="true"
        aria-describedby={flyoutId}
        className="block cursor-not-allowed opacity-60"
        data-soon="true"
        data-testid={`nav-${item.key}`}
        {...handlers}
      >
        {body}
        <span className="sr-only">{label}</span>
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      // The flyout only exists while it is open; the reference is inert
      // otherwise, and the name never depends on it.
      aria-describedby={flyoutId}
      data-active={active || undefined}
      data-testid={`nav-${item.key}`}
      className="block w-11"
      {...handlers}
    >
      {body}
    </Link>
  );
}
