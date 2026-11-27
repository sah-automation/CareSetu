"use client";

// PHASE-6 profile redesign (#968): the public provider profile's RENDERER,
// rewritten to the finalized two-column prototype layout
// (prototype/phase-6/doctor-profile.html and partner-profile.html):
//
//   - breadcrumb (full width)
//   - left column: hero (ribbon, rating, facts, tags, fee), trust cue,
//     credentials, practice/details grid, services (non-doctor), CTA
//   - right column (sticky): month grid, map card
//
// It stays a presentational component fed a projection: no fetch, no emit, no
// load status. The fetching container beside it owns the skeleton, the not-found
// state and the retry button. Both hosts (the public page and the doctor's live
// preview) render through this one component and cannot drift.
//
// Truthfulness rules (FEAT-005 / ADR-0011): the verified badge, the trust cue and
// each credential's status render ONLY from the fields the projection carries.
// Nothing here invents a verification. Mock stand-ins (rating, facts, ribbons,
// credential numbers, consultation types) are the same single-swap-point
// placeholders DirectoryCard uses until their backends land.
//
// Declared-vs-verified: after #619 the declared content is folded INTO the
// details card instead of a separate dashed band. The card's solid edge stays
// (it is the platform's card), and a one-line muted note on its title says the
// declared rows are claims nobody checked. The declared groups keep their
// testids (`profile-declared-*`) so the preview and the public page's own
// assertions keep reading the same rows.

import Link from "next/link";
import {
  BadgeCheck,
  Clock,
  Download,
  FileText,
  MapPin,
  ShieldCheck,
  Truck,
  Users,
  Video,
} from "lucide-react";

