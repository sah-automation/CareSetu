// Shared money formatting (api-standards §3: money crosses the wire in paise
// and is rendered in whole rupees). Extracted so no screen has to reach into
// another role's component to format a figure - the operator Observability
// console needed the same formatter the doctor console already had, and two
// Intl configurations for one currency is how the two drift apart.

/**
 * The ONE Intl configuration for the rupee. Two constructors in two modules is
 * how two screens of the same currency drift apart, so both formatters below go
 * through this factory and only differ in how many fraction digits they keep.
 */
const inrFormatter = (fractionDigits: number): Intl.NumberFormat =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });

/**
 * Render paise as whole rupees (`125000` -> `₹1,250`). Fractions of a rupee are
 * dropped: every CareSetu price is a whole-rupee amount, so showing paise as
 * decimals would only suggest a precision the ledger does not carry.
 */
export function formatInrPaise(paise: number): string {
  return inrFormatter(0).format(paise / 100);
}

/**
 * Render paise as rupees KEEPING `fractionDigits` decimals (`1041.67` -> `₹10.42`).
 *
 * For RATES rather than prices. A unit cost is not a price: AI runs at roughly
 * ten paise a request, so the whole-rupee rule above prints "₹10" for 10.42 paise.
 * That is lossy. Note it is still lossy below one paisa - `0.4` paise reads as
 * "₹0.00" - because two decimals is the finest the currency has; a caller whose
 * figures go that small needs a different unit, not more digits.
 */
export function formatInrPaisePrecise(
  paise: number,
  fractionDigits = 2,
): string {
  return inrFormatter(fractionDigits).format(paise / 100);
}
