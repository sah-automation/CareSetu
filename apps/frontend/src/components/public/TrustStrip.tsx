"use client";

// PHASE-2.6 T09 (#200): homepage section 7 - trust & consent strip
// (blueprint §3.1 row 7). Serves the offline-trust persona: verification
// before listing, consent-gated sharing, revocable control.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export function TrustStrip() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const statements = [t.trust.t1, t.trust.t2, t.trust.t3];

  return (
    <section data-testid="section-trust" aria-label={t.trust.t1}>
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <div className="rounded-lg border border-accent-border bg-accent-soft px-6 py-8 text-center">
          <ul className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            {statements.map((statement, index) => (
              <li key={statement} className="flex items-center gap-6">
                {index > 0 && (
                  <span aria-hidden="true" className="text-accent-border">
                    |
                  </span>
                )}
                <span className="text-sm font-semibold text-txt">
                  {statement}
                </span>
              </li>
            ))}
          </ul>
          {/* Placeholder target: the Privacy content page is owned by a later
              ticket; the anchor keeps the strip's anatomy stable until then. */}
          <p className="mt-3 text-xs">
            <a
              href="#"
              className="text-txt-muted underline-offset-2 hover:underline"
            >
              {t.trust.privacy}
            </a>
          </p>
        </div>
      </div>
    </section>
  );
}
