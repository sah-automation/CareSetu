"use client";

// PHASE-6 profile redesign (#968): the public provider profile's RENDERER,
// rewritten to the finalized two-column prototype layout
// (prototype/phase-6/doctor-profile.html and partner-profile.html):
//
//   - breadcrumb (full width)
//   - left column: hero, trust cue, credentials, details
//   - right column (sticky): month grid, map card
//
// It stays a presentational component fed a projection: no fetch, no emit, no
// load status. The fetching container beside it owns the skeleton, the not-found
// state and the retry button. Both hosts (the public page and the doctor's live
// preview) render through this one component and cannot drift.
//
// Truthfulness rules (FEAT-005 / ADR-0011): the verified badge, the trust cue and
// each credential's status render ONLY from the fields the projection carries.
// Nothing here invents a verification.
//
// Declared-vs-verified: after #619 the declared content is folded INTO the
// details card instead of a separate dashed band. The card's solid edge stays
// (it is the platform's card), and a one-line muted note on its title says the
// declared rows are claims nobody checked. The declared groups keep their
// testids (`profile-declared-*`) so the preview and the public page's own
// assertions keep reading the same rows.

import Link from "next/link";
import { MapPin } from "lucide-react";

import { formatInrPaise } from "@/lib/money";
import {
  getMockPackagePrice,
  getMockProfileDistance,
  getMockServices,
} from "@/lib/directory/mockDisplay";
import {
  DIRECTORY_ROUTE,
  DIRECTORY_VARIANT_ROUTES,
  type ProviderType,
} from "@/lib/directory/links";
import { declaredText, type ProviderProfile } from "@/lib/directory/profile";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileMonthGrid } from "./ProfileMonthGrid";
import { ProfileMapCard } from "./ProfileMapCard";

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

/** The label for one member of a closed vocabulary, or `null` when this client
 * cannot name it. `null` is the honest answer for a value the map does not hold -
 * a row can outlive the vocabulary it was written against - and dropping it keeps
 * the rule the same everywhere: no label, no value, no invented string. */
function labelFor(
  labels: Record<string, string>,
  value: string,
): string | null {
  const label = labels[value];
  return typeof label === "string" && label !== "" ? label : null;
}

/** A declared selection as one line of text: every member this client can name,
 * in the provider's own declared order, and nothing for a member it cannot. */
function declaredSelectionText(
  labels: Record<string, string>,
  selection: readonly string[],
): string | null {
  const named = selection
    .map((value) => labelFor(labels, value))
    .filter((label): label is string => label !== null);
  return named.length > 0 ? named.join(", ") : null;
}

/** The structured address, as the separately declared parts the provider saved.
 * Each part keeps its FIELD name beside its label because the field name is what
 * identifies it to a test and a screen reader, while the label is what identifies
 * it to a patient - and the label changes with the language. A part that was not
 * declared is dropped, so a half-saved address shows the half that exists rather
 * than five rows of which two are blank. */
function declaredAddressParts(
  profile: ProviderProfile,
  landmarkLabel: string,
  address: {
    addressLineLabel: string;
    addressLocalityLabel: string;
    addressCityLabel: string;
    addressPinLabel: string;
  },
): [string, string, string][] {
  return (
    [
      ["address-line", address.addressLineLabel, profile.address_line],
      ["landmark", landmarkLabel, profile.landmark],
      // `locality`, and only `locality`. The payload also carries `area`, and
      // since #612/#613 that is the SAME fact - the server serves both from
      // `address_locality` - so falling back to it would be dead code that
      // pretends a second source exists. It is here rather than in the summary
      // band because the narrow surfaces read `area` and this band reads the
      // field it names, which is why the two agree about where a practice is.
      ["locality", address.addressLocalityLabel, profile.locality],
      ["city", address.addressCityLabel, profile.city],
      ["pin-code", address.addressPinLabel, profile.pin_code],
    ] as const
  )
    .map(([field, label, value]) => [field, label, declaredText(value)])
    .filter((row): row is [string, string, string] => row[2] !== null);
}

