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
import { NotificationsSettingsSection } from "@/components/settings/NotificationsSettingsSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
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

function SettingsPlaceholder({
  testId,
  title,
  description,
  body,
}: {
  testId: string;
  title: string;
  description: string;
  body: string;
}) {
  return (
    <SettingsSection testId={testId} title={title} description={description}>
      <p className="text-sm text-txt-muted">{body}</p>
    </SettingsSection>
  );
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

        <SettingsPlaceholder
          testId="settings-feature-flags"
          title={t.sections.featureFlags}
          description={t.featureFlags.description}
          body={t.featureFlags.body}
        />

        <SettingsPlaceholder
          testId="settings-users"
          title={t.sections.users}
          description={t.users.description}
          body={t.users.body}
        />
      </div>
    </>
  );
}
