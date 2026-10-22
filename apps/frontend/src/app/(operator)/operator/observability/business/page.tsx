"use client";

// #737: the operator Business lens page (spec #717, plan-phase14 §9.2).
// Nine panels, ONE read, six questions:
//   * "Is this spend healthy?"  <- the cap, what is consumed, where the month
//                                  lands. GET .../business
//   * "Where does it go?"        <- spend by task type, the one grain an
//                                  operator can act on.
//   * "Who is being paid?"       <- spend by provider, then by model: what the
//                                  bill is made of and at what rate.
//   * "What do the tokens cost?" <- input against output, and the rate per
//                                  thousand of each.
//   * "What does a unit of value cost?"  <- per request, per completed task, per
//                                  patient, per doctor, cost of pass.
//   * "Is it worth it?"          <- margin and cost of goods, which report a
//                                  reason rather than a figure when revenue has
//                                  not been captured.
//   * "Who is heavy?"            <- the heaviest patients and doctors, with the
//                                  population they sit in.
// Plus the shared deep-links panel, so the page is not a dead end.
//
// One read, not nine. Spend, cap, breakdown, unit costs and attribution are
// answers to different questions about the SAME window; splitting them across
// routes would let the panels disagree - a breakdown that reconciles to a spend
// figure the headline no longer shows is worse than one honest failure. So the
// whole page shares one `useKeyedRead`, and every panel fails together. Each
// panel still owns its own EMPTY state, because "nothing ran" is a different
// fact from "no revenue captured" and from "nothing attributed".
//
// The WINDOW is the page's one input. The period control changes the key the
// read belongs to, so a switch re-reads the whole page and no panel is left
// holding the previous window's figures: the read drops the old payload rather
// than showing it behind a loading skeleton (usePanelRead).
//
// Every state - loading, empty, failure with retry - belongs to the panel that
// owns the read (blueprint §9.1). The frame is ReadPanel, unchanged: this page
// contributes its reads, its copy and its charts, nothing else.
//
// Every visible string on this page comes from the `operatorBusiness`
// dictionary, in both locales.

import { useState } from "react";

import {
  HeavyActorList,
  ModelSpendTable,
  PeriodSelector,
  ProviderSpendTable,
  SpendAgainstCapChart,
  SpendByTaskTypeChart,
  TokenCostList,
  TokenVolumeChart,
  UnitCostsList,
} from "@/components/observability/BusinessCharts";
import { DeeplinksPanel } from "@/components/observability/DeeplinksPanel";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  BUSINESS_PERIOD_LABEL_KEY,
  STRINGS,
  type OperatorBusinessStrings,
} from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchBusiness,
  fetchDeeplinks,
  type BusinessPeriod,
  type BusinessRead,
} from "@/lib/operator/observability";
import {
  DASH,
  formatCount,
  formatMarginPercent,
  formatMoney,
  formatPct,
} from "@/lib/operator/observability-format";
import { useKeyedRead, usePanelRead } from "@/lib/operator/usePanelRead";

/**
 * The window the page opens on: the route's own default (`month_to_date`), so
 * the first read asks for the same window the backend would have chosen.
 */
const DEFAULT_PERIOD: BusinessPeriod = "month_to_date";

/**
 * The window the panels are reporting on, spelled out. The read echoes it and
 * the page prints it, because a spend figure with no window next to it cannot be
 * compared with yesterday's - which is the whole question this page answers.
 */
function windowLine(read: BusinessRead, t: OperatorBusinessStrings): string {
  return t.window(
    t.period[BUSINESS_PERIOD_LABEL_KEY[read.period]],
    read.period_start,
    read.period_end,
  );
}

