// PHASE-2.6 T07 (#198): partner route group under the full-density AppShell.
// One console serves lab and chemist, type-filtered by account attribute
// (blueprint §7.1). See (patient)/layout.tsx for the group-split rationale.

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";

export default function PartnerGroupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShell role="partner">{children}</AppShell>;
}
