"use client";

// PHASE-2.6 T09 (#200): homepage section 5 - featured doctor cards
// (blueprint §3.1 row 5). Live proof of supply: cards render from the
// public-directory integration point (lib/directory/featured - gap G2),
// which since PHASE-6 T05b (#318) resolves through the real search API; when
// no activated supply exists the section shows the honest "Directory
// launching soon in Daltonganj" empty state. No fake/static provider cards,
// ever.
//
// #961: card anatomy follows the prototype's `.illus-card` template. #965
// completes the template with the full homepage-resolved-v2 anatomy - the
// video badge, ribbon, credentials, practice (clinic), specialty + years of
// experience, mock rating, fact rows, verified badge + distance, mode and
// language tags, the declared address line and the consult fee - the same
// content the directory and provider-profile cards already render. Real
// directory fields (practice, experience, languages, address) ride the
// featured payload; backend-less decorations (rating, video badge, ribbon,
// facts, tags) resolve through lib/directory/mockDisplay. Loading and
// fetch-failure degradation are unchanged (failure logs and degrades to
// empty).
//
// #962: the card row is the prototype's horizontal scroll-snap carousel
// (`.illus-track` + `.illus-nav` + `.illus-hint`) - fixed-width cards, arrow
// buttons that disable at both ends, a swipe hint underneath, and instant
// scrolling under prefers-reduced-motion. The card streams the doctor's
// profile photo through the same `usePartnerPhotoSource` hook the directory
// card uses (backend-only reads, so a leaked URL discloses nothing) and
// falls back to the initials avatar. Only the nearest FEATURED_LIMIT doctors
// render; "View all doctors" is the path to the full directory.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { MapPin, ShieldCheck, Users, Video } from "lucide-react";

import {
  fetchFeaturedDoctors,
  type FeaturedDoctor,
} from "@/lib/directory/featured";
import { directoryHref, providerProfileHref } from "@/lib/directory/links";
import { specialtyLabel } from "@/lib/directory/specialtyLabel";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";
import {
  getMockCardData,
  getMockRating,
  type MockTag,
} from "@/lib/directory/mockDisplay";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// Two-letter monogram from the display name: honorifics ("Dr.", "Prof.") are
// skipped so "Dr. A. Kumar" reads "AK". Purely presentational - the name
// itself always renders next to it.
const PAISE_PER_RUPEE = 100;
/** Track gap (`gap-4`) between cards - the carousel's scroll step unit. */
const CARD_GAP_PX = 16;
/** Prototype card width; the ≤560px rule narrows it (see card classes). */
const CARD_WIDTH_PX = 330;
/** End tolerance from the prototype's `initIllusCarousel` (2px). */
const CAROUSEL_END_TOLERANCE_PX = 2;

interface DoctorCardStrings {
  verified: string;
  viewProfile: string;
  consultLabel: string;
}

interface CarouselStrings extends DoctorCardStrings {
  carouselPrev: string;
  carouselNext: string;
  carouselLabel: string;
  carouselHint: string;
}

function initialsOf(name: string): string {
  const words = name
    .split(/\s+/)
    .filter((word) => word.length > 0 && !/^(dr\.?|prof\.?)$/i.test(word));
  const letters = words
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");
  return letters || name.charAt(0).toUpperCase();
}

/** Mock fact icon -> lucide element. Fields without a mapping render label
 * only - the backend will own these icons when the card payload lands. */
const FACT_ICON: Record<string, React.ElementType> = {
  video: Video,
  insurance: ShieldCheck,
  "new-patients": Users,
};

// Reduced-motion floor (blueprint §9.4): the carousel only animates its
// scroll when the visitor has not asked for less motion. Without matchMedia
// (or before the query resolves) the smooth path is the default.
function prefersSmoothScroll(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return true;
  }
  return window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
}