/** The spend panel's one line: what is spent, against what, heading where. */
function spendTakeaway(read: BusinessRead, t: OperatorBusinessStrings): string {
  const parts = [
    t.spend.spent(formatMoney(read.spend_paise)),
    t.spend.capShare(
      formatPct(read.cap_consumed_pct),
      formatMoney(read.monthly_cap_paise),
    ),
  ];
  if (read.projected_month_end_paise !== null) {
    parts.push(
      read.projected_over_cap
        ? t.spend.projectedOverCap(formatMoney(read.projected_month_end_paise))
        : t.spend.projected(formatMoney(read.projected_month_end_paise)),
    );
  }
  return parts.join(" · ");
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

function breakdownTakeaway(
  read: BusinessRead,
  t: OperatorBusinessStrings,
): string {
  const largest = largestTask(read);
  return t.breakdown.takeaway(
    read.by_task_type.length,
    largest === null ? null : largest.task_type,
    largest === null ? null : formatMoney(largest.spend_paise),
  );
}

/** The heaviest provider, or null when there is no provider bill to weigh. */
function largestProvider(read: BusinessRead) {
  return read.by_provider.reduce<BusinessRead["by_provider"][number] | null>(
    (heaviest, row) =>
      heaviest === null || row.spend_paise > heaviest.spend_paise
        ? row
        : heaviest,
    null,
  );
}

function providerTakeaway(
  read: BusinessRead,
  t: OperatorBusinessStrings,
): string {
  const largest = largestProvider(read);
  return t.providers.takeaway(
    read.by_provider.length,
    largest === null ? null : largest.provider,
    largest === null ? null : formatMoney(largest.spend_paise),
  );
}

/** The heaviest model, or null when there is no model bill to weigh. */
function largestModel(read: BusinessRead) {
  return read.by_model.reduce<BusinessRead["by_model"][number] | null>(
    (heaviest, row) =>
      heaviest === null || row.spend_paise > heaviest.spend_paise
        ? row
        : heaviest,
    null,
  );
}

function modelTakeaway(read: BusinessRead, t: OperatorBusinessStrings): string {
  const largest = largestModel(read);
  return t.models.takeaway(
    read.by_model.length,
    largest === null ? null : largest.model,
    largest === null ? null : formatMoney(largest.spend_paise),
  );
}

/**
 * The population, not the row count. `actors` counts every attributed actor while
 * `top_patients`/`top_doctors` are capped at the ten heaviest - so a page that
 * counted its own rows would report "10 patients" for a deployment with 400.
 */
function actorsTakeaway(
  read: BusinessRead,
  t: OperatorBusinessStrings,
): string {
  return t.actors.takeaway(read.patient_spend.actors, read.doctor_spend.actors);
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
  t: OperatorBusinessStrings,
): string {
  const figure = (paise: number | null) =>
    paise === null ? DASH : formatMoney(paise);
  return t.actors.distribution(
    figure(distribution.median_spend_paise),
    figure(distribution.p95_spend_paise),
  );
}

/**
 * The margin's one line.
 *
 * The margin clause is DROPPED when there is no margin to report, rather than
 * printing a dash or a zero in its place: the absence is explained in the panel
 * body, and a summary line that says "gross margin" with no figure would read
 * as a zero gross margin to anyone reading only the summary.
 */
function marginTakeaway(
  read: BusinessRead,
  t: OperatorBusinessStrings,
): string {
  const margin = read.margin.gross_margin.value;
  return t.margin.takeaway(
    formatMoney(read.margin.revenue_paise),
    formatMoney(read.margin.cost_of_goods_paise),
    margin === null ? null : formatPct(margin),
  );
}

export default function ObservabilityBusinessPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const [period, setPeriod] = useState<BusinessPeriod>(DEFAULT_PERIOD);

  // The period is the read's KEY: changing it re-reads the page and drops the
  // previous window's payload, so no panel is left showing yesterday's figures
  // under today's title.
  const business = useKeyedRead(() => fetchBusiness({ period }), period);
  // The business read carries no trace id of its own - its identifier grain is
  // the pseudonymous actor key, and #736's route derives every vendor filter from
  // the context a panel hands it. So this panel asks with NO invented context and
  // renders the vendors' own default views, rather than passing a window string
  // the vendors' vocabulary does not define (a link filtered by an unknown range
  // opens an empty dashboard and reads as "no AI activity").
  const deeplinks = usePanelRead(() => fetchDeeplinks());

  const read = business.data;

  return (
    <ObservabilityPanelPage title={t.title} description={t.description}>
      <div className="flex flex-col gap-4">
        {/* The window the whole page is about. It is here, above the panels,
            because it changes every panel - a control inside one of them would
            leave the other eight answering a different question. */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-hairline bg-surface px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-medium uppercase tracking-wide text-txt-sub">
              {t.period.label}
            </span>
            <PeriodSelector
              period={period}
              onSelect={setPeriod}
              testId="business-period"
            />
          </div>
          <p
            data-testid="business-period-current"
            className="text-xs text-txt-muted"
          >
            {t.period.showing(t.period[BUSINESS_PERIOD_LABEL_KEY[period]])}
          </p>
        </div>

        <ReadPanel
          testId="business-spend"
          title={t.spend.title}
          read={business}
          isEmpty={(data) => data.spend_paise === 0 && data.jobs === 0}
          emptyTitle={t.spend.emptyTitle}
          emptyBody={t.spend.emptyBody}
          errorMessage={t.spend.error}
          takeaway={read ? spendTakeaway(read, t) : undefined}
        >
          {(data) => (
            <>
              <p
                data-testid="business-spend-window"
                className="mb-2 text-xs text-txt-muted"
              >
                {windowLine(data, t)}
              </p>
              <SpendAgainstCapChart read={data} testId="business-spend-chart" />
            </>
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-breakdown"
          title={t.breakdown.title}
          read={business}
          isEmpty={(data) => data.by_task_type.length === 0}
          emptyTitle={t.breakdown.emptyTitle}
          emptyBody={t.breakdown.emptyBody}
          errorMessage={t.breakdown.error}
          takeaway={read ? breakdownTakeaway(read, t) : undefined}
        >
          {(data) => (
            <SpendByTaskTypeChart
              rows={data.by_task_type}
              testId="business-breakdown-chart"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-providers"
          title={t.providers.title}
          read={business}
          isEmpty={(data) => data.by_provider.length === 0}
          emptyTitle={t.providers.emptyTitle}
          emptyBody={t.providers.emptyBody}
          errorMessage={t.providers.error}
          takeaway={read ? providerTakeaway(read, t) : undefined}
        >
          {(data) => (
            <ProviderSpendTable
              rows={data.by_provider}
              testId="business-providers-table"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-models"
          title={t.models.title}
          read={business}
          isEmpty={(data) => data.by_model.length === 0}
          emptyTitle={t.models.emptyTitle}
          emptyBody={t.models.emptyBody}
          errorMessage={t.models.error}
          takeaway={read ? modelTakeaway(read, t) : undefined}
        >
          {(data) => (
            <ModelSpendTable
              rows={data.by_model}
              testId="business-models-table"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-tokens"
          title={t.tokens.title}
          read={business}
          isEmpty={(data) => data.jobs === 0}
          emptyTitle={t.tokens.emptyTitle}
          emptyBody={t.tokens.emptyBody}
          errorMessage={t.tokens.error}
          takeaway={
            read
              ? t.tokens.takeaway(
                  formatCount(read.input_tokens),
                  formatCount(read.output_tokens),
                )
              : undefined
          }
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <TokenCostList read={data} testId="business-tokens-figures" />
              <TokenVolumeChart
                rows={data.by_provider}
                testId="business-tokens-chart"
              />
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-unit-costs"
          title={t.unitCosts.title}
          read={business}
          isEmpty={(data) =>
            data.jobs === 0 ||
            data.cost_per_request_paise === null ||
            data.cost_per_completed_task_paise === null
          }
          emptyTitle={t.unitCosts.emptyTitle}
          emptyBody={t.unitCosts.emptyBody}
          errorMessage={t.unitCosts.error}
          takeaway={
            read
              ? t.unitCosts.takeaway(
                  read.jobs,
                  read.completed_jobs,
                  read.failed_jobs,
                )
              : undefined
          }
        >
          {(data) => (
            <UnitCostsList read={data} testId="business-unit-costs-list" />
          )}
        </ReadPanel>

        <ReadPanel
          testId="business-margin"
          title={t.margin.title}
          read={business}
          isEmpty={(data) => !data.margin.revenue_captured}
          emptyTitle={t.margin.emptyTitle}
          emptyBody={t.margin.emptyBody}
          errorMessage={t.margin.error}
          takeaway={
            read && read.margin.revenue_captured
              ? marginTakeaway(read, t)
              : undefined
          }
        >
          {(data) => (
            <dl
              data-testid="business-margin-figures"
              className="flex flex-col gap-1"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">{t.margin.revenue}</dt>
                <dd className="font-medium text-txt">
                  {formatMoney(data.margin.revenue_paise)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">{t.margin.costOfGoods}</dt>
                <dd className="font-medium text-txt">
                  {formatMoney(data.margin.cost_of_goods_paise)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">
                  {t.margin.headlineMonthCostOfGoods}
                </dt>
                <dd
                  data-testid="business-margin-headline-month-cogs"
                  className="font-medium text-txt"
                >
                  {data.margin.headline_month_cost_of_goods_paise === null
                    ? DASH
                    : formatMoney(
                        data.margin.headline_month_cost_of_goods_paise,
                      )}
                </dd>
              </div>
              {/* The gross margin is a figure OR a reason. `formatMarginPercent`
                  prints the reason when there is no figure, because a "0%" here
                  reads as "the AI costs nothing" - a claim about the business
                  rather than a fact about the data. */}
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">{t.margin.grossMargin}</dt>
                <dd
                  data-testid="business-margin-gross-margin"
                  className="font-medium text-txt"
                >
                  {formatMarginPercent(
                    data.margin.gross_margin,
                    t.margin.reasons,
                  )}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <dt className="text-txt-sub">{t.margin.aiCostPct}</dt>
                <dd
                  data-testid="business-margin-ai-cost-pct"
                  className="font-medium text-txt"
                >
                  {formatMarginPercent(
                    data.margin.ai_cost_pct_of_revenue,
                    t.margin.reasons,
                  )}
                </dd>
              </div>
              {data.margin.tier_keys.length > 0 && (
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">{t.margin.tiersCaptured}</dt>
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
          title={t.actors.title}
          read={business}
          isEmpty={(data) =>
            data.top_patients.length === 0 && data.top_doctors.length === 0
          }
          emptyTitle={t.actors.emptyTitle}
          emptyBody={t.actors.emptyBody}
          errorMessage={t.actors.error}
          takeaway={read ? actorsTakeaway(read, t) : undefined}
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <HeavyActorList
                title={t.actors.patientsTitle(
                  distributionLabel(data.patient_spend, t),
                )}
                testId="business-heavy-actors-patients"
                rows={data.top_patients.map((patient) => ({
                  key: patient.patient_key,
                  detail: `${t.actors.jobs(patient.jobs)} · ${
                    patient.attributed_doctor_key === null
                      ? t.actors.noDoctorAttributed
                      : patient.attributed_doctor_key
                  }`,
                  spend_paise: patient.spend_paise,
                }))}
              />
              <HeavyActorList
                title={t.actors.doctorsTitle(
                  distributionLabel(data.doctor_spend, t),
                )}
                testId="business-heavy-actors-doctors"
                rows={data.top_doctors.map((doctor) => ({
                  key: doctor.doctor_key,
                  detail: `${t.actors.jobs(doctor.jobs)} · ${
                    doctor.patients === null
                      ? t.actors.noPatientsRecorded
                      : t.actors.patients(doctor.patients)
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
