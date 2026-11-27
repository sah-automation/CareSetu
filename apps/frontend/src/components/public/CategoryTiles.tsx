"use client";

// PHASE-2.6 T09 (#200): homepage section 4 - category tiles (blueprint §3.1
// row 4). Three primary browse entries linking to the directory with the
// provider-type preset. The tile ids anchor the header's Doctors/Labs/
// Chemists nav. Marketing navigation over specialties - not disease browsing
// (gap G1).
//
// #961: SVG icons replace the emoji set, tiles gain the prototype's decorative
// accent wash, hover lift and "Explore ..." arrow CTA.

import type { ReactNode } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { directoryHref, type ProviderType } from "@/lib/directory/links";
import { useLang } from "@/lib/i18n/LangContext";

// 26x26 stroke icons from prototype homepage-resolved-v2 .category-icon.
const ICONS: Record<ProviderType, ReactNode> = {
  doctor: (
    <>
      <path d="M12 2a4 4 0 0 0-4 4v7" />
      <path d="M4 13a8 8 0 0 0 16 0" />
      <path d="M12 9v3" />
      <path d="M12 16v3" />
    </>
  ),
  lab: (
    <>
      <path d="M10 2v2" />
      <path d="M14 2v2" />
      <path d="M10 16v2" />
      <path d="M14 16v2" />
      <path d="M4 10h16" />
      <path d="M6 14h12" />
      <path d="M8 6h8" />
      <path d="M9 4v2" />
      <path d="M15 4v2" />
    </>
  ),
  chemist: (
    <>
      <path d="M12 2a4 4 0 0 0-4 4v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a4 4 0 0 0-4-4z" />
      <path d="M12 6v6" />
      <path d="M9 9h6" />
    </>
  ),
};

const ARROW = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M5 12h14" />
    <path d="M12 5l7 7-7 7" />
  </svg>
);

const TILES: {
  id: "doctors" | "labs" | "chemists";
  type: ProviderType;
  subKey: "doctorsSub" | "labsSub" | "chemistsSub";
  exploreKey: "explore" | "exploreLabs" | "exploreChemists";
}[] = [
  {
    id: "doctors",
    type: "doctor",
    subKey: "doctorsSub",
    exploreKey: "explore",
  },
  { id: "labs", type: "lab", subKey: "labsSub", exploreKey: "exploreLabs" },
  {
    id: "chemists",
    type: "chemist",
    subKey: "chemistsSub",
    exploreKey: "exploreChemists",
  },
];

export function CategoryTiles() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  return (
    <section data-testid="section-tiles">
      <div className="mx-auto w-full max-w-6xl px-4 py-10">
        <div className="flex flex-col gap-1">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-accent">
            {t.tiles.eyebrow}
          </div>
          <h2 className="home-h2 text-txt">{t.tiles.title}</h2>
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {TILES.map((tile) => (
            <a
              key={tile.id}
              id={tile.id}
              href={directoryHref(tile.type)}
              className="home-cat-tile group flex flex-col gap-4 rounded-[18px] border border-hairline bg-surface p-7"
            >
              <span
                aria-hidden="true"
                className="relative z-10 flex h-[54px] w-[54px] items-center justify-center rounded-2xl border border-accent-border bg-accent-soft text-accent-strong"
              >
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  {ICONS[tile.type]}
                </svg>
              </span>
              <div className="relative z-10">
                <h3 className="text-xl font-bold tracking-tight text-txt">
                  {t.nav[tile.id]}
                </h3>
                <p className="mt-1 text-sm text-txt-muted">
                  {t.tiles[tile.subKey]}
                </p>
              </div>
              <span className="relative z-10 mt-auto inline-flex items-center gap-1.5 text-sm font-semibold text-accent-strong">
                {t.tiles[tile.exploreKey]}
                <span className="transition-transform duration-150 group-hover:translate-x-0.5">
                  {ARROW}
                </span>
              </span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
