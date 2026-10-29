"use client";

// #781: the operator Security page (PHASE-14B Batch 2).
// Shows auth/lockout trends, consent/rate-limit anomalies, CSP violations,
// prompt-injection counts, and webhook monitoring status.

import { cn } from "@/lib/utils";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  fetchSecurity,
  type SecuritySummary,
  type SecuritySignalView,
  type CspAggregateView,
} from "@/lib/operator/observability";
import { usePanelRead } from "@/lib/operator/usePanelRead";

const NO_SECURITY_BODY = "The security scan has not recorded any signals yet.";

const DEFERRED_BADGE_CLASS =
  "inline-flex items-center rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-txt";

const ACTIVE_BADGE_CLASS =
  "inline-flex items-center rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success";

function SignalBadge({
  deferred,
  label,
}: {
  deferred: boolean;
  label: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        deferred ? DEFERRED_BADGE_CLASS : ACTIVE_BADGE_CLASS,
        "whitespace-nowrap",
      )}
      data-testid={`signal-badge-${deferred ? "deferred" : "active"}`}
    >
      {label}
    </span>
  );
}

function SignalRow({ signal }: { signal: SecuritySignalView }) {
  const isDeferred = signal.is_deferred;
  const alertKind = signal.alert_kind ?? "-";
  const threshold = signal.threshold ?? "-";
  const count = signal.count_last_5m;

  return (
    <tr
      className="border-b border-hairline-soft"
      data-testid={`signal-row-${signal.signal_kind}`}
    >
      <th scope="row" className="py-2 pr-3 text-left font-normal text-txt">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm">{signal.signal_kind}</span>
          <SignalBadge
            deferred={isDeferred}
            label={isDeferred ? "Deferred" : "Active"}
          />
        </div>
      </th>
      <td className="py-2 pr-3 text-right tabular-nums text-txt-sub">
        {count.toLocaleString("en-IN")}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-txt-sub">
        {threshold === "-" ? "-" : threshold.toLocaleString("en-IN")}
      </td>
      <td className="py-2 pr-3 text-right font-mono text-xs text-txt-muted">
        {alertKind}
      </td>
      {isDeferred && (
        <td className="py-2 pr-3 text-left text-xs text-txt-muted" colSpan={3}>
          {signal.deferred_reason}
        </td>
      )}
    </tr>
  );
}

function CspRow({ csp }: { csp: CspAggregateView }) {
  return (
    <tr
      className="border-b border-hairline-soft"
      data-testid={`csp-row-${csp.directive}-${csp.disposition}`}
    >
      <td className="py-2 pr-3 font-mono text-xs text-txt">{csp.directive}</td>
      <td className="py-2 pr-3 text-txt-sub">{csp.disposition}</td>
      <td className="py-2 pr-3 text-txt-sub">{csp.blocked_source}</td>
      <td className="py-2 pr-3 text-right tabular-nums text-txt-sub">
        {csp.count.toLocaleString("en-IN")}
      </td>
    </tr>
  );
}

export default function ObservabilitySecurityPage() {
  const security = usePanelRead(() => fetchSecurity());

  return (
    <ObservabilityPanelPage
      title="Security"
      description="Auth trends, lockout signals, CSP violations, and webhook monitoring status."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="security-signals"
          title="Security signals (last 5 minutes)"
          read={security}
          isEmpty={(data) => data.signals.length === 0}
          emptyTitle="No security signals"
          emptyBody={NO_SECURITY_BODY}
          errorMessage="Could not load security signals."
          takeaway={
            security.data
              ? `Webhook monitoring: ${security.data.webhook_monitoring_status} - ${security.data.webhook_monitoring_reason}`
              : undefined
          }
        >
          {(data) => (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-xs text-txt-muted">
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Signal kind
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 text-right font-medium"
                    >
                      Count (5m)
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 text-right font-medium"
                    >
                      Threshold
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 text-right font-medium"
                    >
                      Alert kind
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.signals.map((signal) => (
                    <SignalRow key={signal.signal_kind} signal={signal} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="security-csp"
          title="CSP violations (daily aggregate)"
          read={security}
          isEmpty={(data) => data.csp_aggregates.length === 0}
          emptyTitle="No CSP violations"
          emptyBody="The CSP report collector has not received any violations yet."
          errorMessage="Could not load CSP aggregates."
        >
          {(data) => (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-xs text-txt-muted">
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Directive
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Disposition
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Blocked source
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 text-right font-medium"
                    >
                      Count
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.csp_aggregates.map((csp, idx) => (
                    <CspRow key={idx} csp={csp} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="security-prompt-injection"
          title="Prompt-injection findings"
          read={security}
          isEmpty={(data) => data.prompt_injection_count === 0}
          emptyTitle="No prompt-injection findings"
          emptyBody="The pre-egress screen has not detected any injection attempts."
          errorMessage="Could not load prompt-injection counts."
        >
          {(data) => (
            <div className="flex items-center gap-4">
              <div className="text-3xl font-bold tabular-nums text-txt">
                {data.prompt_injection_count.toLocaleString("en-IN")}
              </div>
              <div className="text-xs text-txt-muted">
                Total findings in the current scan window
              </div>
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="security-webhook"
          title="Webhook signature monitoring"
          read={security}
          isEmpty={() => false}
          emptyTitle="-"
          emptyBody="-"
          errorMessage="Could not load webhook monitoring status."
        >
          {(data) => (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <SignalBadge
                  deferred={data.webhook_monitoring_status === "deferred"}
                  label={
                    data.webhook_monitoring_status === "deferred"
                      ? "Deferred"
                      : "Active"
                  }
                />
                <span className="text-sm text-txt">
                  {data.webhook_monitoring_reason}
                </span>
              </div>
              <p className="text-xs text-txt-muted">
                The <code className="font-mono">webhook_signature_failure</code>{" "}
                event and alert kind are reserved in the registries. When an
                inbound webhook is added, the producer will emit using the
                reserved name and monitoring will activate automatically.
              </p>
              <p className="text-xs text-txt-muted">
                Reference: <code className="font-mono">ADR-0032</code> (accepted
                risk)
              </p>
            </div>
          )}
        </ReadPanel>
      </div>
    </ObservabilityPanelPage>
  );
}
