// PHASE-6 card redesign (#965): Static stand-ins until
// rating/video/badge/availability backends land - single swap point.
//
// Every export here is a pure, synchronous placeholder for a field the
// directory payload does not carry yet. Each placeholder is marked
// TODO(BACKEND): when the real backend lands, only the import sites
// (DirectoryCard, ProviderProfileBody and friends) change - the call
// signatures are shaped to be dropped in as-is.
//
// Determinism rule: every value derives from a stable hash of
// `partner_id`, so the same provider always renders the same card and
// different providers do not all look identical during visual testing.

import type { ProviderType } from "./links";

/** 32-bit avalanche mix (the prototype's `hash`), seeded with the value to
 * scramble. Returns an unsigned 32-bit integer. */
function hashSeed(seed: number): number {
  let h = seed | 0;
  h = Math.imul(h ^ (h >>> 15), 2246822519);
  h = Math.imul(h ^ (h >>> 13), 3266489917);
  return (h ^ (h >>> 16)) >>> 0;
}

function hashPartner(partnerId: number): number {
  return hashSeed(partnerId);
}

/** Deterministic rating stand-in: stars in 4.5-4.9 (one decimal) plus a
 * review count, both derived from `partner_id` so a provider's rating never
 * flickers between renders. */
export interface MockRating {
  stars: number;
  reviewCount: number;
}

// TODO(BACKEND): rating + review-count service keyed by partner_id.
export function getMockRating(partnerId: number): MockRating {
  const h = hashPartner(partnerId);
  const stars = 4.5 + (h % 5) / 10;
  const reviewCount = 25 + (h % 300);
  return { stars, reviewCount };
}

/** Icon key for a fact row - the consumer maps it to its own SVG. */
export type MockFactIcon =
  | "video"
  | "insurance"
  | "new-patients"
  | "home-collection"
  | "clock"
  | "certified"
  | "delivery"
  | "erx"
  | "hours";

export interface MockFact {
  label: string;
  icon: MockFactIcon;
}

/** Badge label with its visual variant: `accent` is the highlighted pill,
 * `muted` the secondary one (prototype `.badge-accent` / `.badge-muted`). */
export interface MockTag {
  label: string;
  variant: "accent" | "muted";
}

/** Per-type card content: fact rows, tags, highlight ribbon, credential
 * abbreviation and the video badge - everything the redesigned card shows
 * that the backend does not send yet. */
export interface MockCardTemplate {
  /** Orange highlight ribbon above the name, or null when the card shows none. */
  highlightRibbon: string | null;
  /** Credential abbreviation ("MD"/"BDS") for doctors; null for lab/chemist. */
  credentials: string | null;
  /** Video-visits badge (doctors only in the prototype). */
  videoBadge: boolean;
  facts: readonly MockFact[];
  tags: MockTag[];
}

const DOCTOR_RIBBONS: readonly (string | null)[] = [
  "Top rated in Daltonganj",
  null,
  "20+ years experience",
];

const LAB_RIBBONS: readonly (string | null)[] = [
  "NABL Accredited",
  null,
  "Home Collection",
];

const CHEMIST_RIBBONS: readonly (string | null)[] = [
  "E-Rx Delivery",
  "Prescription Medicines",
  null,
];

const DOCTOR_FACTS_WITH_VIDEO: readonly MockFact[] = [
  { label: "Video visits", icon: "video" },
  { label: "In-network insurance", icon: "insurance" },
  { label: "New patients", icon: "new-patients" },
];

const DOCTOR_FACTS: readonly MockFact[] = [
  { label: "In-network insurance", icon: "insurance" },
  { label: "New patients", icon: "new-patients" },
];

const LAB_FACTS_24H: readonly MockFact[] = [
  { label: "Home collection", icon: "home-collection" },
  { label: "Reports in 24h", icon: "clock" },
  { label: "NABL Accredited", icon: "certified" },
];

const LAB_FACTS_48H: readonly MockFact[] = [
  { label: "Home collection", icon: "home-collection" },
  { label: "Reports in 48h", icon: "clock" },
  { label: "ISO Certified", icon: "certified" },
];

const CHEMIST_FACTS_ERX: readonly MockFact[] = [
  { label: "Home delivery", icon: "delivery" },
  { label: "E-prescription", icon: "erx" },
  { label: "Open 8AM-10PM", icon: "hours" },
];

const CHEMIST_FACTS_GENERIC: readonly MockFact[] = [
  { label: "Home delivery", icon: "delivery" },
  { label: "Generic meds", icon: "erx" },
  { label: "Open 8AM-9PM", icon: "hours" },
];

/** Per-type card template: fact rows, tags, ribbon, credentials and the
 * video flag, all deterministic in `partner_id`. Doctors carry the
 * prototype's MD/BDS credential text and a hash-picked video badge; labs and
 * chemists carry neither. */
// TODO(BACKEND): replace with the real card-payload fields once the
// rating/video/badge backends land - keep this signature as the drop-in.
export function getMockCardData(
  partnerId: number,
  type: ProviderType,
): MockCardTemplate {
  const h = hashPartner(partnerId);

  if (type === "doctor") {
    const videoBadge = (h & 1) === 1;
    return {
      highlightRibbon: DOCTOR_RIBBONS[(h >>> 3) % DOCTOR_RIBBONS.length],
      credentials: ((h >>> 5) & 1) === 0 ? "MD" : "BDS",
      videoBadge,
      facts: videoBadge ? DOCTOR_FACTS_WITH_VIDEO : DOCTOR_FACTS,
      tags:
        (h >>> 7) & 1
          ? [
              { label: "Video + clinic", variant: "accent" },
              { label: "Hindi", variant: "muted" },
            ]
          : [
              { label: "In-clinic", variant: "accent" },
              { label: "Hindi, English", variant: "muted" },
            ],
    };
  }

  if (type === "lab") {
    return {
      highlightRibbon: LAB_RIBBONS[(h >>> 3) % LAB_RIBBONS.length],
      credentials: null,
      videoBadge: false,
      facts: (h >>> 5) & 1 ? LAB_FACTS_48H : LAB_FACTS_24H,
      tags:
        (h >>> 7) & 1
          ? [
              { label: "Walk-in only", variant: "accent" },
              { label: "Card accepted", variant: "muted" },
            ]
          : [
              { label: "Walk-in & Home", variant: "accent" },
              { label: "Card accepted", variant: "muted" },
            ],
    };
  }

  return {
    highlightRibbon: CHEMIST_RIBBONS[(h >>> 3) % CHEMIST_RIBBONS.length],
    credentials: null,
    videoBadge: false,
    facts: (h >>> 5) & 1 ? CHEMIST_FACTS_GENERIC : CHEMIST_FACTS_ERX,
    tags:
      (h >>> 7) & 1
        ? [
            { label: "Delivery available", variant: "accent" },
            { label: "Card accepted", variant: "muted" },
          ]
        : [
            { label: "Delivery available", variant: "accent" },
            { label: "UPI accepted", variant: "muted" },
          ],
  };
}

/** Deterministic profile-hero distance, "x.x km away" in 0.3-4.7 km. */
// TODO(BACKEND): profile distance - the search payload's `distance_km` is
// scoped to the search centroid, the profile hero needs its own value.
export function getMockProfileDistance(partnerId: number): string {
  const h = hashPartner(partnerId);
  const km = 0.3 + (h % 45) / 10;
  return `${km.toFixed(1)} km away`;
}
