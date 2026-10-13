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
// The cost/usage/quality/latency panels are #709; this page is the KPIs only.
//
// Reuses the doctor dashboard's KpiTile/KpiRow pattern
// (app/(doctor)/doctor/page.tsx): a tile shows a skeleton while its read is in
// flight and an em dash once a rate proves unmeasurable, never a fabricated
// zero. A deployment the nightly rollup has never covered is an EMPTY page
// rather than a wall of dashes - "no telemetry yet" is a different fact from
// "telemetry that says nothing is wrong".

import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { ApiError } from "@/lib/api-errors";
import { formatInrPaise } from "@/lib/money";
import { fetchOverview, type Overview } from "@/lib/operator/observability";

type LoadStatus = "loading" | "ready" | "error";

/** An unmeasured figure (see facade.Overview: a `null` rate, never a zero). */
const DASH = "\u2014";

interface KpiTileProps {
  testId: string;
  label: string;
  value: string;
  /** The figure's denominator or context ("of ₹5,000 budget"). */
  hint?: string;
  pending: boolean;
  /** `critical` once the budget is exhausted; absent otherwise. */
  tone?: "critical";
}

/**
 * The headline-KPI tile, mirroring the doctor dashboard's: the value carries
 * the test hook, the label and hint sit under it. Rendered as a card rather
 * than the doctor's `Link` because the panels these tiles would drill into are
 * #709 - a live link to a page that does not exist yet is the dead-navigation
 * failure the nav's `soon` flag exists to prevent.
 */
function KpiTile({ testId, label, value, hint, pending, tone }: KpiTileProps) {
  return (
    <div
      data-testid={testId}
      data-tone={tone}
      className="flex flex-col gap-1 rounded-lg border border-hairline bg-surface p-4"
    >
      {pending ? (
        <span
          data-testid={`${testId}-value`}
          className="h-7 w-12 animate-pulse rounded bg-hairline-soft"
        />
      ) : (
        <span
          className={
            tone === "critical"
              ? "text-2xl font-semibold text-danger"
              : "text-2xl font-semibold text-txt"
          }
          data-testid={`${testId}-value`}
        >
          {value}
        </span>
      )}
      <span className="text-xs text-txt-muted">{label}</span>
      {!pending && hint && <span className="text-xs text-txt-sub">{hint}</span>}
    </div>
  );
}

/**
 * Percentages read at one decimal, trailing zeros dropped: `95.0` is "95%" on a
 * tile and `2.6` is "2.6%". A `null` rate is the em dash, not a zero.
 */
function formatPct(value: number | null): string {
  if (value === null) return DASH;
  return `${Number(value.toFixed(1))}%`;
}

/** Latency in seconds past a second ("4.2s"), whole milliseconds below that. */
function formatDuration(ms: number | null): string {
  if (ms === null) return DASH;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${Number((ms / 1000).toFixed(1))}s`;
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
}

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
    },
    {
      testId: "kpi-ai-calls",
      label: LABELS.aiCalls,
      value: String(overview.total_calls),
      hint: `last ${overview.days} days`,
    },
    {
      testId: "kpi-success-rate",
      label: LABELS.successRate,
      value: formatPct(overview.success_rate),
      hint: `${overview.success_count} of ${overview.total_calls} calls`,
    },
    {
      testId: "kpi-low-confidence",
      label: LABELS.lowConfidence,
      value: formatPct(overview.low_confidence_rate),
      hint: `${overview.low_confidence_count} completions flagged`,
    },
    {
      testId: "kpi-p95-latency",
      label: LABELS.p95Latency,
      value: formatDuration(overview.p95_duration_ms),
      hint: "slowest provider",
    },
    {
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
  const [overview, setOverview] = useState<Overview | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    fetchOverview()
      .then((data) => {
        setOverview(data);
        setStatus("ready");
        setBannerOpen(false);
      })
      .catch((error: unknown) => {
        setErrorTraceId(error instanceof ApiError ? error.traceId : undefined);
        setStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message="Could not load the observability overview."
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
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
