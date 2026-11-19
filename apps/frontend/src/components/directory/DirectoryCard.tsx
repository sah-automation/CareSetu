"use client";

// PHASE-6 T05a (#317): one directory result card (PROTO-PHASE-6 `.dir-card`
// visual binding, derived from the FeaturedDoctors `DoctorCard` shape so the
// two directory surfaces share one card language). The card deep-links to the
// provider profile surface (`/providers/:id`) that ships with PHASE-6 T06.
//
// Truthfulness rules (FEAT-005 / ADR-0011): the verified tick renders only
// when the backend-derived flag is true (search visibility and the tick share
// one derivation, so a false-tick row can never show), and the card renders
// name, partner type, specialty and area - never the dropped `consultType`,
// never an invented area string.

"use client";

import Link from "next/link";

import { emitPartnerSelected } from "@/lib/directory/emit";
import { providerProfileHref } from "@/lib/directory/links";
import type { DirectoryEntry } from "@/lib/directory/search";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";

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

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? "")
    .join("")
    .toUpperCase();
}

export function DirectoryCard({
  entry,
  typeLabel,
  specialtyLabel,
  verifiedLabel,
  distanceLabel,
}: DirectoryCardProps) {
  const name = entry.practice_name ?? "CareSetu provider";
  const photo = usePartnerPhotoSource(
    entry.partner_id,
    entry.photo_ref ?? null,
  );

  // Defensive second gate on the one shared derivation: a row the backend
  // marks unverified must not surface a card ("tick gone = card gone").
  if (!entry.verified) return null;

  const meta = [entry.specialty && specialtyLabel, typeLabel, entry.area]
    .filter(Boolean)
    .join(" \u00b7 ");

  return (
    <Link
      href={providerProfileHref(entry.partner_id)}
      data-testid="directory-card"
      onClick={() =>
        // T6 (#328): a card tap is one interaction - fire the anonymous
        // `partner.selected` pick exactly once (onClick, not an effect that
        // could re-run on re-render). Fire-and-forget; never blocks nav.
        emitPartnerSelected({
          partner_id: entry.partner_id,
          partner_type: entry.partner_type,
          source: "search_card",
        })
      }
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
      <div className="flex items-center gap-3">
        {photo.src ? (
          <img
            src={photo.src}
            alt={name}
            className="h-10 w-10 rounded-full object-cover"
          />
        ) : (
          <span
            aria-hidden="true"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent-strong"
          >
            {initials(name)}
          </span>
        )}
        <strong className="text-txt">{name}</strong>
      </div>
      <span className="text-sm text-txt-muted">{meta}</span>
    </Link>
  );
}
