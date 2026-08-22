"use client";

// PHASE-2.6 T06 (#197): the generic dashboard group renders through the
// shared AppShell family, parameterized by the session's selected role. The
// retired JS viewport-collapse mechanics are gone - viewport behavior lives
// entirely in CSS inside the shells. Route-group split and guards are
// ticket 07. Session state comes from the root-layout AuthProvider
// (PHASE-2.6 T01, #192).

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";
import { resolveRole } from "@/components/dashboard/types";
import { useAuth } from "@/lib/auth/AuthContext";

function DashboardChrome({ children }: { children: ReactNode }) {
  const { selectedRole, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-page-bg">
        <div className="text-sm text-txt-muted">Loading...</div>
      </div>
    );
  }

  return <AppShell role={resolveRole(selectedRole)}>{children}</AppShell>;
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <DashboardChrome>{children}</DashboardChrome>;
}