import { formatInrPaise } from "@/lib/money";
import {
  getMockAccreditation,
  getMockAvatarEmoji,
  getMockCardData,
  getMockConsultationTypes,
  getMockCredentialDetail,
  getMockHomeCollection,
  getMockPackagePrice,
  getMockProfileDistance,
  getMockRating,
  getMockReportTurnaround,
  getMockServiceArea,
  getMockServices,
  getMockTrustDetail,
  type MockFact,
  type MockTag,
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

/** Prototype `.grid2` practice/details row: muted label left, strong value right. */
function DetailRow({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <span className="text-txt-muted">{label}</span>
      <strong
        className="text-right font-semibold text-txt"
        data-testid={testId}
      >
        {value}
      </strong>
    </div>
  );
}

/** Mock fact icon -> lucide element. Fields without a mapping render label only. */
const FACT_ICON: Record<string, React.ElementType> = {
  video: Video,
  insurance: ShieldCheck,
  "new-patients": Users,
  "home-collection": Download,
  clock: Clock,
  certified: BadgeCheck,
  delivery: Truck,
  erx: FileText,
  hours: Clock,
};

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
  const dir = STRINGS[lang].directory;
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

  const mock = getMockCardData(profile.partner_id, profile.partner_type);
  const rating = getMockRating(profile.partner_id);
  const emoji = getMockAvatarEmoji(profile.partner_type);

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
    // `0` is a fact a provider can declare and renders as one. A truthfulness check
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
    if (profile.partner_type === "lab") subtitleParts.push("NABL accredited");
  }
  const subtitle =
    subtitleParts.length > 0 ? subtitleParts.join(" \u00b7 ") : null;

  // The hero's right-aligned price line: the real consultation fee for a doctor.
  // `consultation_fee` is the price the provider set, so it renders as a price and
  // never carries a verified marker. Non-doctors carry no fee block (prototype
  // puts their package price in the hero strip instead).
  const heroFee =
    isDoctor && profile.consultation_fee !== null
      ? formatInrPaise(profile.consultation_fee)
      : null;

  // Hero-strip package price for a lab/chemist (prototype's
  // "Full body checkup: ₹1,200").
  const heroPackage = !isDoctor
    ? getMockPackagePrice(profile.partner_id, profile.partner_type)
    : null;

  // The trust cue reads only from the credentials the projection carries: it
  // appears when one of them is verified, and its title is per-type.
  const hasVerifiedCredential = profile.credentials.some(
    (credential) => credential.status === "verified",
  );
  const trustDetail = getMockTrustDetail(
    profile.partner_id,
    profile.partner_type,
  );

  const address = [profile.address_line, profile.locality, profile.city]
    .filter((p) => typeof p === "string" && p.length > 0)
    .join(", ");
  const distance = getMockProfileDistance(profile.partner_id);

  // Hero tags: prototype's accent mode tag + languages + a secondary tag.
  // Real declared languages win over the mock language tag when present.
  const heroTags: MockTag[] = [];
  if (mock.tags[0]) heroTags.push(mock.tags[0]);
  if (declared.languages) {
    heroTags.push({ label: declared.languages, variant: "muted" });
  }
  for (const tag of mock.tags.slice(1)) {
    if (declared.languages && tag.variant === "muted") continue;
    heroTags.push(tag);
  }
  if (heroTags.length < 2 && mock.tags[1]) heroTags.push(mock.tags[1]);

  const facts: readonly MockFact[] = mock.facts;
  const consultationTypes = getMockConsultationTypes(profile.partner_type);
  const credentialDetailFor = (credentialType: string) =>
    getMockCredentialDetail(profile.partner_id, credentialType);

  // Practice / details grid rows (prototype `.grid2`).
  const detailRows: Array<{
    label: string;
    value: string;
    testId?: string;
    key: string;
  }> = [];
  detailRows.push({
    key: "type",
    label: t.typeLabel,
    value: variantLabel,
  });
  if (isDoctor) {
    // Specialty row only when the declared SELECTION names at least one member.
    // A selection of unknown/blank members is "declared nothing named", not a
    // reason to fall back to the singular `specialty` (the hero subtitle already
    // carries that label for the directory's one-representative display).
    if (declared.specialties) {
      detailRows.push({
        key: "specialty",
        label: t.specialtyLabel,
        value: declared.specialties,
        testId: "profile-declared-specialties",
      });
    }
    if (declared.experience) {
      detailRows.push({
        key: "experience",
        label: t.experienceLabel,
        value: declared.experience,
        testId: "profile-declared-experience",
      });
    }
    if (consultationTypes) {
      detailRows.push({
        key: "consult-types",
        label: t.consultationTypesLabel,
        value: consultationTypes,
      });
    }
    if (declared.languages) {
      detailRows.push({
        key: "languages",
        label: t.languagesLabel,
        value: declared.languages,
        testId: "profile-declared-languages",
      });
    }
    if (declared.consultingDays) {
      detailRows.push({
        key: "days",
        label: t.consultingDaysLabel,
        value: declared.consultingDays,
        testId: "profile-declared-days",
      });
    }
    if (declared.consultingHours) {
      detailRows.push({
        key: "hours",
        label: t.consultingHoursLabel,
        value: declared.consultingHours,
        testId: "profile-declared-hours",
      });
    }
    if (declared.clinicName) {
      detailRows.push({
        key: "clinic",
        label: t.clinicNameLabel,
        value: declared.clinicName,
        testId: "profile-declared-clinic-name",
      });
    }
    if (address) {
      detailRows.push({
        key: "location",
        label: t.locationLabel,
        value: address,
      });
    }
    // Structured address parts keep their field testids for the suite and the
    // screen reader; they sit under the joined Location row as the parts that
    // produced it.
    for (const [field, label, value] of declared.address) {
      detailRows.push({
        key: `addr-${field}`,
        label,
        value,
        testId: `profile-declared-address-${field}`,
      });
    }
    if (heroFee) {
      detailRows.push({
        key: "fee",
        label: t.consultationFeeLabel,
        value: heroFee,
      });
    }
  } else {
    const accreditation = getMockAccreditation(profile.partner_type);
    if (accreditation) {
      detailRows.push({
        key: "accreditation",
        label: t.accreditationLabel,
        value: accreditation,
      });
    }
    if (address) {
      detailRows.push({
        key: "location",
        label: t.locationLabel,
        value: address,
      });
    }
    for (const [field, label, value] of declared.address) {
      detailRows.push({
        key: `addr-${field}`,
        label,
        value,
        testId: `profile-declared-address-${field}`,
      });
    }
    const serviceArea = getMockServiceArea(profile.locality);
    if (serviceArea) {
      detailRows.push({
        key: "service-area",
        label: t.serviceAreaLabel,
        value: serviceArea,
      });
    }
    const homeCollection = getMockHomeCollection(profile.partner_type);
    if (homeCollection) {
      detailRows.push({
        key: "home-collection",
        label: t.homeCollectionLabel,
        value: homeCollection,
      });
    }
    const turnaround = getMockReportTurnaround(profile.partner_type);
    if (turnaround) {
      detailRows.push({
        key: "turnaround",
        label: t.reportTurnaroundLabel,
        value: turnaround,
      });
    }
    if (declared.languages) {
      detailRows.push({
        key: "languages",
        label: t.languagesLabel,
        value: declared.languages,
        testId: "profile-declared-languages",
      });
    }
  }

  const services = isDoctor ? [] : getMockServices(profile.partner_type);

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
          {/* Profile hero (PROTO-PHASE-6 `.profile-hero`) */}
          <section
            className="mt-4 rounded-lg border border-hairline bg-surface p-6 shadow-card"
            data-testid="profile-hero"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-4 min-w-0">
                {photo.src ? (
                  <img
                    src={photo.src}
                    alt={name}
                    className={`h-[72px] w-[72px] shrink-0 border-2 border-accent-border object-cover ${
                      isDoctor ? "rounded-full" : "rounded-lg"
                    }`}
                  />
                ) : (
                  <span
                    aria-hidden="true"
                    className={`flex h-[72px] w-[72px] shrink-0 items-center justify-center border-2 border-accent-border bg-accent-soft text-2xl font-semibold text-accent-strong ${
                      isDoctor ? "rounded-full" : "rounded-lg"
                    }`}
                  >
                    {isDoctor ? initials(name) : emoji ?? initials(name)}
                  </span>
                )}
                <div className="min-w-0">
                  {mock.highlightRibbon && (
                    <span
                      data-testid="profile-highlight"
                      className="inline-block w-fit whitespace-nowrap rounded-full border border-[#fed7aa] bg-warm-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-warm"
                    >
                      {mock.highlightRibbon}
                    </span>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Heading
                      data-testid="profile-name"
                      className="text-2xl font-semibold text-txt"
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
                    <p
                      data-testid="profile-subtitle"
                      className="mt-1 text-txt-sub"
                    >
                      {subtitle}
                    </p>
                  ) : null}
                  <div
                    className="mt-1 flex items-center gap-1.5 text-sm"
                    data-testid="profile-rating"
                  >
                    <span
                      className="leading-none tracking-[1px] text-warm"
                      aria-hidden="true"
                    >
                      {Array.from({ length: Math.floor(rating.stars) })
                        .map(() => "\u2605")
                        .join("")}
                      {rating.stars % 1 >= 0.5 ? "\u2606" : ""}
                    </span>
                    <span className="text-txt-muted">
                      {`${rating.stars.toFixed(1)} (${dir.ratingReviews(
                        rating.reviewCount,
                      )})`}
                    </span>
                  </div>
                  <div
                    className="mt-1 flex flex-wrap gap-3 text-[0.8125rem] text-txt-sub"
                    data-testid="profile-facts"
                  >
                    {facts.map((fact, index) => {
                      const Icon = FACT_ICON[fact.icon];
                      return (
                        <span
                          key={index}
                          data-testid="profile-fact"
                          className="inline-flex items-center gap-1"
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
                  <div
                    className="mt-1 flex flex-wrap gap-1.5"
                    data-testid="profile-tags"
                  >
                    {heroTags.map((tag, index) => (
                      <span
                        key={index}
                        data-testid="profile-tag"
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
                </div>
              </div>
              {heroFee && (
                <div
                  className="shrink-0 text-right"
                  data-testid="profile-hero-fee"
                >
                  <div className="text-2xl font-semibold text-accent">
                    {heroFee}
                  </div>
                  <div className="text-xs text-txt-muted">
                    {t.consultationFeeLabel}
                  </div>
                </div>
              )}
            </div>
            {address || distance || profile.consulting_hours || heroPackage ? (
              <div
                data-testid="profile-hero-strip"
                className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-hairline-soft pt-3 text-sm text-txt-muted"
              >
                {address ? (
                  <span className="inline-flex items-center gap-1 text-txt-sub">
                    <MapPin
                      className="h-3.5 w-3.5 shrink-0 text-txt-muted"
                      aria-hidden="true"
                    />
                    {address}
                  </span>
                ) : null}
                {distance ? (
                  <span data-testid="profile-hero-distance" className="text-xs">
                    {distance}
                  </span>
                ) : null}
                {isDoctor && profile.consulting_hours ? (
                  <span
                    data-testid="profile-hero-hours"
                    className="text-txt-sub"
                  >
                    {t.opdLabel}: {profile.consulting_hours}
                  </span>
                ) : null}
                {!isDoctor && heroPackage ? (
                  <span
                    data-testid="profile-hero-package"
                    className="text-txt-sub"
                  >
                    {heroPackage}
                  </span>
                ) : null}
              </div>
            ) : null}
          </section>

          {/* Trust cue */}
          {hasVerifiedCredential && (
            <section
              className="mt-3 flex items-center gap-3 rounded-lg border border-accent-border bg-accent-soft px-4 py-3"
              data-testid="profile-trust"
            >
              <span aria-hidden="true" className="text-xl">
                {"\u{1F512}"}
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-txt">
                  {isDoctor ? t.trustDoctorTitle : t.trustPartnerTitle}
                </div>
                <div
                  className="text-xs text-txt-muted"
                  data-testid="profile-trust-detail"
                >
                  {trustDetail}
                </div>
                {profile.verified && (
                  <span className="mt-1.5 inline-block rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
                    {t.active}
                  </span>
                )}
              </div>
            </section>
          )}

          {/* Credentials display (FEAT-005 - label + status, never raw documents).
              This is the VERIFIED band, and it is the only band with a solid edge. */}
          <section
            className="mt-3 rounded-lg border border-hairline bg-surface p-5 shadow-card"
            data-testid="profile-credentials"
          >
            <h2 className="text-base font-semibold text-txt">
              {isDoctor
                ? t.credentialsHeading
                : t.credentialsAndLicensesHeading}
            </h2>
            <ul className="mt-2 divide-y divide-hairline">
              {profile.credentials.map((credential) => {
                const detail = credentialDetailFor(credential.credential_type);
                const expiry = credential.expires_at
                  ? t.expiresOn(formatExpiryDate(credential.expires_at, lang))
                  : null;
                const sub = joinParts([detail, expiry]);
                return (
                  <li
                    key={credential.credential_type}
                    data-testid="credential-row"
                    className="flex items-start justify-between gap-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-txt">
                        {t.credentialTypes[
                          credential.credential_type as keyof typeof t.credentialTypes
                        ] ?? credential.credential_type}
                      </div>
                      {sub ? (
                        <div
                          className="text-xs text-txt-muted"
                          data-testid="credential-detail"
                        >
                          {sub}
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
                );
              })}
            </ul>
          </section>

          {/* Practice details / Details card (solid edge): prototype grid2
              rows + the provider's own claims, with a muted note on the title. */}
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
            <div
              data-testid={declaresSomething ? "profile-declared" : undefined}
              className="mt-3"
            >
              <div className="grid gap-3 sm:grid-cols-2">
                {detailRows.map((row) => (
                  <DetailRow
                    key={row.key}
                    label={row.label}
                    value={row.value}
                    testId={row.testId}
                  />
                ))}
              </div>

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
          </section>

          {/* Services (non-doctor): standalone card, as in partner-profile.html */}
          {services.length > 0 && (
            <section
              className="mt-3 rounded-lg border border-hairline bg-surface p-5 shadow-card"
              data-testid="profile-services"
            >
              <h2 className="text-base font-semibold text-txt">
                {t.servicesHeading}
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {services.map((service) => (
                  <span
                    key={service}
                    className="inline-flex min-h-9 items-center rounded-lg border border-hairline bg-surface px-3 py-1 text-sm text-txt-sub"
                  >
                    {service}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* CTA (future phase) */}
          <section className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-5 shadow-card">
            <div>
              <div className="text-sm font-semibold text-txt">
                {isDoctor ? t.ctaDoctorTitle : t.ctaPartnerTitle}
              </div>
              <p className="mt-0.5 text-xs text-txt-muted">
                {isDoctor ? t.ctaDoctorBody : t.ctaPartnerBody}
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
