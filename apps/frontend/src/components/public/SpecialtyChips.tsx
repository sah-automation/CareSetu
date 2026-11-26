"use client";

// PHASE-2.6 T09 (#200): homepage section 3 - quick specialty chips
// (blueprint §3.1 row 3). Zero-typing search entry: each chip pre-seeds the
// directory filters (provider type + specialty query). Marketing navigation
// over specialties only - never disease browsing (gap G1).

import { STRINGS } from "@/lib/i18n/dictionaries";
import { directoryHref, type ProviderType } from "@/lib/directory/links";
import { useLang } from "@/lib/i18n/LangContext";

// The four doctor chips are a curated MARKETING subset of the backend's
// twenty-value specialty vocabulary (`DIRECTORIES_SPECIALTIES`): the homepage
// advertises the four a first-time visitor most plausibly browses, while the
// directory page's own filter and the pick-a-doctor pre-filter expose all
// twenty. The distinction from the lab and chemist chips is load-bearing: a
// doctor chip carries a specialty from that closed vocabulary and belongs in
// the membership filter, whereas "Blood test", "X-ray" and "Medicine
// delivery" are service keywords that are not specialties at all and match
// nothing against it - they belong in free-text search.
export function SpecialtyChips() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const chips: {
    label: string;
    type: ProviderType;
    filter: { specialty?: string; q?: string };
  }[] = [
    {
      label: t.chips.generalPhysician,
      type: "doctor",
      filter: { specialty: "General Physician" },
    },
    {
      label: t.chips.pediatrician,
      type: "doctor",
      filter: { specialty: "Pediatrician" },
    },
    {
      label: t.chips.gynecologist,
      type: "doctor",
      filter: { specialty: "Gynecologist" },
    },
    {
      label: t.chips.dentist,
      type: "doctor",
      filter: { specialty: "Dentist" },
    },
    { label: t.chips.bloodTest, type: "lab", filter: { q: "Blood test" } },
    { label: t.chips.xRay, type: "lab", filter: { q: "X-ray" } },
    {
      label: t.chips.fullBodyCheckup,
      type: "lab",
      filter: { q: "Full body checkup" },
    },
    {
      label: t.chips.medicineDelivery,
      type: "chemist",
      filter: { q: "Medicine delivery" },
    },
  ];

  return (
    <section data-testid="section-chips" aria-label={t.chips.title}>
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-txt-muted">
          {t.chips.title}
        </h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {chips.map((chip) => (
            <li key={chip.filter.specialty ?? chip.filter.q}>
              <a
                href={directoryHref(chip.type, chip.filter)}
                className="inline-block rounded-full border border-hairline bg-surface px-3 py-1.5 text-sm text-txt-sub shadow-sm transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
              >
                {chip.label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
