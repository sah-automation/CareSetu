"use client";

// PHASE-6 T05a (#317): one directory result card (PROTO-PHASE-6 `.dir-card`
// visual binding, derived from the FeaturedDoctors `DoctorCard` shape so the
// two directory surfaces share one card language). The card deep-links to the
// provider profile surface (`/providers/:id`) that ships with PHASE-6 T06.
//
// Truthfulness rules (FEAT-005 / ADR-0011): the verified tick renders only
// when the backend-derived flag is true (search visibility and the tick share
// one derivation, so a false-tick row can never show), and the card renders
// name, partner type and specialty - never the dropped `consultType`, never
// an area string the search projection does not carry.

import Link from "next/link";

import { providerProfileHref } from "@/lib/directory/links";
import type { DirectoryEntry } from "@/lib/directory/search";

export function formatDistanceKm(
  distanceKm: number,
  formatKm: (km: string) => string,
): string {
  return formatKm(distanceKm.toFixed(1));
}

interface DirectoryCardProps {
  entry: DirectoryEntry;
  /** Provider-type label (localised, e.g. "Doctors"). */
  typeLabel: string;
  /** Doctor-only specialty label, or null for labs/chemists. */
  specialtyLabel: string | null;
  verifiedLabel: string;
  /** Distance already localised by the caller (e.g. "1.2 km"). */
  distanceLabel: string;
}

export function DirectoryCard({
  entry,
  typeLabel,
  specialtyLabel,
  verifiedLabel,
  distanceLabel,
}: DirectoryCardProps) {
  // Defensive second gate on the one shared derivation: a row the backend
  // marks unverified must not surface a card ("tick gone = card gone").
  if (!entry.verified) return null;

  const meta =
    entry.specialty && specialtyLabel
      ? [specialtyLabel, typeLabel].join(" \u00b7 ")
      : typeLabel;

  return (
    <Link
      href={providerProfileHref(entry.partner_id)}
      data-testid="directory-card"
      className="flex flex-col items-start gap-1 rounded-lg border border-hairline bg-surface p-4 shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <span className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
          {verifiedLabel}
        </span>
        <span className="whitespace-nowrap text-sm text-txt-sub">
          {distanceLabel}
        </span>
      </div>
      <strong className="text-txt">
        {entry.practice_name ?? "CareSetu provider"}
      </strong>
      <span className="text-sm text-txt-muted">{meta}</span>
    </Link>
  );
}
