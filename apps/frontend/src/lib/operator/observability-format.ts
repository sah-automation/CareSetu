// #709 C2b: the operator Observability console's figure formatters, extracted
// from the C2a overview page so the four chart panels (#709) format a rate, a
// duration and a rupee exactly as the landing page does.
//
// The two rules these encode are the ones an ops console gets wrong most
// easily, and the reason they live here rather than in each panel:
//   * A rate the rollup has no sample for is `null` (facade.Overview: "not yet
//     measured"), and it renders as an em dash. It is never coerced to zero -
//     a zero success rate and a provider nobody has called are not the same
//     fact, and a chart that draws one where the other belongs invents an
//     incident.
//   * Money crosses the wire in paise (api-standards §3) and renders as whole
//     rupees through lib/money.ts; the charts divide before they plot, so a
//     y-axis of "1250000" never reaches an operator's screen.

import { formatInrPaise, formatInrPaisePrecise } from "@/lib/money";

/** An unmeasured figure (see facade.Overview: a `null` rate, never a zero). */
export const DASH = "\u2014";

/**
 * Percentages read at one decimal, trailing zeros dropped: `95.0` is "95%" on a
 * tile and `2.6` is "2.6%". A `null` rate is the em dash, not a zero.
 */
export function formatPct(value: number | null): string {
  if (value === null) return DASH;
  return `${Number(value.toFixed(1))}%`;
}

/**
 * A RATE, which the backend stores as a FRACTION: `success_rate` of `"0.8750"`
 * means 87.5% of calls succeeded, and `error_rate` of `"0.1818"` means 18.18%
 * of requests failed.
 *
 * DELIBERATELY NOT `formatPct`. That formatter takes a figure already on the
 * 0-100 scale - `cap_consumed_pct` arrives as `"25.00"` - and a fraction
 * printed through it reports a provider that is 87.5% healthy as "0.9%", which
 * is not a rounding difference but the opposite of the fact. Two names for two
 * scales is the whole point: reach for the one that matches the field's `_pct`
 * suffix, and neither here.
 */
export function formatRate(fraction: number | null): string {
  if (fraction === null) return DASH;
  return `${Number((fraction * 100).toFixed(1))}%`;
}

/**
 * A margin percentage, or the REASON it is absent.
 *
 * The margin read reports a figure OR a reason, never a zero (facade: a
 * deployment that has not written revenue has no gross margin). Printing that
 * `null` through `formatPct` would render the em dash, which says "not
 * measured" without saying why - and the reason is the fact an operator needs:
 * "revenue not captured" is a thing to go and fix, and a bare dash is not.
 *
 * So the reason travels with the figure and is rendered in its place. The
 * reason phrases are the console's copy, passed in by the caller so the
 * wording stays in the dictionary beside every other string on the page.
 */
export function formatMarginPercent(
  percent: {
    value: number | null;
    reason: string | null;
    detail?: string | null;
  },
  reasons: { revenueNotCaptured: string; revenueZero: string },
): string {
  if (percent.value !== null) return formatPct(percent.value);
  if (percent.reason === "revenue_not_captured") {
    return reasons.revenueNotCaptured;
  }
  if (percent.reason === "revenue_zero") return reasons.revenueZero;
  // Neither a figure nor a named reason: still not a zero.
  return DASH;
}

/**
 * A count, grouped the way the console's money already is.
 *
 * `toLocaleString("en-IN")` spelled inline is one authority per call site, and
 * two tables on one page that group 1,234 and 1,23,4 differently is exactly the
 * drift the money formatter exists to prevent.
 */
export function formatCount(value: number): string {
  return value.toLocaleString("en-IN");
}

/**
 * How long ago something happened, in the operator queue's register ("2h",
 * "3 days").
 *
 * Shared because two panels already needed it and had each written their own:
 * the alert feed's rows and the error feed's rows are both timelines, and "when"
 * is the question an operator asks before "what". The exact timestamp stays in
 * the element's `title`/`dateTime` for anyone who needs it. No PHI is involved
 * - the value is a clock time.
 */
export function formatAge(timestamp: string): string {
  const ms = Date.now() - new Date(timestamp).getTime();
  if (ms < 60_000) return "< 1m";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

/** Latency in seconds past a second ("4.2s"), whole milliseconds below that. */
export function formatDuration(ms: number | null): string {
  if (ms === null) return DASH;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${Number((ms / 1000).toFixed(1))}s`;
}

/** A rupee amount for prose and tooltips. `formatInrPaise` is the formatter. */
export function formatMoney(paise: number): string {
  return formatInrPaise(paise);
}

/**
 * Paise as rupees, for a chart's numeric axis. A plot needs a number, not a
 * formatted string - recharts positions a tick by its value - so the currency
 * symbol and grouping belong in the tick/tooltip formatter and the division
 * belongs here.
 */
export function rupeesFromPaise(paise: number): number {
  return paise / 100;
}

/**
 * Rupees, for an axis tick or a tooltip value that is ALREADY in rupees.
 *
 * Charts divide before they plot (see `rupeesFromPaise`), so the value coming
 * back out of a chart is rupees - the inverse of the wire format and the
 * opposite of `formatMoney`. Re-multiplying by 100 to reuse `formatMoney` would
 * be a round trip through the wire unit, and would be wrong by two orders of
 * magnitude the moment anyone changed the divisor.
 */
export function formatRupees(rupees: number): string {
  return formatInrPaise(rupees * 100);
}

/**
 * A unit cost, in rupees, at paise precision.
 *
 * Deliberately NOT `formatMoney`. That formatter drops fractions because every
 * CareSetu PRICE is a whole-rupee amount (lib/money.ts), and a price is what it
 * was written for. A unit cost is a RATE: AI runs at roughly ten paise a
 * request, so the whole-rupee rule reports "₹10" for 10.42 paise.
 *
 * Both go through the one Intl configuration in lib/money.ts, so the two
 * renderings of one currency cannot drift. Two decimals always, so a column of
 * unit costs lines up.
 */
export function formatUnitCost(paise: number): string {
  return formatInrPaisePrecise(paise);
}
