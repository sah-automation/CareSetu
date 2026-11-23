"use client";

// PHASE-2.6 T09 (#200): homepage section 8 - For Providers band
// (blueprint §3.1 row 8). Recruits the supply side with one-line benefits;
// every Register CTA carries the application-type preset consumed by ticket
// 11's wizard. Copy states verification-before-listing and never implies
// instant listing.
//
// #961: prototype's supply-side band - warm eyebrow, headline, subline, and
// cards opening with the warm role badge (doctorT/labT/chemistT) above the
// benefit body, with the Register pill CTA.

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { providerRegisterHref, type ProviderType } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { SectionHeading } from "@/components/public/SectionHeading";

export function ProvidersBand() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const cards: {
    type: ProviderType;
    role: string;
    body: string;
  }[] = [
    { type: "doctor", role: t.providers.doctorT, body: t.providers.doctorB },
    { type: "lab", role: t.providers.labT, body: t.providers.labB },
    {
      type: "chemist",
      role: t.providers.chemistT,
      body: t.providers.chemistB,
    },
  ];

  return (
    <section data-testid="section-providers">
      <div className="mx-auto w-full max-w-6xl px-4 py-10">
        <SectionHeading
          eyebrow={t.providers.eyebrow}
          title={t.providers.title}
          eyebrowClassName="text-warm"
        >
          <p className="mt-1 max-w-[58ch] text-sm text-txt-muted">
            {t.providers.sub}
          </p>
        </SectionHeading>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {cards.map((card) => (
            <div
              key={card.type}
              className="flex flex-col gap-2.5 rounded-2xl border border-hairline bg-surface p-6 shadow-card"
            >
              <span className="self-start rounded-full bg-warm-soft px-2.5 py-1 text-[0.7rem] font-bold uppercase tracking-[0.07em] text-warm">
                {card.role}
              </span>
              <p className="text-sm leading-relaxed text-txt-muted">
                {card.body}
              </p>
              <Button
                asChild
                className="mt-auto w-full rounded-full font-semibold"
              >
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
