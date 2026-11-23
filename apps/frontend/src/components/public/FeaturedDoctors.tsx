"use client";

// PHASE-2.6 T09 (#200): homepage section 5 - featured doctor cards
// (blueprint §3.1 row 5). Live proof of supply: cards render from the
// public-directory integration point (lib/directory/featured - gap G2),
// which since PHASE-6 T05b (#318) resolves through the real search API; when
// no activated supply exists the section shows the honest "Directory
// launching soon in Daltonganj" empty state. No fake/static provider cards,
// ever.
//
// #961: card anatomy follows the prototype's `.illus-card` template - avatar
// with initials, name, specialty, area, verified badge, distance and consult
// fee when present - but rendered ONLY from real directory fields. Payload
// fields that do not exist (rating, reviews, video, tags, ribbons) are never
// fabricated: the node is omitted. Loading and fetch-failure degradation are
// unchanged (failure logs and degrades to empty).

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  fetchFeaturedDoctors,
  type FeaturedDoctor,
} from "@/lib/directory/featured";
import { directoryHref, providerProfileHref } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// Two-letter monogram from the display name: honorifics ("Dr.", "Prof.") are
// skipped so "Dr. A. Kumar" reads "AK". Purely presentational - the name
// itself always renders next to it.
const PAISE_PER_RUPEE = 100;

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

function DoctorCard({
  doctor,
  featured,
}: {
  doctor: FeaturedDoctor;
  featured: {
    verified: string;
    viewProfile: string;
    consultLabel: string;
  };
}) {
  // Cards deep-link to the provider profile surface that ships with
  // PHASE-6 T06. Every card is active-and-verified by construction (the
  // featured endpoint only returns FEAT-004 Rule 1 rows), so the verified
  // indicator is truthful. Distance and fee render only when the payload
  // carried them; a card with neither simply has no fee cell text.
  const distance = Number(doctor.distance_km.toFixed(1));
  const feeRupees =
    doctor.consultation_fee === null
      ? null
      : Math.round(doctor.consultation_fee / PAISE_PER_RUPEE);

  return (
    <Link
      href={providerProfileHref(doctor.id)}
      className="group flex h-full flex-col gap-2.5 rounded-2xl border border-hairline bg-surface p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-border hover:shadow-[0_14px_30px_-16px_rgba(2,6,23,0.22)]"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-lg font-semibold text-accent-strong"
        >
          {initialsOf(doctor.name)}
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-base font-bold leading-snug tracking-tight text-txt">
            {doctor.name}
          </span>
          {doctor.specialty && (
            <span className="text-sm text-txt-muted">{doctor.specialty}</span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-success-soft px-2.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wide text-success-text">
          {featured.verified}
        </span>
        <span className="text-xs font-medium text-txt-muted">
          {distance} km
        </span>
      </div>
      {doctor.area && (
        <span className="flex items-center gap-1.5 text-sm text-txt-sub">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="shrink-0 text-txt-muted"
          >
            <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {doctor.area}
        </span>
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
            className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          >
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-44 animate-pulse rounded-2xl bg-hairline-soft"
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
          <div
            className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
            data-testid="featured-cards"
          >
            {doctors.map((doctor) => (
              <DoctorCard
                key={doctor.id}
                doctor={doctor}
                featured={t.featured}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
