// #747 (spec #717 out-of-scope note): Settings is a destination in the
// console's sub-menu, and this page is the placeholder shell behind it. The
// Batch 2 settings surface - AI configuration, notification configuration,
// feature flags and user management - stays out of scope; the shell exists so
// the destination is real (a live page, not a coming-soon stub) and so the
// boundary is enforced by something an operator can actually visit.
// #796: admin-only - direct navigation renders a clear permission state for
// non-admin operators.

"use client";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { useAuth } from "@/lib/auth/AuthContext";

function useAuthOrNull() {
  try {
    return useAuth();
  } catch {
    return null;
  }
}

export default function ObservabilitySettingsPage() {
  const auth = useAuthOrNull();
  const isAdmin =
    auth?.user?.roles?.includes("operator") === true &&
    auth?.user?.tier === "admin";

  if (!isAdmin) {
    return (
      <>
        <PageHeader
          title="Settings"
          description="Configuration for the operator console."
        />
        <EmptyState
          title="Permission denied"
          body="You do not have permission to access Settings."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Configuration for the operator console."
      />
      <EmptyState
        title="Nothing to configure yet"
        body="Operating settings arrive with a later batch. Until then there is nothing to set on this page."
      />
    </>
  );
}
