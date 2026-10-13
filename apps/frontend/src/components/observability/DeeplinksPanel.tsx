"use client";

// #710 C3: the operator Observability deep-links panel (plan-phase14 §9.2,
// §3). One panel reads GET /v1/operator/observability/deeplinks and renders
// outbound links to Grafana, Sentry and Langfuse, so the operator can drill
// from a poor in-app number into the raw traces, errors and AI spans.
//
// The rule the backend already enforces and this panel must honour: an
// unconfigured vendor is an ABSENT link, never a broken one (domain/deeplinks.py
// - each key derives independently and returns null when unset). So the panel
// renders the keys that came back and omits the rest; it never falls back to a
// placeholder href. A deployment with only Sentry shows only a Sentry link.
//
// Outbound, in a new tab, `noopener noreferrer` - and no PHI in any link, since
// the URL is a fixed vendor project address (plan §10).

import { ExternalLink } from "lucide-react";

import { ReadPanel } from "@/components/observability/ObservabilityPanelPage";
import type { Deeplinks } from "@/lib/operator/observability";
import type { PanelRead } from "@/lib/operator/usePanelRead";

/** The three vendors, in the order an operator reaches for them. */
const VENDORS: { key: keyof Deeplinks; label: string }[] = [
  { key: "grafana", label: "Grafana" },
  { key: "sentry", label: "Sentry" },
  { key: "langfuse", label: "Langfuse" },
];

/** Every vendor switched off is the panel's one empty state. */
function noLinksConfigured(links: Deeplinks): boolean {
  return (
    links.grafana === null && links.sentry === null && links.langfuse === null
  );
}

export function DeeplinksPanel({ read }: { read: PanelRead<Deeplinks> }) {
  return (
    <ReadPanel
      testId="observability-deeplinks"
      title="Open in your tools"
      read={read}
      isEmpty={noLinksConfigured}
      emptyTitle="No vendor links configured"
      emptyBody="Grafana, Sentry and Langfuse are switched off for this deployment."
      errorMessage="Could not load the vendor links."
    >
      {(links) => (
        <ul
          className="flex flex-wrap gap-2"
          data-testid="observability-deeplinks-list"
        >
          {VENDORS.map((vendor) => {
            const href = links[vendor.key];
            if (href === null) return null;
            return (
              <li key={vendor.key}>
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid={`observability-deeplink-${vendor.key}`}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-hairline bg-surface px-3 text-sm font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                >
                  {vendor.label}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </ReadPanel>
  );
}
