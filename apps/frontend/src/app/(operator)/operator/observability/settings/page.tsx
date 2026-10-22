// #747 (spec #717 out-of-scope note): Settings is a destination in the
// console's sub-menu, and this page is the placeholder shell behind it. The
// Batch 2 settings surface - AI configuration, notification configuration,
// feature flags and user management - stays out of scope; the shell exists so
// the destination is real (a live page, not a coming-soon stub) and so the
// boundary is enforced by something an operator can actually visit.

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";

export default function ObservabilitySettingsPage() {
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
