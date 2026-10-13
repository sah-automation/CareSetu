"use client";

// #708 C2a: the operator Observability overview - the surface's landing page
// (plan-phase14-observability §9.2). One number per question the console opens
// with, read in one call: is the AI bill on plan (GET
// /v1/operator/observability/overview), is the AI working, is anything broken,
// and how stale the telemetry itself is.
//
// The figures come from /overview rather than from each panel's own read so a
// tile can never disagree with the page behind it: the backend computes
// `spend_paise` from the same aggregate `/cost` headlines (facade.Overview).
//
// #709 (C2b) landed the panels these tiles drill into, so the tiles are live
// links again - the doctor dashboard's whole-card `Link` shape (#681) - except
// open alerts, whose feed is #712 and must not link to a page that does not
// exist. `formatPct`/`formatDuration` moved to lib/operator/observability-format
// so the panels format a rate exactly as this page does.
//
// Reuses the doctor dashboard's KpiTile/KpiRow pattern
// (app/(doctor)/doctor/page.tsx): a tile shows a skeleton while its read is in
// flight and an em dash once a rate proves unmeasurable, never a fabricated
// zero. A deployment the nightly rollup has never covered is an EMPTY page
// rather than a wall of dashes - "no telemetry yet" is a different fact from
// "telemetry that says nothing is wrong".

import Link from "next/link";

import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { PanelTabs } from "@/components/observability/ObservabilityPanelPage";
import { formatInrPaise } from "@/lib/money";
import { fetchOverview, type Overview } from "@/lib/operator/observability";
import { formatDuration, formatPct } from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

interface KpiTileProps {
  testId: string;
  label: string;
  value: string;
  /** The figure's denominator or context ("of ₹5,000 budget"). */
  hint?: string;
  pending: boolean;
  /** `critical` once the budget is exhausted; absent otherwise. */
  tone?: "critical";
  /**
   * The panel this tile summarises. Absent only for the open-alerts tile,
   * whose alert feed is #712 - a tile with no destination renders as a card,
   * because a live link to a page that does not exist is the dead navigation
   * the nav's `soon` flag exists to prevent.
   */
  href?: string;
}

/**
 * The headline-KPI tile, mirroring the doctor dashboard's: the value carries
 * the test hook, the label and hint sit under it. A tile whose panel exists is
 * a whole-card link to it (the doctor's `KpiTile` shape, #681); a tile whose
 * panel is still a ticket renders as a plain card, which is what #708 shipped
 * while every panel was #709.
 */
function KpiTile({
  testId,
  label,
  value,
  hint,
  pending,
  tone,
  href,
}: KpiTileProps) {
  const className =
    "flex flex-col gap-1 rounded-lg border border-hairline bg-surface p-4";
  const toneClassName = tone === "critical" ? "text-danger" : "text-txt";
  const body = (
    <>
      {pending ? (
        <span
          data-testid={`${testId}-value`}
          className="h-7 w-12 animate-pulse rounded bg-hairline-soft"
        />
      ) : (
        <span
          className={`text-2xl font-semibold ${toneClassName}`}
          data-testid={`${testId}-value`}
        >
          {value}
        </span>
      )}
      <span className="text-xs text-txt-muted">{label}</span>
      {!pending && hint && <span className="text-xs text-txt-sub">{hint}</span>}
    </>
  );

  if (!href) {
    return (
      <div data-testid={testId} data-tone={tone} className={className}>
        {body}
      </div>
    );
  }

  return (
    <Link
      href={href}
      data-testid={testId}
      data-tone={tone}
      className={`${className} transition-[box-shadow,transform] hover:-translate-y-0.5 hover:shadow-pop focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring`}
    >
      {body}
    </Link>
  );
}

/**
 * The tile labels, declared once so the pending row and the loaded row cannot
 * disagree about what a tile is called. Only the value is ever a skeleton -
 * a label that flickered with the load would make the loading state read as a
 * different set of tiles.
 */
const LABELS = {
  aiSpend: "AI spend this period",
  budgetUsed: "Budget used",
  aiCalls: "AI calls",
  successRate: "Success rate",
  lowConfidence: "Low-confidence rate",
  p95Latency: "p95 latency",
  openAlerts: "Open alerts",
  openBreakers: "Open breakers",
} as const;

/**
/** One resolved tile: the figure, its context line, and any alert tone. */
interface TileSpec {
  testId: string;
  label: string;
  value: string;
  hint?: string;
  tone?: "critical";
  /** The panel this tile drills into; absent while that panel is unbuilt. */
  href?: string;
}

/** The panel routes each KPI tile summarises (#709). */
const PANEL_HREFS = {
  cost: "/operator/observability/cost",
  usage: "/operator/observability/usage",
  quality: "/operator/observability/quality",
  health: "/operator/observability/health",
} as const;

/**
 * The headline row's tiles, in display order: the bill, the AI's health, what
 * is broken. Built once from the overview so a tile cannot be declared without
 * a test id, and so the pending state is one branch rather than eight.
 */
