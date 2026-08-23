"use client";

// PHASE-2.6 T13 (#204): the dedicated route for the first-login
// profile-completion wizard. The page is fully client-side; the draft
// lives in localStorage (lib/profile/profileState, gap G5) and the
// wizard is fully controlled so it can also be embedded inline by the
// gating component when a care action triggers a gate.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { ProfileCompletionWizard } from "@/components/patient/profile/ProfileCompletionWizard";
import {
  initialDraft,
  loadDraft,
  saveDraft,
  type ProfileDraft,
} from "@/lib/profile/profileState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export default function ProfileCompletionPage() {
  const router = useRouter();
  const { lang } = useLang();
  // Start at the empty draft and adopt the stored one after mount
  // (hydration-safe, mirrors AppShell's storage convention).
  const [draft, setDraft] = useState<ProfileDraft>(initialDraft);

  useEffect(() => {
    setDraft(loadDraft());
  }, []);

  const handleDraftChange = (next: ProfileDraft) => {
    setDraft(next);
    saveDraft(next);
  };

  const handleFinish = () => {
    router.push("/patient");
    router.refresh();
  };

  return (
    <>
      <PageHeader title={STRINGS[lang].profile.pageTitle} />
      <ProfileCompletionWizard
        draft={draft}
        onDraftChange={handleDraftChange}
        onFinish={handleFinish}
      />
    </>
  );
}
