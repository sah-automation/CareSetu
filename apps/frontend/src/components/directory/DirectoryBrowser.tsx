"use client";

// PHASE-6 T05a (#317): the interactive /directory browse surface
// (blueprint §3.1 row 2 look, PROTO-PHASE-6 finalized views as the visual
// binding). Search by name (free-text) front and center, filter chips for
// partner type and doctor specialty, result cards with the truthful verified
// tick, and the wider-area fallback labelled honestly "outside your area"
// with every other filter preserved (glossary). Type-preset variants and
// homepage wiring are #318 (T05b) - see the `presetType` prop below.
//
// The URL is the single committed source of truth for filters (?type=&q=&
// specialty=): chips and the search submit replace the query params, and the
// fetch effect keys on them - so a search is deep-linkable and back/forward
// navigable. The only state the URL does not hold is the typed-but-unsubmitted
// query in the input, which is intentionally uncontrolled (keyed by the
// committed query, so external changes remount it fresh without an effect).
//
// `presetType` (T05b): a type-preset variant route (/doctors, /labs,
// /chemists) pins the partner type - the URL's `type` param is ignored, the
// type-filter chip row is suppressed (the route *is* the type filter), and
// commits stay on the variant route instead of /directory.

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { DirectoryCard, formatDistanceKm } from "./DirectoryCard";
import {
  DIRECTORIES_SPECIALTIES,
  searchDirectory,
  type DirectorySearchView,
  type Specialty,
} from "@/lib/directory/search";
import { DIRECTORY_ROUTE, type ProviderType } from "@/lib/directory/links";
import { DIRECTORY_VARIANT_ROUTES } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadState = "loading" | "loaded" | "error";

const PROVIDER_TYPES: ProviderType[] = ["doctor", "lab", "chemist"];

type TypeKey = "typeDoctor" | "typeLab" | "typeChemist";
type SpecialtyKey =
  | "generalPhysician"
  | "pediatrician"
  | "gynecologist"
  | "dentist";

const SPECIALTY_LABEL_KEY: Record<string, SpecialtyKey> = {
  "General Physician": "generalPhysician",
  Pediatrician: "pediatrician",
  Gynecologist: "gynecologist",
  Dentist: "dentist",
};

const TYPE_LABEL_KEY: Record<ProviderType, TypeKey> = {
  doctor: "typeDoctor",
  lab: "typeLab",
  chemist: "typeChemist",
};

function parseProviderType(value: string | null): ProviderType | null {
  return PROVIDER_TYPES.includes(value as ProviderType)
    ? (value as ProviderType)
    : null;
}

function parseSpecialty(value: string | null): Specialty | null {
  return (DIRECTORIES_SPECIALTIES as readonly string[]).includes(
    value as string,
  )
    ? (value as Specialty)
    : null;
}

function mapTypeToKey(type: ProviderType | null): "$all" | ProviderType {
  return type ?? "$all";
}

const chipClass = (active: boolean) =>
  `rounded-full border px-3 py-1.5 text-sm shadow-sm transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong ${
    active
      ? "border-accent-border bg-accent-soft text-accent-strong"
      : "border-hairline bg-surface text-txt-sub"
  }`;

