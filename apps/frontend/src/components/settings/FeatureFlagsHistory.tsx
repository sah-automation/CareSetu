"use client";

// #800: feature flag history panel with loading/error/empty states and retry.

import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import type { FeatureFlagHistoryEntry } from "@/lib/operator/settings";

type FeatureFlagsStrings = OperatorSettingsStrings["featureFlags"];

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

function kindLabel(kind: string, t: FeatureFlagsStrings): string {
  return kind === "runtime" ? t.runtime : t.restartRequired;
}

function kindBadgeVariant(kind: string): "default" | "destructive" {
  return kind === "runtime" ? "default" : "destructive";
}

export function FeatureFlagsHistory({
  entries,
  t,
  status,
  errorMessage,
  onRetry,
}: {
  entries: FeatureFlagHistoryEntry[];
  t: FeatureFlagsStrings;
  status: "loading" | "ready" | "error";
  errorMessage: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="mt-5 border-t border-hairline pt-4"
      data-testid="settings-feature-flags-history"
    >
      <h3
        className="text-sm font-medium text-txt-sub"
        data-testid="settings-feature-flags-history-title"
      >
        {t.historyTitle}
      </h3>
      <p className="mt-0.5 text-xs text-txt-muted">{t.historyDescription}</p>

      {status === "loading" && (
        <div
          className="mt-2"
          data-testid="settings-feature-flags-history-loading"
        >
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="mt-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
          data-testid="settings-feature-flags-history-error"
        >
          <p className="text-sm text-danger">{errorMessage}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex min-h-9 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
            data-testid="settings-feature-flags-history-retry"
          >
            {t.historyRetry}
          </button>
        </div>
      )}

      {status === "ready" && entries.length === 0 && (
        <p
          className="mt-2 text-sm text-txt-muted"
          data-testid="settings-feature-flags-history-empty"
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
                  {t.flagKey}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.enabled}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t.type}
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
                  key={`${entry.flag_key}-${entry.version}`}
                  className="border-b border-hairline last:border-0"
                  data-testid={`settings-feature-flags-history-row-${entry.flag_key}-${entry.version}`}
                >
                  <th
                    scope="row"
                    className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                  >
                    {entry.flag_key}
                  </th>
                  <td className="py-2 pr-3 text-txt">
                    {entry.enabled ? t.toggleOn : t.toggleOff}
                  </td>
                  <td className="py-2 pr-3 text-txt">
                    <Badge
                      variant={kindBadgeVariant(entry.flag_kind)}
                      className="text-xs"
                    >
                      {kindLabel(entry.flag_kind, t)}
                    </Badge>
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
