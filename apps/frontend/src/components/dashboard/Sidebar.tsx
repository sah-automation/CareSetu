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
//
// #575: the expanded rail narrows from 240px to 208px (`w-60` -> `w-52`) so
// more of the clinical workspace is visible. The collapsed rail keeps its 64px
// `w-16` on purpose: it is the width the doctor is used to, and the
// viewport-fixed flyout below positions itself with a hardcoded `left-16`, so
// the two must move together or the hover label detaches from the rail. Only
// the expanded branch of the width ternary changed, and the pinned collapsed
// assertions were left alone. No design token was added or re-valued - both
// widths remain literal stock spacing utilities, as #560 requires.
//
// #745: the operator rail returns to 240px (`w-60`). Its Observability
// disclosure indents nine sub-labels under a guide rail, and the doctor's
// 208px floor - sized for the unindented "Profile & Settings" - no longer
// clears the longest indented sub-label. The widening is operator-only, so the
// doctor and partner rails keep #575's 208px, and the collapsed `w-16` (and
// therefore the flyout's `left-16`) is untouched for all roles.

import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronLeft, ChevronRight, LogOut } from "lucide-react";

import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS, type Lang } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import { NAV_CONFIG, isNavItemActive, sidebarSections } from "./nav-config";
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
        // The doctor/partner expanded rail is 208px (#575), down from 240px, so
        // more of the clinical workspace is visible. The longest nav label is
        // `Profile & Settings` at ~116px in text-sm (~95px in Hindi, whose
        // conjuncts stack), and the row spends a fixed 72px on nav p-2, row
        // px-3, the 20px icon and gap-3, so the floor is 188px. w-48 (192px)
        // clears that floor by 4px, which is not a margin; 208px is the next
        // stock step and leaves 17% of headroom. The operator rail is 240px
        // (#745) because its indent+guide-rail push the sub-labels past the
        // 208px floor. The collapsed `w-16` rail is deliberately untouched, and
        // the collapsed flyout's `left-16` below depends on it staying 64px.
        collapsed ? "w-16" : role === "operator" ? "w-60" : "w-52",
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

      {/* #745: the navigation landmark is named. The name is the same one the
          public header's primary nav already uses ("Primary"), a shared
          landmark identity rather than a per-role string. */}
      <nav
        className="flex-1 space-y-4 p-2"
        aria-label="Primary"
        data-testid="sidebar-nav"
      >
        {sections.map((section, index) => (
          <Fragment key={section.labelKey ?? "ungrouped"}>
            {/* #745: hairline dividers separate the operator's Work and
                Observability groups. They are operator-only so the doctor's
                Work/Account split keeps its pre-#745 spacing. */}
            {role === "operator" && index > 0 && (
              <div
                className="border-t border-hairline"
                data-testid="sidebar-section-divider"
              />
            )}
            <SidebarSectionGroup section={section} collapsed={collapsed} />
          </Fragment>
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
      {section.items.map((item) => {
        // #745: an item carrying children is a disclosure parent. Expanded it
        // is a toggle + sub-menu; collapsed it is an icon whose flyout lists
        // its sub-destinations so the group stays navigable in the rail.
        if (collapsed) {
          return item.children?.length ? (
            <CollapsedGroupNavItem key={item.key} item={item} />
          ) : (
            <CollapsedNavItem key={item.key} item={item} />
          );
        }
        return item.children?.length ? (
          <DisclosureNavItem key={item.key} item={item} />
        ) : (
          <NavItemLink key={item.key} item={item} variant="sidebar" />
        );
      })}
    </div>
  );
}

// #745: the expanded Observability disclosure. A hand-rolled controlled
// disclosure - no dependency is installed (the component-library research
// directs keeping the sidebar hand-rolled, decision 30). The header is a
// button, not a link: nine sub-destinations would otherwise sit behind a
// control that also navigates, and the group's own landing is the Overview
// child (decision 28's resolved reading in nav-config.ts). Its expanded state
// is exposed to assistive technology via `aria-expanded`/`aria-controls`, and
// the chevron rotates with that same state.
//
// The expanded state is per-navigation as far as the route is concerned: the
// group opens itself when the operator is inside it, and a manual collapse
// sticks until they leave and re-enter. That default is deliberate - a
// disclosure that starts open would put nine rows back in the rail and defeat
// the reason it exists.
function DisclosureNavItem({ item }: { item: NavItemDef }) {
  const pathname = usePathname();
  const { lang } = useLang();
  const label = STRINGS[lang].nav[item.labelKey];
  const Icon = item.icon;
  const active = isNavItemActive(item, pathname);
  const [open, setOpen] = useState(active);
  const submenuId = useId();
  const children = item.children ?? [];

  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  return (
    <div data-testid={`sidebar-group-${item.key}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={submenuId}
        // The parent reads as the current group while any sub-destination is
        // current - the same shared predicate (#744) the collapsed rail and the
        // phone sheet consume, so the surfaces can never disagree about where
        // the operator is. The value is "true", not "page": the parent is a
        // disclosure toggle, not the destination, and the destination row
        // carries `aria-current="page"`. Two elements claiming the current
        // page inside one navigation set is the classic aria-current
        // anti-pattern (the current page gets announced twice).
        aria-current={active ? "true" : undefined}
        data-active={active || undefined}
        data-testid={`nav-${item.key}`}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "relative flex min-h-11 w-full items-center gap-3 whitespace-nowrap rounded px-3 py-2 text-sm",
          active
            ? "bg-accent-soft font-semibold text-accent-strong"
            : "font-medium text-txt-sub hover:bg-accent-soft hover:text-txt",
        )}
      >
        {active && <ActiveIndicator />}
        <Icon size={20} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronDown
          size={16}
          aria-hidden="true"
          data-testid={`${item.key}-disclosure-chevron`}
          className={cn("shrink-0 transition-transform", open && "rotate-180")}
        />
      </button>
      {/* The guide rail: a hairline left border aligned under the parent's
          icon, with the rows inset past it. Existing tokens only. The menu
          stays mounted and toggles a class rather than the `hidden` attribute
          (the same shape the doctor-profile disclosure uses), so the toggle's
          `aria-controls` always resolves to a real element. */}
      <ul
        id={submenuId}
        data-testid={`sidebar-group-${item.key}-menu`}
        className={cn(
          "mt-1 ml-5 space-y-1 border-l border-hairline pl-1",
          !open && "hidden",
        )}
      >
        {children.map((child) => (
          <li key={child.key}>
            <NavItemLink item={child} variant="sidebar-sub" />
          </li>
        ))}
      </ul>
    </div>
  );
}

// #745: the collapsed-rail form of a disclosure parent. The icon itself is a
// link to the group landing (so the group is one click away), and its hover /
// focus flyout lists every sub-destination so the group stays navigable while
// the rail is collapsed. Unlike the single-destination flyout above it is NOT
// a tooltip: role=tooltip may not contain interactive content, and this one
// carries links. Focus-within keeps it open while tabbing through those links.
function CollapsedGroupNavItem({ item }: { item: NavItemDef }) {
  const pathname = usePathname();
  const { lang } = useLang();
  const [flyoutOpen, setFlyoutOpen] = useState(false);
  const [flyoutTop, setFlyoutTop] = useState(0);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const label = STRINGS[lang].nav[item.labelKey];
  const Icon = item.icon;
  const active = isNavItemActive(item, pathname);
  const children = item.children ?? [];

  function openFlyout() {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (rect) setFlyoutTop(rect.top + rect.height / 2);
    setFlyoutOpen(true);
  }

  // Keep the flyout open while focus is anywhere inside the group; close it
  // only when focus leaves for something outside.
  function closeOnFocusOut(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setFlyoutOpen(false);
    }
  }

  return (
    <div
      className="relative flex w-11 items-center justify-center"
      data-testid={`sidebar-group-${item.key}-collapsed`}
      onMouseEnter={openFlyout}
      onMouseLeave={() => setFlyoutOpen(false)}
      onFocus={openFlyout}
      onBlur={closeOnFocusOut}
    >
      <Link
        href={item.href}
        aria-label={label}
        // The collapsed rail reads the same group-level marker as the expanded
        // toggle and the phone sheet: the group is current ("true"), the
        // destination inside it is the page ("page").
        aria-current={active ? "true" : undefined}
        data-active={active || undefined}
        data-testid={`nav-${item.key}`}
        className="block w-11"
      >
        <span
          ref={anchorRef}
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
      </Link>
      {flyoutOpen && (
        <div
          style={{ top: flyoutTop }}
          className="fixed left-16 z-50 -translate-y-1/2 rounded-md border border-hairline bg-surface p-2 text-sm text-txt shadow-card"
          data-testid="sidebar-flyout"
        >
          <p
            className={cn(
              "px-2 pb-1 whitespace-nowrap",
              active
                ? "font-semibold text-accent-strong"
                : "font-medium text-txt-sub",
            )}
          >
            {label}
          </p>
          <ul className="space-y-0.5">
            {children.map((child) => (
              <li key={child.key}>
                <CollapsedFlyoutChild child={child} lang={lang} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// #745: one flyout row for a collapsed group. The Soon form reuses the shared
// dimmed/non-interactive convention so a coming-soon sub-destination cannot
// become tappable just because it moved into an overflow surface.
function CollapsedFlyoutChild({
  child,
  lang,
}: {
  child: NavItemDef;
  lang: Lang;
}) {
  const pathname = usePathname();
  const label = STRINGS[lang].nav[child.labelKey];
  // The flyout row is a real destination, so it carries the page-level marker
  // the expanded sub-menu row carries. The collapsed group's own link is the
  // group marker ("true"), so exactly one element in the rail claims the page.
  const active = isNavItemActive(child, pathname);

  if (child.soon) {
    return (
      <span
        aria-disabled="true"
        className="flex cursor-not-allowed items-center gap-2 rounded px-2 py-1.5 whitespace-nowrap text-txt-sub opacity-60"
        data-soon="true"
        data-testid={`nav-${child.key}`}
      >
        <span className="min-w-0 truncate">{label}</span>
        <SoonBadge />
      </span>
    );
  }

  return (
    <Link
      href={child.href}
      aria-current={active ? "page" : undefined}
      data-active={active || undefined}
      data-testid={`nav-${child.key}`}
      className="flex items-center gap-2 rounded px-2 py-1.5 whitespace-nowrap text-txt-sub hover:bg-accent-soft hover:text-txt"
    >
      <span className="min-w-0 truncate">{label}</span>
    </Link>
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
  const active = isNavItemActive(item, pathname);

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
