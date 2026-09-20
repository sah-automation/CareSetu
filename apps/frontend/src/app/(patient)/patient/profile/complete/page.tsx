"use client";

// PHASE-2.6 T13 (#204): the dedicated route for the first-login
// profile-completion wizard. PHASE-8.1 T2 (#488): the editable draft
// (identity-scoped buffer) and the saved server profile come from the patient
// ProfileProvider - hydration answers saved-profile state before the buffer is
// consulted - and the page routes back to the dashboard only after Finish
// persisted through PUT /v1/me/profile. Save in-flight/error/saved state
// renders bilingually while the write runs.

import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { ProfileCompletionWizard } from "@/components/patient/profile/ProfileCompletionWizard";
import { ProfileSaveStatusNotice } from "@/components/patient/profile/SaveStatusNotice";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfile } from "@/lib/profile/ProfileContext";

export default function ProfileCompletionPage() {
  const router = useRouter();
  const { lang } = useLang();
  const { draft, saveStatus, updateDraft, finishProfile } = useProfile();

  const handleFinish = () => {
    void finishProfile().then((ok) => {
      if (ok) {
        router.push("/patient");
        router.refresh();
      }
    });
  };

  return (
    <>
      <PageHeader title={STRINGS[lang].profile.pageTitle} />
      <ProfileSaveStatusNotice saveStatus={saveStatus} />
      <ProfileCompletionWizard
        draft={draft}
        onDraftChange={updateDraft}
        onFinish={handleFinish}
      />
    </>
  );
}
