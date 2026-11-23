"use client";

// PHASE-2.6 T09 (#200): homepage section 6 - how-it-works explainer
// (blueprint §3.1 row 6). The care loop in three steps; step 2 states the
// pre-summary truth rule (AI drafts, the doctor always reviews).
//
// #961: prototype's bento - centered section head (eyebrow, title, sub) and
// three step cards where the middle one is featured with the teal gradient,
// white text, and the "AI assisted" tag in the top-right corner.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { SectionHeading } from "@/components/public/SectionHeading";

export function HowItWorks() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const steps = [
    { title: t.how.s1t, body: t.how.s1b, featured: false },
    { title: t.how.s2t, body: t.how.s2b, featured: true },
    { title: t.how.s3t, body: t.how.s3b, featured: false },
  ];

  return (
    <section id="how-it-works" data-testid="section-how">
      <div className="mx-auto w-full max-w-6xl px-4 py-10">
        <div className="flex flex-col items-center text-center">
          <SectionHeading eyebrow={t.how.eyebrow} title={t.how.title}>
            <p className="mt-1 max-w-[56ch] text-sm text-txt-muted">
              {t.how.sub}
            </p>
          </SectionHeading>
        </div>
        <ol className="mt-5 grid gap-4 sm:grid-cols-3">
          {steps.map((step, index) => (
            <li
              key={step.title}
              className={
                step.featured
                  ? "home-how-featured relative flex flex-col gap-2.5 overflow-hidden rounded-2xl border p-6"
                  : "relative flex flex-col gap-2.5 overflow-hidden rounded-2xl border border-hairline bg-surface p-6 text-txt shadow-card transition-transform duration-200 hover:-translate-y-0.5"
              }
            >
              {step.featured && (
                <span className="absolute right-[1.15rem] top-[1.15rem] rounded-full bg-white/20 px-2.5 py-1 text-[0.675rem] font-bold uppercase tracking-[0.05em] text-on-accent">
                  {t.how.aiTag}
                </span>
              )}
              <span
                aria-hidden="true"
                className={
                  step.featured
                    ? "flex h-11 w-11 items-center justify-center rounded-[13px] border border-white/35 bg-white/20 text-lg font-bold text-on-accent"
                    : "flex h-11 w-11 items-center justify-center rounded-[13px] border border-accent-border bg-accent-soft text-lg font-bold text-accent-strong"
                }
              >
                {index + 1}
              </span>
              <strong className="text-base font-semibold">{step.title}</strong>
              <p
                className={
                  step.featured
                    ? "home-how-featured-body text-sm leading-relaxed"
                    : "text-sm leading-relaxed text-txt-muted"
                }
              >
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
