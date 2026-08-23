// PHASE-2.6 T07 (#198): the generic dashboard group split into per-role route
// groups (blueprint §2.1). The path prefix fixes the shell role, so each
// group layout pins the shared AppShell family to one role instead of
// resolving it from the session's selectedRole. Unauthenticated hits are
// redirected by the cookie-presence proxy (src/proxy.ts, ADR-0005); wrong-
// role enforcement stays client-side UX - real authorization is gateway RBAC.

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";

export default function PatientGroupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShell role="patient">{children}</AppShell>;
}
