"use client";

// #797: the read-only AI section of the admin Settings page. It reads the
// effective-settings endpoint and shows each value with where it came from and
// whether a restart is needed. Editable knobs and history arrive in #798.

import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchEffectiveSettings,
  type EffectiveSetting,
  type SettingSource,
} from "@/lib/operator/settings";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { SettingsSection } from "./SettingsSection";

type AiStrings = OperatorSettingsStrings["ai"];

function sourceLabel(source: SettingSource, t: AiStrings): string {
  switch (source) {
    case "database":
      return t.sources.database;
    case "environment":
      return t.sources.environment;
    case "default":
      return t.sources.default;
  }
}

function formatValue(value: unknown, t: AiStrings): string {
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

function AiSettingsTable({
  settings,
  t,
}: {
  settings: EffectiveSetting[];
  t: AiStrings;
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
            <th scope="col" className="py-2 font-medium">
              {t.restartRequired}
            </th>
          </tr>
        </thead>
        <tbody>
          {settings.map((setting) => (
            <tr
              key={setting.key}
              data-testid={`settings-ai-row-${setting.key}`}
              className="border-b border-hairline last:border-0"
            >
              <th
                scope="row"
                className="py-2 pr-3 font-mono text-xs font-normal text-txt"
              >
                {setting.key}
              </th>
              <td
                className="py-2 pr-3 text-txt"
                data-testid={`settings-ai-value-${setting.key}`}
              >
                {formatValue(setting.value, t)}
              </td>
              <td className="py-2 pr-3">
                <Badge
                  variant="secondary"
                  data-testid={`settings-ai-source-${setting.key}`}
                >
                  {sourceLabel(setting.source, t)}
                </Badge>
              </td>
              <td className="py-2">
                {setting.restart_required ? (
                  <Badge
                    variant="destructive"
                    data-testid={`settings-ai-restart-${setting.key}`}
                  >
                    {t.restartRequired}
                  </Badge>
                ) : (
                  <span
                    className="text-xs text-txt-muted"
                    data-testid={`settings-ai-no-restart-${setting.key}`}
                  >
                    -
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AiSettingsSection({ t }: { t: OperatorSettingsStrings }) {
  const read = usePanelRead(() => fetchEffectiveSettings());
  const ai =
    read.data?.filter((setting) => setting.key.startsWith("ai.")) ?? [];

  return (
    <SettingsSection
      testId="settings-ai"
      title={t.sections.ai}
      description={t.ai.description}
    >
      {read.status === "loading" && (
        <div data-testid="settings-ai-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {read.status === "error" && (
        <div
          role="alert"
          data-testid="settings-ai-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {read.error?.expected ? t.ai.errorExpected : t.ai.error}
          </p>
          {read.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid="settings-ai-error-trace-id"
            >
              {t.ai.traceLabel}: {read.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid="settings-ai-error-no-trace"
            >
              {t.ai.noTrace}
            </p>
          )}
          <button
            type="button"
            onClick={read.reload}
            data-testid="settings-ai-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.retry}
          </button>
        </div>
      )}

      {read.status === "ready" && ai.length === 0 && (
        <EmptyState title={t.ai.emptyTitle} body={t.ai.emptyBody} />
      )}

      {read.status === "ready" && ai.length > 0 && (
        <>
          <p
            className="mb-2 text-xs text-txt-muted"
            data-testid="settings-ai-takeaway"
          >
            {t.ai.takeaway(ai.length)}
          </p>
          <AiSettingsTable settings={ai} t={t.ai} />
        </>
      )}
    </SettingsSection>
  );
}
