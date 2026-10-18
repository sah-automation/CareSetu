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
