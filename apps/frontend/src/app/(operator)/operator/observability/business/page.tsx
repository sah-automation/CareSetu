"use client";

// #737: the operator Business lens page (spec #717, plan-phase14 §9.2).
// Five panels, ONE read, four questions:
//   * "Is this spend healthy?"  <- the cap, what is consumed, where the month
//                                  lands. GET .../business
//   * "Where does it go?"        <- spend by task type, the one grain an
//                                  operator can act on.
//   * "What does a unit of value cost?"  <- per request, per completed task, per
//                                  patient, per doctor, cost of pass.
//   * "Who is heavy?"            <- the heaviest patients and doctors, with the
//                                  population they sit in.
//   * "Is it worth it?"          <- margin, which today reports a reason rather
//                                  than a figure.
// Plus the shared deep-links panel, so the page is not a dead end.
//
// One read, not five. Spend, cap, breakdown, unit costs and attribution are five
// answers to five questions about the SAME month; splitting them across routes
// would let the panels disagree - a breakdown that reconciles to a spend figure
// the headline no longer shows is worse than one honest failure. So the whole
// page shares one `usePanelRead`, and every panel fails together. Each panel
// still owns its own EMPTY state, because "nothing ran" is a different fact from
// "no revenue captured" and from "nothing attributed".
//
// Every state - loading, empty, failure with retry - belongs to the panel that
// owns the read (blueprint §9.1). The frame is ReadPanel, unchanged: this page
// contributes its reads, its copy and its charts, nothing else.

import {
  HeavyActorList,
  SpendAgainstCapChart,
  SpendByTaskTypeChart,
  UnitCostsList,
} from "@/components/observability/BusinessCharts";
import { DeeplinksPanel } from "@/components/observability/DeeplinksPanel";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  fetchBusiness,
  fetchDeeplinks,
  type BusinessPeriod,
  type BusinessRead,
} from "@/lib/operator/observability";
import {
  DASH,
  formatMoney,
  formatPct,
} from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

/** Nothing ran in this window - a fact about usage, not about configuration. */
const NO_SPEND_BODY =
  "No AI job ran in this window, so there is no spend to report.";

/** The breakdown has its own empty reason: the window had rows, but no tasks. */
const NO_BREAKDOWN_BODY =
  "AI jobs ran in this window but none recorded a task type to bill against.";

/**
 * Revenue is not captured yet. This is the one empty state that is NOT about
 * usage: spend exists, and the platform simply has no revenue to divide it by.
 * Rendering 0% instead would read as "the AI costs nothing", which is a claim
 * about the business, not a fact about the data (spec #717 stories 21-22).
 */
const NO_REVENUE_BODY =
  "The platform has not recorded revenue yet, so a margin cannot be computed. AI cost of goods is still counted above.";

/** Nobody is attributed, so "who is heavy" has no answer to give. */
const NO_ACTORS_BODY =
  "No patient or doctor has an AI spend edge in this window.";

/** A patient with no settled doctor. Never a guess - see facade #732. */
const NO_DOCTOR_ATTRIBUTED = "no doctor attributed";

/**
 * A doctor with no recorded patient edge. A DIFFERENT fact from the one above,
 * and it gets its own words: printing "no doctor attributed" on a doctor row
 * states something about the row that is not true.
 */
const NO_PATIENTS_RECORDED = "no patients recorded";

const PERIOD_LABELS: Record<BusinessPeriod, string> = {
  today: "Today",
  week_to_date: "Week to date",
  month_to_date: "Month to date",
};

/**
 * The window the panels are reporting on, spelled out. The read echoes it and
 * the page prints it, because a spend figure with no window next to it cannot be
 * compared with yesterday's - which is the whole question this page answers.
 */
function windowLine(read: BusinessRead): string {
  return `${PERIOD_LABELS[read.period]}, ${read.period_start} to ${
    read.period_end
  }`;
}

