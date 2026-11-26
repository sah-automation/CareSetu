"use client";

// #737: the Business lens page's NON-CHART components - tables, controls, lists.
// Chart components are in BusinessChartsDynamic.tsx to enable dynamic import
// and keep the recharts runtime out of the initial page bundle.

import type { ReactNode } from "react";

import {
  BUSINESS_PERIOD_LABEL_KEY,
  STRINGS,
  type OperatorBusinessStrings,
} from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  DASH,
  formatCount,
  formatRupees,
  formatUnitCost,
  rupeesFromPaise,
} from "@/lib/operator/observability-format";
import type {
  BusinessPeriod,
  BusinessRead,
  ModelSpend,
  ProviderSpend,
} from "@/lib/operator/observability";
import { cn } from "@/lib/utils";

/**
 * The two heavy-actor tables, as a list rather than a plot.
 *
 * A ranked table is the honest form for this panel: the question is "who is
 * heavy", and the answer is a name, a figure and a job count read against the
 * population - none of which a bar encodes better than a row of text. A chart
 * here would also have to plot pseudonymous hashes on an axis, which reads as
 * identity rather than as the join key it is.
 *
 * Keys are rendered as SHOWN - the platform's own pseudonymous hashes - because
 * they are the join key an operator hands the deep-links panel, and inventing a
 * display name for a hash is how PHI ends up in a console.
 */
