"use client";

// PHASE-2.6 T09 (#200): homepage section 2 - hero + directory search
// (blueprint §3.1 row 2). One-line value prop; search bar submits natively
// to /directory?type=&q=&location= (GET form - works without JS); location
// defaults to the beachhead and stays editable. The default value is
// locale-invariant on purpose: it is submitted query data for directory
// matching, not display copy, so the EN/Hindi toggle must never rewrite or
// remount it (that would silently discard a visitor's edit). Secondary CTA
// follows the §3.2 role-entry model like the header button.

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { DIRECTORY_ROUTE } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useRoleHomeHref } from "@/lib/auth/useRoleHomeHref";
import { useLang } from "@/lib/i18n/LangContext";

// Beachhead city, kept as raw query data (never translated).
const DEFAULT_LOCATION = "Daltonganj";

export function HeroSearch() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;
  const getStartedHref = useRoleHomeHref();

  return (
    <section data-testid="section-hero" className="bg-page-bg">
      <div className="mx-auto w-full max-w-3xl px-4 pb-10 pt-12 text-center">
        <h1 className="mx-auto max-w-xl text-4xl font-bold leading-tight text-txt">
          {STRINGS[lang].home.hero.h1}
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-lg text-txt-muted">
          {t.hero.sub}
        </p>
        <form
          action={DIRECTORY_ROUTE}
          method="get"
          className="mx-auto mt-6 flex max-w-2xl flex-col items-stretch gap-2 sm:flex-row sm:items-center"
        >
          <select
            name="type"
            aria-label={t.hero.typeLabel}
            defaultValue="doctor"
            className="rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt-sub focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="doctor">{t.hero.typeDoctor}</option>
            <option value="lab">{t.hero.typeLab}</option>
            <option value="chemist">{t.hero.typeChemist}</option>
          </select>
          <input
            type="search"
            name="q"
            placeholder={t.hero.searchPlaceholder}
            aria-label={t.hero.searchPlaceholder}
            className="min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt placeholder:text-txt-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <input
            type="text"
            name="location"
            defaultValue={DEFAULT_LOCATION}
            aria-label={t.hero.locationLabel}
            title={t.hero.locationLabel}
            className="w-full rounded-full border border-hairline bg-surface px-3 py-2 text-sm text-txt-sub sm:w-36"
          />
          <Button type="submit">{t.hero.cta}</Button>
        </form>
        <div className="mt-4">
          <Button asChild variant="secondary">
            <Link href={getStartedHref}>{t.hero.getStarted}</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
