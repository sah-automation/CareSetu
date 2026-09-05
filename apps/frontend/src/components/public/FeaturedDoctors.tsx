"use client";

// PHASE-2.6 T09 (#200): homepage section 5 - featured doctor cards
// (blueprint §3.1 row 5). Live proof of supply: cards render from the
// public-directory integration point (lib/directory/featured - gap G2),
// which since PHASE-6 T05b (#318) resolves through the real search API; when
// no activated supply exists the section shows the graceful "Directory
// launching soon in Daltonganj" empty state. No fake/static provider cards,
// ever.

import { useEffect, useState } from "react";
import Link from "next/link";

import { EmptyState } from "@/components/layout/EmptyState";
import {
  fetchFeaturedDoctors,
  type FeaturedDoctor,
} from "@/lib/directory/featured";
import { directoryHref, providerProfileHref } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

function DoctorCard({
  doctor,
  verifiedLabel,
}: {
  doctor: FeaturedDoctor;
  verifiedLabel: string;
}) {
  // Cards deep-link to the provider profile surface that ships with
  // PHASE-6 T06. Every card is active-and-verified by construction (the
  // featured endpoint only returns FEAT-004 Rule 1 rows), so the verified
  // indicator is truthful. Meta joins only non-null parts - the search
  // projection never carries `area`, and `consultType` is dropped (PRD).
  const meta = [doctor.specialty, doctor.area].filter(Boolean).join(" \u00b7 ");
  return (
    <Link
      href={providerProfileHref(doctor.id)}
      className="flex flex-col items-start gap-1 rounded-lg border border-hairline bg-surface p-4 shadow-card transition-shadow hover:shadow-pop"
    >
      <span className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
        {verifiedLabel}
      </span>
      <strong className="text-txt">{doctor.name}</strong>
      {meta ? <span className="text-sm text-txt-muted">{meta}</span> : null}
    </Link>
  );
}

export function FeaturedDoctors() {
  const { lang } = useLang();
  const t = STRINGS[lang].home.featured;
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
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-2xl font-semibold text-txt">{t.title}</h2>
          <a
            href={directoryHref("doctor")}
            className="text-sm text-accent hover:underline"
          >
            {t.viewAll}
          </a>
        </div>
        {doctors === null ? (
          <div
            data-testid="featured-loading"
            className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          >
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-28 animate-pulse rounded-lg bg-hairline-soft"
              />
            ))}
          </div>
        ) : doctors.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              title={t.emptyTitle}
              body={t.emptyBody}
              action={
                <Link
                  href="/login"
                  className="text-sm font-medium text-accent hover:underline"
                >
                  {t.emptyCta}
                </Link>
              }
            />
          </div>
        ) : (
          <div
            className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
            data-testid="featured-cards"
          >
            {doctors.map((doctor) => (
              <DoctorCard
                key={doctor.id}
                doctor={doctor}
                verifiedLabel={t.verified}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
