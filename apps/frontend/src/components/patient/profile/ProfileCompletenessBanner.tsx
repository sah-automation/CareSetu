"use client";

// #500: the slim, one-line profile-completeness banner on the reworked patient
// home (PROTO-2.7 binding, shell-light.html profile-banner). Name/age/gender
// are the care-action basics (blueprint §5.9); while any is missing and the
// banner has not been dismissed, it nudges under the greeting strip - never a
// blocking gate, never the old nudge stack. Dismissal persists per device via
// localStorage (profileState), so a later visit stays clean - unlike the
// session-scoped nudge cards. Renders nothing until the saved profile settles
// (no false flash for a complete-profile patient) and nothing at all once
// basics are complete.

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import Link from "next/link";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfile } from "@/lib/profile/ProfileContext";
import {
  basicsComplete,
  dismissProfileBanner,
  isProfileBannerDismissed,
} from "@/lib/profile/profileState";

export function ProfileCompletenessBanner() {
  const { draft, hydrated } = useProfile();
  const { lang } = useLang();
  const t = STRINGS[lang].patientHome;
  const [dismissed, setDismissed] = useState(false);

  // SSR guard, same as LangContext's adoptStoredLang: the server render cannot
  // touch localStorage, so the first client render starts undismissed and the
  // durable flag is adopted once after mount - hydration always matches.
  useEffect(() => {
    if (isProfileBannerDismissed()) setDismissed(true);
  }, []);

  if (!hydrated || basicsComplete(draft) || dismissed) {
    return null;
  }

  return (
    <section
      data-testid="pc-banner"
      className="flex flex-wrap items-center gap-3 rounded-md border border-accent-border bg-accent-soft px-4 py-2.5 text-accent-strong"
    >
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
        <strong className="text-sm font-semibold">{t.banner}</strong>
        <Link
          href="/patient/profile/complete"
          className="text-sm font-medium underline-offset-2 hover:underline"
        >
          {t.bannerCta}
        </Link>
      </div>
      <button
        type="button"
        data-testid="pc-banner-dismiss"
        onClick={() => {
          dismissProfileBanner();
          setDismissed(true);
        }}
        className="shrink-0 rounded-full p-1.5 text-accent-strong hover:bg-hairline"
        aria-label={t.bannerDismiss}
      >
        <X className="h-4 w-4" />
      </button>
    </section>
  );
}
