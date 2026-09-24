"use client";

// #501: the patient's location chip and its single-city picker sheet
// (PROTO-2.7 binding, shell-light.html `.topbar-location` / `.home-location-chip`
// and `#location-sheet`). One component, two placements: hidden on phones in
// the light top bar (`location-chip-topbar`) and shown at the top of the mobile
// feed (`location-chip-feed`), each swapped by the matching responsive
// wrapper. The chip shows the persisted profile area - localized when it names
// a known service area, verbatim when it is free text - falling back to the
// localized launch beachhead; tapping it opens a bottom sheet listing every
// service area (one city today, explicitly marked single-city with a
// coming-soon note).
// Choosing persists the city into the profile draft's `area` through the
// existing profile flow, so the chip and Find Care's default location both
// reflect it. No new data seam: the draft is the single source of truth.

import { useState } from "react";
import { MapPin } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useOptionalProfile } from "@/lib/profile/ProfileContext";
import {
  SERVICE_AREAS,
  resolveServiceArea,
  serviceAreaLabel,
  type ServiceArea,
} from "@/lib/location/serviceArea";

interface LocationChipProps {
  /** Which mount this is: the desktop top bar or the mobile feed top. */
  placement: "topbar" | "feed";
  /** Responsive display wrapper classes (the topbar chip is desktop-only, the
   * feed chip mobile-only - the prototype swaps them at the lg breakpoint). */
  className?: string;
}

export function LocationChip({ placement, className }: LocationChipProps) {
  const profile = useOptionalProfile();
  const { lang } = useLang();
  const t = STRINGS[lang].loc;
  const labels = t.cities;
  const [open, setOpen] = useState(false);
  // The picker's pending choice; re-synced from the persisted area each time
  // the sheet opens so the radio always reflects what the profile holds.
  const [selected, setSelected] = useState<ServiceArea>(() =>
    resolveServiceArea(profile?.draft.area),
  );

  const area = serviceAreaLabel(profile?.draft.area, labels);

  function openSheet() {
    setSelected(resolveServiceArea(profile?.draft.area));
    setOpen(true);
  }

  function apply() {
    // Persist the chosen city through the profile draft/save flow. The draft
    // is the in-flight edit buffer; absent a provider (shared chrome outside
    // the patient group) the chip stays a read-only display of the beachhead.
    if (profile) {
      profile.updateDraft({ ...profile.draft, area: selected });
    }
    setOpen(false);
  }

  return (
    <>
      <span className={className}>
        <button
          type="button"
          data-testid={`location-chip-${placement}`}
          aria-label={t.aria}
          aria-haspopup="dialog"
          onClick={openSheet}
          className="inline-flex min-h-[34px] items-center gap-1.5 rounded-full border border-hairline bg-surface px-3 py-1.5 text-sm font-medium text-txt-sub shadow-sm transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <MapPin aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
          {area}
        </button>
      </span>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="bottom"
          data-testid="location-sheet"
          className="mx-auto max-w-lg rounded-t-lg sm:max-w-lg"
        >
          <SheetHeader>
            <SheetTitle>{t.title}</SheetTitle>
            <SheetDescription>{t.desc}</SheetDescription>
          </SheetHeader>

          <div className="mt-3 flex flex-col gap-3">
            {/* The picker lists every service area; each id carries its own
                localized label from the dictionary (widening SERVICE_AREAS
                adds a city + its `loc.cities` entry). */}
            {SERVICE_AREAS.map((city) => (
              <label
                key={city}
                className="flex cursor-pointer items-start gap-3 rounded-md border border-hairline bg-surface px-3 py-2.5"
              >
                <input
                  type="radio"
                  name={`home-loc-${placement}`}
                  checked={selected === city}
                  onChange={() => setSelected(city)}
                  className="mt-0.5 h-4 w-4 accent-accent-strong"
                />
                <span className="flex flex-col">
                  <strong className="text-sm font-medium text-txt">
                    {labels[city]}
                  </strong>
                  <span className="text-xs text-txt-muted">{t.citySub}</span>
                </span>
              </label>
            ))}
            <p className="text-xs text-txt-muted">{t.more}</p>
          </div>

          <div className="mt-4">
            <Button
              type="button"
              className="w-full"
              data-testid="location-apply"
              onClick={apply}
            >
              {t.apply}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
