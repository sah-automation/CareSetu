"use client";

import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchEffectiveSettings,
  fetchSettingHistory,
  writeSetting,
  type EffectiveSetting,
  type SettingHistoryEntry,
  type SettingSource,
  type SettingWriteValue,
} from "@/lib/operator/settings";
import { isSecretKey } from "@/lib/operator/config-filter";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { CollapsibleSettingsSection } from "./CollapsibleSettingsSection";

type SaveStatus = "idle" | "saving" | "saved" | "error";
type Draft = string | boolean;

function sourceLabel(
  source: SettingSource,
  t: OperatorSettingsStrings["ai"],
): string {
  switch (source) {
    case "database":
      return t.sources.database;
    case "environment":
      return t.sources.environment;
    case "default":
      return t.sources.default;
  }
}

function formatValue(value: unknown, t: OperatorSettingsStrings["ai"]): string {
  if (value === null || value === undefined) return t.notReturned;
  if (typeof value === "boolean") return value ? t.yes : t.no;
  if (Array.isArray(value)) {
    return value.length === 0
      ? t.emptyList
      : value.map((item) => formatValue(item, t)).join(", ");
  }
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

function isArraySetting(setting: EffectiveSetting): boolean {
  return Array.isArray(setting.value);
}

function isBooleanSetting(setting: EffectiveSetting): boolean {
  return (
    typeof setting.value === "boolean" ||
    setting.key.endsWith("_enabled") ||
    setting.key.endsWith(".enabled")
  );
}

function draftFor(
  setting: EffectiveSetting,
  drafts: Record<string, Draft>,
): Draft {
  const draft = drafts[setting.key];
  if (draft !== undefined) return draft;
  if (isBooleanSetting(setting)) return Boolean(setting.value);
  if (isArraySetting(setting)) {
    return Array.isArray(setting.value)
      ? setting.value.map(String).join(", ")
      : "";
  }
  return setting.value === null || setting.value === undefined
    ? ""
    : String(setting.value);
}

function buildWriteValue(
  setting: EffectiveSetting,
  raw: Draft,
): SettingWriteValue {
  if (isBooleanSetting(setting)) {
    return Boolean(raw);
  }
  if (isArraySetting(setting)) {
    const text = typeof raw === "string" ? raw : String(raw ?? "");
    return text
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return typeof raw === "string" ? raw.trim() : String(raw ?? "").trim();
}

type AiStrings = OperatorSettingsStrings["ai"];

function NotificationsSettingsTable({
  settings,
  t,
  drafts,
  saveStates,
  saveErrors,
  onDraft,
  onSave,
}: {
  settings: EffectiveSetting[];
  t: AiStrings;
  drafts: Record<string, Draft>;
  saveStates: Record<string, SaveStatus>;
  saveErrors: Record<string, string>;
  onDraft: (key: string, draft: Draft) => void;
  onSave: (setting: EffectiveSetting) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t.description}</caption>
        <thead>
          <tr className="border-b border-hairline text-xs text-txt-muted">
            <th scope="col" className="py-2 pr-3 font-medium">
              {t.key}
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              {t.value}
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              {t.source}
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              {t.restartRequired}
            </th>
            <th scope="col" className="py-2 font-medium">
              {t.actions}
            </th>
          </tr>
        </thead>
        <tbody>
          {settings.map((setting) => {
            const status = saveStates[setting.key] ?? "idle";
            const error = saveErrors[setting.key];
            const editable = setting.editable && !setting.restart_required;
            return (
              <tr
                key={setting.key}
                data-testid={`settings-notifications-row-${setting.key}`}
                className="border-b border-hairline align-top last:border-0"
              >
                <th
                  scope="row"
                  className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                >
                  {setting.key}
                </th>
                <td
                  className="py-2 pr-3 text-txt"
                  data-testid={`settings-notifications-value-${setting.key}`}
                >
                  {editable ? (
                    isBooleanSetting(setting) ? (
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-accent"
                        checked={Boolean(draftFor(setting, drafts))}
                        onChange={(event) =>
                          onDraft(setting.key, event.target.checked)
                        }
                        data-testid={`settings-notifications-input-${setting.key}`}
                      />
                    ) : isArraySetting(setting) ? (
                      <textarea
                        className="w-full min-w-[12rem] rounded-md border border-hairline px-2 py-1 text-sm text-txt"
                        value={String(draftFor(setting, drafts))}
                        onChange={(event) =>
                          onDraft(setting.key, event.target.value)
                        }
                        data-testid={`settings-notifications-input-${setting.key}`}
                      />
                    ) : (
                      <input
                        type="text"
                        className="w-full min-w-[12rem] rounded-md border border-hairline px-2 py-1 text-sm text-txt"
                        value={String(draftFor(setting, drafts))}
                        onChange={(event) =>
                          onDraft(setting.key, event.target.value)
                        }
                        data-testid={`settings-notifications-input-${setting.key}`}
                      />
                    )
                  ) : (
                    formatValue(setting.value, t)
                  )}
                </td>
                <td className="py-2 pr-3">
                  <Badge
                    variant="secondary"
                    data-testid={`settings-notifications-source-${setting.key}`}
                  >
                    {sourceLabel(setting.source, t)}
                  </Badge>
                </td>
                <td className="py-2 pr-3">
                  {setting.restart_required ? (
                    <Badge
                      variant="destructive"
                      data-testid={`settings-notifications-restart-${setting.key}`}
                    >
                      {t.restartRequired}
                    </Badge>
                  ) : (
                    <span
                      className="text-xs text-txt-muted"
                      data-testid={`settings-notifications-no-restart-${setting.key}`}
                    >
                      -
                    </span>
                  )}
                </td>
                <td className="py-2">
                  {editable ? (
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        disabled={status === "saving"}
                        onClick={() => onSave(setting)}
                        className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                        data-testid={`settings-notifications-save-${setting.key}`}
                      >
                        {status === "saving" ? t.saving : t.save}
                      </button>
                      {status === "saved" && (
                        <span
                          className="text-xs text-success"
                          data-testid={`settings-notifications-save-status-${setting.key}`}
                        >
                          {t.saved}
                        </span>
                      )}
                      {status === "error" && (
                        <span
                          role="alert"
                          className="text-xs text-danger"
                          data-testid={`settings-notifications-save-error-${setting.key}`}
                        >
                          {error}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span
                      className="text-xs text-txt-muted"
                      data-testid={`settings-notifications-readonly-${setting.key}`}
                    >
                      {t.readOnly}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NotificationsHistory({
  entries,
  t,
  status,
  errorMessage,
  onRetry,
}: {
  entries: SettingHistoryEntry[];
  t: AiStrings;
  status: "loading" | "ready" | "error";
  errorMessage: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="mt-5 border-t border-hairline pt-4"
      data-testid="settings-notifications-history"
    >
      <h3
        className="text-sm font-medium text-txt-sub"
        data-testid="settings-notifications-history-title"
      >
        {t.historyTitle}
      </h3>
      <p className="mt-0.5 text-xs text-txt-muted">{t.historyDescription}</p>

      {status === "loading" && (
        <div
          className="mt-2"
          data-testid="settings-notifications-history-loading"
        >
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="mt-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
          data-testid="settings-notifications-history-error"
        >
          <p className="text-sm text-danger">{errorMessage}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex min-h-9 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
            data-testid="settings-notifications-history-retry"
          >
            {t.historyRetry}
          </button>
        </div>
      )}

      {status === "ready" && entries.length === 0 && (
        <p
          className="mt-2 text-sm text-txt-muted"
          data-testid="settings-notifications-history-empty"
        >
          {t.historyEmpty}
        </p>
      )}

      {status === "ready" && entries.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-hairline text-xs text-txt-muted">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.key}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.value}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.historyVersion}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.historyChangedBy}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t.historyChangedAt}
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={`${entry.setting_key}-${entry.version}`}
                  className="border-b border-hairline last:border-0"
                  data-testid={`settings-notifications-history-row-${entry.setting_key}-${entry.version}`}
                >
                  <th
                    scope="row"
                    className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                  >
                    {entry.setting_key}
                  </th>
                  <td className="py-2 pr-3 text-txt">
                    {formatValue(entry.value, t)}
                  </td>
                  <td className="py-2 pr-3 text-txt">{entry.version}</td>
                  <td className="py-2 pr-3 text-txt">
                    {entry.changed_by ?? t.historyUnknownActor}
                  </td>
                  <td className="py-2 text-txt">
                    {formatTimestamp(entry.changed_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function NotificationsSettingsSection({
  t,
}: {
  t: OperatorSettingsStrings;
}) {
  const read = usePanelRead(() => fetchEffectiveSettings());
  const history = usePanelRead(() => fetchSettingHistory());
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saveStates, setSaveStates] = useState<Record<string, SaveStatus>>({});
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});

  const ai = t.ai as AiStrings;

  const notifications =
    read.data?.filter(
      (setting) =>
        setting.key.startsWith("notification.") && !isSecretKey(setting.key),
    ) ?? [];

  const notificationHistory =
    history.data?.filter(
      (entry) =>
        entry.setting_key.startsWith("notification.") &&
        !isSecretKey(entry.setting_key),
    ) ?? [];

  function handleDraft(key: string, draft: Draft) {
    setDrafts((current) => ({ ...current, [key]: draft }));
    setSaveStates((current) => ({ ...current, [key]: "idle" }));
    setSaveErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  async function handleSave(setting: EffectiveSetting) {
    setSaveErrors((current) => {
      if (!(setting.key in current)) return current;
      const next = { ...current };
      delete next[setting.key];
      return next;
    });

    const value = buildWriteValue(setting, draftFor(setting, drafts));
    setSaveStates((current) => ({ ...current, [setting.key]: "saving" }));
    try {
      await writeSetting(setting.key, value as SettingWriteValue);
      setSaveStates((current) => ({ ...current, [setting.key]: "saved" }));
      setDrafts((current) => {
        if (!(setting.key in current)) return current;
        const next = { ...current };
        delete next[setting.key];
        return next;
      });
      read.reload();
      history.reload();
    } catch (error) {
      setSaveStates((current) => ({ ...current, [setting.key]: "error" }));
      setSaveErrors((current) => ({
        ...current,
        [setting.key]:
          error instanceof ApiError
            ? error.message || t.notifications.errorExpected
            : t.notifications.saveError,
      }));
    }
  }

  return (
    <CollapsibleSettingsSection
      sectionKey="notifications"
      testId="settings-notifications"
      title={t.sections.notifications}
      description={t.notifications.description}
    >
      {read.status === "loading" && (
        <div data-testid="settings-notifications-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {read.status === "error" && (
        <div
          role="alert"
          data-testid="settings-notifications-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {read.error?.expected
              ? t.notifications.errorExpected
              : t.notifications.error}
          </p>
          {read.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid="settings-notifications-error-trace-id"
            >
              {t.ai.traceLabel}: {read.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid="settings-notifications-error-no-trace"
            >
              {t.ai.noTrace}
            </p>
          )}
          <button
            type="button"
            onClick={read.reload}
            data-testid="settings-notifications-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.retry}
          </button>
        </div>
      )}

      {read.status === "ready" && notifications.length === 0 && (
        <EmptyState title={t.ai.emptyTitle} body={t.ai.emptyBody} />
      )}

      {read.status === "ready" && notifications.length > 0 && (
        <>
          <p
            className="mb-2 text-xs text-txt-muted"
            data-testid="settings-notifications-takeaway"
          >
            {t.ai.takeaway(notifications.length)}
          </p>
          <NotificationsSettingsTable
            settings={notifications}
            t={ai}
            drafts={drafts}
            saveStates={saveStates}
            saveErrors={saveErrors}
            onDraft={handleDraft}
            onSave={(setting) => void handleSave(setting)}
          />
          <NotificationsHistory
            entries={notificationHistory}
            t={ai}
            status={history.status}
            errorMessage={
              history.error?.expected
                ? t.ai.historyErrorExpected
                : t.ai.historyError
            }
            onRetry={history.reload}
          />
        </>
      )}
    </CollapsibleSettingsSection>
  );
}
