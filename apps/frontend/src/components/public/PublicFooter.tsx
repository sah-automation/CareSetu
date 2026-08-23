"use client";

// PHASE-2.6 T09 (#200): homepage section 10 - four-column public footer +
// meta row (blueprint §3.3). The operator console appears nowhere except its
// discreet low-emphasis footer link; the route itself enforces auth/RBAC.

import Link from "next/link";

import {
  directoryHref,
  providerRegisterHref,
  type ProviderType,
} from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// The three find-a-X / register-a-X links mirror the tiles' ProviderType
// presets.
const PROVIDER_TYPES: ProviderType[] = ["doctor", "lab", "chemist"];

export function PublicFooter() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;

  const findLabels: Record<ProviderType, string> = {
    doctor: t.footer.findDoctors,
    lab: t.footer.findLabs,
    chemist: t.footer.findChemists,
  };
  const registerLabels: Record<ProviderType, string> = {
    doctor: t.footer.regDoctor,
    lab: t.footer.regLab,
    chemist: t.footer.regChemist,
  };

  return (
    <footer
      data-testid="section-footer"
      className="border-t border-hairline bg-surface"
    >
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-10 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <h3 className="text-sm font-semibold text-txt">
            {t.footer.patients}
          </h3>
          <ul className="mt-3 space-y-2 text-sm text-txt-sub">
            {PROVIDER_TYPES.map((type) => (
              <li key={type}>
                <a className="hover:text-accent" href={directoryHref(type)}>
                  {findLabels[type]}
                </a>
              </li>
            ))}
            <li>
              <a className="hover:text-accent" href="#how-it-works">
                {t.footer.howItWorks}
              </a>
            </li>
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-txt">
            {t.footer.providersCol}
          </h3>
          <ul className="mt-3 space-y-2 text-sm text-txt-sub">
            {PROVIDER_TYPES.map((type) => (
              <li key={type}>
                <Link
                  className="hover:text-accent"
                  href={providerRegisterHref(type)}
                >
                  {registerLabels[type]}
                </Link>
              </li>
            ))}
            <li>
              <Link className="hover:text-accent" href="/staff/login">
                {t.footer.staffLogin}
              </Link>
            </li>
          </ul>
        </div>
        {/* Placeholder targets: the About/Privacy/Terms/Contact content pages
            are owned by a later ticket; the anchors keep footer anatomy stable
            until then. */}
        <div>
          <h3 className="text-sm font-semibold text-txt">
            {t.footer.companyLegal}
          </h3>
          <ul className="mt-3 space-y-2 text-sm text-txt-sub">
            <li>
              <a className="hover:text-accent" href="#">
                {t.footer.about}
              </a>
            </li>
            <li>
              <a className="hover:text-accent" href="#">
                {t.footer.privacy}
              </a>
            </li>
            <li>
              <a className="hover:text-accent" href="#">
                {t.footer.terms}
              </a>
            </li>
            <li>
              <a className="hover:text-accent" href="#">
                {t.footer.contact}
              </a>
            </li>
          </ul>
        </div>
        <div>
          <p className="text-sm leading-relaxed text-txt-muted">{t.trust.t1}</p>
          <p className="mt-2 text-sm leading-relaxed text-txt-muted">
            {t.trust.t2}
          </p>
        </div>
      </div>
      <div className="border-t border-hairline-soft">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 text-xs text-txt-muted">
          <span>{t.footer.meta}</span>
          <Link
            href="/operator"
            className="text-txt-muted hover:text-accent hover:underline"
          >
            {t.footer.operatorConsole}
          </Link>
        </div>
      </div>
    </footer>
  );
}
