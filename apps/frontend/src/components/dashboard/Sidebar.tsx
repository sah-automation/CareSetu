"use client";

// PHASE-2.6 T06 (#197): full-shell desktop sidebar (blueprint §2.3 right).
// Responsiveness is pure CSS - `hidden lg:flex` removes the sidebar from the
// layout entirely below the lg breakpoint, where the bottom tab bar takes
// over; the retired JS viewport-collapse / icon-rail mechanics are gone. The
// only collapse control is the user's own toggle, persisted per role by the
// AppShell (spec decision 6).

import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

import { NAV_CONFIG } from "./nav-config";
import { NavItemLink } from "./NavItemLink";
import type { Role } from "./types";

interface SidebarProps {
  role: Role;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({ role, collapsed, onToggleCollapse }: SidebarProps) {
  const items = NAV_CONFIG[role];

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col overflow-y-auto border-r border-hairline bg-surface transition-[width] duration-200 lg:flex",
        collapsed ? "w-16" : "w-60",
      )}
      data-collapsed={collapsed || undefined}
      data-testid="sidebar"
    >
      <div className="flex h-14 shrink-0 items-center overflow-hidden border-b border-hairline px-4">
        {!collapsed && (
          <span className="text-base font-semibold whitespace-nowrap text-accent">
            CareSetu
          </span>
        )}
      </div>

      <nav className="flex-1 p-2" data-testid="sidebar-nav">
        {items.map((item) => (
          <NavItemLink
            key={item.key}
            item={item}
            variant="sidebar"
            hideLabel={collapsed}
          />
        ))}
      </nav>

      <div className="shrink-0 border-t border-hairline-soft p-2">
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          data-testid="sidebar-toggle"
          className="flex min-h-11 w-full items-center gap-3 rounded px-3 text-sm font-medium text-txt-sub hover:bg-accent-soft hover:text-txt"
        >
          {collapsed ? (
            <ChevronRight size={20} className="shrink-0" />
          ) : (
            <ChevronLeft size={20} className="shrink-0" />
          )}
          {!collapsed && <span>Collapse sidebar</span>}
        </button>
      </div>
    </aside>
  );
}
