// #618 AC 2: the doctor's live preview - the same renderer the public page runs,
// fed what the doctor is typing instead of what the API answered.
//
// What this component is responsible for, and nothing else:
//
//   1. Map (saved projection + typed draft) to the public projection and hand it to
//      `ProviderProfileBody`. The renderer is the public page's renderer; there is
//      no second copy of a band here to fall behind.
//   2. Say what the preview is and where it comes from. A doctor looking at a
//      profile-shaped thing has to be able to tell it is a preview of THEIR edits,
//      and that the tick in it is CareSetu's, not theirs.
//   3. Get out of the way on a phone. Sticky on desktop, collapsible on mobile -
//      the same split the console chrome itself makes (`lg:hidden` sidebar, sticky
//      topbar), because a preview that owns half a phone screen while a doctor is
//      typing into fields is a preview nobody reads.
//
// What it must NOT be responsible for, because each of these was a live bug shape
// in this area:
//
//   - It must not emit a patient pick. `emitPartnerSelected` belongs to the public
//     page and stays there; a preview that fired one would report a patient
//     choosing a provider every time a doctor re-renders.
//   - It must not fetch. The saved projection comes from the shared source the
//     console already reads, so there is no second read to keep in step.
//   - It must not decide stickiness for the page. `lg:sticky` is here because this
//     is the preview's own box; the grid that gives it a column is the shell's.
//
// The heading level is `2` because the console's `h1` is the identity band's name,
// and #615 asserts this page has exactly one. The renderer takes the level as a
// prop for that reason, not because the two surfaces may differ.

"use client";

import { useState } from "react";

import { ProviderProfileBody } from "@/components/public/ProviderProfileBody";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

import { usePublicProfileDraft } from "./PublicProfileDraftContext";
import { projectPublicProfile } from "./publicProfileProjection";

/** The id the toggle's `aria-controls` points at. */
const BODY_ID = "profile-live-preview-body";

export function ProfileLivePreview() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const { profile, draft } = usePublicProfileDraft();
  // Open by default on both sizes. A preview the doctor has to discover before it
  // updates is a preview that fails its one job, and the mobile affordance is
  // there to get it OUT of the way, not to hide it by default.
  const [expanded, setExpanded] = useState(true);

  const projection = projectPublicProfile(profile, draft);

  return (
    // `lg:sticky` sits under the console header (`top-14`) plus the anchor-chip
    // index's own height, so a long preview stops short of the chips rather than
    // under them. The height cap and its scroll are what keep a five-band profile
    // from running past the fold with nothing of the form left on screen.
    <section
      data-testid="profile-live-preview"
      aria-labelledby="profile-live-preview-heading"
      className="rounded-lg border border-hairline bg-surface lg:sticky lg:top-28 lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto"
    >
      <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
        <div className="min-w-0">
          <h2
            id="profile-live-preview-heading"
            className="text-sm font-semibold text-txt"
          >
            {t.livePreviewHeading}
          </h2>
          <p className="mt-0.5 text-xs text-txt-muted">{t.livePreviewHelp}</p>
        </div>
        {/* Mobile only, by construction (`lg:hidden`): on a desktop the rail is a
            permanent column and a control that could hide it would be a control
            over what the doctor can see. The focus ring and the 44px tap target
            are on the button itself, which is the focusable element (§9.4). */}
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={BODY_ID}
          onClick={() => setExpanded((open) => !open)}
          data-testid="profile-live-preview-toggle"
          className="ml-auto inline-flex min-h-11 shrink-0 items-center rounded-lg border border-hairline bg-surface px-3 text-xs font-medium text-txt focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-border lg:hidden"
        >
          {expanded ? t.livePreviewHide : t.livePreviewShow}
        </button>
      </div>

      {/* Visibility is CSS, not the `hidden` attribute: the UA rule for `[hidden]`
          is beaten by an author `lg:block`, so an attribute would read as "always
          collapsed" on desktop. `display:none` is what actually removes the region
          from the accessibility tree when the toggle says it is closed. */}
      <div
        id={BODY_ID}
        data-testid="profile-live-preview-content"
        className={`px-4 pb-4 pt-3 lg:block ${expanded ? "block" : "hidden"}`}
      >
        <ProviderProfileBody profile={projection} headingLevel={2} />
      </div>
    </section>
  );
}
