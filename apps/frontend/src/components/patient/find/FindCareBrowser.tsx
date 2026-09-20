"use client";

// PHASE-8.1 T11 (#485): the authed Find Care browse page (blueprint §5.3)
// under the patient shell. The verified-directory surface is the shared
// DirectoryBrowser reused as-is, with two seams: filter commits stay on
// /patient/find (baseRoute) and the card grid fits the patient column width.
// Above the browse, when the intake flow has an in-progress intake it carries
// ?intake=<id> onto this page (per §5.4 "Find Care booking flow carrying the
// intake id"), and a continuation CTA deep-links back into that intake's pick
// step - browsing and choosing one doctor stay connected (US-6). No intake
// param means plain browse with no booking deep-link; the pick step is the
// only booking surface, so a stale/foreign id simply lands on the pick page's
// own not-found handling. The URL is the single source of truth for both the
// browse filters and the continuation seam - no client-side intake state.

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { DirectoryBrowser } from "@/components/directory/DirectoryBrowser";
import { Button } from "@/components/ui/button";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const FIND_ROUTE = "/patient/find";

/** Query param the intake flow uses to signal an in-progress intake, and the
 * deep-link target the pick step derives from (blueprint §5.4/§5.3). */
const INTAKE_QUERY_PARAM = "intake";

/** Accepts only a positive integer intake id - anything else is "no intake in
 * progress" so a malformed param can never fabricate a deep link. */
function parseIntakeId(value: string | null): number | null {
  if (value === null) return null;
  if (!/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

export function FindCareBrowser() {
  const { lang } = useLang();
  const t = STRINGS[lang].findCare;
  const searchParams = useSearchParams();
  const intakeId = parseIntakeId(searchParams.get(INTAKE_QUERY_PARAM));

  return (
    <>
      {intakeId !== null && (
        <section data-testid="resume-consult" className="mb-4 px-1">
          <div className="flex flex-col gap-3 rounded-lg border border-accent-border bg-accent-soft px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div className="flex min-w-0 flex-col gap-0.5">
              <p className="font-medium text-txt">{t.resumeTitle}</p>
              <p className="text-sm text-txt-muted">{t.resumeBody}</p>
            </div>
            <Button asChild className="shrink-0" data-testid="find-care-book">
              <Link href={`/patient/intake/${intakeId}/pick`}>{t.bookCta}</Link>
            </Button>
          </div>
        </section>
      )}

      <DirectoryBrowser
        baseRoute={FIND_ROUTE}
        cardGridClassName="grid gap-4 sm:grid-cols-2"
      />
    </>
  );
}
