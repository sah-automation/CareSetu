"use client";

// PHASE-2.6 T10 (#201): partner "pending / under verification" state screen
// (blueprint §4.4). Lives inside the partner route group, so the session
// guard (/partner/:path*) and the full AppShell wrap it automatically; any
// post-login landing while the application is pending arrives here instead
// of the channel home.
//
// The verification data itself (submitted-at, application identity) is a
// Phase 5 session/API concern - until those endpoints exist the fields show
// an honest placeholder instead of fabricated values.

import { PageHeader } from "@/components/layout/PageHeader";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export default function PartnerStatusPendingPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.pending;

  return (
    <div className="mx-auto w-full max-w-xl">
      <PageHeader title={t.headerTitle} />
      <section
        className="rounded-lg border border-hairline bg-surface p-6 text-center shadow-card"
        data-testid="partner-pending-card"
        aria-labelledby="partner-pending-title"
      >
        <p className="text-4xl" aria-hidden="true">
          ⏳
        </p>
        <span
          className="mt-2 inline-block rounded-full bg-warn-soft px-2 py-0.5 text-xs font-semibold text-warn-text"
          data-testid="partner-status-badge"
        >
          {t.badge}
        </span>
        <h1 id="partner-pending-title" className="mt-3 text-xl font-bold">
          {t.title}
        </h1>

        <dl className="mx-auto mt-4 max-w-sm space-y-1 text-left text-sm">
          {[
            [t.submittedLabel, t.detailPlaceholder],
            [t.applicationLabel, t.detailPlaceholder],
            [t.verifyingLabel, t.detailPlaceholder],
            [t.windowLabel, t.windowValue],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4">
              <dt className="text-txt-muted">{label}</dt>
              <dd className="text-right font-medium">{value}</dd>
            </div>
          ))}
        </dl>

        <div
          role="note"
          data-testid="partner-pending-note"
          className="mt-4 rounded-md border border-hairline bg-page-bg px-3 py-2 text-left text-sm"
        >
          {t.infoBanner}
        </div>

        <a
          href="#"
          className="mt-4 inline-block rounded-md border border-hairline px-4 py-2 text-sm"
          data-testid="partner-help-link"
        >
          {t.helpCta}
        </a>
      </section>
    </div>
  );
}
