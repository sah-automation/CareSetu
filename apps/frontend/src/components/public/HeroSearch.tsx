"use client";

// PHASE-2.6 T09 (#200): homepage section 2 - hero + directory search
// (blueprint §3.1 row 2). Typography-led hero per prototype
// homepage-resolved-v2 (#961): eyebrow pill, clamped headline, short subline
// and a segmented search card. Search still submits natively to
// /directory?type=&q=&location= (GET form - works without JS); location
// defaults to the beachhead and stays editable. The default value is
// locale-invariant on purpose: it is submitted query data for directory
// matching, not display copy, so the EN/Hindi toggle must never rewrite or
// remount it (that would silently discard a visitor's edit). The secondary
// "Get started" CTA is dropped here (#961) - it lives on the final CTA band.

import { DIRECTORY_ROUTE } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// Beachhead city, kept as raw query data (never translated).
const DEFAULT_LOCATION = "Daltonganj";

export function HeroSearch() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  return (
    <section data-testid="section-hero" className="home-hero-bg relative">
      <div className="relative mx-auto w-full max-w-6xl px-4 pb-12 pt-14 text-center md:pt-16">
        <span className="inline-flex items-center gap-2 rounded-full border border-accent-border bg-surface px-3.5 py-1.5 text-xs font-semibold text-accent-strong shadow-card">
          <span aria-hidden="true" className="home-hero-dot" />
          {t.hero.eyebrow}
        </span>
        <h1 className="home-h1 mx-auto mt-5 text-txt">{t.hero.h1}</h1>
        <p className="mx-auto mt-4 max-w-[52ch] text-base text-txt-sub md:text-lg">
          {t.hero.sub}
        </p>

        <form
          action={DIRECTORY_ROUTE}
          method="get"
          className="home-search-card mx-auto mt-9 flex max-w-[980px] flex-col gap-1 text-left md:flex-row md:items-stretch"
        >
          <div className="home-search-seg">
            <label className="home-search-label" htmlFor="hero-type">
              {t.hero.careLabel}
            </label>
            <select
              id="hero-type"
              name="type"
              aria-label={t.hero.typeLabel}
              defaultValue="doctor"
              className="home-search-control font-semibold"
            >
              <option value="doctor">{t.hero.typeDoctor}</option>
              <option value="lab">{t.hero.typeLab}</option>
              <option value="chemist">{t.hero.typeChemist}</option>
            </select>
          </div>
          <div className="home-search-seg">
            <label className="home-search-label" htmlFor="hero-q">
              {t.hero.searchLabel}
            </label>
            <input
              id="hero-q"
              type="search"
              name="q"
              placeholder={t.hero.searchPlaceholder}
              aria-label={t.hero.searchPlaceholder}
              className="home-search-control"
            />
          </div>
          <div className="home-search-seg">
            <label className="home-search-label" htmlFor="hero-loc">
              {t.hero.locationLabel}
            </label>
            <input
              id="hero-loc"
              type="text"
              name="location"
              defaultValue={DEFAULT_LOCATION}
              placeholder={t.hero.locationPlaceholder}
              aria-label={t.hero.locationLabel}
              title={t.hero.locationLabel}
              className="home-search-control"
            />
          </div>
          <button type="submit" className="home-search-submit">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
            {t.hero.cta}
          </button>
        </form>
      </div>
    </section>
  );
}
