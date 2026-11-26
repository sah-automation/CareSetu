"use client";

// PHASE-2.6 T09 (#200): homepage section 6 - how-it-works explainer
// (blueprint §3.1 row 6). The care loop in three steps; step 2 states the
// pre-summary truth rule (AI drafts, the doctor always reviews).

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export function HowItWorks() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const steps = [
    { title: t.how.s1t, body: t.how.s1b },
    { title: t.how.s2t, body: t.how.s2b },
    { title: t.how.s3t, body: t.how.s3b },
  ];

  return (
    <section id="how-it-works" data-testid="section-how">
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <h2 className="text-2xl font-semibold text-txt">{t.how.title}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {steps.map((step, index) => (
            <div
              key={step.title}
              className="flex flex-col gap-1 rounded-lg border border-hairline bg-surface p-5 shadow-card"
            >
              <span
                aria-hidden="true"
                className="text-3xl font-bold text-warm-mid"
              >
                {index + 1}
              </span>
              <strong className="text-txt">{step.title}</strong>
              <p className="text-sm leading-relaxed text-txt-muted">
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
