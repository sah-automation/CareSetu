"use client";

// PHASE-2.6 T10 (#201): partner "rejected with reason" state screen (blueprint
// §4.4, FEAT-014 scenario 2). Same group placement as the pending screen -
// session guard + full AppShell come from the partner layout.
//
// The rejection reason and operator note are Phase 5 data; until then the
// reason block shows an honest placeholder. The resubmission edge
// (Rejected -> Under Verification, PRD §10 G4) is stubbed: the CTA names
// Phase 5 instead of navigating anywhere or faking a submission.

import { useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export default function PartnerStatusRejectedPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.rejected;
  const [stubRevealed, setStubRevealed] = useState(false);

  return (
    <div className="mx-auto w-full max-w-xl">
      <PageHeader title={t.headerTitle} />
      <section
        className="rounded-lg border border-hairline bg-surface p-6 text-center shadow-card"
        data-testid="partner-rejected-card"
        aria-labelledby="partner-rejected-title"
      >
        <span
          className="inline-block rounded-full bg-danger-soft px-2 py-0.5 text-xs font-semibold text-danger"
          data-testid="partner-status-badge"
        >
          {t.badge}
        </span>
        <h1 id="partner-rejected-title" className="mt-3 text-xl font-bold">
          {t.title}
        </h1>

        <div
          role="alert"
          data-testid="partner-rejection-reason"
          className="mt-4 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-left text-sm"
        >
          <p>
            <strong>{t.reasonHeading}</strong> {t.reasonPlaceholder}
          </p>
        </div>

        <p className="mt-3 text-sm text-txt-sub">{t.fixNote}</p>

        {stubRevealed ? (
          <p
            role="status"
            data-testid="partner-resubmit-stub"
            className="mt-3 rounded-md border border-hairline bg-page-bg px-3 py-2 text-left text-sm text-txt-muted"
          >
            {t.resubmitStubNotice}
          </p>
        ) : null}

        <button
          type="button"
          onClick={() => setStubRevealed(true)}
          data-testid="partner-resubmit-cta"
          className="mt-4 w-full rounded-md bg-accent px-4 py-2 font-semibold text-on-accent"
        >
          {t.resubmitCta}
        </button>
        <a
          href="#"
          className="mt-2 inline-block text-sm underline"
          data-testid="partner-help-link"
        >
          {t.helpCta}
        </a>
      </section>
    </div>
  );
}
