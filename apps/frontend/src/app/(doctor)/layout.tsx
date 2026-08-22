// PHASE-2.6 T07 (#198): doctor route group under the full-density AppShell.
// No staff session can reach it until Phase 5 staff auth exists; the stub
// page proves the shell renders and gives the nav-config queue entry a real
// destination. See (patient)/layout.tsx for the group-split rationale.

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";

export default function DoctorGroupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShell role="doctor">{children}</AppShell>;
}
