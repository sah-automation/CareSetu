"use client";

// FEAT-015 (operator console) / #865, #866, #868: the operator tier chip shared
// by the account-menu identity header and the profile page's identity zone.
// Admin is accented, operator is muted, and the label comes from the
// operatorProfile namespace so Hindi parity holds in both places. The caller
// supplies the test id because each surface names its own chip.

import type { OperatorTier } from "@/lib/operator/api";
import { cn } from "@/lib/utils";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export function OperatorTierBadge({
  tier,
  testId,
}: {
  tier: OperatorTier | undefined;
  testId?: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorProfile;
  const isAdmin = tier === "admin";
  return (
    <span
      className={cn(
        "shrink-0 rounded px-1.5 py-0.5 text-xs font-medium",
        isAdmin ? "bg-accent-soft text-accent" : "bg-muted-soft text-muted",
      )}
      data-testid={testId}
    >
      {isAdmin ? t.tierAdmin : t.tierOperator}
    </span>
  );
}
