// PHASE-6 T06 (#312), extracted by #618: the public provider profile's RENDERER.
// One presentational component, fed a projection, that owns no transport - so the
// public page and the doctor's live preview run the same code and cannot drift.
//
// The split is the whole point, so both halves say what they are for:
//
//   - THIS component decides what a patient reads. It takes the projection as a
//     prop and fetches nothing, emits nothing, and holds no load status, because
//     a projection either exists or it does not.
//   - The fetching container beside it decides what is reachable. The skeleton,
//     the not-found state and the retryable error are about the request, and the
//     retry button's state lives with the request.
//
// Truthfulness rules (FEAT-005 / ADR-0011): the verified badge, the trust cue and
// each credential's status render ONLY from the fields the projection carries -
// `verified` and `credential.status`. Nothing here invents a verification, and
// nothing renders a field the payload does not carry.
//
// #619: the profile now has TWO bands, and this file owns the platform's half of
// the boundary. The VERIFIED bands are here - the seal, the trust cue and the
// credentials, each with a solid edge and a tick that came from the API. The
// DECLARED band is the doctor's own claims and lives beside this file, in
// `ProviderProfileDeclaredBand`, with a dashed edge and a heading that says
// nobody checked it.
//
// The one rule that decides what belongs where: a value the platform derived may
// sit in a solid-edged band, and a value the provider DECLARED may not - not
// because it reads untrustworthy, but because putting it inside the verified edge
// would vouch for it. That is why the summary rows below carry the provider's
// type and nothing else: `area` is the declared locality since #612/#613, so it
// renders in the declared band with the rest of the address rather than here.
//
// The breadcrumb is in the body, not in the container, on purpose: it is what a
// patient actually reads on this surface, so the doctor's preview shows it too
// rather than showing a profile that is one row short of the real one.
//
// The cost of that choice is that the preview's breadcrumb links point at the
// PUBLIC directory (`DIRECTORY_VARIANT_ROUTES`), so a doctor who clicks "Doctor"
// inside their own preview leaves the console and lands on the patient surface.
// That is a link that navigates where its label says it does, and a doctor
// clicking it is a doctor asking to see the real page - which is why it is left
// live rather than defanged, and why the preview is rendered as content the
// doctor can interact with rather than as a disabled mock.

import Link from "next/link";

import { ProviderProfileDeclaredBand } from "./ProviderProfileDeclaredBand";
import {
  DIRECTORY_ROUTE,
  DIRECTORY_VARIANT_ROUTES,
  type ProviderType,
} from "@/lib/directory/links";
import type { ProviderProfile } from "@/lib/directory/profile";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

function formatExpiryDate(value: string, lang: "en" | "hi"): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
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

function joinParts(parts: Array<string | null | undefined>): string {
  return parts
    .filter((p) => typeof p === "string" && p.length > 0)
    .join(" \u00b7 ");
}

/**
 * The profile, rendered from a projection.
 *
 * `headingLevel` is the ONE thing the host states, and it is a document-outline
 * fact rather than a profile fact: the public route's `<main>` makes the doctor's
 * name its `h1`, while the console already gives its `h1` to the identity band
 * and #615 asserts the page has exactly one. Same text, same element, only the
 * level differs - which is why this cannot become a place the two surfaces
 * disagree about what a patient reads.
 */