/** The spend panel's one line: what is spent, against what, heading where. */
function spendTakeaway(read: BusinessRead): string {
  const spent = `${formatMoney(read.spend_paise)} spent · ${formatPct(
    read.cap_consumed_pct,
  )} of ${formatMoney(read.monthly_cap_paise)} cap`;
  if (read.projected_month_end_paise === null) return spent;
  const projected = `${formatMoney(
    read.projected_month_end_paise,
  )} projected by month end`;
  return `${spent} · ${
    read.projected_over_cap ? `${projected}, over cap` : projected
  }`;
}

/** The heaviest task type, or null when there is no breakdown to weigh. */
function largestTask(read: BusinessRead) {
  return read.by_task_type.reduce<BusinessRead["by_task_type"][number] | null>(
    (heaviest, row) =>
      heaviest === null || row.spend_paise > heaviest.spend_paise
        ? row
        : heaviest,
    null,
  );
}

function breakdownTakeaway(read: BusinessRead): string {
  const largest = largestTask(read);
  const count = `${read.by_task_type.length} task types`;
  if (largest === null) return count;
  return `${count} · the largest is ${largest.task_type} at ${formatMoney(
    largest.spend_paise,
  )}`;
}

/**
 * The population, not the row count. `actors` counts every attributed actor while
 * `top_patients`/`top_doctors` are capped at the ten heaviest - so a page that
 * counted its own rows would report "10 patients" for a deployment with 400.
 */
function actorsTakeaway(read: BusinessRead): string {
  return `${read.patient_spend.actors} patients · ${read.doctor_spend.actors} doctors attributed`;
}

/**
 * A distribution's shape, for the panel heading.
 *
 * The percentiles are `null` when the population is too small to interpolate -
 * and a `?? 0` here would print "median ₹0", which reads as "every patient cost
 * nothing" rather than "there is no median yet". Unmeasured is the dash.
 */
function distributionLabel(
  distribution: BusinessRead["patient_spend"],
): string {
  const figure = (paise: number | null) =>
    paise === null ? DASH : formatMoney(paise);
  return `median ${figure(distribution.median_spend_paise)}, p95 ${figure(
    distribution.p95_spend_paise,
  )}`;
}

function marginTakeaway(read: BusinessRead): string {
  return (
    `${formatMoney(read.margin.revenue_paise)} revenue · ` +
    `${formatMoney(read.margin.cost_of_goods_paise)} AI cost of goods · ` +
    `${formatPct(read.margin.gross_margin.value)} gross margin`
  );
}

