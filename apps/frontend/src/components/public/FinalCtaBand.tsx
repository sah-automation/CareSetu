"use client";

// PHASE-2.6 T09 (#200): homepage section 9 - final CTA band
// (blueprint §3.1 row 9, §3.2 role-entry model). Get started follows the
// session like the header (anonymous -> /login, authenticated -> role
// dashboard); the Dashboard button renders only when a session exists so an
// anonymous visitor never sees a control that cannot mean anything yet.

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
        <div className="rounded-lg bg-accent px-6 py-10 text-center text-on-accent">
          <h2 className="text-2xl font-semibold">{t.finalCta.title}</h2>
          <p className="mx-auto mt-2 max-w-md text-accent-border">
            {t.finalCta.sub}
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg" variant="secondary">
              <Link href={sessionHomeHref}>{t.hero.getStarted}</Link>
            </Button>
            {isAuthenticated && (
              <Button
                asChild
                size="lg"
                variant="ghost"
                className="text-on-accent hover:bg-primary/90 hover:text-on-accent"
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
