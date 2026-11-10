"use client";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { AiSettingsSection } from "@/components/settings/AiSettingsSection";
import { CacheRedisSettingsSection } from "@/components/settings/CacheRedisSettingsSection";
import { ScalingSettingsSection } from "@/components/settings/ScalingSettingsSection";
import { ObservabilityTuningSettingsSection } from "@/components/settings/ObservabilityTuningSettingsSection";
import { FeatureFlagsSettingsSection } from "@/components/settings/FeatureFlagsSettingsSection";
import { NotificationsSettingsSection } from "@/components/settings/NotificationsSettingsSection";
import { UsersSettingsSection } from "@/components/settings/UsersSettingsSection";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

export default function SettingsPage() {
  const auth = useAuth();
  const { lang } = useLang();
  const t = STRINGS[lang].operatorSettings;
  const isAdmin = auth.user?.tier === "admin";

  if (!isAdmin) {
    return (
      <>
        <PageHeader title={t.title} description={t.description} />
        <div data-testid="settings-permission-denied">
          <EmptyState
            title={t.permissionDeniedTitle}
            body={t.permissionDeniedBody}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t.title} description={t.description} />
      <div className="flex flex-col gap-4" data-testid="settings-shell">
        <AiSettingsSection t={t} />

        <FeatureFlagsSettingsSection t={t} />

        <NotificationsSettingsSection t={t} />

        <UsersSettingsSection t={t} />

        <CacheRedisSettingsSection t={t} />

        <ScalingSettingsSection t={t} />

        <ObservabilityTuningSettingsSection t={t} />
      </div>
    </>
  );
}
