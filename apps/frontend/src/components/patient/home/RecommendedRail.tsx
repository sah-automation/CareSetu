"use client";

// #503: the "Recommended near you" rail (PROTO-2.7 binding, shell-light.html
// `.rec`), a sibling of the home search card (#502) that reads the same
// display-driven scope and refetches from real directory data per active
// Doctor / Lab / Chemist scope. The panel therefore shows only operator-
// verified providers within the Daltonganj service area, distance-sorted
// ascending. On a phone it is a horizontal snap-scroll row; at >=720px (the
// prototype's tablet breakpoint) a 3-up grid. A friendly empty state covers
// no-results; a failed fetch degrades to that same honest state with the
// failure logged (third-party-integration standard) so it stays
// distinct from true emptiness. The scoped "See all" CTA is not re-created
// here: #502's search card already owns it (the Search / See-all destination
// the brief says to swap together), so the rail only owns the title + panel.

import { useEffect, useState } from "react";
import Link from "next/link";

import { formatDistanceKm } from "@/components/directory/DirectoryCard";
import { EmptyState } from "@/components/layout/EmptyState";
import type { ProviderType } from "@/lib/directory/links";
import { providerProfileHref } from "@/lib/directory/links";
import { fetchRecommended } from "@/lib/directory/recommended";
import type { DirectoryEntry } from "@/lib/directory/search";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// Directory card-language maps (same keys DirectoryBrowser feeds DirectoryCard
// with) - the rail joins the shared card vocabulary rather than inventing its
// own label derivation.
const TYPE_LABEL_KEY = {
  doctor: "typeDoctor",
  lab: "typeLab",
  chemist: "typeChemist",
} as const;

type SpecialtyKey =
  | "generalPhysician"
  | "pediatrician"
  | "gynecologist"
  | "dentist";

const SPECIALTY_LABEL_KEY: Record<string, SpecialtyKey> = {
  "General Physician": "generalPhysician",
  Pediatrician: "pediatrician",
  Gynecologist: "gynecologist",
  Dentist: "dentist",
};

/** Two-letter initials for the avatar circle, "?" when the name is empty. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

interface RailCardProps {
  entry: DirectoryEntry;
  typeLabel: string;
  specialtyLabel: string | null;
  verifiedLabel: string;
  distanceLabel: string;
  fallbackName: string;
}

function RailCard({
  entry,
  typeLabel,
  specialtyLabel,
  verifiedLabel,
  distanceLabel,
  fallbackName,
}: RailCardProps) {
  // Defensive second gate on the one shared derivation, matching DirectoryCard:
  // a row the backend marks unverified must not surface a card ("tick gone =
  // card gone" - the API never sends one, but the card drops it anyway).
  if (!entry.verified) return null;

  // An empty practice name must not render a blank card: `||` (not `??`)
  // catches the whitespace-empty case too and the fallback is the home surface's
  // i18n name (never an English literal - US-22). `initials` then always sees a
  // real name unless the fallback itself is empty, where it degrades to "?".
  const name = entry.practice_name || fallbackName;
  const meta = [entry.specialty && specialtyLabel, typeLabel, entry.area]
    .filter(Boolean)
    .join(" \u00b7 ");

  return (
    <Link
      href={providerProfileHref(entry.partner_id)}
      data-testid="rec-card"
      className="flex basis-[78%] shrink-0 max-w-[260px] snap-start flex-col gap-2.5 rounded-lg border border-hairline bg-surface p-3.5 shadow-card transition-shadow hover:shadow-pop min-[720px]:basis-auto min-[720px]:max-w-none"
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-accent-border bg-accent-soft text-sm font-semibold text-accent-strong"
        >
          {initials(name)}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[0.9375rem] font-semibold leading-snug text-txt">
            {name}
          </span>
          <span className="block truncate text-[0.8125rem] text-txt-muted">
            {meta}
          </span>
        </span>
      </span>
      <span className="flex items-center justify-between gap-2">
        <span className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
          {verifiedLabel}
        </span>
        <span className="inline-flex items-center gap-1 whitespace-nowrap text-[0.8125rem] text-txt-sub">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {distanceLabel}
        </span>
      </span>
    </Link>
  );
}

export interface RecommendedRailProps {
  /** The active scope, owned by the page (#502). Every scope change refetches
   * the panel so content and the Search / See-all destinations swap together. */
  scope: ProviderType;
}

export function RecommendedRail({ scope }: RecommendedRailProps) {
  const { lang } = useLang();
  const t = STRINGS[lang];
  // null = resolving the directory for this scope; [] = nothing verified yet.
  const [entries, setEntries] = useState<DirectoryEntry[] | null>(null);

  useEffect(() => {
    let active = true;
    setEntries(null);
    fetchRecommended(scope)
      .then((rows) => {
        if (active) setEntries(rows);
      })
      .catch((err: unknown) => {
        // Degradation rule (third-party-integration standard): a failed fetch
        // degrades to the honest empty state - but the failure is logged so it
        // stays distinguishable from true emptiness (FeaturedDoctors pattern).
        console.warn(
          "[recommended-near-you] fetch failed, degrading to empty state:",
          err,
        );
        if (active) setEntries([]);
      });
    return () => {
      active = false;
    };
  }, [scope]);

  return (
    <section
      data-testid="rec-rail"
      aria-label={t.rec.aria}
      className="border-t border-hairline-soft pt-3.5"
    >
      <h2 className="text-[0.95rem] font-semibold text-txt">{t.rec.title}</h2>

      {entries === null ? (
        <div
          data-testid="rec-loading"
          role="status"
          aria-label={t.rec.loading}
          className="mt-3 flex gap-3 pb-1 min-[720px]:grid min-[720px]:grid-cols-3 min-[720px]:gap-3"
        >
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg bg-hairline-soft"
            />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="mt-3">
          <EmptyState title={t.rec.emptyTitle} body={t.rec.emptyBody} />
        </div>
      ) : (
        <div
          data-testid="rec-scroll"
          className="mt-3 flex gap-3 overflow-x-auto overscroll-x-contain pb-1 snap-x snap-mandatory [scrollbar-width:none] [&::-webkit-scrollbar]:hidden min-[720px]:grid min-[720px]:grid-cols-3 min-[720px]:gap-3 min-[720px]:overflow-visible min-[720px]:pb-0 min-[720px]:snap-none"
        >
          {entries.map((entry) => (
            <RailCard
              key={entry.partner_id}
              entry={entry}
              typeLabel={t.directory[TYPE_LABEL_KEY[entry.partner_type]]}
              specialtyLabel={
                entry.specialty
                  ? t.directory.specialties[
                      SPECIALTY_LABEL_KEY[entry.specialty]
                    ] ?? entry.specialty
                  : null
              }
              verifiedLabel={t.directory.verified}
              distanceLabel={formatDistanceKm(
                entry.distance_km,
                t.directory.distanceKm,
              )}
              fallbackName={t.rec.providerFallback}
            />
          ))}
        </div>
      )}
    </section>
  );
}
