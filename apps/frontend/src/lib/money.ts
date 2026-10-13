// Shared money formatting (api-standards §3: money crosses the wire in paise
// and is rendered in whole rupees). Extracted so no screen has to reach into
// another role's component to format a figure - the operator Observability
// console needed the same formatter the doctor console already had, and two
// Intl configurations for one currency is how the two drift apart.

/**
 * Render paise as whole rupees (`125000` -> `₹1,250`). Fractions of a rupee are
 * dropped: every CareSetu price is a whole-rupee amount, so showing paise as
 * decimals would only suggest a precision the ledger does not carry.
 */
export function formatInrPaise(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);
}
