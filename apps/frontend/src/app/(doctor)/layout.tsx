// PHASE-2.6 T07 (#198): doctor route group under the full-density AppShell.
// No staff session can reach it until Phase 5 staff auth exists; the stub
// page proves the shell renders and gives the nav-config queue entry a real
// destination. See (patient)/layout.tsx for the group-split rationale.
//
// #583: the shared DoctorProfileProvider mounts here, wrapping the shell rather
// than sitting inside it, so it sits above both the console chrome and every
// page beneath it. That is the whole structural reason the account avatar and
// the Profile page can never disagree: they read one source. The same mounting
// is what scopes the doctor profile read to this group - the partner and
// operator layouts mount no provider at all, so there is no code path in which
// a non-doctor staff shell starts a doctor read.

import type { ReactNode } from "react";

import { AppShell } from "@/components/dashboard/AppShell";
import { DoctorProfileProvider } from "@/lib/doctor/DoctorProfileContext";

export default function DoctorGroupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <DoctorProfileProvider>
      <AppShell role="doctor">{children}</AppShell>
    </DoctorProfileProvider>
  );
}
