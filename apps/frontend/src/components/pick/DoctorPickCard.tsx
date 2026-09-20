"use client";

// PHASE-8.1 T11 (#449): one doctor card on the patient pick-a-doctor step.
// Shares DirectoryCard's verified-truthfulness rules (ADR-0011 "tick gone =
// card gone" - the verified pill renders only when the backend-derived flag
// is true, and the card still defensively drops a false-tick row). Beyond the
// shared browse surface, the pick card carries the consultation fee (or the
// fee-not-set marker, US-10 - a missing fee never blocks the pick), the
// credentials-verified summary, a deep link to the verified profile, and the
// "Book with this doctor" CTA that opens the pick consent sheet.

import Link from "next/link";
import { BadgeCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { providerProfileHref } from "@/lib/directory/links";
import type { DirectoryEntry } from "@/lib/directory/search";

export function formatFeePaise(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);
}

interface DoctorPickCardProps {
  entry: DirectoryEntry;
  /** Provider-type label (localised, e.g. "Doctors"). */
  typeLabel: string;
  /** Doctor-only specialty label, or null for labs/chemists. */
  specialtyLabel: string | null;
  verifiedLabel: string;
  /** Distance already localised by the caller (e.g. "1.2 km"). */
  distanceLabel: string;
  /** Consultation-fee field label from the pick dictionary. */
  feeLabel: string;
  feeNotSetLabel: string;
  credentialsVerifiedLabel: string;
  bookCtaLabel: string;
  viewProfileLabel: string;
  /** Opens the consent sheet for this doctor. */
  onBook: (entry: DirectoryEntry) => void;
}

export function DoctorPickCard({
  entry,
  typeLabel,
  specialtyLabel,
  verifiedLabel,
  distanceLabel,
  feeLabel,
  feeNotSetLabel,
  credentialsVerifiedLabel,
  bookCtaLabel,
  viewProfileLabel,
  onBook,
}: DoctorPickCardProps) {
  if (!entry.verified) return null;

  const meta = [entry.specialty && specialtyLabel, typeLabel, entry.area]
    .filter(Boolean)
    .join(" \u00b7 ");

  const fee =
    entry.consultation_fee !== null
      ? formatFeePaise(entry.consultation_fee)
      : feeNotSetLabel;

  return (
    <div
      data-testid="pick-doctor-card"
      className="flex flex-col gap-3 rounded-lg border border-hairline bg-surface p-4 shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <span
          data-testid="pick-verified"
          className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text"
        >
          <BadgeCheck aria-hidden="true" className="h-3 w-3" />
          {verifiedLabel}
        </span>
        <span className="whitespace-nowrap text-sm text-txt-sub">
          {distanceLabel}
        </span>
      </div>

      <Link
        href={providerProfileHref(entry.partner_id)}
        data-testid="pick-doctor-name"
        className="text-txt hover:underline"
      >
        <strong>{entry.practice_name ?? "CareSetu provider"}</strong>
      </Link>
      <span className="text-sm text-txt-muted">{meta}</span>

      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
            {feeLabel}
          </dt>
          <dd
            data-testid="pick-fee"
            className={
              entry.consultation_fee === null ? "text-txt-muted" : "text-txt"
            }
          >
            {fee}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
            {credentialsVerifiedLabel}
          </dt>
          <dd data-testid="pick-credentials" className="text-txt">
            {verifiedLabel}
          </dd>
        </div>
      </dl>

      <div className="mt-auto flex items-center justify-between gap-3 pt-1">
        <Link
          href={providerProfileHref(entry.partner_id)}
          data-testid="pick-view-profile"
          className="text-sm font-medium text-accent-strong underline-offset-4 hover:underline"
        >
          {viewProfileLabel}
        </Link>
        <Button size="sm" data-testid="pick-book" onClick={() => onBook(entry)}>
          {bookCtaLabel}
        </Button>
      </div>
    </div>
  );
}