function tileSpecs(overview: Overview): TileSpec[] {
  // An exhausted budget tones the two SPEND tiles only. Toning all eight would
  // paint a healthy success rate, a fine latency and an empty alert feed red,
  // which reads as "everything is broken" when the truth is "the bill is over".
  const spendTone = overview.budget_exhausted
    ? ("critical" as const)
    : undefined;

  return [
    {
      testId: "kpi-ai-spend",
      label: LABELS.aiSpend,
      value: formatInrPaise(overview.spend_paise),
      hint: `of ${formatInrPaise(overview.budget_paise)} budget`,
      tone: spendTone,
      href: PANEL_HREFS.cost,
    },
    {
      testId: "kpi-budget-used",
      label: LABELS.budgetUsed,
      value: formatPct(overview.budget_utilization_pct),
      hint: overview.budget_exhausted
        ? "exhausted"
        : `${formatInrPaise(
            overview.budget_paise - overview.spend_paise,
          )} remaining`,
      tone: spendTone,
      href: PANEL_HREFS.cost,
    },
    {
      testId: "kpi-ai-calls",
      label: LABELS.aiCalls,
      value: String(overview.total_calls),
      hint: `last ${overview.days} days`,
      href: PANEL_HREFS.usage,
    },
    {
      testId: "kpi-success-rate",
      label: LABELS.successRate,
      value: formatPct(overview.success_rate),
      hint: `${overview.success_count} of ${overview.total_calls} calls`,
      href: PANEL_HREFS.quality,
    },
    {
      testId: "kpi-low-confidence",
      label: LABELS.lowConfidence,
      value: formatPct(overview.low_confidence_rate),
      hint: `${overview.low_confidence_count} completions flagged`,
      href: PANEL_HREFS.quality,
    },
    {
      testId: "kpi-p95-latency",
      label: LABELS.p95Latency,
      value: formatDuration(overview.p95_duration_ms),
      hint: "slowest provider",
      href: PANEL_HREFS.health,
    },
    {
      // No href: the alert feed is #712. The tile stays a card until its
      // destination exists rather than linking to a page that does not.
      testId: "kpi-open-alerts",
      label: LABELS.openAlerts,
      value: String(overview.open_alerts),
      hint: `${overview.critical_open_alerts} critical`,
    },
    {
      testId: "kpi-open-breakers",
      label: LABELS.openBreakers,
      value: String(overview.open_breakers),
      hint: "circuits tripped",
      href: PANEL_HREFS.health,
    },
  ];
}

/**
 * The headline row: bill, AI health, breakage. `overview` is `null` while the
 * read is in flight, which renders the same tiles pending rather than a
 * separate skeleton block - the tiles hold their place, so nothing below them
 * has to move when the numbers land.
 */
function KpiRow({ overview }: { overview: Overview | null }) {
  const specs = overview === null ? PENDING_TILES : tileSpecs(overview);

  return (
    <section className="mb-6" data-testid="observability-kpis">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {specs.map((spec) => (
          <KpiTile
            key={spec.testId}
            testId={spec.testId}
            label={spec.label}
            value={spec.value}
            hint={spec.hint}
            pending={overview === null}
            tone={spec.tone}
            href={spec.href}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * The same tiles with no figures, which is what a read in flight renders: the
 * labels stay put so the loading state reads as the same dashboard rather than
 * a different one.
 */
const PENDING_TILES: TileSpec[] = [
  ["kpi-ai-spend", LABELS.aiSpend],
  ["kpi-budget-used", LABELS.budgetUsed],
  ["kpi-ai-calls", LABELS.aiCalls],
  ["kpi-success-rate", LABELS.successRate],
  ["kpi-low-confidence", LABELS.lowConfidence],
  ["kpi-p95-latency", LABELS.p95Latency],
  ["kpi-open-alerts", LABELS.openAlerts],
  ["kpi-open-breakers", LABELS.openBreakers],
].map(([testId, label]) => ({ testId, label, value: "" }));

/**
 * Nothing has ever been rolled and nothing has been called: every rate would
 * read as an em dash, so the page says the one true thing instead.
 */
function hasNoTelemetry(overview: Overview): boolean {
  return overview.total_calls === 0 && overview.last_rolled_date === null;
}

export default function ObservabilityOverviewPage() {
  const {
    data: overview,
    status,
    errorTraceId,
    bannerOpen,
    reload: load,
    dismissBanner,
  } = usePanelRead(fetchOverview);

  const empty =
    status === "ready" && overview !== null && hasNoTelemetry(overview);

  return (
    <>
      <PageHeader
        title="Observability"
        description={
          overview
            ? `AI spend, quality and reliability over the last ${overview.days} days.`
            : "AI spend, quality and reliability."
        }
      />

      <PanelTabs current="overview" />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message="Could not load the observability overview."
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={dismissBanner}
        />
      )}

      {status === "loading" && <KpiRow overview={null} />}

      {status === "ready" && overview !== null && !empty && (
        <>
          <KpiRow overview={overview} />
          <p
            className="text-xs text-txt-muted"
            data-testid="observability-rollup-age"
          >
            {overview.last_rolled_date
              ? `Telemetry as of ${overview.last_rolled_date}`
              : "Telemetry not yet rolled"}
          </p>
        </>
      )}

      {empty && (
        <EmptyState
          title="No telemetry yet"
          body="The nightly rollup has not recorded any AI activity for this window."
        />
      )}
    </>
  );
}
