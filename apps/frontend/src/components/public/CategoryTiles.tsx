"use client";

// PHASE-2.6 T09 (#200): homepage section 4 - Practo-style category tiles
// (blueprint §3.1 row 4). Three primary browse entries linking to the
// directory with the provider-type preset. The tile ids anchor the header's
// Doctors/Labs/Chemists nav. Marketing navigation over specialties - not
// disease browsing (gap G1).

import { STRINGS } from "@/lib/i18n/dictionaries";
import { directoryHref } from "@/lib/directory/links";
import { useLang } from "@/lib/i18n/LangContext";

const TILES = [
  { id: "doctors", icon: "\u{1FA7A}", type: "doctor", subKey: "doctorsSub" },
  { id: "labs", icon: "\u{1F9EA}", type: "lab", subKey: "labsSub" },
  { id: "chemists", icon: "\u{1F48A}", type: "chemist", subKey: "chemistsSub" },
] as const;

export function CategoryTiles() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  return (
    <section data-testid="section-tiles">
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <h2 className="text-2xl font-semibold text-txt">{t.tiles.title}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {TILES.map((tile) => (
            <a
              key={tile.id}
              id={tile.id}
              href={directoryHref(tile.type)}
              className="flex flex-col gap-1 rounded-lg border border-hairline bg-surface p-5 shadow-card transition-shadow hover:shadow-pop"
            >
              <strong className="text-lg text-txt">
                <span aria-hidden="true">{tile.icon} </span>
                {t.nav[tile.id]}
              </strong>
              <span className="text-sm text-txt-muted">
                {t.tiles[tile.subKey]}
              </span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
