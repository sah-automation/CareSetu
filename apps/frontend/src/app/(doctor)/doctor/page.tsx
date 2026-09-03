"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { readSession, type StoredSession } from "@/lib/auth/session";

export default function DoctorDashboardPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctor;
  const [session, setSession] = useState<StoredSession | null>(null);

  useEffect(() => {
    setSession(readSession());
  }, []);

  const displayName = session?.phone
    ? t.doctorWithPhone(session.phone)
    : t.doctorLabel;

  return (
    <>
      <PageHeader
        title={t.welcome(displayName)}
        description={t.workspaceActive}
      />
      <div className="space-y-6">
        <section className="rounded-lg border border-border bg-bg p-4">
          <h2 className="text-sm font-semibold text-txt">{t.statusHeading}</h2>
          <p className="mt-1 text-sm text-txt-muted">{t.profileActive}</p>
        </section>

        <section className="rounded-lg border border-border bg-bg p-4">
          <h2 className="text-sm font-semibold text-txt">
            {t.nextStepsHeading}
          </h2>
          <ul className="mt-2 space-y-1 text-sm text-txt-muted">
            {t.nextSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