function DoctorCard({
  doctor,
  featured,
}: {
  doctor: FeaturedDoctor;
  featured: DoctorCardStrings;
}) {
  // Cards deep-link to the provider profile surface that ships with
  // PHASE-6 T06. Every card is active-and-verified by construction (the
  // featured endpoint only returns FEAT-004 Rule 1 rows), so the verified
  // indicator is truthful. Distance and fee render only when the payload
  // carried them; a card with neither simply has no fee cell text.
  const { lang } = useLang();
  const dir = STRINGS[lang].directory;
  const photo = usePartnerPhotoSource(doctor.id, doctor.photo_ref ?? null);
  const distance = Number(doctor.distance_km.toFixed(1));
  const feeRupees =
    doctor.consultation_fee === null
      ? null
      : Math.round(doctor.consultation_fee / PAISE_PER_RUPEE);
  const mock = getMockCardData(doctor.id, "doctor");
  const rating = getMockRating(doctor.id);

  // Real declared data first: practice (clinic, or the locality when no
  // clinic is declared), specialty · years of experience, and the declared
  // address line - the same mapping rules the directory card applies.
  const practiceLine = doctor.clinic_name ?? doctor.area ?? "";
  const experienceLabel =
    doctor.experience_years != null
      ? dir.experienceYears?.(doctor.experience_years) ??
        `${doctor.experience_years} years experience`
      : null;
  const specialtyLine = [
    doctor.specialty ? specialtyLabel(lang, doctor.specialty) : null,
    experienceLabel,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");
  const addressLine = [doctor.address_line, doctor.city]
    .filter(Boolean)
    .join(", ");

  // Mode tag from the mock template; real declared languages win over the
  // mock language tag when present (the profile hero's rule).
  const languageLabels: Record<string, string> =
    STRINGS[lang].doctorProfile.languageLabels;
  const languagesLabel =
    doctor.languages
      .map((value) => languageLabels[value] ?? null)
      .filter((label): label is string => label !== null && label !== "")
      .join(", ") || null;
  const tags: MockTag[] = [];
  if (mock.tags[0]) tags.push(mock.tags[0]);
  if (languagesLabel) {
    tags.push({ label: languagesLabel, variant: "muted" });
  }
  for (const tag of mock.tags.slice(1)) {
    if (languagesLabel && tag.variant === "muted") continue;
    tags.push(tag);
  }
  if (tags.length < 2 && mock.tags[1]) tags.push(mock.tags[1]);

  return (
    <li className="w-[330px] shrink-0 snap-start max-[560px]:w-[285px]">
      <Link
        href={providerProfileHref(doctor.id)}
        className="group flex h-full flex-col gap-2.5 rounded-2xl border border-hairline bg-surface p-5 transition-all duration-200 hover:-translate-y-[3px] hover:border-accent-border hover:shadow-[0_14px_30px_-16px_rgba(2,6,23,0.22)]"
      >
        <div className="flex items-start gap-3">
          <div className="relative h-[60px] w-[60px] shrink-0">
            {photo.src ? (
              <img
                src={photo.src}
                alt={doctor.name}
                className="h-full w-full rounded-full border-2 border-accent-border object-cover"
              />
            ) : (
              <span
                aria-hidden="true"
                className="flex h-full w-full items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-lg font-semibold text-accent-strong"
              >
                {initialsOf(doctor.name)}
              </span>
            )}
            {mock.videoBadge && (
              <span
                data-testid="featured-card-video-badge"
                aria-label="Video visits available"
                className="absolute bottom-0 right-0 flex h-6 w-6 items-center justify-center rounded-full border-2 border-surface bg-accent text-on-accent"
              >
                <Video className="h-3 w-3" aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            {mock.highlightRibbon && (
              <span
                data-testid="featured-card-ribbon"
                className="inline-block self-start text-[0.6875rem] font-semibold text-warm bg-warm-soft border border-[#fed7aa] rounded-full px-2 py-0.5 whitespace-nowrap"
              >
                {mock.highlightRibbon}
              </span>
            )}
            <div className="flex items-baseline gap-1.5 flex-wrap min-w-0">
              <span className="text-[1.05rem] font-bold leading-snug tracking-tight text-txt">
                {doctor.name}
              </span>
              {mock.credentials && (
                <span className="text-[0.8125rem] font-normal text-txt-muted truncate">
                  {mock.credentials}
                </span>
              )}
            </div>
            {practiceLine && (
              <span
                data-testid="featured-card-practice"
                className="text-sm font-medium text-txt-sub truncate"
              >
                {practiceLine}
              </span>
            )}
          </div>
        </div>
        {specialtyLine && (
          <span
            data-testid="featured-card-specialty"
            className="text-sm text-txt-muted"
          >
            {specialtyLine}
          </span>
        )}
        <div
          data-testid="featured-card-rating"
          className="flex items-center gap-1.5"
        >
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
            {`${rating.stars.toFixed(1)} (${dir.ratingReviews(
              rating.reviewCount,
            )})`}
          </span>
        </div>
        <div data-testid="featured-card-facts" className="flex flex-wrap gap-3">
          {mock.facts.map((fact, index) => {
            const Icon = FACT_ICON[fact.icon];
            return (
              <span
                key={index}
                data-testid="featured-card-fact"
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
          <span className="rounded-full bg-success-soft px-2.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wide text-success-text">
            {featured.verified}
          </span>
          <span className="text-[0.8rem] font-medium text-txt-muted">
            {distance} km
          </span>
        </div>
        <div
          data-testid="featured-card-tags"
          className="flex flex-wrap gap-1.5"
        >
          {tags.map((tag, index) => (
            <span
              key={index}
              data-testid="featured-card-tag"
              className={`inline-flex min-h-6 items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${
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
            data-testid="featured-card-location"
            className="flex items-center gap-[0.3rem] text-txt-sub text-sm"
          >
            <MapPin
              className="h-3.5 w-3.5 shrink-0 text-txt-muted"
              aria-hidden="true"
            />
            {addressLine}
          </div>
        )}
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-hairline-soft pt-2.5">
          <span className="text-sm font-bold text-txt">
            {feeRupees !== null ? (
              <>
                {"₹"}
                {feeRupees}{" "}
                <span className="text-xs font-normal text-txt-muted">
                  {featured.consultLabel}
                </span>
              </>
            ) : null}
          </span>
          <span className="rounded-full border border-accent-border bg-accent-soft px-3 py-1 text-xs font-semibold text-accent-strong transition-colors group-hover:border-accent group-hover:bg-accent group-hover:text-on-accent">
            {featured.viewProfile}
          </span>
        </div>
      </Link>
    </li>
  );
}

// The prototype's `.illus-carousel`: a scroll-snap track with overlay arrow
// buttons that disable at each end, plus the hint line underneath.
function FeaturedCarousel({
  doctors,
  featured,
}: {
  doctors: FeaturedDoctor[];
  featured: CarouselStrings;
}) {
  const trackRef = useRef<HTMLUListElement | null>(null);
  // Both ends start disabled: the track's real dimensions land in the mount
  // effect, so no arrow ever claims content that is not there.
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(true);

  useEffect(() => {
    const track = trackRef.current;
    if (track === null) return;
    const update = () => {
      // Same end tolerance as the prototype's initIllusCarousel.
      const max =
        track.scrollWidth - track.clientWidth - CAROUSEL_END_TOLERANCE_PX;
      setAtStart(track.scrollLeft <= CAROUSEL_END_TOLERANCE_PX);
      setAtEnd(track.scrollLeft >= max);
    };
    update();
    track.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      track.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [doctors]);

  const scrollByCards = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (track === null) return;
    const firstCard = track.firstElementChild;
    const step =
      (firstCard instanceof HTMLElement
        ? firstCard.getBoundingClientRect().width
        : CARD_WIDTH_PX) + CARD_GAP_PX;
    const behavior: ScrollBehavior = prefersSmoothScroll() ? "smooth" : "auto";
    if (typeof track.scrollBy === "function") {
      track.scrollBy({ left: direction * step, behavior });
    } else {
      track.scrollLeft += direction * step;
    }
  };

  return (
    <div className="relative mt-5">
      <ul
        data-testid="featured-cards"
        ref={trackRef}
        aria-label={featured.carouselLabel}
        className="flex items-stretch snap-x snap-mandatory gap-4 overflow-x-auto pb-4 pt-1 [scrollbar-color:var(--hairline)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar]:rounded-full [&::-webkit-scrollbar-thumb]:bg-hairline"
      >
        {doctors.map((doctor) => (
          <DoctorCard key={doctor.id} doctor={doctor} featured={featured} />
        ))}
      </ul>
      <button
        type="button"
        data-testid="featured-prev"
        aria-label={featured.carouselPrev}
        disabled={atStart}
        onClick={() => scrollByCards(-1)}
        className="absolute -left-2 top-[40%] z-5 flex h-10 w-10 items-center justify-center rounded-full border border-hairline bg-surface text-txt shadow-pop transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-40 max-[560px]:left-0"
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
      <button
        type="button"
        data-testid="featured-next"
        aria-label={featured.carouselNext}
        disabled={atEnd}
        onClick={() => scrollByCards(1)}
        className="absolute -right-2 top-[40%] z-5 flex h-10 w-10 items-center justify-center rounded-full border border-hairline bg-surface text-txt shadow-pop transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-40 max-[560px]:right-0"
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      <p className="-mt-1.5 text-center text-xs text-txt-muted">
        {featured.carouselHint}
      </p>
    </div>
  );
}

export function FeaturedDoctors() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;
  // null = still resolving the integration point; [] = no activated supply.
  const [doctors, setDoctors] = useState<FeaturedDoctor[] | null>(null);

  useEffect(() => {
    let active = true;
    fetchFeaturedDoctors()
      .then((cards) => {
        if (active) setDoctors(cards);
      })
      .catch((err: unknown) => {
        // Degradation rule (third-party-integration standard): a failed
        // proof-of-supply fetch degrades to the honest empty state - but the
        // failure is logged so it stays distinguishable from true emptiness.
        console.warn(
          "[featured-doctors] fetch failed, degrading to empty state:",
          err,
        );
        if (active) setDoctors([]);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section data-testid="section-featured">
      <div className="mx-auto w-full max-w-6xl px-4 pb-10 pt-4">
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="flex flex-col gap-1">
            <div className="text-xs font-bold uppercase tracking-[0.08em] text-accent">
              {t.featured.eyebrow}
            </div>
            <h2 className="home-h2 text-txt">{t.featured.title}</h2>
          </div>
          <a
            href={directoryHref("doctor")}
            className="text-sm font-semibold text-accent-strong hover:underline"
          >
            {t.featured.viewAll}
          </a>
        </div>
        {doctors === null ? (
          <div
            data-testid="featured-loading"
            className="mt-5 flex gap-4 overflow-hidden pb-4 pt-1"
          >
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-44 w-[330px] shrink-0 animate-pulse rounded-2xl bg-hairline-soft max-[560px]:w-[285px]"
              />
            ))}
          </div>
        ) : doctors.length === 0 ? (
          <div
            data-testid="empty-state"
            className="mt-5 flex flex-col items-center rounded-[18px] border border-dashed border-accent-border bg-surface px-6 py-11 text-center"
          >
            <span
              aria-hidden="true"
              className="mb-4 flex h-[60px] w-[60px] items-center justify-center rounded-full border border-accent-border bg-accent-soft text-accent"
            >
              <svg
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 11l3 3L22 4" />
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
              </svg>
            </span>
            <h3 className="text-xl font-bold tracking-tight text-accent-strong">
              {t.featured.emptyTitle}
            </h3>
            <p className="mt-2 max-w-[46ch] text-sm text-txt-sub">
              {t.featured.emptyBody}
            </p>
            <Link
              href="/login"
              className="mt-5 inline-flex items-center justify-center rounded-full bg-accent px-6 py-2.5 text-sm font-semibold text-on-accent shadow-[0_6px_16px_-6px_rgba(15,118,110,0.5)] transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {t.featured.emptyCta}
            </Link>
          </div>
        ) : (
          <FeaturedCarousel doctors={doctors} featured={t.featured} />
        )}
      </div>
    </section>
  );
}
