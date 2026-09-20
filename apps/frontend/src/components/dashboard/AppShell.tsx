"use client";

// PHASE-2.6 T06 (#197): one shell component family parameterized by role,
// producing the two blueprint densities (§2.3):
//
//   Light (patient): top bar + slim desktop top-nav, bottom tab bar on
//     phones - never a sidebar at any width.
//   Full (doctor/partner/operator): collapsible sidebar (desktop) + top bar;
//     below the lg breakpoint the sidebar leaves the layout via pure CSS and
//     the bottom tab bar takes over.
//
// Sidebar collapse is a user preference persisted per role - namespaced
// localStorage key per spec decision 6. Adoption follows mount so server and
// first client render agree on expanded (same hydration guard as LangContext).

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { listOpenCases } from "@/lib/care/api";

import { NAV_CONFIG, sidebarStorageKey } from "./nav-config";
import { BottomTabs } from "./BottomTabs";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import type { NavItemDef } from "./nav-config";
import type { Role } from "./types";

export function AppShell({
  role,
  children,
}: {
  role: Role;
  children: ReactNode;
}) {
  const light = role === "patient";

  if (light) {
    return (
      <div
        className="flex min-h-dvh flex-col bg-page-bg"
        data-density="light"
        data-testid="app-shell"
      >
        <Topbar density="light" role={role} />
        <main className="mx-auto w-full max-w-[760px] flex-1 px-4 pt-6 pb-28 lg:pb-10">
          {children}
        </main>
        <BottomTabs role={role} />
      </div>
    );
  }
  return (
    <div
      className="min-h-dvh bg-page-bg"
      data-density="full"
      data-testid="app-shell"
    >
      <FullShellBody role={role}>{children}</FullShellBody>
    </div>
  );
}

function FullShellBody({
  role,
  children,
}: {
  role: Role;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);

  // PHASE-8.1 T8 (#483): the doctor Cases tab carries a live count pill fed
  // from the existing open-cases read (listOpenCases) - one fetch per full
  // shell, shared by the sidebar and phone tab bar. Failures are silent: the
  // pill is a bonus, never a navigational blocker.
  const openCasesCount = useOpenCasesCount(role);
  const navItems = useMemo(() => {
    if (role !== "doctor" || openCasesCount === undefined) {
      return undefined;
    }
    return NAV_CONFIG[role].map((item: NavItemDef) =>
      item.key === "cases" && !item.soon
        ? { ...item, count: openCasesCount }
        : item,
    );
  }, [role, openCasesCount]);

  // Adopt this role's stored preference after mount (hydration-safe), then
  // mirror every change back into storage under the role's own key.
  useEffect(() => {
    const stored = window.localStorage.getItem(sidebarStorageKey(role));
    setCollapsed(stored === "collapsed");
  }, [role]);
  useEffect(() => {
    window.localStorage.setItem(
      sidebarStorageKey(role),
      collapsed ? "collapsed" : "expanded",
    );
  }, [role, collapsed]);

  return (
    <div className="flex min-h-dvh">
      <Sidebar
        role={role}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((value) => !value)}
        items={navItems}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar density="full" role={role} />
        <main className="flex-1 p-6 pb-28 lg:pb-8">{children}</main>
      </div>
      <BottomTabs role={role} items={navItems} />
    </div>
  );
}

function useOpenCasesCount(role: Role): number | undefined {
  const [count, setCount] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (role !== "doctor") return;
    let cancelled = false;
    listOpenCases()
      .then((items) => {
        // Pill carries the actionable count only - zero or a feed failure
        // degrades to no pill, never a "0" badge.
        if (!cancelled && items.length > 0) setCount(items.length);
      })
      .catch((err: unknown) => {
        // Degrade to no pill - nav chrome is a bonus, never a blocker.
        // Still surfaced so a silent feed failure stays visible.
        console.warn("[shell] open-cases count failed to load:", err);
      });
    return () => {
      cancelled = true;
    };
  }, [role]);

  return count;
}
