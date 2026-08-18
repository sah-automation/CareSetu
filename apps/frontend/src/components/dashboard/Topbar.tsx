"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { IconChevronRight } from "@/components/auth/icons";
import { roleLabel } from "./types";
import type { Role } from "./types";

export function Topbar() {
  const { user, selectedRole, switchRole, logout } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const otherRoles = (user?.roles ?? []).filter(
    (r): r is Role =>
      r !== selectedRole && ["patient", "partner", "operator"].includes(r),
  );

  return (
    <header
      className="fixed right-0 top-0 z-30 flex h-14 items-center justify-between border-b border-hairline bg-surface px-4"
      data-testid="topbar"
    >
      <div className="flex items-center gap-3">
        <span className="text-sm text-txt-muted">{user?.phone}</span>
        {selectedRole && (
          <span className="rounded bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
            {roleLabel(selectedRole as Role)}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        {otherRoles.length > 0 && (
          <div className="relative" ref={dropdownRef}>
            <button
              type="button"
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-1 rounded border border-hairline px-2 py-1 text-xs text-txt-sub hover:bg-hairline-soft"
              data-testid="role-switcher"
            >
              Switch role
              <IconChevronRight size={12} />
            </button>

            {dropdownOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded border border-hairline bg-surface shadow-pop">
                {otherRoles.map((role) => (
                  <button
                    key={role}
                    type="button"
                    onClick={() => {
                      switchRole(role);
                      setDropdownOpen(false);
                    }}
                    className="flex w-full items-center px-3 py-2 text-left text-sm text-txt-sub hover:bg-hairline-soft"
                    data-testid={`switch-to-${role}`}
                  >
                    {roleLabel(role)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={logout}
          className="rounded px-2 py-1 text-xs text-txt-muted hover:bg-hairline-soft hover:text-txt"
          data-testid="logout-button"
        >
          Logout
        </button>
      </div>
    </header>
  );
}
