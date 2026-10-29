"use client";

// #800: feature flags table with editable runtime flags and read-only restart-required flags.

import { Badge } from "@/components/ui/badge";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import type { FeatureFlag } from "@/lib/operator/settings";

type FeatureFlagsStrings = OperatorSettingsStrings["featureFlags"];
type SaveStatus = "idle" | "saving" | "saved" | "error";

function kindLabel(kind: string, t: FeatureFlagsStrings): string {
  return kind === "runtime" ? t.runtime : t.restartRequired;
}

function kindBadgeVariant(kind: string): "default" | "destructive" {
  return kind === "runtime" ? "default" : "destructive";
}

export function FeatureFlagsTable({
  flags,
  t,
  drafts,
  saveStates,
  saveErrors,
  onDraft,
  onSave,
}: {
  flags: FeatureFlag[];
  t: FeatureFlagsStrings;
  drafts: Record<string, boolean>;
  saveStates: Record<string, SaveStatus>;
  saveErrors: Record<string, string>;
  onDraft: (key: string, enabled: boolean) => void;
  onSave: (flag: FeatureFlag) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t.description}</caption>
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
              {t.descriptionLabel}
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              {t.lastUpdated}
            </th>
            <th scope="col" className="py-2 font-medium">
              {t.actions}
            </th>
          </tr>
        </thead>
        <tbody>
          {flags.map((flag) => {
            const status = saveStates[flag.flag_key] ?? "idle";
            const error = saveErrors[flag.flag_key];
            const draft = drafts[flag.flag_key] ?? flag.enabled;
            return (
              <tr
                key={flag.flag_key}
                data-testid={`settings-feature-flags-row-${flag.flag_key}`}
                className="border-b border-hairline align-top last:border-0"
              >
                <th
                  scope="row"
                  className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                >
                  {flag.flag_key}
                </th>
                <td
                  className="py-2 pr-3 text-txt"
                  data-testid={`settings-feature-flags-enabled-${flag.flag_key}`}
                >
                  {flag.editable ? (
                    <label className="inline-flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-accent"
                        checked={draft}
                        onChange={(event) =>
                          onDraft(flag.flag_key, event.target.checked)
                        }
                        data-testid={`settings-feature-flags-input-${flag.flag_key}`}
                      />
                      <span className="text-sm text-txt-sub">
                        {draft ? t.toggleOn : t.toggleOff}
                      </span>
                    </label>
                  ) : (
                    <span className="text-sm text-txt-sub">
                      {flag.enabled ? t.toggleOn : t.toggleOff}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <Badge
                    variant={kindBadgeVariant(flag.flag_kind)}
                    data-testid={`settings-feature-flags-type-${flag.flag_key}`}
                  >
                    {kindLabel(flag.flag_kind, t)}
                  </Badge>
                </td>
                <td className="py-2 pr-3 text-txt-sub">
                  {flag.description ?? "-"}
                </td>
                <td className="py-2 pr-3 text-xs text-txt-muted">
                  {flag.updated_at}
                </td>
                <td className="py-2">
                  {flag.editable ? (
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        disabled={status === "saving"}
                        onClick={() => onSave(flag)}
                        className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                        data-testid={`settings-feature-flags-save-${flag.flag_key}`}
                      >
                        {status === "saving" ? t.saving : t.save}
                      </button>
                      {status === "saved" && (
                        <span
                          className="text-xs text-success"
                          data-testid={`settings-feature-flags-save-status-${flag.flag_key}`}
                        >
                          {t.saved}
                        </span>
                      )}
                      {status === "error" && (
                        <span
                          role="alert"
                          className="text-xs text-danger"
                          data-testid={`settings-feature-flags-save-error-${flag.flag_key}`}
                        >
                          {error}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <span
                        className="text-xs text-txt-muted"
                        data-testid={`settings-feature-flags-readonly-${flag.flag_key}`}
                      >
                        {t.readOnly}
                      </span>
                      <span
                        className="text-xs text-txt-muted"
                        data-testid={`settings-feature-flags-restart-explanation-${flag.flag_key}`}
                      >
                        {t.restartExplanation}
                      </span>
                    </div>
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
