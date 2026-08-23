"use client";

// PHASE-2.6 T06 (#197): shared top bar, one component for both densities
// (blueprint §2.3/§2.8). Light shell (patient): brand wordmark + slim desktop
// top-nav derived from the same nav-config as the mobile tabs - at most five
// non-center destinations in config order, matching the finalized
// PROTO-PHASE-2.6 view - plus the language toggle; never a sidebar. Full
// shell (doctor/partner/operator): page-title slot on the left (breadcrumbs
// land here in a later ticket); the sidebar carries the brand. Both densities
// end in the §2.6 account cluster.

import { NAV_CONFIG, TABBAR_MAX_DESTINATIONS } from "./nav-config";
import type { NavItemDef } from "./nav-config";
import { AccountMenu } from "./AccountMenu";
import { LangToggle } from "./LangToggle";
import { NavItemLink } from "./NavItemLink";
import type { Role } from "./types";

export type TopbarDensity = "light" | "full";

interface TopbarProps {
  density: TopbarDensity;
  role: Role;
}

const TOPNAV_PATIENT: NavItemDef[] = NAV_CONFIG.patient
  .filter((item) => !item.center)
  .slice(0, TABBAR_MAX_DESTINATIONS);

export function Topbar({ density, role }: TopbarProps) {
  return (
    <header
      className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-hairline bg-surface px-4"
      data-density={density}
      data-testid="topbar"
    >
      {density === "light" && (
        <>
          <span className="text-lg font-semibold whitespace-nowrap text-accent">
            CareSetu
          </span>
          <nav
            aria-label="Primary"
            className="hidden items-center gap-1 lg:flex"
            data-testid="topnav"
          >
            {TOPNAV_PATIENT.map((item) => (
              <NavItemLink key={item.key} item={item} variant="topnav" />
            ))}
          </nav>
        </>
      )}
      {density === "full" && (
        <div
          className="min-w-0 flex-1 truncate text-sm font-semibold text-txt"
          data-testid="topbar-page-slot"
        />
      )}
      <div
        className={`flex items-center gap-2 ${
          density === "full" ? "" : "ms-auto"
        }`}
      >
        {density === "light" && <LangToggle />}
        <AccountMenu />
      </div>
    </header>
  );
}
