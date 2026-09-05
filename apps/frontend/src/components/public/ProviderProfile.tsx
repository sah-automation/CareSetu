"use client";

// PHASE-6 T06 (#312): the public provider profile at /providers/:id
// (blueprint §3.1 row 5, PROTO-PHASE-6 doctor-profile.html / partner-profile
// .html as the visual binding - `.profile-hero` mobile left-aligned, binding).
//
// Truthfulness rules: the verified badge and per-credential state render only
// from the backend-derived fields the profile API returns (FEAT-005/ADR-0011);
// the page never invents a verification or a field the payload does not carry
// (no fee/languages/experience/services/consult-type - those exceed the API's
// verified-safe projection). A 404 from the API (partner not `[Active]`, no
// index entry, or an invalid credential) renders the clear not-found state;
// any other failure renders the retryable error state.

import Link from "next/link";

import { useEffect, useState } from "react";

import {
  fetchProviderProfile,
  type ProviderProfile,
} from "@/lib/directory/profile";
import {
  DIRECTORY_ROUTE,
  DIRECTORY_VARIANT_ROUTES,
  type ProviderType,
} from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadStatus = "loading" | "error" | "not-found" | "ready";

interface ProviderProfileProps {
  partnerId: number;
}

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

export function ProviderProfile({ partnerId }: ProviderProfileProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile;
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [profile, setProfile] = useState<ProviderProfile | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setStatus("loading");
    fetchProviderProfile(partnerId)
      .then((result) => {
        if (!active) return;
        if (result.status === "found") {
          setProfile(result.profile);
          setStatus("ready");
        } else {
          setProfile(null);
          setStatus("not-found");
        }
      })
      .catch((err: unknown) => {
        // Operational failure (error-handling-observability §2): logged and
        // surfaced as the retryable error state, distinct from not-found.
        console.error("[provider-profile] load failed:", err);
        if (active) {
          setProfile(null);
          setStatus("error");
        }
      });
    return () => {
      active = false;
    };
  }, [partnerId, retryNonce]);

  const typeLabel: Record<ProviderType, string> = {
    doctor: t.typeDoctor,
    lab: t.typeLab,
    chemist: t.typeChemist,
  };

  if (status === "loading") {
    return (
      <main
        className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6"
        data-testid="profile-loading"
        role="status"
      >
        <p className="sr-only">{t.loadingProfile}</p>
        <div className="h-24 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
        <div className="mt-3 h-20 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
      </main>
    );
  }

  if (status === "not-found") {
    return (
      <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
        <nav aria-label="Breadcrumb" className="text-sm text-txt-muted">
          <Link href={DIRECTORY_ROUTE} className="hover:underline">
            {t.breadcrumbDirectory}
          </Link>
        </nav>
        <div
          data-testid="profile-not-found"
          className="mt-6 rounded-lg border border-hairline bg-surface p-6 text-center"
        >
          <p className="font-medium text-txt">{t.notFoundTitle}</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-txt-muted">
            {t.notFoundBody}
          </p>
          <Link
            href={DIRECTORY_ROUTE}
            className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent/90"
          >
            {t.notFoundCta}
          </Link>
        </div>
      </main>
    );
  }

  if (status === "error" || !profile) {
    return (
      <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
        <div
          data-testid="profile-error"
          className="mt-6 rounded-lg border border-hairline bg-surface p-6 text-center"
        >
          <p className="font-medium text-txt">{t.loadError}</p>
          <button
            type="button"
            onClick={() => setRetryNonce((n) => n + 1)}
            className="mt-4 rounded-lg border border-hairline bg-surface px-4 py-2 text-sm font-medium text-txt hover:bg-hairline-soft"
          >
            {t.retry}
          </button>
        </div>
      </main>
    );
  }

  const name = profile.practice_name ?? "CareSetu provider";
  const variantHref =
    DIRECTORY_VARIANT_ROUTES[profile.partner_type] ?? DIRECTORY_ROUTE;
  const variantLabel = typeLabel[profile.partner_type];
  const subtitle = joinParts([
    variantLabel,
    ...(profile.specialty ? [profile.specialty] : []),
  ]);

  return (
    <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
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
              <h1
                data-testid="profile-name"
                className="text-xl font-semibold text-txt"
              >
                {name}
              </h1>
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

      {/* Credentials display (FEAT-005 - label + status, never raw documents) */}
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
                <span className="shrink-0 rounded-full bg-success-soft px-2 py-0.5 text-xs font-medium text-success-text">
                  {t.verified}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* Details (verified-safe fields only: type, specialty, service area) */}
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
          {profile.specialty ? (
            <div className="flex justify-between gap-3">
              <dt className="text-txt-muted">{t.specialtyLabel}</dt>
              <dd className="text-right font-medium text-txt">
                {profile.specialty}
              </dd>
            </div>
          ) : null}
          {profile.area ? (
            <div className="flex justify-between gap-3">
              <dt className="text-txt-muted">{t.areaLabel}</dt>
              <dd className="text-right font-medium text-txt">
                {profile.area}
              </dd>
            </div>
          ) : null}
        </dl>
      </section>

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
    </main>
  );
}
