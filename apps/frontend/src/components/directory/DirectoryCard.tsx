"use client";

// PHASE-6 T05a (#966): directory result card rewritten to the finalized
// Phase-6 Zocdoc-style two-panel prototype (prototype/phase-6/doctors.html,
// `.dir-card-zoc` / `.dir-p1` / `.dir-p2`). Left panel carries the provider
// anatomy (avatar, ribbon, name, credentials, practice, specialty +
// experience, rating, facts, verified tick, distance, tags, location, fee);
// right panel is the 14-day `AvailabilityDateGrid`. The card deep-links to
// `/providers/:id` and fires `partner.selected` on click (T6).

// Truthfulness rules (FEAT-005 / ADR-0011): the verified tick renders only
// when the backend-derived flag is true (search visibility and the tick share
// one derivation, so a false-tick row can never show), and the card renders
// name, partner type, specialty and area - never the dropped `consultType`,
// never an invented area string.

"use client";

import Link from "next/link";
import { BadgeCheck, MapPin, Video } from "lucide-react";

import { emitPartnerSelected } from "@/lib/directory/emit";
import { providerProfileHref } from "@/lib/directory/links";
import type { DirectoryEntry } from "@/lib/directory/search";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";
import { getMockCardData, getMockRating } from "@/lib/directory/mockDisplay";
import { AvailabilityDateGrid } from "./AvailabilityDateGrid";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

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

/** Mock fact icon -> lucide element. Fields without a mapping render label
 * only - the backend will own these icons when the card payload lands. */
const FACT_ICON: Record<string, React.ElementType> = {
  video: Video,
  home: Video,
  homeCollection: Video,
};

