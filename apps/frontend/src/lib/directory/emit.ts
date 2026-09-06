// PHASE-6 T6 (#328): tiny fire-and-forget client emitter for the
// `partner.selected` analytics event (MOD-002, FEAT-004, gap G2). Consumes
// the public directory pick route `POST /v1/directory/select` that #326
// shipped: the emitted event name and payload mirror the backend
// `PartnerSelectRequest` envelope exactly (partner_id + pick-only facts).
//
// Client-initiated product analytics, not a regulated act - no identity, no
// consent, no PHI. The event carries only the picked partner and the source
// surface; the public route is unauthenticated, so the actor is anonymous by
// construction.
//
// The emitter is fire-and-forget on purpose: a pick must never block or
// distract from the browse surface, so the POST is not awaited and failures
// are silent (degrade-gracefully, like the featured-doctors pattern). Exactly
// once per interaction is the caller's job - an onClick handler on a card, a
// mount-once effect on a profile - never an effect that can re-run.

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import type { ProviderType } from "@/lib/directory/links";

/** The source surface of a pick, matching the backend `PartnerSelectRequest`
 * `source` vocabulary (a search card or a provider profile). */
export type PartnerSelectSource = "search_card" | "provider_profile";

/** Pick-only facts for one `partner.selected` event (anonymous actor). */
export interface PartnerSelectFacts {
  partner_id: number;
  /** The picked partner's type (doctor/lab/chemist) when the caller knows it. */
  partner_type: ProviderType | null;
  source: PartnerSelectSource;
}

/** Fire one anonymous `partner.selected` pick, never blocking or surfacing
 * failures. Returns nothing; a rejected POST is swallowed silently. */
export function emitPartnerSelected(facts: PartnerSelectFacts): void {
  void authedFetch(`${API_BASE_URL}/v1/directory/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(facts),
  }).catch(() => {
    // Analytics only - the pick happened on the client regardless of whether
    // the POST landed. Failures are intentionally silent (see module header).
  });
}