export function DirectoryBrowser({
  presetType,
}: {
  /** T05b: pin the partner type on a variant route (/doctors, /labs,
   * /chemists). The URL's `type` param is ignored while set. */
  presetType?: ProviderType;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].directory;
  const router = useRouter();
  const searchParams = useSearchParams();

  const committedType =
    presetType ?? parseProviderType(searchParams.get("type"));
  const committedSpecialty = parseSpecialty(searchParams.get("specialty"));
  const committedQuery = searchParams.get("q") ?? "";

  const [status, setStatus] = useState<LoadState>("loading");
  const [view, setView] = useState<DirectorySearchView | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let active = true;
    searchDirectory({
      q: committedQuery,
      partnerType: committedType,
      specialty: committedSpecialty,
    })
      .then((result) => {
        if (active) {
          setView(result);
          setStatus("loaded");
        }
      })
      .catch((err: unknown) => {
        if (active) {
          // Operational failure (error-handling-observability §2: `error` for
          // failures, `warn` reserved for degradations) - logged and surfaced
          // as the retryable error state.
          console.error("[directory] search failed:", err);
          setView(null);
          setStatus("error");
        }
      });
    return () => {
      active = false;
    };
  }, [committedQuery, committedType, committedSpecialty, retryNonce]);

  /** Replace the committed filter params on the URL (history replace - chip
   * toggling must not spam the history stack). On a type-preset variant the
   * commits stay on the variant route, dropping the pinned `type` from the
   * URL. */
  function commitFilters(next: {
    type?: ProviderType | null;
    specialty?: Specialty | null;
    q?: string | null;
  }) {
    const params = new URLSearchParams(searchParams.toString());
    const apply = (key: string, value: string | null | undefined) => {
      if (value === undefined) return;
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    };
    // On a type-preset variant the type is fixed by the route itself - any
    // stale `type` param is scrubbed from the URL on commit.
    apply("type", presetType ? null : next.type);
    apply(
      "specialty",
      next.specialty === undefined ? undefined : next.specialty,
    );
    apply("q", next.q === undefined ? undefined : next.q);
    const qs = params.toString();
    const base = presetType
      ? DIRECTORY_VARIANT_ROUTES[presetType]
      : DIRECTORY_ROUTE;
    router.replace(qs ? `${base}?${qs}` : base);
  }

  function selectType(type: ProviderType | null) {
    // Specialty is doctors-only (closed pick-list): switching to lab/chemist
    // drops it so the URL never carries a filter the API ignores.
    commitFilters({
      type,
      specialty: type !== null && type !== "doctor" ? null : committedSpecialty,
    });
  }

  function selectSpecialty(specialty: Specialty | null) {
    // Picking a specialty implies a doctor search (facade pins the type);
    // clearing it keeps any active type choice.
    commitFilters({ type: specialty ? "doctor" : committedType, specialty });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Uncontrolled input: the typed value is read straight from the form.
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    commitFilters({ q });
  }

  function retry() {
    setStatus("loading");
    setRetryNonce((n) => n + 1);
  }

  function clearSearch() {
    commitFilters({ q: null });
  }

  const typeKey = mapTypeToKey(committedType);
  const showSpecialtyChips =
    committedType === null || committedType === "doctor";
  const heading = typeKey === "$all" ? t.heading.all : t.heading[typeKey];

  return (
    <main className="mx-auto w-full max-w-6xl px-4 pb-14 pt-6">
      <header className="flex flex-col gap-1">
        <h1
          data-testid="directory-heading"
          className="text-3xl font-semibold text-txt"
        >
          {heading}
        </h1>
        <p className="text-sm text-txt-muted">{t.subtitle}</p>
      </header>

      <form
        onSubmit={submitSearch}
        role="search"
        className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center"
      >
        <label className="sr-only" htmlFor="directory-search-input">
          {t.searchLabel}
        </label>
        <input
          id="directory-search-input"
          name="q"
          type="search"
          defaultValue={committedQuery}
          key={`query-${committedQuery}`}
          placeholder={t.searchPlaceholder}
          className="min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt placeholder:text-txt-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <Button type="submit">{t.searchCta}</Button>
      </form>

      <div
        className="mt-4 flex flex-wrap items-center gap-2"
        role="group"
        aria-label={t.filtersLabel}
      >
        {/* Type chips are a /directory (all-types) concern: on a type-preset
            variant route the route itself is the type filter. */}
        {!presetType && (
          <>
            <button
              type="button"
              data-testid="type-chip"
              data-active={typeKey === "$all"}
              aria-pressed={typeKey === "$all"}
              onClick={() => selectType(null)}
              className={chipClass(typeKey === "$all")}
            >
              {t.typeAll}
            </button>
            {PROVIDER_TYPES.map((type) => {
              const active = typeKey === type;
              return (
                <button
                  key={type}
                  type="button"
                  data-testid="type-chip"
                  data-active={active}
                  aria-pressed={active}
                  onClick={() => selectType(active ? null : type)}
                  className={chipClass(active)}
                >
                  {t[TYPE_LABEL_KEY[type]]}
                </button>
              );
            })}
          </>
        )}

        {showSpecialtyChips && (
          <>
            <span className="mx-1 hidden h-4 w-px bg-hairline sm:block" />
            {DIRECTORIES_SPECIALTIES.map((specialty) => {
              const active = committedSpecialty === specialty;
              return (
                <button
                  key={specialty}
                  type="button"
                  data-testid="specialty-chip"
                  data-active={active}
                  aria-pressed={active}
                  onClick={() => selectSpecialty(active ? null : specialty)}
                  className={chipClass(active)}
                >
                  {t.specialties[SPECIALTY_LABEL_KEY[specialty]]}
                </button>
              );
            })}
          </>
        )}

        <span className="ml-auto inline-flex items-center gap-1.5 text-sm text-txt-muted">
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
          >
            <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {t.locationDaltonganj}
        </span>
      </div>

      <section aria-live="polite" className="mt-5">
        {status === "loading" && view === null ? (
          <div
            data-testid="directory-loading"
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
            role="status"
          >
            <span className="sr-only">{t.loading}</span>
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-32 animate-pulse rounded-lg bg-hairline-soft"
              />
            ))}
          </div>
        ) : status === "error" && view === null ? (
          <div
            data-testid="directory-error"
            className="rounded-lg border border-hairline bg-accent-soft px-6 py-10 text-center"
          >
            <p className="font-medium text-txt">{t.errorTitle}</p>
            <p className="mt-1 text-sm text-txt-muted">{t.errorBody}</p>
            <Button
              type="button"
              variant="secondary"
              className="mt-4"
              onClick={retry}
            >
              {t.retry}
            </Button>
          </div>
        ) : view && view.items.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              title={t.emptyTitle}
              body={t.emptyBody}
              action={
                <Button variant="secondary" onClick={clearSearch}>
                  {t.clearSearch}
                </Button>
              }
            />
          </div>
        ) : view ? (
          <div data-testid="directory-cards">
            {view.fell_back && (
              <div
                data-testid="outside-area"
                className="mb-4 rounded-lg border border-accent-border bg-accent-soft px-4 py-3"
              >
                <p className="font-medium text-accent-strong">
                  {t.outsideAreaLabel}
                </p>
                <p className="mt-0.5 text-sm text-txt-muted">
                  {t.outsideAreaBody}
                </p>
              </div>
            )}
            <p className="text-sm text-txt-muted">
              {t.resultsCount(view.items.length)}
            </p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {view.items.map((entry) => (
                <DirectoryCard
                  key={entry.partner_id}
                  entry={entry}
                  typeLabel={t[TYPE_LABEL_KEY[entry.partner_type]]}
                  specialtyLabel={
                    entry.specialty
                      ? t.specialties[SPECIALTY_LABEL_KEY[entry.specialty]] ??
                        entry.specialty
                      : null
                  }
                  verifiedLabel={t.verified}
                  distanceLabel={formatDistanceKm(
                    entry.distance_km,
                    t.distanceKm,
                  )}
                />
              ))}
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
