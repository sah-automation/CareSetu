"use client";

// PHASE-2.7 T1 (#499): the patient home shell, composed to the finalized
// PROTO-2.7 binding (prototype/phase-2-6/shell-light.html). A full-width
// greeting strip greets the saved first name in the current language (generic
// fallback when none is saved), then the feed: a two-column layout with a
// 300px sticky right rail at >=1024px, stacking to a single column in the same
// reading order below it. Children keep `min-w-0` so intrinsic widths never
// widen the page from 320-1440px.
//
// The profile completion meter, nudge stack, ProfileGateDemo and
// LabBookingConsentDemo leave the home here - the components stay defined and
// ProfileGate keeps gating the care-action moments (blueprint §5.9). The feed
// cards land in the sibling PROTO-2.7 tickets (#500+); this ticket ships the
// shell, so both columns render empty.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfile } from "@/lib/profile/ProfileContext";

export default function PatientDashboardPage() {
  const { draft } = useProfile();
  const { lang } = useLang();
  const t = STRINGS[lang].patientHome;

  const firstName = draft.name.trim().split(/\s+/)[0];

  return (
    <>
      {/* Greeting strip: full width, no rail beside it. */}
      <section className="mb-6" data-testid="patient-home-greeting">
        <h1 className="text-xl font-semibold text-txt">
          {firstName ? t.welcome(firstName) : t.welcomeGuest}
        </h1>
        <p className="mt-1 text-sm text-txt-muted">{t.greetSub}</p>
      </section>

      {/* Feed: main cards column + 300px sticky rail on desktop; single
          column, same reading order, on mobile. */}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-6">
        <div className="min-w-0 space-y-6" />
        <aside
          className="min-w-0 lg:sticky lg:top-[4.5rem]"
          data-testid="patient-home-rail"
        />
      </div>
    </>
  );
}
