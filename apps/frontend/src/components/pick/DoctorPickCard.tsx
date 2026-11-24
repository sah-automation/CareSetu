"use client";

// PHASE-8.1 T11 (#966): one doctor card on the patient pick-a-doctor step,
// restyled to the Phase-6 card visual language (left-panel anatomy from
// DirectoryCard: avatar, name, credentials, practice, specialty +
// experience, rating, facts, verified tick, distance, fee) while keeping the
// pick-specific Book CTA and fee/verified footer. Shares DirectoryCard's
// verified-truthfulness rules (ADR-0011 "tick gone = card gone"). Beyond the
// shared browse surface, the pick card carries the consultation fee (or the
// fee-not-set marker, US-10 - a missing fee never blocks the pick), the
// credentials-verified summary, a deep link to the verified profile, and the
// "Book with this doctor" CTA that opens the pick consent sheet.

import Link from "next/link";
import { BadgeCheck, Video } from "lucide-react";

import { Button } from "@/components/ui/button";
import { providerProfileHref } from "@/lib/directory/links";
import type { DirectoryEntry } from "@/lib/directory/search";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";
import { getMockCardData, getMockRating } from "@/lib/directory/mockDisplay";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { formatInrPaise } from "@/lib/money";

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

function initials(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .filter((word) => word.length > 0 && !/^(dr\.?|prof\.?)$/i.test(word))
      .slice(0, 2)
      .map((part) => part[0] ?? "")
      .join("")
      .toUpperCase() || name.charAt(0).toUpperCase()
  );
}

const FACT_ICON: Record<string, React.ElementType> = {
  video: Video,
};

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
  const { lang } = useLang();
  const t = STRINGS[lang].directory;
  const name = entry.practice_name ?? "CareSetu provider";
  const photo = usePartnerPhotoSource(
    entry.partner_id,
    entry.photo_ref ?? null,
  );
  const mock = getMockCardData(entry.partner_id, entry.partner_type);
  const rating = getMockRating(entry.partner_id);

  if (!entry.verified) return null;

  const practiceLine =
    entry.partner_type === "doctor"
      ? entry.clinic_name ?? entry.area ?? ""
      : entry.area ?? "";

  const experienceLabel =
    entry.experience_years != null
      ? `${
          t.experienceYears?.(entry.experience_years) ??
          `${entry.experience_years} years experience`
        }`
      : null;

  const specialtyLine = [
    entry.specialty && specialtyLabel,
    typeLabel,
    experienceLabel,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");

  const fee =
    entry.consultation_fee !== null
      ? formatInrPaise(entry.consultation_fee)
      : feeNotSetLabel;

  return (
    <div
      data-testid="pick-doctor-card"
      className="flex flex-col gap-3 rounded-lg border border-hairline bg-surface p-4 shadow-card transition-shadow hover:shadow-pop min-w-0"
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

      <div className="grid grid-cols-[72px_1fr] gap-0.5 items-start min-w-0 mb-2">
        <div
          className="relative shrink-0 w-[72px] h-[72px]"
          data-testid="pick-avatar-wrap"
        >
          {photo.src ? (
            <img
              src={photo.src}
              alt={name}
              className="w-full h-full rounded-full border-2 border-accent-border object-cover"
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex h-full w-full items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-lg font-semibold text-accent-strong"
            >
              {initials(name)}
            </span>
          )}
          {mock.videoBadge && (
            <span
              data-testid="pick-video-badge"
              aria-label="Video visits available"
              className="absolute bottom-1 right-1 h-6 w-6 rounded-full bg-accent text-on-accent flex items-center justify-center shadow-pop border-2 border-surface text-xs"
            >
              <Video className="h-3 w-3" aria-hidden="true" />
            </span>
          )}
        </div>
        <div className="flex flex-col gap-0.25 min-w-0">
          {mock.highlightRibbon && (
            <span
              data-testid="pick-ribbon"
              className="inline-block text-[0.6875rem] font-bold uppercase tracking-wide text-accent-strong bg-accent-soft border border-accent-border rounded-full px-2 py-0.5 whitespace-nowrap"
            >
              {mock.highlightRibbon}
            </span>
          )}
          <div className="flex items-baseline gap-0.5 flex-wrap min-w-0">
            <Link
              href={providerProfileHref(entry.partner_id)}
              data-testid="pick-doctor-name"
              className="text-txt hover:underline truncate"
            >
              <strong className="text-sm leading-snug">{name}</strong>
            </Link>
            {mock.credentials && (
              <span className="text-txt-muted text-xs truncate">
                {mock.credentials}
              </span>
            )}
          </div>
          {practiceLine && (
            <span
              data-testid="pick-practice"
              className="text-txt-sub text-xs truncate whitespace-normal"
            >
              {practiceLine}
            </span>
          )}
        </div>
      </div>

      {specialtyLine && (
        <span data-testid="pick-specialty" className="text-txt-muted text-xs">
          {specialtyLine}
        </span>
      )}
      <div className="flex items-center gap-0.375">
        <span
          className="text-accent-strong text-[0.875rem] font-bold leading-none"
          aria-hidden="true"
        >
          {Array.from({ length: Math.floor(rating.stars) })
            .map(() => "★")
            .join("")}
          {rating.stars % 1 >= 0.5 ? "☆" : ""}
        </span>
        <span className="text-txt-muted text-[0.8125rem]">
          {`${rating.reviewCount} reviews`}
        </span>
      </div>
      <div data-testid="pick-facts" className="flex flex-wrap gap-0.75 mt-0.5">
        {mock.facts.map((fact, index) => {
          const Icon = FACT_ICON[fact.icon];
          return (
            <span
              key={index}
              data-testid="pick-fact"
              className="inline-flex items-center gap-0.25 text-txt-sub text-[0.8125rem]"
            >
              {Icon && (
                <Icon
                  className="h-3.5 w-3.5 shrink-0 text-txt-muted"
                  aria-hidden="true"
                />
              )}
              {fact.label}
            </span>
          );
        })}
      </div>

      <dl className="grid grid-cols-2 gap-2 text-sm mt-2">
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
