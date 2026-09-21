"use client";

// #504: the fixed 4-tile services grid (PROTO-2.7 binding, shell-light.html
// `.services-grid`): Consult a doctor, Book a lab test, Start visit and Order
// medicine - in that fixed order. Order medicine renders marked Soon and never
// navigates (a dimmed span, not a link); Start visit is the accent tile. The
// consult and lab tiles point at the same scoped Find Care destinations the
// home search card (#502) builds, so the top care actions and the search card
// agree on one route vocabulary; Start visit goes to the live intake start
// (`/patient/intake`, the center accent of the patient tab bar). The grid is
// 2-up on a phone and 4-across at >=720px, tile-for-tile with the binding.

import Link from "next/link";
import {
  Activity,
  FlaskConical,
  Pill,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { findCareHref } from "@/components/patient/home/SearchCard";
import { PATIENT_START_VISIT_ROUTE } from "@/components/dashboard/nav-config";

// Destinations come from the two single sources the home already keys off: the
// scoped Find Care builder the search card (#502) owns and the patient
// navigation config's live start-visit route (#197) - so the tiles can never
// drift from the search card or the tab bar.

type TileLabelKey = "doctor" | "lab" | "chemist" | "start";

interface ServiceTileSpec {
  key: TileLabelKey;
  icon: LucideIcon;
  href?: string;
  accent?: boolean;
  soon?: boolean;
}

export function ServicesGrid() {
  const { lang } = useLang();
  const t = STRINGS[lang].services;

  // Fixed order from the binding: doctor, lab, chemist (Soon, no destination),
  // start (the accent). Destinations are decided here, not by the tile, so the
  // soon tile structurally has nothing to navigate to.
  const tiles: ServiceTileSpec[] = [
    { key: "doctor", icon: Stethoscope, href: findCareHref("doctor") },
    { key: "lab", icon: FlaskConical, href: findCareHref("lab") },
    { key: "chemist", icon: Pill, soon: true },
    {
      key: "start",
      icon: Activity,
      href: PATIENT_START_VISIT_ROUTE,
      accent: true,
    },
  ];

  return (
    <section
      data-testid="services-grid"
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <h2 className="text-[1.05rem] font-semibold text-txt">{t.title}</h2>
      <div
        data-testid="services-grid-tiles"
        className="mt-2 grid grid-cols-2 gap-3 min-[720px]:grid-cols-4"
      >
        {tiles.map((tile) => {
          const label = t[tile.key];
          const iconClass = `flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
            tile.accent
              ? "bg-white/20 text-on-accent"
              : "bg-accent-soft text-accent-strong"
          }`;
          const tileClass = `flex min-h-24 flex-col items-start gap-2.5 rounded-lg border p-4 ${
            tile.accent
              ? "border-accent bg-accent"
              : "border-hairline bg-surface"
          } ${tile.soon ? "opacity-55 pointer-events-none" : ""}`;

          const body = (
            <>
              <span aria-hidden="true" className={iconClass}>
                <tile.icon size={22} strokeWidth={1.8} />
              </span>
              <span
                className={`text-[0.9375rem] font-semibold leading-snug ${
                  tile.accent ? "text-on-accent" : "text-txt"
                }`}
              >
                {label}
              </span>
              {tile.soon ? (
                <span className="rounded-full border border-dashed border-hairline bg-hairline-soft px-2 py-0.5 text-[0.6875rem] font-medium tracking-wide text-txt-muted uppercase">
                  {t.soon}
                </span>
              ) : null}
            </>
          );

          // The Soon tile is a dimmed span - present in the grid but never a
          // link, so it structurally cannot navigate. The others are links.
          return tile.href ? (
            <Link
              key={tile.key}
              href={tile.href}
              data-testid="svc-tile"
              data-svc-key={tile.key}
              className={`${tileClass} transition-shadow hover:shadow-pop`}
            >
              {body}
            </Link>
          ) : (
            <span
              key={tile.key}
              data-testid="svc-tile"
              data-svc-key={tile.key}
              data-svc-soon="true"
              aria-disabled="true"
              className={tileClass}
            >
              {body}
            </span>
          );
        })}
      </div>
    </section>
  );
}
