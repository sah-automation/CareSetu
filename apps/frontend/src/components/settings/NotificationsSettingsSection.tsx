"use client";

// #799: the Notifications section of the admin Settings page.
// Routing matrix, recipients, channel toggles, test send, recent deliveries, redelivery.

import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchEffectiveSettings,
  writeSetting,
  fetchAlertDeliveries,
  testAlertDelivery,
  redeliverAlertDelivery,
  type EffectiveSetting,
  type AlertDeliveryRow,
  type AlertDeliveryPage,
} from "@/lib/operator/settings";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { SettingsSection } from "./SettingsSection";

type NotificationsStrings = OperatorSettingsStrings["notifications"];
type SaveStatus = "idle" | "saving" | "saved" | "error";
type TestStatus = "idle" | "testing" | "success" | "error";
type RedeliverStatus = "idle" | "redelivering" | "success" | "error";

const ALERT_KINDS = [
  "ai_budget",
  "provider_health_drop",
  "breaker_open",
  "outbox_backlog",
  "outbox_dead_letter",
  "queue_age",
  "cost_outlier",
  "error_rate_high",
  "provider_rate_limited",
  "latency_objective_breach",
  "audit_tamper",
  "ai_egress",
  "auth_failure_high",
  "operator_mfa_failure_high",
  "record_denial_high",
  "rate_limit_high",
  "prompt_injection_high",
  "otp_lockout",
  "operator_mfa_lockout",
  "consent_revocation",
  "webhook_signature_failure",
] as const;

const CHANNELS = ["slack", "email", "none"] as const;

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function statusBadge(
  status: string,
  t: NotificationsStrings["recentDeliveries"]["status"],
) {
  const variant =
    status === "delivered"
      ? "default"
      : status === "failed" || status === "dead_letter"
        ? "destructive"
        : status === "in_progress"
          ? "secondary"
          : "outline";
  // Convert snake_case to camelCase for i18n key lookup
  const i18nKey = status.replace(/_([a-z])/g, (_, letter) =>
    letter.toUpperCase(),
  );
  return (
    <Badge variant={variant} className="text-xs">
      {t[i18nKey as keyof typeof t] ?? status}
    </Badge>
  );
}

function ChannelToggle({
  channel,
  enabled,
  onChange,
  testStatus,
  testError,
  onTest,
  t,
}: {
  channel: "slack" | "email";
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  testStatus: TestStatus;
  testError: string;
  onTest: () => void;
  t: NotificationsStrings["channels"][typeof channel];
}) {
  // Allow test send even when channel is disabled (to verify config)
  const disabled = testStatus === "testing";

  return (
    <div className="space-y-2 p-4 rounded-lg border border-hairline">
      <div className="flex items-center justify-between">
        <span className="font-medium text-txt">{t.label}</span>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 accent-accent"
            data-testid={`settings-notifications-channel-${channel}-enabled`}
          />
          <span className="text-sm text-txt-sub">
            {enabled ? t.enabled : t.disabled}
          </span>
        </label>
      </div>

      {!enabled && <p className="text-xs text-txt-muted">{t.notConfigured}</p>}

      <button
        type="button"
        disabled={disabled}
        onClick={onTest}
        className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
        data-testid={`settings-notifications-channel-${channel}-test`}
      >
        {testStatus === "testing" ? t.testing : t.testSend}
      </button>

      {testStatus === "success" && (
        <p
          className="text-xs text-success"
          data-testid={`settings-notifications-channel-${channel}-test-success`}
        >
          {t.testSuccess}
        </p>
      )}

      {testStatus === "error" && (
        <p
          className="text-xs text-danger"
          data-testid={`settings-notifications-channel-${channel}-test-error`}
        >
          {t.testFailed.replace("{error}", testError)}
        </p>
      )}
    </div>
  );
}

