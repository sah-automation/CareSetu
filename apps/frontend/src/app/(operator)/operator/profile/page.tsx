"use client";

import { useEffect, useRef, useState } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  ProfileSectionShell,
  type SectionFailure,
} from "@/components/doctor/profile/ProfileSectionShell";
import { useSectionEditBuffer } from "@/components/doctor/profile/useSectionEditBuffer";
import { OperatorProfilePhotoCard } from "@/components/operator/profile/OperatorProfilePhotoCard";
import { ApiError } from "@/lib/api-errors";
import {
  fetchOperatorProfilePhoto,
  updateOperatorProfile,
  type OperatorProfileView,
} from "@/lib/operator/api";
import { useOperatorProfile } from "@/lib/operator/OperatorProfileContext";
import { idempotencyKey } from "@/lib/idempotency";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";
import Link from "next/link";

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="profile-skeleton">
      <Skeleton className="h-20 w-20 rounded-full" />
      <Skeleton className="h-9 w-full" />
    </div>
  );
}

export default function OperatorProfilePage() {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorProfile;

  const { profile, status, errorTraceId, reload, adoptProfile } =
    useOperatorProfile();

  const [photoFailure, setPhotoFailure] = useState<SectionFailure | null>(null);
  const [photoBusy] = useState(false);
  const nameAttemptKey = useRef<string | null>(null);

  const newestProfile = useRef<OperatorProfileView | null>(null);
  useEffect(() => {
    newestProfile.current = profile;
  }, [profile]);

  function adoptRef<K extends keyof OperatorProfileView>(
    field: K,
    value: OperatorProfileView[K],
  ) {
    const current = newestProfile.current;
    if (current === null) return;
    adoptProfile({ ...current, [field]: value });
  }

  const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(
    profile?.photo_ref ?? null,
    fetchOperatorProfilePhoto,
  );

  const [bannerOpen, setBannerOpen] = useState(false);
  useEffect(() => {
    if (status === "error") setBannerOpen(true);
  }, [status]);

  function retryLoad() {
    setBannerOpen(false);
    reload();
  }

  const identityBuffer = useSectionEditBuffer(profile, (answer) => ({
    name: answer.name ?? "",
  }));

  useEffect(() => {
    nameAttemptKey.current = null;
  }, [identityBuffer.edits]);

  async function saveIdentity() {
    if (identityBuffer.value === null) return { status: "declined" as const };
    const key = nameAttemptKey.current ?? idempotencyKey();
    nameAttemptKey.current = key;
    try {
      const view = await updateOperatorProfile(
        { name: identityBuffer.value.name.trim() || null },
        key,
      );
      nameAttemptKey.current = null;
      adoptProfile(view);
      return { status: "saved" as const };
    } catch (err) {
      return {
        status: "failed" as const,
        failure: {
          traceId: err instanceof ApiError ? err.traceId : undefined,
        },
      };
    }
  }

  const ready = status === "ready" && profile != null;

  const createdLabel =
    profile != null
      ? new Intl.DateTimeFormat(lang, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(profile.created_at))
      : "";

  const tierLabel = profile?.tier === "admin" ? "Admin" : "Operator";
  const mfaEnabled = profile?.mfa_enabled ?? false;

  const anchors = [
    { id: "profile-section-identity", label: t.identityHeading },
    { id: "profile-section-account", label: t.accountHeading },
    { id: "profile-section-security", label: t.securityHeading },
  ];

  return (
    <>
      {status === "loading" && (
        <PageHeader title={t.title} description={t.description} />
      )}
      {status === "error" && bannerOpen && (
        <>
          <PageHeader title={t.title} description={t.description} />
          <ErrorBanner
            message="Could not load your profile."
            traceId={errorTraceId}
            onRetry={retryLoad}
            onDismiss={() => setBannerOpen(false)}
          />
        </>
      )}
      {status === "loading" && <LoadingSkeleton />}

      {ready && (
        <div className="space-y-4" data-testid="operator-profile-page">
          <details
            className="rounded-md border border-hairline bg-surface p-2"
            data-testid="profile-section-index"
          >
            <summary className="cursor-pointer text-sm font-medium">
              Sections
            </summary>
            <nav className="mt-2 flex flex-wrap gap-2">
              {anchors.map((anchor) => (
                <a
                  key={anchor.id}
                  href={`#${anchor.id}`}
                  data-testid={`profile-anchor-${anchor.id}`}
                  className="inline-flex min-h-11 items-center text-sm"
                >
                  {anchor.label}
                </a>
              ))}
            </nav>
          </details>

          <ProfileSectionShell
            title={t.identityHeading}
            help={t.description}
            anchorId="profile-section-identity"
            testId="profile-identity"
            save={{
              onSave: saveIdentity,
              label: t.save,
              savedLabel: t.saved,
              unsavedLabel: t.saveFailed,
              failureMessage: t.saveFailed,
              dirty: identityBuffer.dirty,
              edits: identityBuffer.edits,
              buttonTestId: "profile-identity-save",
              savedTestId: "profile-identity-saved",
              unsavedTestId: "profile-identity-unsaved",
            }}
          >
            <OperatorProfilePhotoCard
              photoRef={profile?.photo_ref ?? null}
              name={profile?.name ?? ""}
              onPhotoRefChange={(ref) => adoptRef("photo_ref", ref)}
            />

            <div className="mt-4 flex flex-col gap-2">
              <label
                htmlFor="profile-name"
                className="text-sm font-medium text-txt"
              >
                {t.nameLabel}
              </label>
              <input
                id="profile-name"
                data-testid="profile-name"
                type="text"
                className="block h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={t.namePlaceholder}
                value={identityBuffer.value?.name ?? ""}
                onChange={(e) =>
                  identityBuffer.change({ name: e.target.value })
                }
              />
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className="text-sm text-txt-muted">{t.tierLabel}</span>
              <span
                data-testid="operator-tier-badge"
                className="rounded px-1.5 py-0.5 text-xs font-medium bg-accent-soft text-accent"
              >
                {tierLabel}
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-sm text-txt-muted">{t.mfaLabel}</span>
              <span data-testid="operator-mfa-status">
                {mfaEnabled ? t.mfaEnabled : t.mfaDisabled}
              </span>
            </div>
          </ProfileSectionShell>

          <ProfileSectionShell
            title={t.accountHeading}
            anchorId="profile-section-account"
            testId="profile-account"
          >
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-sm text-txt-muted">{t.phoneLabel}</p>
                <p data-testid="operator-phone" className="text-sm text-txt">
                  {profile?.phone}
                </p>
              </div>
              <div>
                <p className="text-sm text-txt-muted">{t.createdLabel}</p>
                <p
                  data-testid="operator-created-at"
                  className="text-sm text-txt"
                >
                  {createdLabel}
                </p>
              </div>
            </div>
          </ProfileSectionShell>

          <ProfileSectionShell
            title={t.securityHeading}
            anchorId="profile-section-security"
            testId="profile-security"
          >
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-sm text-txt-muted">{t.mfaLabel}</p>
                <p data-testid="operator-mfa-status-security">
                  {mfaEnabled ? t.mfaEnabled : t.mfaDisabled}
                </p>
              </div>
              <Link
                href="/operator/security"
                data-testid="operator-mfa-manage"
                className="inline-flex min-h-11 items-center text-sm text-accent underline"
              >
                {t.mfaManage}
              </Link>
            </div>
          </ProfileSectionShell>
        </div>
      )}
    </>
  );
}
