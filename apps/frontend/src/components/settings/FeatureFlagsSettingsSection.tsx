"use client";

// #800: the Feature Flags section of the admin Settings page.
// Lists all flags with their type. Runtime flags are editable toggles.
// Restart-required flags are read-only with an explanation.
// History is visible for all flags.

import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchFeatureFlags,
  fetchFeatureFlagHistory,
  writeFeatureFlag,
  type FeatureFlag,
  type FeatureFlagHistoryEntry,
} from "@/lib/operator/settings";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { FeatureFlagsHistory } from "./FeatureFlagsHistory";
import { FeatureFlagsTable } from "./FeatureFlagsTable";
import { SettingsSection } from "./SettingsSection";

type FeatureFlagsStrings = OperatorSettingsStrings["featureFlags"];
type SaveStatus = "idle" | "saving" | "saved" | "error";

export function FeatureFlagsSettingsSection({
  t,
}: {
  t: OperatorSettingsStrings;
}) {
  const flagsRead = usePanelRead(() => fetchFeatureFlags());
  const historyRead = usePanelRead(() => fetchFeatureFlagHistory());
  const [drafts, setDrafts] = useState<Record<string, boolean>>({});
  const [saveStates, setSaveStates] = useState<Record<string, SaveStatus>>({});
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});

  function handleDraft(key: string, enabled: boolean) {
    setDrafts((current) => ({ ...current, [key]: enabled }));
    setSaveStates((current) => ({ ...current, [key]: "idle" }));
    setSaveErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  async function handleSave(flag: FeatureFlag) {
    setSaveErrors((current) => {
      if (!(flag.flag_key in current)) return current;
      const next = { ...current };
      delete next[flag.flag_key];
      return next;
    });

    const enabled = drafts[flag.flag_key] ?? flag.enabled;

    setSaveStates((current) => ({ ...current, [flag.flag_key]: "saving" }));
    try {
      await writeFeatureFlag(flag.flag_key, enabled);
      setSaveStates((current) => ({ ...current, [flag.flag_key]: "saved" }));
      setDrafts((current) => {
        if (!(flag.flag_key in current)) return current;
        const next = { ...current };
        delete next[flag.flag_key];
        return next;
      });
      flagsRead.reload();
      historyRead.reload();
    } catch (error) {
      setSaveStates((current) => ({ ...current, [flag.flag_key]: "error" }));
      setSaveErrors((current) => ({
        ...current,
        [flag.flag_key]:
          error instanceof ApiError
            ? error.message || t.featureFlags.editErrorExpected
            : t.featureFlags.editError,
      }));
    }
  }

  return (
    <SettingsSection
      testId="settings-feature-flags"
      title={t.sections.featureFlags}
      description={t.featureFlags.description}
    >
      {flagsRead.status === "loading" && (
        <div data-testid="settings-feature-flags-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {flagsRead.status === "error" && (
        <div
          role="alert"
          data-testid="settings-feature-flags-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {flagsRead.error?.expected
              ? t.featureFlags.editErrorExpected
              : t.featureFlags.editError}
          </p>
          {flagsRead.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid="settings-feature-flags-error-trace-id"
            >
              {t.featureFlags.editErrorExpected}: {flagsRead.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid="settings-feature-flags-error-no-trace"
            >
              {t.featureFlags.editError}
            </p>
          )}
          <button
            type="button"
            onClick={flagsRead.reload}
            data-testid="settings-feature-flags-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.retry}
          </button>
        </div>
      )}

      {flagsRead.status === "ready" && flagsRead.data?.length === 0 && (
        <EmptyState title={t.featureFlags.title} body={t.featureFlags.body} />
      )}

      {flagsRead.status === "ready" &&
        flagsRead.data &&
        flagsRead.data.length > 0 && (
          <>
            <p
              className="mb-2 text-xs text-txt-muted"
              data-testid="settings-feature-flags-takeaway"
            >
              {flagsRead.data.length} {t.featureFlags.title.toLowerCase()}
            </p>
            <FeatureFlagsTable
              flags={flagsRead.data}
              t={t.featureFlags}
              drafts={drafts}
              saveStates={saveStates}
              saveErrors={saveErrors}
              onDraft={handleDraft}
              onSave={handleSave}
            />
            <FeatureFlagsHistory
              entries={historyRead.data ?? []}
              t={t.featureFlags}
              status={historyRead.status}
              errorMessage={
                historyRead.error?.expected
                  ? t.featureFlags.historyErrorExpected
                  : t.featureFlags.historyError
              }
              onRetry={historyRead.reload}
            />
          </>
        )}
    </SettingsSection>
  );
}