export function DirectoryCard({
  entry,
  typeLabel,
  specialtyLabel,
  verifiedLabel,
  distanceLabel,
}: DirectoryCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].directory;
  const name = entry.practice_name ?? "CareSetu provider";
  const photo = usePartnerPhotoSource(
    entry.partner_id,
    entry.photo_ref ?? null,
  );
  const mock = getMockCardData(entry.partner_id, entry.partner_type);
  const rating = getMockRating(entry.partner_id);

  // Defensive second gate on the one shared derivation: a row the backend
  // marks unverified must not surface a card ("tick gone = card gone").
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

  const feeRupees =
    entry.consultation_fee === null
      ? null
      : Math.round(entry.consultation_fee / 100);

  const addressLine = [entry.address_line, entry.city]
    .filter(Boolean)
    .join(", ");

  return (
    <Link
      href={providerProfileHref(entry.partner_id)}
      data-testid="directory-card"
      onClick={() =>
        // T6: a card tap is one interaction - fire the anonymous
        // `partner.selected` pick exactly once (onClick, not an effect that
        // could re-run on re-render). Fire-and-forget; never blocks nav.
        emitPartnerSelected({
          partner_id: entry.partner_id,
          partner_type: entry.partner_type,
          source: "search_card",
        })
      }
      className="grid grid-cols-[40%_60%] grid-rows-[1fr_auto] items-start gap-2 rounded-lg border border-hairline bg-surface p-4 shadow-card transition hover:shadow-pop hover:-translate-y-px min-w-0 [@media_(max-width:720px)]:grid-cols-[1fr] [@media_(max-width:720px)]:gap-3 [@media_(max-width:720px)]:p-4"
    >
      {/* P1 LEFT */}
      <div
        data-testid="directory-card-p1"
        className="grid grid-rows-[auto_1fr] gap-3 min-w-0 pl-2 [@media_(max-width:720px)]:grid-rows-[auto_auto] [@media_(max-width:720px)]:pl-0"
      >
        {/* P1T: Avatar | Tag+Name+Practice */}
        <div
          data-testid="directory-card-p1t"
          className="grid grid-cols-[72px_1fr] gap-2 items-start min-w-0 [@media_(max-width:720px)]:grid-cols-[64px_1fr] [@media_(max-width:480px)]:grid-cols-[1fr] [@media_(max-width:480px)]:text-left"
        >
          <div
            data-testid="directory-card-avatar-wrap"
            className="relative shrink-0 w-[72px] h-[72px] [@media_(max-width:720px)]:w-16 [@media_(max-width:720px)]:h-16 [@media_(max-width:480px)]:w-16 [@media_(max-width:480px)]:h-16"
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
                className="flex h-full w-full items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-2xl font-semibold text-accent-strong [@media_(max-width:720px)]:text-xl"
              >
                {initials(name)}
              </span>
            )}
            {mock.videoBadge && (
              <span
                data-testid="directory-card-video-badge"
                aria-label="Video visits available"
                className="absolute bottom-0.5 right-0.5 h-6 w-6 rounded-full bg-accent text-on-accent flex items-center justify-center border-2 border-surface text-xs"
              >
                <Video className="h-3 w-3" aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1 min-w-0">
            {mock.highlightRibbon && (
              <span
                data-testid="directory-card-ribbon"
                className="inline-block self-start text-[0.6875rem] font-semibold text-warm bg-warm-soft border border-[#fed7aa] rounded-full px-2 py-0.5 whitespace-nowrap"
              >
                {mock.highlightRibbon}
              </span>
            )}
            <div className="flex items-baseline gap-2 flex-wrap min-w-0">
              <strong className="text-txt text-lg font-semibold leading-[1.3]">
                {name}
              </strong>
              {mock.credentials && (
                <span className="text-txt-muted text-[0.8125rem]">
                  {mock.credentials}
                </span>
              )}
            </div>
            {practiceLine && (
              <span
                data-testid="directory-card-practice"
                className="text-txt-sub text-sm font-medium truncate"
              >
                {practiceLine}
              </span>
            )}
          </div>
        </div>

        {/* P1B: Specialty, Rating, Facts, Meta, Tags, Location, Fee */}
        <div
          data-testid="directory-card-p1b"
          className="flex flex-col gap-1.5 min-w-0"
        >
          {specialtyLine && (
            <span
              data-testid="directory-card-specialty"
              className="text-txt-muted text-sm"
            >
              {specialtyLine}
            </span>
          )}
          <div className="flex items-center gap-1.5">
            <span
              className="text-warm text-sm leading-none tracking-[1px]"
              aria-hidden="true"
            >
              {Array.from({ length: Math.floor(rating.stars) })
                .map(() => "★")
                .join("")}
              {rating.stars % 1 >= 0.5 ? "☆" : ""}
            </span>
            <span className="text-txt-muted text-sm">
              {`${rating.stars.toFixed(1)} (${t.ratingReviews(
                rating.reviewCount,
              )})`}
            </span>
          </div>
          <div
            data-testid="directory-card-facts"
            className="flex flex-wrap gap-3"
          >
            {mock.facts.map((fact, index) => {
              const Icon = FACT_ICON[fact.icon];
              return (
                <span
                  key={index}
                  data-testid="directory-card-fact"
                  className="inline-flex items-center gap-1 text-txt-sub text-[0.8125rem]"
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
          <div className="flex flex-wrap items-center gap-2">
            <span
              data-testid="directory-card-verified"
              className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-xs font-semibold text-success-text"
            >
              <BadgeCheck className="h-3 w-3 shrink-0" aria-hidden="true" />
              {verifiedLabel}
            </span>
            <span className="text-txt-muted text-[0.8125rem] whitespace-nowrap">
              {distanceLabel}
            </span>
          </div>
          <div
            data-testid="directory-card-tags"
            className="flex flex-wrap gap-1.5"
          >
            {mock.tags.map((tag, index) => (
              <span
                key={index}
                data-testid="directory-card-tag"
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold min-h-6 whitespace-nowrap ${
                  tag.variant === "accent"
                    ? "border border-accent-border bg-accent-soft text-accent-strong"
                    : "bg-hairline-soft text-txt-muted"
                }`}
              >
                {tag.label}
              </span>
            ))}
          </div>
          {addressLine && (
            <div
              data-testid="directory-card-location"
              className="flex items-center gap-[0.3rem] text-txt-sub text-sm"
            >
              <MapPin
                className="h-3.5 w-3.5 shrink-0 text-txt-muted"
                aria-hidden="true"
              />
              {addressLine}
            </div>
          )}
          {feeRupees !== null && (
            <div
              data-testid="directory-card-fee"
              className="text-txt-muted text-sm"
            >
              {`${t.fee}: ₹${feeRupees}`}
            </div>
          )}
        </div>
      </div>

      {/* P2 RIGHT: Date Grid */}
      <div
        data-testid="directory-card-p2"
        className="flex flex-col gap-2 pl-3 border-l border-hairline-soft min-h-full [@media_(max-width:720px)]:pl-0 [@media_(max-width:720px)]:border-l-0 [@media_(max-width:720px)]:border-t [@media_(max-width:720px)]:border-hairline-soft [@media_(max-width:720px)]:pt-2 [@media_(max-width:720px)]:mt-1"
      >
        <AvailabilityDateGrid
          mode={entry.partner_type}
          partnerId={entry.partner_id}
        />
      </div>
    </Link>
  );
}

export function formatDistanceKm(
  distanceKm: number,
  formatKm: (km: string) => string,
): string {
  return formatKm(distanceKm.toFixed(1));
}
