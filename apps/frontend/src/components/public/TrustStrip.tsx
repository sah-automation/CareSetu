"use client";

// PHASE-2.6 T09 (#200): homepage section 7 - trust & consent strip
// (blueprint §3.1 row 7). Serves the offline-trust persona: verification
// before listing, consent-gated sharing, revocable control.
//
// #961: prototype's trust panel - teal-to-white gradient panel with three
// check-circle statements in a grid (icon above centered text) and the
// privacy link placeholder.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const CHECK = (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

export function TrustStrip() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const statements = [t.trust.t1, t.trust.t2, t.trust.t3];

  return (
    <section data-testid="section-trust" aria-label={t.trust.eyebrow}>
      <div className="mx-auto w-full max-w-6xl px-4 py-6">
        <div className="home-trust-panel rounded-[20px] px-6 py-9 text-center md:px-8">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-accent-strong">
            {t.trust.eyebrow}
          </div>
          <h2 className="home-trust-h2 mx-auto mt-1.5 text-txt">
            {t.trust.title}
          </h2>
          <ul className="mx-auto mt-6 grid max-w-4xl gap-6 md:grid-cols-3">
            {statements.map((statement) => (
              <li
                key={statement}
                className="flex flex-col items-center gap-2.5"
              >
                <span
                  aria-hidden="true"
                  className="flex h-[42px] w-[42px] items-center justify-center rounded-full bg-accent text-on-accent shadow-[0_6px_14px_-6px_rgba(15,118,110,0.55)]"
                >
                  {CHECK}
                </span>
                <span className="max-w-[26ch] text-sm font-semibold text-txt">
                  {statement}
                </span>
              </li>
            ))}
          </ul>
          {/* Placeholder target: the Privacy content page is owned by a later
              ticket; the anchor keeps the strip's anatomy stable until then. */}
          <p className="mt-6 text-xs">
            <a
              href="#"
              className="font-semibold text-accent-strong underline-offset-2 hover:underline"
            >
              {t.trust.privacy}
            </a>
          </p>
        </div>
      </div>
    </section>
  );
}