function RoutingMatrix({
  settings,
  t,
  drafts,
  onDraft,
}: {
  settings: EffectiveSetting[];
  t: NotificationsStrings["routing"];
  drafts: Record<string, string>;
  onDraft: (key: string, value: string) => void;
}) {
  const routingSettings = settings.filter((s) =>
    s.key.startsWith("notification.routing."),
  );

  // Parse comma-separated channels from current value
  function parseChannels(value: string): string[] {
    return value
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);
  }

  // Format channels array to comma-separated string
  function formatChannels(channels: string[]): string {
    return channels.join(",");
  }

  return (
    <div className="space-y-4">
      <h4 className="text-sm font-medium text-txt">{t.title}</h4>
      <p className="text-xs text-txt-muted">{t.description}</p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline text-xs text-txt-muted">
              <th scope="col" className="py-2 pr-3 font-medium w-1/3">
                {t.alertKind}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {t.channels}
              </th>
            </tr>
          </thead>
          <tbody>
            {ALERT_KINDS.map((kind) => {
              const setting = routingSettings.find(
                (s) => s.key === `notification.routing.${kind}`,
              );
              const currentValue = setting?.value
                ? String(setting.value)
                : "none";
              const draft =
                drafts[`notification.routing.${kind}`] ?? currentValue;
              const selectedChannels = parseChannels(draft);

              return (
                <tr
                  key={kind}
                  className="border-b border-hairline last:border-0"
                  data-testid={`settings-notifications-routing-${kind}`}
                >
                  <th
                    scope="row"
                    className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                  >
                    {kind}
                  </th>
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap gap-2">
                      {CHANNELS.filter((c) => c !== "none").map((channel) => (
                        <label
                          key={channel}
                          className="inline-flex items-center gap-1.5 cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={selectedChannels.includes(channel)}
                            onChange={(e) => {
                              const newChannels = e.target.checked
                                ? [...selectedChannels, channel]
                                : selectedChannels.filter((c) => c !== channel);
                              onDraft(
                                `notification.routing.${kind}`,
                                formatChannels(newChannels),
                              );
                            }}
                            className="h-4 w-4 accent-accent"
                            data-testid={`settings-notifications-routing-${kind}-${channel}`}
                          />
                          <span className="text-sm text-txt-sub">
                            {t[channel as keyof typeof t]}
                          </span>
                        </label>
                      ))}
                      {selectedChannels.length === 0 && (
                        <span className="text-xs text-txt-muted">{t.none}</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmailRecipients({
  setting,
  draft,
  saveStatus,
  saveError,
  onDraft,
  onSave,
  t,
}: {
  setting: EffectiveSetting | undefined;
  draft: string;
  saveStatus: SaveStatus;
  saveError: string;
  onDraft: (value: string) => void;
  onSave: () => void;
  t: NotificationsStrings["recipients"];
}) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-txt">{t.title}</h4>
      <p className="text-xs text-txt-muted">{t.description}</p>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <input
          type="text"
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          placeholder={t.placeholder}
          className="flex-1 min-w-0 rounded-md border border-hairline px-3 py-2 text-sm text-txt"
          data-testid="settings-notifications-recipients-input"
        />
        <button
          type="button"
          disabled={saveStatus === "saving"}
          onClick={onSave}
          className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
          data-testid="settings-notifications-recipients-save"
        >
          {saveStatus === "saving" ? t.saving : t.save}
        </button>
      </div>

      {saveStatus === "saved" && (
        <p
          className="text-xs text-success"
          data-testid="settings-notifications-recipients-saved"
        >
          {t.saved}
        </p>
      )}

      {saveStatus === "error" && (
        <p
          className="text-xs text-danger"
          data-testid="settings-notifications-recipients-error"
        >
          {saveError}
        </p>
      )}
    </div>
  );
}

function RecentDeliveries({
  deliveries,
  t,
  redeliverStatus,
  onRedeliver,
  page,
  totalCount,
  pageSize,
  onPageChange,
}: {
  deliveries: AlertDeliveryPage | undefined | null;
  t: NotificationsStrings["recentDeliveries"];
  redeliverStatus: Record<number, RedeliverStatus>;
  onRedeliver: (deliveryId: number) => void;
  page: number;
  totalCount: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const rows = deliveries?.deliveries ?? [];
  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div className="space-y-4">
      <h4 className="text-sm font-medium text-txt">{t.title}</h4>
      <p className="text-xs text-txt-muted">{t.description}</p>

      {rows.length === 0 ? (
        <EmptyState title={t.empty} body="" />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-hairline text-xs text-txt-muted">
                  <th scope="col" className="py-2 pr-3 font-medium w-16">
                    {t.columns.id}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.columns.alertKind}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium w-24">
                    {t.columns.channel}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium w-28">
                    {t.columns.status}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium w-16">
                    {t.columns.attempts}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.columns.lastAttempt}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    {t.columns.actions}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((delivery) => {
                  const status = redeliverStatus[delivery.id] ?? "idle";
                  const canRedeliver =
                    delivery.status === "failed" ||
                    delivery.status === "dead_letter";

                  return (
                    <tr
                      key={delivery.id}
                      className="border-b border-hairline last:border-0"
                      data-testid={`settings-notifications-delivery-${delivery.id}`}
                    >
                      <td className="py-2 pr-3 font-mono text-xs text-txt">
                        {delivery.id}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs text-txt">
                        {delivery.alert_id.slice(0, 8)}...
                      </td>
                      <td className="py-2 pr-3 text-txt-sub">
                        {delivery.channel}
                      </td>
                      <td className="py-2 pr-3">
                        {statusBadge(delivery.status, t.status)}
                      </td>
                      <td className="py-2 pr-3 text-txt">
                        {delivery.attempts}
                      </td>
                      <td className="py-2 pr-3 text-xs text-txt-muted">
                        {delivery.last_attempt_at
                          ? formatTimestamp(delivery.last_attempt_at)
                          : "-"}
                      </td>
                      <td className="py-2">
                        {canRedeliver && (
                          <button
                            type="button"
                            disabled={status === "redelivering"}
                            onClick={() => onRedeliver(delivery.id)}
                            className="inline-flex min-h-8 items-center rounded-md border border-danger-border px-2 text-xs font-medium text-danger hover:bg-danger-soft/60 disabled:opacity-50"
                            data-testid={`settings-notifications-delivery-${delivery.id}-redeliver`}
                          >
                            {status === "redelivering"
                              ? t.redelivering
                              : t.redeliver}
                          </button>
                        )}
                        {status === "success" && (
                          <span
                            className="text-xs text-success"
                            data-testid={`settings-notifications-delivery-${delivery.id}-redeliver-success`}
                          >
                            {t.redeliverSuccess}
                          </span>
                        )}
                        {status === "error" && (
                          <span
                            className="text-xs text-danger"
                            data-testid={`settings-notifications-delivery-${delivery.id}-redeliver-error`}
                          >
                            {t.redeliverFailed}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-xs text-txt-muted">
              <span>
                Page {page} of {totalPages} ({totalCount} total)
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page === 1}
                  onClick={() => onPageChange(page - 1)}
                  className="inline-flex min-h-8 items-center rounded-md border border-hairline px-2 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={page === totalPages}
                  onClick={() => onPageChange(page + 1)}
                  className="inline-flex min-h-8 items-center rounded-md border border-hairline px-2 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function NotificationsSettingsSection({
  t,
}: {
  t: OperatorSettingsStrings;
}) {
  const settingsRead = usePanelRead(() => fetchEffectiveSettings());
  const deliveriesRead = usePanelRead(() =>
    fetchAlertDeliveries(deliveryPage, 25),
  );

  const [routingDrafts, setRoutingDrafts] = useState<Record<string, string>>(
    {},
  );
  const [recipientsDraft, setRecipientsDraft] = useState("");
  const [saveStates, setSaveStates] = useState<Record<string, SaveStatus>>({});
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});
  const [testStatuses, setTestStatuses] = useState<
    Record<"slack" | "email", TestStatus>
  >({
    slack: "idle",
    email: "idle",
  });
  const [testErrors, setTestErrors] = useState<
    Record<"slack" | "email", string>
  >({
    slack: "",
    email: "",
  });
  const [redeliverStatuses, setRedeliverStatuses] = useState<
    Record<number, RedeliverStatus>
  >({});
  const [deliveryPage, setDeliveryPage] = useState(1);

  const notificationSettings =
    settingsRead.data?.filter((s) => s.key.startsWith("notification.")) ?? [];

  const routingSetting = notificationSettings.find((s) =>
    s.key.startsWith("notification.routing."),
  );
  const recipientsSetting = notificationSettings.find(
    (s) => s.key === "notification.email.recipients",
  );
  const slackEnabledSetting = notificationSettings.find(
    (s) => s.key === "notification.channels.slack.enabled",
  );
  const emailEnabledSetting = notificationSettings.find(
    (s) => s.key === "notification.channels.email.enabled",
  );

  function handleRoutingDraft(key: string, value: string) {
    setRoutingDrafts((current) => ({ ...current, [key]: value }));
    setSaveStates((current) => ({ ...current, [key]: "idle" }));
    setSaveErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function handleRecipientsDraft(value: string) {
    setRecipientsDraft(value);
    setSaveStates((current) => ({
      ...current,
      ["notification.email.recipients"]: "idle",
    }));
    setSaveErrors((current) => {
      if (!("notification.email.recipients" in current)) return current;
      const next = { ...current };
      delete next["notification.email.recipients"];
      return next;
    });
  }

  async function handleSave(key: string, value: unknown) {
    setSaveErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });

    setSaveStates((current) => ({ ...current, [key]: "saving" }));
    try {
      await writeSetting(
        key,
        value as string | number | boolean | string[] | null,
      );
      setSaveStates((current) => ({ ...current, [key]: "saved" }));
      if (key.startsWith("notification.routing.")) {
        setRoutingDrafts((current) => {
          if (!(key in current)) return current;
          const next = { ...current };
          delete next[key];
          return next;
        });
      } else if (key === "notification.email.recipients") {
        setRecipientsDraft("");
      }
      settingsRead.reload();
    } catch (error) {
      setSaveStates((current) => ({ ...current, [key]: "error" }));
      setSaveErrors((current) => ({
        ...current,
        [key]:
          error instanceof ApiError
            ? error.message || t.notifications.errorExpected
            : t.notifications.saveError,
      }));
    }
  }

  async function handleTestSend(channel: "slack" | "email") {
    setTestStatuses((current) => ({ ...current, [channel]: "testing" }));
    setTestErrors((current) => ({ ...current, [channel]: "" }));
    try {
      const result = await testAlertDelivery(channel);
      setTestStatuses((current) => ({
        ...current,
        [channel]: result.success ? "success" : "error",
      }));
      if (!result.success && result.error) {
        setTestErrors((current) => ({ ...current, [channel]: result.error }));
      }
    } catch (error) {
      setTestStatuses((current) => ({ ...current, [channel]: "error" }));
      setTestErrors((current) => ({
        ...current,
        [channel]:
          error instanceof ApiError ? error.message : t.notifications.error,
      }));
    }
  }

  async function handleRedeliver(deliveryId: number) {
    setRedeliverStatuses((current) => ({
      ...current,
      [deliveryId]: "redelivering",
    }));
    try {
      const result = await redeliverAlertDelivery(deliveryId);
      setRedeliverStatuses((current) => ({
        ...current,
        [deliveryId]: result.success ? "success" : "error",
      }));
      if (result.success) {
        deliveriesRead.reload();
      }
    } catch {
      setRedeliverStatuses((current) => ({
        ...current,
        [deliveryId]: "error",
      }));
    }
  }

  const slackEnabled = slackEnabledSetting?.value === true;
  const emailEnabled = emailEnabledSetting?.value === true;

  const recipientsValue = recipientsSetting?.value;
  const recipientsDraftValue =
    recipientsDraft ||
    (Array.isArray(recipientsValue) ? recipientsValue.join(", ") : "");

  return (
    <SettingsSection
      testId="settings-notifications"
      title={t.sections.notifications}
      description={t.notifications.description}
    >
      {settingsRead.status === "loading" && (
        <div data-testid="settings-notifications-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {settingsRead.status === "error" && (
        <div
          role="alert"
          data-testid="settings-notifications-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {settingsRead.error?.expected
              ? t.notifications.errorExpected
              : t.notifications.error}
          </p>
          <button
            type="button"
            onClick={settingsRead.reload}
            data-testid="settings-notifications-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.notifications.retry}
          </button>
        </div>
      )}

      {settingsRead.status === "ready" && notificationSettings.length === 0 && (
        <EmptyState title={t.notifications.body} body="" />
      )}

      {settingsRead.status === "ready" && notificationSettings.length > 0 && (
        <div className="space-y-6">
          <RoutingMatrix
            settings={notificationSettings}
            t={t.notifications.routing}
            drafts={routingDrafts}
            onDraft={handleRoutingDraft}
          />

          <div className="pt-4 border-t border-hairline">
            <EmailRecipients
              setting={recipientsSetting}
              draft={recipientsDraftValue}
              saveStatus={saveStates["notification.email.recipients"] ?? "idle"}
              saveError={saveErrors["notification.email.recipients"] ?? ""}
              onDraft={handleRecipientsDraft}
              onSave={() =>
                handleSave(
                  "notification.email.recipients",
                  recipientsDraftValue
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                )
              }
              t={t.notifications.recipients}
            />
          </div>

          <div className="pt-4 border-t border-hairline grid gap-4 sm:grid-cols-2">
            <ChannelToggle
              channel="slack"
              enabled={slackEnabled}
              onChange={(enabled) =>
                handleSave("notification.channels.slack.enabled", enabled)
              }
              testStatus={testStatuses.slack}
              testError={testErrors.slack}
              onTest={() => handleTestSend("slack")}
              t={t.notifications.channels.slack}
            />
            <ChannelToggle
              channel="email"
              enabled={emailEnabled}
              onChange={(enabled) =>
                handleSave("notification.channels.email.enabled", enabled)
              }
              testStatus={testStatuses.email}
              testError={testErrors.email}
              onTest={() => handleTestSend("email")}
              t={t.notifications.channels.email}
            />
          </div>

          <div className="pt-4 border-t border-hairline">
            <RecentDeliveries
              deliveries={deliveriesRead.data}
              t={t.notifications.recentDeliveries}
              redeliverStatus={redeliverStatuses}
              onRedeliver={handleRedeliver}
              page={deliveryPage}
              totalCount={deliveriesRead.data?.total_count ?? 0}
              pageSize={25}
              onPageChange={setDeliveryPage}
            />
          </div>
        </div>
      )}
    </SettingsSection>
  );
}