function DeclaredRow({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-txt-muted">{label}</dt>
      <dd className="text-right font-medium text-txt" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function DeclaredGroup({
  testId,
  heading,
  children,
}: {
  testId: string;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4" data-testid={testId}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
        {heading}
      </h3>
      <dl className="mt-1.5 space-y-2 text-sm">{children}</dl>
    </div>
  );
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
  const vocab = STRINGS[lang].doctorProfile;
  const Heading = `h${headingLevel}` as "h1" | "h2";

  const typeLabel: Record<ProviderType, string> = {
    doctor: t.typeDoctor,
    lab: t.typeLab,
    chemist: t.typeChemist,
  };

  const isDoctor = profile.partner_type === "doctor";
  const name = profile.practice_name ?? "CareSetu provider";
  const photo = usePartnerPhotoSource(
    profile.partner_id,
    profile.photo_ref ?? null,
  );
  const variantHref =
    DIRECTORY_VARIANT_ROUTES[profile.partner_type] ?? DIRECTORY_ROUTE;
  const variantLabel = typeLabel[profile.partner_type];

  const declared = {
    clinicName: declaredText(profile.clinic_name),
    specialties: declaredSelectionText(
      vocab.specialtyLabels,
      profile.specialties,
    ),
    languages: declaredSelectionText(vocab.languageLabels, profile.languages),
    consultingDays: declaredSelectionText(
      vocab.dayLabels,
      profile.consulting_days,
    ),
    consultingHours: declaredText(profile.consulting_hours),
    about: declaredText(profile.about),
    // `0` is a fact a provider can declare and renders as one. A truthiness check
    // here would report a provider with no experience as having declared nothing,
    // which is a different claim and the wrong one.
    experience:
      typeof profile.experience_years === "number"
        ? t.yearsOfExperience(profile.experience_years)
        : null,
    address: declaredAddressParts(profile, t.declaredLandmarkLabel, vocab),
  };

  const declaresSomething =
    declared.clinicName !== null ||
    declared.specialties !== null ||
    declared.languages !== null ||
    declared.consultingDays !== null ||
    declared.consultingHours !== null ||
    declared.about !== null ||
    declared.experience !== null ||
    declared.address.length > 0;

  const subtitleParts: string[] = [];
  if (isDoctor) {
    if (profile.specialty) subtitleParts.push(profile.specialty);
    if (typeof profile.experience_years === "number") {
      subtitleParts.push(t.yearsOfExperience(profile.experience_years));
    }
    if (declared.clinicName) subtitleParts.push(declared.clinicName);
  } else {
    subtitleParts.push(variantLabel);
  }
  const subtitle =
    subtitleParts.length > 0 ? subtitleParts.join(" \u00b7 ") : null;

  // The hero's right-aligned price line: the real consultation fee for a doctor,
  // a mock package price for a lab or chemist. `consultation_fee` is the price
  // the provider set, so it renders as a price and never carries a verified
  // marker; the non-doctor price is a stand-in until a backend price lands.
  const heroPackage = !isDoctor
    ? getMockPackagePrice(profile.partner_id, profile.partner_type)
    : null;

  // The trust cue reads only from the credentials the projection carries: it
  // appears when one of them is verified, and its title is per-type.
  const hasVerifiedCredential = profile.credentials.some(
    (credential) => credential.status === "verified",
  );

  const address = [profile.address_line, profile.locality, profile.city]
    .filter((p) => typeof p === "string" && p.length > 0)
    .join(", ");
  const distance = getMockProfileDistance(profile.partner_id);

  return (
    <div data-testid="public-profile-body">
      {/* Breadcrumb (full width, above the two columns). */}
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

      {/* Two columns: left holds the profile, right holds the rail. */}
      <div className="grid grid-cols-[minmax(0,1fr)_440px] gap-5 max-[980px]:grid-cols-1">
        <div className="flex flex-col gap-4 min-w-0">
          {/* Profile hero (PROTO-PHASE-6 `.profile-hero`, mobile left-aligned) */}
          <section
            className="mt-4 rounded-lg border border-hairline bg-surface p-6 shadow-card"
            data-testid="profile-hero"
          >
            <div className="flex items-start gap-4">
              {photo.src ? (
                <img
                  src={photo.src}
                  alt={name}
                  className="h-14 w-14 shrink-0 rounded-full border-2 border-accent-border object-cover"
                />
              ) : (
                <span
                  aria-hidden="true"
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-lg font-semibold text-accent-strong"
                >
                  {initials(name)}
                </span>
              )}
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
                  {isDoctor && profile.consultation_fee !== null && (
                    <span
                      data-testid="profile-hero-fee"
                      className="ml-auto shrink-0"
                    >
                      {formatInrPaise(profile.consultation_fee)}
                    </span>
                  )}
                </div>
                {subtitle ? (
                  <p
                    data-testid="profile-subtitle"
                    className="mt-1 text-txt-sub"
                  >
                    {subtitle}
                  </p>
                ) : null}
                {heroPackage ? (
                  <p
                    data-testid="profile-hero-package"
                    className="mt-1 text-xs text-txt-muted"
                  >
                    {heroPackage}
                  </p>
                ) : null}
              </div>
            </div>
            {address || distance || profile.consulting_hours ? (
              <div
                data-testid="profile-hero-strip"
                className="mt-4 flex flex-wrap gap-3 text-xs text-txt-muted"
              >
                {address ? (
                  <span className="inline-flex items-center gap-1">
                    <MapPin
                      className="h-3.5 w-3.5 shrink-0"
                      aria-hidden="true"
                    />
                    {address}
                  </span>
                ) : null}
                {distance ? (
                  <span data-testid="profile-hero-distance">{distance}</span>
                ) : null}
                {profile.consulting_hours ? (
                  <span data-testid="profile-hero-hours">
                    {t.availability.kinds.doctor}: {profile.consulting_hours}
                  </span>
                ) : null}
              </div>
            ) : null}
          </section>

          {/* Trust cue */}
          {hasVerifiedCredential && (
            <section className="mt-3 flex items-center gap-3 rounded-lg border border-accent-border bg-accent-soft px-4 py-3">
              <span aria-hidden="true" className="text-xl">
                {"\u{1F512}"}
              </span>
              <div>
                <div className="text-sm font-semibold text-txt">
                  {isDoctor ? t.trustDoctorTitle : t.trustPartnerTitle}
                </div>
                <div className="text-xs text-txt-muted">{variantLabel}</div>
              </div>
              {profile.verified && (
                <span className="ml-auto shrink-0 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
                  {t.active}
                </span>
              )}
            </section>
          )}

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
                        {t.expiresOn(
                          formatExpiryDate(credential.expires_at, lang),
                        )}
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

          {/* Details card (solid edge): the platform's card, with the provider's
              own claims folded into it and a muted note on its title. */}
          <section
            className="mt-3 rounded-lg border border-hairline bg-surface p-5 shadow-card"
            data-testid="profile-details"
          >
            <h2 className="text-base font-semibold text-txt">
              {isDoctor ? t.practiceDetailsHeading : t.detailsHeading}
            </h2>
            {declaresSomething && (
              <p
                className="mt-1 text-xs text-txt-muted"
                data-testid="profile-declared-note"
              >
                {t.declaredNote}
              </p>
            )}
            <dl className="mt-2 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-txt-muted">{t.typeLabel}</dt>
                <dd className="text-right font-medium text-txt">
                  {variantLabel}
                </dd>
              </div>
            </dl>
            {declaresSomething && (
              <div data-testid="profile-declared" className="mt-3">
                {declared.clinicName || declared.specialties ? (
                  <DeclaredGroup
                    testId="profile-declared-practice"
                    heading={t.declaredPracticeHeading}
                  >
                    {declared.clinicName ? (
                      <DeclaredRow
                        label={t.clinicNameLabel}
                        value={declared.clinicName}
                        testId="profile-declared-clinic-name"
                      />
                    ) : null}
                    {declared.specialties ? (
                      <DeclaredRow
                        label={t.specialtiesLabel}
                        value={declared.specialties}
                        testId="profile-declared-specialties"
                      />
                    ) : null}
                  </DeclaredGroup>
                ) : null}

                {declared.address.length > 0 ? (
                  <DeclaredGroup
                    testId="profile-declared-address"
                    heading={t.declaredAddressHeading}
                  >
                    {declared.address.map(([field, label, value]) => (
                      <DeclaredRow
                        key={field}
                        label={label}
                        value={value}
                        testId={`profile-declared-address-${field}`}
                      />
                    ))}
                  </DeclaredGroup>
                ) : null}

                {declared.languages ||
                declared.consultingDays ||
                declared.consultingHours ||
                declared.experience ? (
                  <DeclaredGroup
                    testId="profile-declared-consulting"
                    heading={t.declaredConsultingHeading}
                  >
                    {declared.languages ? (
                      <DeclaredRow
                        label={t.languagesLabel}
                        value={declared.languages}
                        testId="profile-declared-languages"
                      />
                    ) : null}
                    {declared.consultingDays ? (
                      <DeclaredRow
                        label={t.consultingDaysLabel}
                        value={declared.consultingDays}
                        testId="profile-declared-days"
                      />
                    ) : null}
                    {declared.consultingHours ? (
                      <DeclaredRow
                        label={t.consultingHoursLabel}
                        value={declared.consultingHours}
                        testId="profile-declared-hours"
                      />
                    ) : null}
                    {declared.experience ? (
                      <DeclaredRow
                        label={t.experienceLabel}
                        value={declared.experience}
                        testId="profile-declared-experience"
                      />
                    ) : null}
                  </DeclaredGroup>
                ) : null}

                {/* Prose, not a label/value row: `about` is not a value, it is the one
                    declared field long enough that reading it as a value would flatten it. */}
                {declared.about ? (
                  <div
                    className="mt-4"
                    data-testid="profile-declared-about-block"
                  >
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                      {t.declaredAboutHeading}
                    </h3>
                    <p
                      className="mt-1.5 text-sm text-txt-sub"
                      data-testid="profile-declared-about"
                    >
                      {declared.about}
                    </p>
                  </div>
                ) : null}
              </div>
            )}

            {isDoctor ? null : (
              <div data-testid="profile-services" className="mt-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
                  {t.servicesHeading}
                </h3>
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {getMockServices(profile.partner_type).map((service) => (
                    <span
                      key={service}
                      className="rounded-lg border border-hairline bg-surface px-2.5 py-0.5 text-[0.75rem] text-txt-sub"
                    >
                      {service}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* CTA (future phase) */}
          <section className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-5 shadow-card">
            <div>
              <div className="text-sm font-semibold text-txt">
                {isDoctor ? t.ctaDoctorTitle : t.ctaPartnerTitle}
              </div>
              <p className="mt-0.5 text-xs text-txt-muted">
                {t.comingSoonBody}
              </p>
            </div>
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

        {/* Right rail: sticky whole-month availability, then location. */}
        <aside className="sticky top-4 self-start flex flex-col gap-4 min-w-0">
          <ProfileMonthGrid
            partnerId={profile.partner_id}
            mode={profile.partner_type}
            hours={profile.consulting_hours}
          />
          <ProfileMapCard
            mode={profile.partner_type}
            locality={profile.locality}
            city={profile.city}
            pincode={profile.pin_code}
          />
        </aside>
      </div>
    </div>
  );
}
