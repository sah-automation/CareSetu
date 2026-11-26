"use client";

// PHASE-8.1 T2 (#488): bilingual Finish-persistence state surfaced by both
// wizard hosts (complete page + inline gate) while PUT /v1/me/profile runs.
// "idle" renders nothing; saving/saved render a separate live-region status,
// error an alert so assistive tech announces the failure.

import type { ReactNode } from "react";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import type { ProfileSaveStatus } from "@/lib/profile/ProfileContext";

export function ProfileSaveStatusNotice({
  saveStatus,
}: {
  saveStatus: ProfileSaveStatus;
}): ReactNode {
  const { lang } = useLang();
  const t = STRINGS[lang].profile.save;

  if (saveStatus === "idle") return null;

  if (saveStatus === "error") {
    return (
      <p
        role="alert"
        data-testid="profile-save-error"
        className="flex items-start gap-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
      >
        {t.error}
      </p>
    );
  }

  return (
    <p
      role="status"
      data-testid="profile-save-status"
      className="flex items-start gap-2 rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text"
    >
      {saveStatus === "saving" ? t.saving : t.saved}
    </p>
  );
}