export function HeavyActorList({
  title,
  rows,
  testId,
}: {
  title: string;
  rows: { key: string; detail: string; spend_paise: number }[];
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  return (
    <div data-testid={testId}>
      <h3 className="text-xs font-medium uppercase tracking-wide text-txt-sub">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="mt-1 text-sm text-txt-muted">{t.actors.noActors}</p>
      ) : (
        <ul className="mt-1 flex flex-col gap-1">
          {rows.map((row) => (
            <li
              key={row.key}
              data-testid={`${testId}-row-${row.key}`}
              className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
            >
              <span className="font-mono text-xs text-txt">{row.key}</span>
              <span className="text-txt-muted">{row.detail}</span>
              <span className="font-medium text-txt">
                {formatRupees(rupeesFromPaise(row.spend_paise))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The unit-cost line, as text rather than a plot. Five rates of different
 * magnitudes ("₹10.42 per request", "₹250.00 per patient") on one shared axis
 * would put four of them on the baseline, and a bar chart whose bars are all
 * effectively zero tells the operator nothing they could not get wrong.
 *
 * `formatUnitCost`, not `formatMoney`: these are rates, and the whole-rupee
 * price rule would print a real per-request cost as "₹0".
 *
 * The row ids are STATED, not derived from the label: a test id built from a
 * translated label would change with the locale, and a test that only passes in
 * English is a test that has stopped being one.
 */
export function UnitCostsList({
  read,
  testId,
}: {
  read: BusinessRead;
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const units: { id: string; label: string; paise: number | null }[] = [
    {
      id: "per-request",
      label: t.unitCosts.perRequest,
      paise: read.cost_per_request_paise,
    },
    {
      id: "per-completed-task",
      label: t.unitCosts.perCompletedTask,
      paise: read.cost_per_completed_task_paise,
    },
    {
      id: "per-patient",
      label: t.unitCosts.perPatient,
      paise: read.cost_per_patient_paise,
    },
    {
      id: "per-doctor",
      label: t.unitCosts.perDoctor,
      paise: read.cost_per_doctor_paise,
    },
    {
      id: "cost-of-pass",
      label: t.unitCosts.costOfPass,
      paise: read.cost_of_pass_paise,
    },
  ];

  return (
    <dl data-testid={testId} className="flex flex-col gap-1">
      {units.map((unit) => (
        <div
          key={unit.id}
          className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
        >
          <dt className="text-txt-sub">{unit.label}</dt>
          {/* An unmeasured unit cost is the dash, never ₹0.00: a division with a
              zero denominator means "not measured", and "free" is a claim. */}
          <dd
            data-testid={`${testId}-${unit.id}`}
            className="font-medium text-txt"
          >
            {unit.paise === null ? DASH : formatUnitCost(unit.paise)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The window the whole page is reporting on, as a control.
 *
 * It is a PAGE-level question - every panel below answers about the same
 * window - so it sits above the panels rather than inside one of them: a
 * control that changed one panel's numbers and left the other four alone would
 * be a page that disagrees with itself.
 *
 * `aria-pressed` rather than a radio group, because the period is a state of
 * the read rather than a destination, and the same shape the reliability
 * filter uses.
 */
export function PeriodSelector({
  period,
  onSelect,
  testId,
}: {
  period: BusinessPeriod;
  onSelect: (period: BusinessPeriod) => void;
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const periods: BusinessPeriod[] = ["today", "week_to_date", "month_to_date"];

  return (
    <div
      role="group"
      aria-label={t.period.label}
      className="flex flex-wrap gap-2"
      data-testid={`${testId}-group`}
    >
      {periods.map((id) => {
        const selected = id === period;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(id)}
            data-testid={`${testId}-${id}`}
            className={cn(
              "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium",
              selected
                ? "border-accent-border bg-accent-soft text-accent-strong"
                : "border-hairline bg-surface text-txt-sub hover:bg-hairline-soft",
            )}
          >
            {t.period[BUSINESS_PERIOD_LABEL_KEY[id]]}
          </button>
        );
      })}
    </div>
  );
}

/**
 * The table shell both breakdowns share - the same one the reliability board
 * uses, so two tables on two pages read as one console.
 *
 * The caption is the table's text alternative and says what the columns are
 * FOR, not what they are called: a column headed "Per 1k input" is a rate, and
 * the caption is where that is said.
 */
function SpendTable({
  caption,
  headers,
  testId,
  children,
}: {
  caption: string;
  headers: { label: string; right?: boolean }[];
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid={testId}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-hairline text-left text-xs text-txt-muted">
            {headers.map((header, index) => (
              <th
                key={header.label}
                scope="col"
                className={cn(
                  "py-1.5 font-medium",
                  header.right && "text-right",
                  index < headers.length - 1 && "pr-3",
                )}
              >
                {header.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** A rate the read did not measure: the dash, never ₹0.00. */
function rate(paise: number | null): string {
  return paise === null ? DASH : formatUnitCost(paise);
}

/**
 * One provider's line of the bill: what it cost, how many tokens it moved, and
 * what a thousand of each kind cost.
 *
 * The token rates are on the row because the headline rate is an average over
 * every provider: an average that hides a provider costing ten times the rest
 * is an average that has thrown away the thing the operator came for.
 */
export function ProviderSpendTable({
  rows,
  testId,
}: {
  rows: ProviderSpend[];
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;

  return (
    <SpendTable
      caption={t.providers.table.caption}
      testId={testId}
      headers={[
        { label: t.table.provider },
        { label: t.table.jobs, right: true },
        { label: t.table.spend, right: true },
        { label: t.table.inputTokens, right: true },
        { label: t.table.outputTokens, right: true },
        { label: t.table.perThousandInput, right: true },
        { label: t.table.perThousandOutput, right: true },
      ]}
    >
      {rows.map((row) => (
        <tr
          key={row.provider}
          data-testid={`${testId}-row-${row.provider}`}
          className="border-b border-hairline-soft last:border-0"
        >
          <td className="py-1.5 pr-3 font-mono text-xs text-txt">
            {row.provider}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.jobs)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatRupees(rupeesFromPaise(row.spend_paise))}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.input_tokens)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.output_tokens)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {rate(row.paise_per_1k_input_tokens)}
          </td>
          <td className="py-1.5 text-right tabular-nums text-txt">
            {rate(row.paise_per_1k_output_tokens)}
          </td>
        </tr>
      ))}
    </SpendTable>
  );
}

/**
 * One model's line of the bill, with the provider that served it.
 *
 * The provider repeats rather than nests, because the (provider, model) pair
 * is the key: the same model name served by two providers is two prices, and a
 * nested shape would make the model column a lookup.
 */
export function ModelSpendTable({
  rows,
  testId,
}: {
  rows: ModelSpend[];
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;

  return (
    <SpendTable
      caption={t.models.table.caption}
      testId={testId}
      headers={[
        { label: t.table.model },
        { label: t.table.provider },
        { label: t.table.jobs, right: true },
        { label: t.table.spend, right: true },
        { label: t.table.inputTokens, right: true },
        { label: t.table.outputTokens, right: true },
        { label: t.table.perThousandInput, right: true },
        { label: t.table.perThousandOutput, right: true },
      ]}
    >
      {rows.map((row) => (
        <tr
          key={`${row.provider}/${row.model}`}
          data-testid={`${testId}-row-${row.provider}-${row.model}`}
          className="border-b border-hairline-soft last:border-0"
        >
          <td className="py-1.5 pr-3 font-mono text-xs text-txt">
            {row.model}
          </td>
          <td className="py-1.5 pr-3 font-mono text-xs text-txt-muted">
            {row.provider}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.jobs)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatRupees(rupeesFromPaise(row.spend_paise))}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.input_tokens)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {formatCount(row.output_tokens)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt">
            {rate(row.paise_per_1k_input_tokens)}
          </td>
          <td className="py-1.5 text-right tabular-nums text-txt">
            {rate(row.paise_per_1k_output_tokens)}
          </td>
        </tr>
      ))}
    </SpendTable>
  );
}

/**
 * The token bill, as figures.
 *
 * Input and output are priced separately because they are bought separately:
 * one rate for input and another for output is what the vendor bills, and
 * collapsing them into one blended rate would hide which half of the bill is
 * the expensive half.
 *
 * `formatUnitCost`, not `formatMoney`: a rate per thousand tokens is a rate,
 * and the whole-rupee price rule would print ₹0.90 as "₹1" and ₹0.40 as "₹0".
 */
export function TokenCostList({
  read,
  testId,
}: {
  read: BusinessRead;
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const figures: { id: string; label: string; value: string }[] = [
    {
      id: "input-tokens",
      label: t.tokens.inputTokens,
      value: formatCount(read.input_tokens),
    },
    {
      id: "output-tokens",
      label: t.tokens.outputTokens,
      value: formatCount(read.output_tokens),
    },
    {
      id: "per-thousand-input",
      label: t.tokens.perThousandInput,
      value: rate(read.paise_per_1k_input_tokens),
    },
    {
      id: "per-thousand-output",
      label: t.tokens.perThousandOutput,
      value: rate(read.paise_per_1k_output_tokens),
    },
  ];

  return (
    <dl data-testid={testId} className="flex flex-col gap-1">
      {figures.map((figure) => (
        <div
          key={figure.id}
          className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
        >
          <dt className="text-txt-sub">{figure.label}</dt>
          <dd
            data-testid={`${testId}-${figure.id}`}
            className="font-medium text-txt"
          >
            {figure.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
