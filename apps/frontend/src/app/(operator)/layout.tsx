// PHASE-2.6 T07 (#198): operator route group under the full-density AppShell.
// See (patient)/layout.tsx for the group-split rationale.

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";

export default function OperatorGroupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShell role="operator">{children}</AppShell>;
}
