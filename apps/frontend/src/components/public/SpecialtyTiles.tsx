"use client";

// PHASE-2.6 T09 (#200): homepage section 3 - quick specialty entry, restyled
// to the prototype's icon-tile grid (#961, section marker `section-chips`
// unchanged so the composition suite stays green). Zero-typing search entry:
// each tile pre-seeds the directory filters (provider type + specialty query).
// Marketing navigation over specialties only - never disease browsing (gap
// G1).

import type { ReactNode } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { directoryHref, type ProviderType } from "@/lib/directory/links";
import { useLang } from "@/lib/i18n/LangContext";

// 26x26 stroke icons from prototype homepage-resolved-v2 .specialty-icon.
const ICONS = {
  gp: (
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  ),
  pediatrician: (
    <>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  gynecologist: (
    <>
      <circle cx="12" cy="13.5" r="2.5" />
      <path d="M12 16v6" />
      <path d="M9 19h6" />
    </>
  ),
  dentist: (
    <>
      <path d="M12 22c5-3 7-7 7-7s-2-4-7-4-7 4-7 7" />
      <path d="M9 15h6" />
      <path d="M12 12v6" />
    </>
  ),
  bloodTest: <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />,
  xRay: (
    <>
      <rect x="2" y="2" width="20" height="20" rx="2" />
      <path d="M12 9v11" />
      <path d="M9 15h6" />
    </>
  ),
  fullBody: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </>
  ),
  medicineDelivery: (
    <>
      <path d="M10 2v2" />
      <path d="M14 2v2" />
      <path d="M10 16v2" />
      <path d="M14 16v2" />
      <path d="M4 10h16" />
      <path d="M6 14h12" />
      <path d="M8 6h8" />
    </>
  ),
} as const;

// The four doctor tiles are a curated MARKETING subset of the backend's
// twenty-value specialty vocabulary (`DIRECTORIES_SPECIALTIES`): the homepage
// advertises the four a first-time visitor most plausibly browses, while the
// directory page's own filter and the pick-a-doctor pre-filter expose all
// twenty. The distinction from the lab and chemist tiles is load-bearing: a
// doctor tile carries a specialty from that closed vocabulary and belongs in
// the membership filter, whereas "Blood test", "X-ray" and "Medicine
// delivery" are service keywords that are not specialties at all and match
// nothing against it - they belong in free-text search.
export function SpecialtyTiles() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const tiles: {
    label: string;
    icon: keyof typeof ICONS;
    type: ProviderType;
    filter: { specialty?: string; q?: string };
  }[] = [
    {
      label: t.chips.generalPhysician,
      icon: "gp",
      type: "doctor",
      filter: { specialty: "General Physician" },
    },
    {
      label: t.chips.pediatrician,
      icon: "pediatrician",
      type: "doctor",
      filter: { specialty: "Pediatrician" },
    },
    {
      label: t.chips.gynecologist,
      icon: "gynecologist",
      type: "doctor",
      filter: { specialty: "Gynecologist" },
    },
    {
      label: t.chips.dentist,
      icon: "dentist",
      type: "doctor",
      filter: { specialty: "Dentist" },
    },
    {
      label: t.chips.bloodTest,
      icon: "bloodTest",
      type: "lab",
      filter: { q: "Blood test" },
    },
    { label: t.chips.xRay, icon: "xRay", type: "lab", filter: { q: "X-ray" } },
    {
      label: t.chips.fullBodyCheckup,
      icon: "fullBody",
      type: "lab",
      filter: { q: "Full body checkup" },
    },
    {
      label: t.chips.medicineDelivery,
      icon: "medicineDelivery",
      type: "chemist",
      filter: { q: "Medicine delivery" },
    },
  ];

  return (
    <section data-testid="section-chips" aria-label={t.chips.headline}>
      <div className="mx-auto w-full max-w-6xl px-4 pb-4 pt-10">
        <div className="flex flex-col gap-1">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-accent">
            {t.chips.title}
          </div>
          <h2 className="home-h2 text-txt">{t.chips.headline}</h2>
        </div>
        <ul className="mt-5 grid grid-cols-2 gap-3.5 md:grid-cols-3 lg:grid-cols-4">
          {tiles.map((tile) => (
            <li key={tile.filter.specialty ?? tile.filter.q}>
              <a
                href={directoryHref(tile.type, tile.filter)}
                className="home-spec-tile flex h-full flex-col items-center gap-2.5 rounded-2xl px-3 py-5 text-center"
              >
                <span
                  aria-hidden="true"
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-accent-border bg-surface text-accent shadow-card"
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
                    {ICONS[tile.icon]}
                  </svg>
                </span>
                <span className="text-sm font-semibold text-txt">
                  {tile.label}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
