"use client";

// PHASE-2.6 T09 (#200): homepage section 8 - For Providers band
// (blueprint §3.1 row 8). Recruits the supply side with one-line benefits;
// every Register CTA carries the application-type preset consumed by ticket
// 11's wizard. Copy states verification-before-listing and never implies
// instant listing.

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { providerRegisterHref, type ProviderType } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export function ProvidersBand() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const cards: { type: ProviderType; title: string; body: string }[] = [
    { type: "doctor", title: t.providers.doctorT, body: t.providers.doctorB },
    { type: "lab", title: t.providers.labT, body: t.providers.labB },
    {
      type: "chemist",
      title: t.providers.chemistT,
      body: t.providers.chemistB,
    },
  ];

  return (
    <section data-testid="section-providers">
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <h2 className="text-2xl font-semibold text-txt">{t.providers.title}</h2>
        <p className="mt-1 text-txt-muted">{t.providers.sub}</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {cards.map((card) => (
            <div
              key={card.type}
              className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-5 shadow-card"
            >
              <strong className="text-txt">{card.title}</strong>
              <p className="text-sm leading-relaxed text-txt-muted">
                {card.body}
              </p>
              <Button asChild className="mt-auto w-full">
                <Link href={providerRegisterHref(card.type)}>
                  {t.providers.register}
                </Link>
              </Button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
