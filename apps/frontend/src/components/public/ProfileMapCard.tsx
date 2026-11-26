"use client";

// PHASE-6 profile redesign (#968): the right rail's location card, ported from
// the finalized prototype (`.pp-map-*`). Embed + the three travel-mode direction
// links + an "open map" fallback, exactly the direction split the prototype
// decided on: patient wants a route, not a screenshot.
//
// The coordinates are the static Daltonganj stand-in per the spec - a doctor
// profile reads one anchor and lab/chemist profiles another, so the same fixture
// does not imply three practices at one address. Swapping in real declared
// coordinates is a follow-up ticket and only touches `coordsFor` here.
//
// `q=` is URL-encoded as a whole (never `+`-joined) so a locality with an ampersand
// or a non-ASCII name survives both the embed and the `dir/?api=1` link.

import {
  MapPin,
  Navigation,
  ExternalLink,
  Footprints,
  Bus,
} from "lucide-react";

import type { ProviderType } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const COORDS: Record<ProviderType, string> = {
  doctor: "23.8450,84.0900",
  lab: "23.8388,84.0966",
  chemist: "23.8388,84.0966",
};

function coordsFor(mode: ProviderType): string {
  return COORDS[mode];
}

function encode(query: string): string {
  return encodeURIComponent(query);
}

function AddressLine({
  locality,
  city,
  pincode,
}: {
  locality: string | null;
  city: string | null;
  pincode: string | null;
}): string {
  return [locality, city, pincode].filter(Boolean).join(", ");
}

export function ProfileMapCard({
  mode,
  locality,
  city,
  pincode,
}: {
  mode: ProviderType;
  locality: string | null;
  city: string | null;
  pincode: string | null;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile.map;

  const coords = coordsFor(mode);
  const address = AddressLine({ locality, city, pincode });
  const hasAddress = address.length > 0;

  // The query prefers the declared address (a patient navigating to a named
  // clinic gets the right pin even when the static anchor is a stand-in) and
  // falls back to the coordinates when nothing is declared.
  const query = hasAddress ? address : coords;

  const embed = `https://maps.google.com/maps?q=${encode(
    query,
  )}&z=15&output=embed`;
  const openMap = `https://www.google.com/maps/search/?api=1&query=${encode(
    query,
  )}`;
  const directions = (travelmode: string) =>
    `https://www.google.com/maps/dir/?api=1&destination=${encode(
      query,
    )}&travelmode=${travelmode}`;

  return (
    <div data-testid="profile-map">
      <h2 className="text-base font-semibold text-txt">{t.heading}</h2>

      {hasAddress ? null : (
        <p
          className="mt-1 text-xs text-txt-muted"
          data-testid="profile-map-empty"
        >
          {t.addressMissing}
        </p>
      )}

      <div className="mt-3 overflow-hidden rounded-lg border border-hairline bg-hairline-soft">
        <iframe
          title={t.ariaLabel}
          data-testid="profile-map-embed"
          src={embed}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          className="h-[150px] w-full border-0"
        />
      </div>

      <p className="mt-3 flex items-start gap-2 text-xs text-txt-muted">
        <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>
          {hasAddress ? address : t.addressMissing}
          {!hasAddress ? null : ` (${coords})`}
        </span>
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <a
          href={directions("driving")}
          target="_blank"
          rel="noreferrer"
          data-testid="profile-map-directions"
          aria-label={`${t.getDirections} - ${t.drive}`}
          className="inline-flex items-center gap-1.5 rounded-lg border border-accent-border bg-accent-soft px-3 py-2 text-xs font-semibold text-accent-strong transition-colors hover:bg-accent hover:text-on-accent"
        >
          <Navigation className="h-3.5 w-3.5" aria-hidden="true" />
          {t.getDirections}
        </a>

        {(["walking", "transit"] as const).map((travelmode) => {
          const isWalking = travelmode === "walking";
          const TravelModeIcon = isWalking ? Footprints : Bus;
          return (
            <a
              key={travelmode}
              href={directions(travelmode)}
              target="_blank"
              rel="noreferrer"
              data-testid={`profile-map-${travelmode}`}
              aria-label={`${t.getDirections} - ${
                isWalking ? t.walk : t.transit
              }`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-hairline px-3 py-2 text-xs font-semibold text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
            >
              <TravelModeIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {isWalking ? t.walk : t.transit}
            </a>
          );
        })}

        <a
          href={openMap}
          target="_blank"
          rel="noreferrer"
          data-testid="profile-map-open"
          aria-label={t.openMap}
          className="inline-flex items-center gap-1.5 rounded-lg border border-hairline px-3 py-2 text-xs font-semibold text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          {t.openMap}
        </a>
      </div>
    </div>
  );
}