export function ProviderProfileBody({
  profile,
  headingLevel,
}: {
  profile: ProviderProfile;
  headingLevel: 1 | 2;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile;
  const Heading = `h${headingLevel}` as "h1" | "h2";

  const typeLabel: Record<ProviderType, string> = {
    doctor: t.typeDoctor,
    lab: t.typeLab,
    chemist: t.typeChemist,
  };

  const name = profile.practice_name ?? "CareSetu provider";
  const variantHref =
    DIRECTORY_VARIANT_ROUTES[profile.partner_type] ?? DIRECTORY_ROUTE;
  const variantLabel = typeLabel[profile.partner_type];
  // The singular `specialty` here IS the declared band's first member, so the two
  // do print the same word. That overlap is #613's decision rather than this
  // file's: the subtitle is the one line the narrow surfaces read - the directory
  // card and every rail that reuses it - and the band is where the whole selection
  // is answered. Dropping the subtitle would strip those surfaces of a label they
  // have always had; dropping the band would leave a patient shown only the first
  // of the kinds of care a provider practises. So it is stated twice, on purpose,
  // and the band is the one that is honest about being unverified.
  const subtitle = joinParts([
    variantLabel,
    ...(profile.specialty ? [profile.specialty] : []),
  ]);

  return (
    <div data-testid="public-profile-body">
      <nav aria-label="Breadcrumb" className="text-sm text-txt-muted">
        <Link href="/" className="hover:underline">
          {STRINGS[lang].nav.home}
        </Link>
        <span className="mx-2">/</span>
        <Link href={variantHref} className="hover:underline">
          {variantLabel}
        </Link>
        <span className="mx-2">/</span>
        <span className="text-txt">{name}</span>
      </nav>

      {/* Profile hero (PROTO-PHASE-6 `.profile-hero`, mobile left-aligned) */}
      <section
        className="mt-4 rounded-lg border border-hairline bg-surface p-6 shadow-card"
        data-testid="profile-hero"
      >
        <div className="flex items-start gap-4">
          <span
            aria-hidden="true"
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-lg font-semibold text-accent-strong"
          >
            {initials(name)}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Heading
                data-testid="profile-name"
                className="text-xl font-semibold text-txt"
              >
                {name}
              </Heading>
              {profile.verified && (
                <span
                  data-testid="profile-verified"
                  className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text"
                >
                  {t.verifiedByCareSetu}
                </span>
              )}
            </div>
            {subtitle ? (
              <p data-testid="profile-subtitle" className="mt-1 text-txt-sub">
                {subtitle}
              </p>
            ) : null}
          </div>
        </div>
      </section>

      {/* Trust cue */}
      <section className="mt-3 flex items-center gap-3 rounded-lg border border-accent-border bg-accent-soft px-4 py-3">
        <span aria-hidden="true" className="text-xl">
          {"\u{1F512}"}
        </span>
        <div>
          <div className="text-sm font-semibold text-txt">
            {profile.verified ? t.verifiedByCareSetu : t.verified}
          </div>
          <div className="text-xs text-txt-muted">{variantLabel}</div>
        </div>
        {profile.verified && (
          <span className="ml-auto shrink-0 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
            {t.active}
          </span>
        )}
      </section>

      {/* Credentials display (FEAT-005 - label + status, never raw documents).
          This is the VERIFIED band, and it is the only band with a solid edge. */}
      <section
        className="mt-3 rounded-lg border border-hairline bg-surface p-5 shadow-card"
        data-testid="profile-credentials"
      >
        <h2 className="text-base font-semibold text-txt">
          {profile.partner_type === "doctor"
            ? t.credentialsHeading
            : t.credentialsAndLicensesHeading}
        </h2>
        <ul className="mt-2 divide-y divide-hairline">
          {profile.credentials.map((credential) => (
            <li
              key={credential.credential_type}
              data-testid="credential-row"
              className="flex items-start justify-between gap-3 py-2.5"
            >
              <div>
                <div className="text-sm font-medium text-txt">
                  {t.credentialTypes[
                    credential.credential_type as keyof typeof t.credentialTypes
                  ] ?? credential.credential_type}
                </div>
                {credential.expires_at ? (
                  <div className="text-xs text-txt-muted">
                    {t.expiresOn(formatExpiryDate(credential.expires_at, lang))}
                  </div>
                ) : null}
              </div>
              {credential.status === "verified" && (
                <span
                  data-testid="credential-verified"
                  className="shrink-0 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text"
                >
                  {t.verified}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* The platform's own summary of what this provider IS. It is a solid-edged
          band, so it carries platform-derived facts only: the type is the fact,
          and the declared band's specialties, address and locality live below, in
          the band that says they are claims. Nothing declared appears here. */}
      <section
        className="mt-3 rounded-lg border border-hairline bg-surface p-5 shadow-card"
        data-testid="profile-details"
      >
        <h2 className="text-base font-semibold text-txt">
          {profile.partner_type === "doctor"
            ? t.practiceDetailsHeading
            : t.detailsHeading}
        </h2>
        <dl className="mt-2 space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-txt-muted">{t.typeLabel}</dt>
            <dd className="text-right font-medium text-txt">{variantLabel}</dd>
          </div>
        </dl>
      </section>

      {/* The provider's own claims, last of the bands and visibly outside them.
          Placed after the platform's summary rather than before it so the page
          reads in one direction: what CareSetu checked, what this provider is,
          and then what the provider says - in that order, with the edge change
          marking the handover. */}
      <ProviderProfileDeclaredBand profile={profile} />

      {/* CTA (future phase) */}
      <section className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-5 shadow-card">
        <p className="text-sm text-txt-muted">{t.comingSoonBody}</p>
        <button
          type="button"
          disabled
          aria-disabled="true"
          tabIndex={-1}
          className="shrink-0 cursor-not-allowed rounded-lg border border-hairline bg-surface px-4 py-2 text-sm font-medium text-txt-muted opacity-70"
        >
          {t.comingSoon}
        </button>
      </section>
    </div>
  );
}
