"use client";

// PHASE-2.6 T09 (#200): homepage section 9 - final CTA band
// (blueprint §3.1 row 9, §3.4 role-entry model). Get started follows the
// session like the header (anonymous -> /login, authenticated -> role
// dashboard); the Dashboard button renders only when a session exists so an
// anonymous visitor never sees a control that cannot mean anything yet.
// The hero no longer carries a Get started CTA (#961) - this band owns it.
//
// #961: prototype's teal gradient panel with the clamped headline and white
// pill CTAs.

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useRoleHomeHref } from "@/lib/auth/useRoleHomeHref";

export function FinalCtaBand() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;
  const { isAuthenticated } = useAuth();
  const sessionHomeHref = useRoleHomeHref();

  return (
    <section data-testid="section-final-cta" className="bg-page-bg">
      <div className="mx-auto w-full max-w-6xl px-4 py-10">
        <div className="home-cta-panel rounded-[18px] px-6 py-12 text-center text-on-accent">
          <h2 className="home-cta-h2">{t.finalCta.title}</h2>
          {/* T14 #205 axe gate: the subline keeps the measured accent-soft
              (#f0fdfa) treatment - 5.4:1 against the gradient's mid stop - so
              the contrast floor the spec pins (>=4.5:1) holds on every point
              of the 135deg wash. White-at-alpha over the lighter #0d9488 end
              stop would drop below it. */}
          <p className="mx-auto mt-3 max-w-md text-base text-accent-soft">
            {t.finalCta.sub}
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <Button
              asChild
              size="lg"
              className="rounded-full bg-surface px-7 font-semibold text-accent-strong shadow-[0_10px_24px_-12px_rgba(2,6,23,0.45)] hover:bg-hairline-soft"
            >
              <Link href={sessionHomeHref}>{t.hero.getStarted}</Link>
            </Button>
            {isAuthenticated && (
              <Button
                asChild
                size="lg"
                variant="ghost"
                className="rounded-full border border-white/70 px-7 font-semibold text-on-accent hover:bg-white/10 hover:text-on-accent"
              >
                <Link href={sessionHomeHref} data-testid="final-dashboard-link">
                  {t.authButton.dashboard}
                </Link>
              </Button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
