"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  IconHome,
  IconDirectory,
  IconFlask,
  IconShield,
  IconBell,
  IconInbox,
  IconCheck,
  IconSearch,
  IconChevronLeft,
  IconChevronRight,
} from "@/components/auth/icons";
import type { Role } from "./types";
import { SIDEBAR_WIDTH_COLLAPSED, SIDEBAR_WIDTH_EXPANDED } from "./types";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  soon?: boolean;
}

const NAV_CONFIG: Record<Role, NavItem[]> = {
  patient: [
    { label: "Home", href: "/patient", icon: IconHome },
    {
      label: "My Records",
      href: "/patient/records",
      icon: IconDirectory,
      soon: true,
    },
    {
      label: "Appointments",
      href: "/patient/appointments",
      icon: IconInbox,
      soon: true,
    },
    {
      label: "Medicines",
      href: "/patient/medicines",
      icon: IconFlask,
      soon: true,
    },
    {
      label: "Consent",
      href: "/patient/consent",
      icon: IconShield,
      soon: true,
    },
    {
      label: "Notifications",
      href: "/patient/notifications",
      icon: IconBell,
      soon: true,
    },
  ],
  partner: [
    { label: "Home", href: "/partner", icon: IconHome },
    {
      label: "Active Cases",
      href: "/partner/cases",
      icon: IconInbox,
      soon: true,
    },
    {
      label: "My Profile",
      href: "/partner/profile",
      icon: IconDirectory,
      soon: true,
    },
    {
      label: "Settlements",
      href: "/partner/settlements",
      icon: IconCheck,
      soon: true,
    },
  ],
  operator: [
    { label: "Home", href: "/operator", icon: IconHome },
    {
      label: "User Management",
      href: "/operator/users",
      icon: IconDirectory,
      soon: true,
    },
    {
      label: "Moderation",
      href: "/operator/moderation",
      icon: IconShield,
      soon: true,
    },
    {
      label: "Audit Trail",
      href: "/operator/audit",
      icon: IconSearch,
      soon: true,
    },
  ],
};

interface SidebarProps {
  role: Role;
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ role, collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const items = NAV_CONFIG[role];

  return (
    <aside
      className={`fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-hairline bg-surface transition-all duration-200 ${
        collapsed ? SIDEBAR_WIDTH_COLLAPSED : SIDEBAR_WIDTH_EXPANDED
      }`}
      data-testid="sidebar"
    >
      <div className="flex h-14 items-center justify-between border-b border-hairline px-3">
        {!collapsed && (
          <span className="text-sm font-semibold text-txt">CareSetu</span>
        )}
        <button
          type="button"
          onClick={onToggle}
          className="flex h-8 w-8 items-center justify-center rounded text-txt-muted hover:bg-hairline-soft"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          data-testid="sidebar-toggle"
        >
          {collapsed ? (
            <IconChevronRight size={16} />
          ) : (
            <IconChevronLeft size={16} />
          )}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-2" data-testid="sidebar-nav">
        {items.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.soon ? "#" : item.href}
              className={`flex items-center gap-3 px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-txt-sub hover:bg-hairline-soft hover:text-txt"
              } ${item.soon ? "pointer-events-none opacity-50" : ""}`}
              aria-disabled={item.soon}
              data-testid={`nav-${item.label
                .toLowerCase()
                .replace(/\s+/g, "-")}`}
            >
              <Icon size={20} />
              {!collapsed && (
                <>
                  <span className="flex-1">{item.label}</span>
                  {item.soon && (
                    <span className="rounded bg-hairline px-1.5 py-0.5 text-[10px] font-medium text-txt-muted">
                      Soon
                    </span>
                  )}
                </>
              )}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
