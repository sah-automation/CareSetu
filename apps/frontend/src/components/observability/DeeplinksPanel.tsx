"use client";

// #710 C3, widened by #736: the operator Observability deep-links panel
// (plan-phase14 §9.2, §3). One panel reads GET
// /v1/operator/observability/deeplinks and renders outbound links to Grafana,
// Sentry and Langfuse, so the operator can drill from a poor in-app number into the
// raw traces, errors and AI spans.
//
// The rule the backend enforces and this panel honours: an unconfigured vendor is
// ABSENT from the response, not `null` in it, and every link it does send already
// carries its filter (a dashboard with its range and variables, an Explore pane for
// one trace, a Sentry query narrowed to this service, a Langfuse view for this model,
// task, actor or session). So the panel renders the links that came back and omits
// the rest; it never falls back to a placeholder href. A deployment with only
// Sentry shows only Sentry's links, and a panel that knows no trace shows a
// dashboard but no Explore pane.
//
// Outbound, in a new tab, `noopener noreferrer` - and no PHI in any link: the
// filters are a dashboard range, a service name, a model and a task, never a patient
// or a conversation (plan §10).

import { ExternalLink } from "lucide-react";

import { ReadPanel } from "@/components/observability/ObservabilityPanelPage";
import type {
  Deeplinks,
  GrafanaDeeplinks,
  LangfuseDeeplinks,
  SentryDeeplinks,
} from "@/lib/operator/observability";
import type { PanelRead } from "@/lib/operator/usePanelRead";

type VendorKey = "grafana" | "sentry" | "langfuse";

/** The three vendors, in the order an operator reaches for them. */
const VENDORS: { key: VendorKey; label: string }[] = [
  { key: "grafana", label: "Grafana" },
  { key: "sentry", label: "Sentry" },
  { key: "langfuse", label: "Langfuse" },
];

interface VendorLink {
  /** `vendor.key`, so a test id and a React key both name where it came from. */
  id: string;
  label: string;
  href: string;
}

/**
 * The links one vendor's group carries, in the order an operator wants them.
 *
 * Typed against the group's OWN keys, so naming a key the group does not have is a
 * compile error rather than a row that silently never renders - the failure mode
 * when a panel reads an untyped object.
 *
 * A link the group does not carry is dropped rather than rendered disabled: there
 * is no honest way to show a "Sentry trace" link on a panel with no trace, because
 * the thing it would open does not exist.
 */
function linksOf<T extends object>(
  vendor: VendorKey,
  group: T | undefined,
  wanted: readonly (readonly [Extract<keyof T, string>, string])[],
): VendorLink[] {
  if (!group) return [];
  return wanted.flatMap(([key, label]) => {
    const href = group[key];
    return typeof href === "string" && href.length > 0
      ? [{ id: `${vendor}.${key}`, label, href }]
      : [];
  });
}

function renderableLinks(links: Deeplinks, vendor: VendorKey): VendorLink[] {
  switch (vendor) {
    case "grafana":
      return linksOf<GrafanaDeeplinks>(vendor, links.grafana, [
        ["dashboard_url", "Dashboard"],
        ["explore_url", "This trace in Explore"],
      ]);
    case "sentry":
      return linksOf<SentryDeeplinks>(vendor, links.sentry, [
        ["issues_url", "This service's issues"],
        ["trace_url", "This trace"],
      ]);
    case "langfuse":
      return linksOf<LangfuseDeeplinks>(vendor, links.langfuse, [
        ["traces_url", "This model's traces"],
        ["trace_url", "This trace"],
        ["actor_url", "This actor"],
        ["session_url", "This session"],
      ]);
  }
}

/** Every vendor switched off, or every link unfiltered, is the panel's empty state. */
function noLinksConfigured(links: Deeplinks): boolean {
  return VENDORS.every(
    (vendor) => renderableLinks(links, vendor.key).length === 0,
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
          className="flex flex-col gap-3"
          data-testid="observability-deeplinks-list"
        >
          {VENDORS.flatMap((vendor) => {
            const vendorLinks = renderableLinks(links, vendor.key);
            if (vendorLinks.length === 0) return [];
            return [
              <li
                key={vendor.key}
                className="flex flex-wrap items-center gap-2"
              >
                <span className="text-xs font-medium uppercase tracking-wide text-txt-sub">
                  {vendor.label}
                </span>
                {vendorLinks.map((link) => (
                  <a
                    key={link.id}
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid={`observability-deeplink-${link.id}`}
                    className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-hairline bg-surface px-3 text-sm font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                  >
                    {link.label}
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  </a>
                ))}
              </li>,
            ];
          })}
        </ul>
      )}
    </ReadPanel>
  );
}
