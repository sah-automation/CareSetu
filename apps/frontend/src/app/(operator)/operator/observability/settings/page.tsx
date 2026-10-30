"use client";

// #797: the admin-only Settings page. Four sections form the shell - AI,
// notifications, feature flags and users - with the AI section live and
// read-only in this ticket. Notification routing, feature flags and operator
// user management fill the other three in #799-#801.
// #796: admin-only - direct navigation renders a clear permission state for
// non-admin operators.

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { AiSettingsSection } from "@/components/settings/AiSettingsSection";
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

export default function ObservabilitySettingsPage() {
  const auth = useAuthOrNull();
  const { lang } = useLang();
  const t = STRINGS[lang].operatorSettings;
  const isAdmin =
    auth?.user?.roles?.includes("operator") === true &&
    auth?.user?.tier === "admin";

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

        <NotificationsSettingsSection t={t} />

        <FeatureFlagsSettingsSection t={t} />

        <UsersSettingsSection t={t} />
      </div>
    </>
  );
}
