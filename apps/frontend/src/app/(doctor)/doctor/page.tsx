"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { readSession, type StoredSession } from "@/lib/auth/session";

export default function DoctorDashboardPage() {
  const [session, setSession] = useState<StoredSession | null>(null);

  useEffect(() => {
    setSession(readSession());
  }, []);

  const displayName = session?.phone ? `Doctor (${session.phone})` : "Doctor";

  return (
    <>
      <PageHeader
        title={`Welcome, ${displayName}`}
        description="Your doctor workspace is active."
      />
      <div className="space-y-6">
        <section className="rounded-lg border border-border bg-bg p-4">
          <h2 className="text-sm font-semibold text-txt">Status</h2>
          <p className="mt-1 text-sm text-txt-muted">
            Your profile is active and verified. You can begin accepting
            consultations.
          </p>
        </section>

        <section className="rounded-lg border border-border bg-bg p-4">
          <h2 className="text-sm font-semibold text-txt">Next Steps</h2>
          <ul className="mt-2 space-y-1 text-sm text-txt-muted">
            <li>- Complete your professional profile (coming soon)</li>
            <li>- Browse the patient directory (Phase 6)</li>
            <li>- Start a consultation from a patient record</li>
          </ul>
        </section>
      </div>
    </>
  );
}
