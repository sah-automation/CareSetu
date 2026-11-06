"use client";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { AiSettingsSection } from "@/components/settings/AiSettingsSection";
import { CollapsibleSettingsSection } from "@/components/settings/CollapsibleSettingsSection";
import { FeatureFlagsSettingsSection } from "@/components/settings/FeatureFlagsSettingsSection";
import { NotificationsSettingsSection } from "@/components/settings/NotificationsSettingsSection";
import { UsersSettingsSection } from "@/components/settings/UsersSettingsSection";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

function useAuthOrNull() {
  try {
    return useAuth();
  } catch {
    return null;
  }
}

export default function SettingsPage() {
  const auth = useAuthOrNull();
  const { lang } = useLang();
  const t = STRINGS[lang].operatorSettings;
  const isAdmin = auth?.user?.tier === "admin";

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

        <CollapsibleSettingsSection
          sectionKey="cache"
          testId="settings-cache"
          title={t.sections.cache}
        >
          <div data-testid="settings-cache-body" />
        </CollapsibleSettingsSection>

        <CollapsibleSettingsSection
          sectionKey="scaling"
          testId="settings-scaling"
          title={t.sections.scaling}
        >
          <div data-testid="settings-scaling-body" />
        </CollapsibleSettingsSection>

        <CollapsibleSettingsSection
          sectionKey="observability"
          testId="settings-observability"
          title={t.sections.observabilityTuning}
        >
          <div data-testid="settings-observability-body" />
        </CollapsibleSettingsSection>
      </div>
    </>
  );
}
