"use client";

// PHASE-2.6 T06 (#197): the single top-right account cluster (blueprint §2.6)
// - phone, role badge, switch-role, and logout consolidated into one dropdown
// behind an avatar-icon trigger, matching the finalized PROTO-PHASE-2.6
// views. Extracted from the pre-T06 Topbar.

import { useAuth } from "@/lib/auth/AuthContext";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { isAppRole, resolveRole, roleLabel } from "./types";

// Stale sessions can carry a user whose JSON predates the T05 additive
// phone field (absent or empty at runtime despite the non-optional type);
// the menu degrades to the subject id rather than crashing (#199 handoff).
function identityLine(user: { phone?: string; id: number } | null): string {
  if (!user) {
    return "";
  }
  return user.phone || `Subject #${user.id}`;
}

export function AccountMenu() {
  const { user, selectedRole, switchRole, logout } = useAuth();
  const currentRole = resolveRole(selectedRole);
  const otherRoles = (user?.roles ?? [])
    .filter(isAppRole)
    .filter((role) => role !== currentRole);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          data-testid="account-menu"
          className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent-strong hover:bg-accent-border"
        >
          {(user?.phone || "?").slice(-2)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel className="flex items-center justify-between gap-2 font-normal">
          <span className="text-sm text-txt">{identityLine(user)}</span>
          <span
            className="rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent"
            data-testid="account-menu-role-badge"
          >
            {roleLabel(currentRole)}
          </span>
        </DropdownMenuLabel>
        {otherRoles.map((role) => (
          <DropdownMenuItem
            key={role}
            onSelect={() => switchRole(role)}
            data-testid={`switch-to-${role}`}
          >
            Switch to {roleLabel(role)}
          </DropdownMenuItem>
        ))}
        {otherRoles.length > 0 && <DropdownMenuSeparator />}
        <DropdownMenuItem onSelect={() => logout()} data-testid="logout-button">
          Logout
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