export default function ObservabilityBusinessPage() {
  const business = usePanelRead(() => fetchBusiness());
  // The business read carries no trace id of its own - its identifier grain is
  // the pseudonymous actor key, and #736's route derives every vendor filter from
  // the context a panel hands it. So this panel asks with NO invented context and
  // renders the vendors' own default views, rather than passing a window string
  // the vendors' vocabulary does not define (a link filtered by an unknown range
  // opens an empty dashboard and reads as "no AI activity").
  const deeplinks = usePanelRead(() => fetchDeeplinks());

  const read = business.data;

  return (
    <ObservabilityPanelPage
      current="business"
      title="Business"
      description="Whether this spend is healthy, where it goes, what a unit of value costs and who is heavy."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="business-spend"
          title="Spend against the monthly cap"
          read={business}
          isEmpty={(data) => data.spend_paise === 0 && data.jobs === 0}
          emptyTitle="No AI spend recorded in this window"
          emptyBody={NO_SPEND_BODY}
          errorMessage="Could not load the AI spend against the cap."
          takeaway={read ? spendTakeaway(read) : undefined}
        >
          {(data) => (
            <>
              <p
                data-testid="business-spend-window"
                className="mb-2 text-xs text-txt-muted"
              >
                {windowLine(data)}
              </p>
              <SpendAgainstCapChart read={data} testId="business-spend-chart" />
            </>
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-breakdown"
          title="Where the spend goes"
          read={business}
          isEmpty={(data) => data.by_task_type.length === 0}
          emptyTitle="No AI spend by task type in this window"
          emptyBody={NO_BREAKDOWN_BODY}
          errorMessage="Could not load the AI spend breakdown."
          takeaway={read ? breakdownTakeaway(read) : undefined}
        >
          {(data) => (
            <SpendByTaskTypeChart
              rows={data.by_task_type}
              testId="business-breakdown-chart"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-unit-costs"
          title="What a unit of value costs"
          read={business}
          isEmpty={(data) =>
            data.jobs === 0 ||
            data.cost_per_request_paise === null ||
            data.cost_per_completed_task_paise === null
          }
          emptyTitle="No unit costs to price"
          emptyBody={NO_SPEND_BODY}
          errorMessage="Could not load the AI unit costs."
          takeaway={
            read
              ? `${read.jobs} AI jobs · ${read.completed_jobs} completed · ${read.failed_jobs} failed`
              : undefined
          }
        >
          {(data) => (
            <UnitCostsList read={data} testId="business-unit-costs-list" />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-margin"
          title="Is it worth it?"
          read={business}
          isEmpty={(data) => !data.margin.revenue_captured}
          emptyTitle="Revenue not captured yet"
          emptyBody={NO_REVENUE_BODY}
          errorMessage="Could not load the AI margin."
          takeaway={
            read && read.margin.revenue_captured
              ? marginTakeaway(read)
              : undefined
          }
        >
          {(data) => (
            <dl
              data-testid="business-margin-figures"
              className="flex flex-col gap-1"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">Revenue</dt>
                <dd className="font-medium text-txt">
                  {formatMoney(data.margin.revenue_paise)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">AI cost of goods</dt>
                <dd className="font-medium text-txt">
                  {formatMoney(data.margin.cost_of_goods_paise)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">AI cost as a share of revenue</dt>
                <dd
                  data-testid="business-margin-ai-cost-pct"
                  className="font-medium text-txt"
                >
                  {formatPct(data.margin.ai_cost_pct_of_revenue.value)}
                </dd>
              </div>
              {data.margin.tier_keys.length > 0 && (
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Revenue tiers captured</dt>
                  <dd className="font-medium text-txt">
                    {data.margin.tier_keys.join(", ")}
                  </dd>
                </div>
              )}
            </dl>
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-heavy-actors"
          title="Who is heavy"
          read={business}
          isEmpty={(data) =>
            data.top_patients.length === 0 && data.top_doctors.length === 0
          }
          emptyTitle="No attributed patients or doctors in this window"
          emptyBody={NO_ACTORS_BODY}
          errorMessage="Could not load the AI spend attribution."
          takeaway={read ? actorsTakeaway(read) : undefined}
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <HeavyActorList
                title={`Heaviest patients (${distributionLabel(
                  data.patient_spend,
                )})`}
                testId="business-heavy-actors-patients"
                rows={data.top_patients.map((patient) => ({
                  key: patient.patient_key,
                  detail: `${patient.jobs} jobs · ${
                    patient.attributed_doctor_key === null
                      ? NO_DOCTOR_ATTRIBUTED
                      : patient.attributed_doctor_key
                  }`,
                  spend_paise: patient.spend_paise,
                }))}
              />
              <HeavyActorList
                title={`Heaviest doctors (${distributionLabel(
                  data.doctor_spend,
                )})`}
                testId="business-heavy-actors-doctors"
                rows={data.top_doctors.map((doctor) => ({
                  key: doctor.doctor_key,
                  detail: `${doctor.jobs} jobs · ${
                    doctor.patients === null
                      ? NO_PATIENTS_RECORDED
                      : `${doctor.patients} patients`
                  }`,
                  spend_paise: doctor.spend_paise,
                }))}
              />
            </div>
          )}
        </ReadPanel>

        <DeeplinksPanel read={deeplinks} />
      </div>
    </ObservabilityPanelPage>
  );
}
