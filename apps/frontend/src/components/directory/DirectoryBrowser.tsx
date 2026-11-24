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
//
// #967: the sticky mobile search card (`.search-sticky` - sticky only ≤720px,
// search input + Filters button), the dismissable active-filter chips row
// (.filter-row for q/type/specialty/location), and the FilterSheet bottom
// sheet. Only `specialty` is wired to the backend query today; the sheet's
// other controls are cosmetic until their query params exist.

import { type FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Filter, MapPin } from "lucide-react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { DirectoryCard, formatDistanceKm } from "./DirectoryCard";
import { FilterSheet, type FilterSheetCommit } from "./FilterSheet";
import {
  DIRECTORIES_SPECIALTIES,
  searchDirectory,
  type DirectorySearchView,
  type Specialty,
} from "@/lib/directory/search";
import { DIRECTORY_ROUTE, type ProviderType } from "@/lib/directory/links";
import { DIRECTORY_VARIANT_ROUTES } from "@/lib/directory/links";
import { specialtyLabel } from "@/lib/directory/specialtyLabel";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadState = "loading" | "loaded" | "error";

const PROVIDER_TYPES: ProviderType[] = ["doctor", "lab", "chemist"];

type TypeKey = "typeDoctor" | "typeLab" | "typeChemist";

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
  baseRoute,
  cardGridClassName,
}: {
  /** T05b: pin the partner type on a variant route (/doctors, /labs,
   * /chemists). The URL's `type` param is ignored while set. */
  presetType?: ProviderType;
  /** PHASE-8.1 T11 (#485): when embedded under an authed shell (the patient
   * /patient/find page), filter commits stay on that route instead of the
   * public /directory so the patient never leaves the shell. It is also the
   * embed seam (#510): the documented embedding caller is the ONLY one that
   * passes `baseRoute`, so its presence means "the shell owns the location
   * control" - the static location line below the search button is suppressed
   * here (the shell's LocationChip is the single per-viewport selector; the
   * shell reads the same persisted draft area, so no redundant line exists).
   * The public /directory browse passes no baseRoute and keeps the beachhead
   * line as its only location context - existing callers are unchanged. */
  baseRoute?: string;
  /** PHASE-8.1 T11 (#485): card-grid density override for shell-embedded
   * browse (the embedded column is narrower than the public full-width
   * browse, so the default lg:grid-cols-4 is too cramped). Defaults to the
   * public full-width grid - existing callers are unchanged. */
  cardGridClassName?: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].directory;
  const router = useRouter();
  const searchParams = useSearchParams();
  const [filterSheetOpen, setFilterSheetOpen] = useState(false);

  const committedType =
    presetType ?? parseProviderType(searchParams.get("type"));
  const committedSpecialty = parseSpecialty(searchParams.get("specialty"));
  const committedQuery = searchParams.get("q") ?? "";
  // #967: cosmetic location draft - carried in the URL for the dismissable
  // chip, not yet forwarded to the API (TODO(BACKEND): geo filtering).
  const committedLocation = searchParams.get("location");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: [
      "directory",
      "search",
      {
        q: committedQuery,
        partnerType: committedType,
        specialty: committedSpecialty,
        location: committedLocation,
      },
    ],
    queryFn: async () => {
      try {
        return await searchDirectory({
          q: committedQuery,
          partnerType: committedType,
          specialty: committedSpecialty,
        });
      } catch (err: unknown) {
        // Operational failure (error-handling-observability §2: `error` for
        // failures, `warn` reserved for degradations) - logged and surfaced
        // as the retryable error state.
        console.error("[directory] search failed:", err);
        throw err;
      }
    },
    staleTime: 60_000,
  });

  const view: DirectorySearchView | null = data ?? null;
  const status: LoadState =
    isError && view === null
      ? "error"
      : isLoading && view === null
        ? "loading"
        : "loaded";

  /** Replace the committed filter params on the URL (history replace - chip
   * toggling must not spam the history stack). On a type-preset variant the
   * commits stay on the variant route, dropping the pinned `type` from the
   * URL. */
  function commitFilters(next: FilterSheetCommit) {
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
    apply("location", next.location === undefined ? undefined : next.location);
    const qs = params.toString();
    const base = presetType
      ? DIRECTORY_VARIANT_ROUTES[presetType]
      : baseRoute ?? DIRECTORY_ROUTE;
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
    void refetch();
  }

  function clearSearch() {
    commitFilters({ q: null });
  }

  const typeKey = mapTypeToKey(committedType);
  const showSpecialtyChips =
    committedType === null || committedType === "doctor";
  const heading = typeKey === "$all" ? t.heading.all : t.heading[typeKey];
  // Shell-embedded browse (patient /patient/find) overrides the density; the
  // public /directory surface keeps the wider full-width grid.
  const gridClass =
    cardGridClassName ?? "grid gap-4 sm:grid-cols-2 lg:grid-cols-4";
  // FilterSheet sections follow the pinned variant, else the committed type,
  // defaulting to the doctor sections on an all-types browse.
  const filterSectionType: ProviderType =
    presetType ?? committedType ?? "doctor";

  // #967: dismissable active-filter chips - one per committed param, each ×
  // removing just that param (the query key change refetches).
  const activeChips: {
    key: "q" | "type" | "specialty" | "location";
    label: string;
    ariaLabel: string;
    onDismiss: () => void;
  }[] = [];
  if (committedQuery) {
    activeChips.push({
      key: "q",
      label: committedQuery,
      ariaLabel: t.clearQuery,
      onDismiss: () => commitFilters({ q: null }),
    });
  }
  if (!presetType && committedType) {
    activeChips.push({
      key: "type",
      label: t[TYPE_LABEL_KEY[committedType]],
      ariaLabel: t.clearTypeFilter,
      onDismiss: () => commitFilters({ type: null }),
    });
  }
  if (committedSpecialty) {
    activeChips.push({
      key: "specialty",
      label: specialtyLabel(lang, committedSpecialty),
      ariaLabel: t.clearSpecialty,
      onDismiss: () => commitFilters({ specialty: null }),
    });
  }
  if (committedLocation) {
    activeChips.push({
      key: "location",
      label: committedLocation,
      ariaLabel: t.clearLocation,
      onDismiss: () => commitFilters({ location: null }),
    });
  }

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

      {/* #967: sticky search card - position:sticky only ≤720px (the
          PublicHeader sits at z-40/4rem, so the card parks beneath it). The
          Filters button opens the FilterSheet; it is the prototype's compact
          input + Filters row on mobile, with the Search submit restored from
          ≥721px so the desktop affordance is unchanged. */}
      <div
        data-testid="search-sticky"
        className="search-sticky mt-4 max-[720px]:sticky max-[720px]:top-16 max-[720px]:z-30 max-[720px]:-mx-4 max-[720px]:bg-page-bg max-[720px]:px-4 max-[720px]:py-2 max-[720px]:shadow-card"
      >
        <form
          onSubmit={submitSearch}
          role="search"
          className="flex items-center gap-2"
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
          <Button type="submit" className="max-[720px]:hidden">
            {t.searchCta}
          </Button>
          <Button
            type="button"
            variant="secondary"
            data-testid="open-filters"
            onClick={() => setFilterSheetOpen(true)}
            className="shrink-0"
          >
            <Filter className="mr-1.5 h-4 w-4" aria-hidden="true" />
            {t.filtersCta}
          </Button>
        </form>
      </div>

      {/* #967: dismissable active-filter chips (.filter-row) - horizontal
          scroll row on mobile per the prototype. */}
      {activeChips.length > 0 && (
        <div
          data-testid="filter-row"
          role="group"
          aria-label={t.activeFiltersLabel}
          className="filter-row mt-3 flex flex-wrap items-center gap-1.5 max-[720px]:flex-nowrap max-[720px]:overflow-x-auto max-[720px]:[scrollbar-width:none]"
        >
          {activeChips.map((chip) => (
            <span
              key={chip.key}
              data-testid="active-filter-chip"
              data-filter={chip.key}
              className={`${chipClass(true)} gap-1.5 pr-1.5`}
            >
              {chip.key === "location" && (
                <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              )}
              <span className="max-w-[12rem] truncate">{chip.label}</span>
              <button
                type="button"
                data-testid={`dismiss-${chip.key}`}
                aria-label={chip.ariaLabel}
                onClick={chip.onDismiss}
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-on-accent/25 text-sm leading-none text-on-accent transition-colors hover:bg-on-accent/40"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

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
                  {specialtyLabel(lang, specialty)}
                </button>
              );
            })}
          </>
        )}

        {/* #510: the static location line only exists on the public browse,
            where no shell provides a location selector (the beachhead is the
            only location context). When embedded under the shell (baseRoute
            set) the shell's LocationChip owns the selector and reads the same
            persisted draft area, so rendering this duplicate line would show
            the patient area twice on one viewport - omitted. */}
        {baseRoute === undefined && (
          <span
            data-testid="directory-location"
            className="ml-auto inline-flex items-center gap-1.5 text-sm text-txt-muted"
          >
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
        )}
      </div>

      <section aria-live="polite" className="mt-5">
        {status === "loading" && view === null ? (
          <div
            data-testid="directory-loading"
            className={gridClass}
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
            <div className={`mt-4 ${gridClass}`}>
              {view.items.map((entry) => (
                <DirectoryCard
                  key={entry.partner_id}
                  entry={entry}
                  typeLabel={t[TYPE_LABEL_KEY[entry.partner_type]]}
                  specialtyLabel={
                    entry.specialty
                      ? specialtyLabel(lang, entry.specialty)
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

      <FilterSheet
        open={filterSheetOpen}
        onOpenChange={setFilterSheetOpen}
        sectionType={filterSectionType}
        specialty={committedSpecialty}
        location={committedLocation}
        items={view?.items ?? []}
        onCommit={commitFilters}
      />
    </main>
  );
}
