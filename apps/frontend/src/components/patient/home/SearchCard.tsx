"use client";

// #502: the home search card (PROTO-2.7 binding, shell-light.html
// `.search-card`). Doctor / Lab / Chemist scope pills are a display-driven
// segmented control: the active pill and the Search / See-all destinations all
// point at scoped Find Care (`/patient/find?type=doctor|lab|chemist`). Enter
// or the Search button routes there with the typed query as `?q`; the See-all
// link carries the scope without a query. The card never searches itself - the
// live DirectoryBrowser on the Find Care route owns the directory filters, so
// this surface only builds the scoped destination URL.
//
// The scope is a controlled prop owned by the page so the sibling Recommended
// rail (#503) can read and write the same value - the single source both
// surfaces key off. Mobile-first layout: the input and Search button stack
// full-width with 48px touch targets on a phone and sit inline from `sm` up;
// the input keeps `flex:1; min-width:0` inside a `min-w-0` flex item so a long
// query can never widen the page at 320px (base.css `.search-card .search-bar`
// regression rule, ui-blueprint §5.2).

import { type FormEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import type { ProviderType } from "@/lib/directory/links";

/** Patient-shell Find Care route; the scope pills commit their `?type` here
 * (FindCareBrowser embeds DirectoryBrowser on this route). Exported so the
 * sibling services grid (#504) shares one route vocabulary with this card. */
export const FIND_CARE_ROUTE = "/patient/find";

/** The three supply-side classes the pills segment over, in tab order. */
const SCOPES: ProviderType[] = ["doctor", "lab", "chemist"];

/** Scoped Find Care destination shared by the search card (#502) and the
 * services grid (#504): `/patient/find?type=<scope>[&q=<query>]`. */
export function findCareHref(scope: ProviderType, query = ""): string {
  const params = new URLSearchParams({ type: scope });
  const q = query.trim();
  if (q) params.set("q", q);
  return `${FIND_CARE_ROUTE}?${params.toString()}`;
}

export interface SearchCardProps {
  /** The active scope, owned by the page; the Recommended rail (#503) reads
   * and writes the same source. */
  scope: ProviderType;
  onScopeChange: (scope: ProviderType) => void;
  /** #509: the page composes the "Recommended near you" rail (#503) as a child
   * so the scope pills + search bar + rail read as one designed card (the
   * binding's `.search-card`). The rail owns its own header row, including the
   * scoped See-all link. */
  children?: ReactNode;
}

export function SearchCard({
  scope,
  onScopeChange,
  children,
}: SearchCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].search;
  const router = useRouter();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Uncontrolled input: the typed value is read straight from the form, so
    // route with the scoped destination carrying it as `?q`.
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    router.push(findCareHref(scope, q));
  }

  const activeClass = (active: boolean) =>
    `min-h-11 flex-1 rounded-full px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:flex-none sm:px-5 ${
      active
        ? "bg-surface font-semibold text-txt-strong shadow-[0_1px_3px_rgba(2,6,23,0.12)]"
        : // txt-muted (slate-500) on the pill-group hairline-soft background
          // measured 4.23:1 - below the 4.5 WCAG AA floor the axe gate enforces.
          // txt-sub (slate-700) clears it and matches the house inactive-chip
          // pattern (pick page specialty chips). The active pill pops on the
          // white surface with the binding's `.search-scope` shadow. Padding
          // tracks the binding (.search-scope button): .75rem on a stretched
          // mobile pill, 1.25rem once the desktop group goes inline-flex.
          "text-txt-sub"
    }`;

  return (
    <section
      data-testid="home-search-card"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      {/* Scope pills: segmented control wiring pill + destinations together.
          House pattern is a pressed-button group (DirectoryBrowser type
          chips), not tab semantics - no panels to switch, so no tablist. The
          group is a flush hairline-soft rail (.search-scope) - borderless, so
          the active pill pops on the white surface (#509). On desktop the
          group turns inline-flex and shrink-wraps its pills (binding
          `width:auto`), so the rail background never spans the full card. */}
      <div
        role="group"
        aria-label={t.scopeAria}
        className="flex w-full gap-1 rounded-full bg-hairline-soft p-1 sm:w-auto sm:inline-flex"
      >
        {SCOPES.map((item) => {
          const active = item === scope;
          return (
            <button
              key={item}
              type="button"
              aria-pressed={active}
              data-testid="search-scope-pill"
              data-active={active}
              onClick={() => onScopeChange(item)}
              className={activeClass(active)}
            >
              {t[item]}
            </button>
          );
        })}
      </div>

      <form
        onSubmit={submit}
        role="search"
        className="mt-3 flex flex-col gap-2 sm:flex-row"
      >
        {/* The `min-w-0 flex-1` wrapper is the long-query overflow guard: an
            intrinsic-width search value cannot push past the flex basis and
            widen the page at 320px (base.css `.search-bar .input-group`). The
            input group is the binding's prefixed anatomy - a non-interactive
            search icon on the left, then the field, on the house radius. */}
        <div className="flex w-full min-w-0 sm:flex-1">
          <label className="sr-only" htmlFor="home-search-input">
            {t.aria}
          </label>
          <span
            aria-hidden="true"
            className="flex shrink-0 items-center rounded-l-md border border-r-0 border-hairline bg-hairline-soft px-3 text-txt-sub"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          </span>
          <input
            id="home-search-input"
            name="q"
            type="search"
            placeholder={t.placeholder}
            className="min-h-12 w-full min-w-0 flex-1 rounded-r-md border border-hairline bg-surface px-3 text-sm text-txt placeholder:text-txt-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <Button
          type="submit"
          data-testid="search-go"
          className="min-h-12 shrink-0"
        >
          {t.go}
        </Button>
      </form>

      {/* #509: the scoped See-all link moved into the Recommended rail's header
          row (rendered by the page as this card's child), so the rail header
          and the search card read as one designed unit. */}
      {children}
    </section>
  );
}
