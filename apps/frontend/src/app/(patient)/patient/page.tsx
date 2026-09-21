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
//
// #500: the slim dismissible profile-completeness banner sits under the
// greeting strip - a one-line nudge when name/age/gender are missing, gone
// when complete or dismissed (per-device persistence).
//
// #502: the search card (scope pills + search bar) opens the feed under the
// greeting strip. Its scope is display-driven state lifted here, so the
// sibling Recommended rail (#503) reads and writes the exact same source.
//
// #503: the Recommended rail joins the feed under the search card on that same
// scope source - it refetches real directory data per active scope, so
// switching a pill swaps the rail panel and the Search / See-all destinations
// together.
//
// #504: the fixed 4-tile services grid sits under the rail - Consult a doctor,
// Book a lab test, Start visit (accent) and Order medicine (Soon, never
// navigates). Its consult/lab tiles reuse the same scoped Find Care routes,
// Start visit points at the live intake start.
//
// #505: the "Action required" card closes the feed - pending consent requests
// listed with Allow / Not now wired to the existing grant-requested / decline
// flows. It is absent entirely when nothing is pending (no empty card).
//
// #506: the "Recent activity" card previews the top few record-timeline events
// (consultations, prescriptions, lab results, metric logs) through the shared
// My Record describe/format helper, with View all opening the full timeline.
//
// #507: the "Health snapshot" card fills the sticky right rail - the newest
// metric and newest lab report derived from the record timeline when they
// exist, honest Soon teasers (P12 metrics, P9 reports) when either is absent.
// The rail keeps its 300px / >=1024px sticky shell from #499; it just gains
// its content here.

import { useState } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfile } from "@/lib/profile/ProfileContext";
import { LocationChip } from "@/components/patient/location/LocationChip";
import { ProfileCompletenessBanner } from "@/components/patient/profile/ProfileCompletenessBanner";
import { ActionRequiredCard } from "@/components/patient/home/ActionRequiredCard";
import { HealthSnapshotCard } from "@/components/patient/home/HealthSnapshotCard";
import { RecommendedRail } from "@/components/patient/home/RecommendedRail";
import { RecentActivityCard } from "@/components/patient/home/RecentActivityCard";
import { SearchCard } from "@/components/patient/home/SearchCard";
import { ServicesGrid } from "@/components/patient/home/ServicesGrid";
import type { ProviderType } from "@/lib/directory/links";

export default function PatientDashboardPage() {
  const { draft } = useProfile();
  const { lang } = useLang();
  const t = STRINGS[lang].patientHome;
  // #502: the home search scope is display-driven and shared with the Search /
  // See-all destinations here and the Recommended rail (#503) - one source.
  const [searchScope, setSearchScope] = useState<ProviderType>("doctor");

  const firstName = draft.name.trim().split(/\s+/)[0];

  return (
    <>
      {/* Top strip: full width, no rail beside it. */}
      <div className="mb-6 space-y-4">
        {/* Greeting strip */}
        <section data-testid="patient-home-greeting">
          <h1 className="text-xl font-semibold text-txt">
            {firstName ? t.welcome(firstName) : t.welcomeGuest}
          </h1>
          <p className="mt-1 text-sm text-txt-muted">{t.greetSub}</p>
        </section>

        {/* Location chip (#501): at the top of the mobile feed; the desktop
            chip mounts in the light top bar instead (Topbar). */}
        <LocationChip placement="feed" className="inline-flex lg:hidden" />

        {/* Slim dismissible profile banner (#500): only while name/age/gender
            are missing and not dismissed per device; never a blocking gate. */}
        <ProfileCompletenessBanner />
      </div>

      {/* Feed: main cards column + 300px sticky rail on desktop; single
          column, same reading order, on mobile. */}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-6">
        <div className="min-w-0 space-y-6">
          <SearchCard scope={searchScope} onScopeChange={setSearchScope} />
          {/* #503: reads and swaps on the exact same scope the card owns, so the
              rail panel and the Search / See-all destinations change together. */}
          <RecommendedRail scope={searchScope} />
          {/* #504: fixed 4-tile services grid - one-tap actions off the home. */}
          <ServicesGrid />
          {/* #505: "Action required" - pending consent requests answered in
              place; the card is absent entirely when nothing is pending. */}
          <ActionRequiredCard />
          {/* #506: "Recent activity" - the top record-timeline events through
              the My Record describe helper, View all to the full timeline. */}
          <RecentActivityCard />
        </div>
        <aside
          className="min-w-0 lg:sticky lg:top-[4.5rem]"
          data-testid="patient-home-rail"
        >
          {/* #507: the sticky health snapshot - last metric + latest report
              derived from the record timeline, Soon teasers when absent. */}
          <HealthSnapshotCard />
        </aside>
      </div>
    </>
  );
}
