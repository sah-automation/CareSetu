"use client";

// #801: the Users section of the admin Settings page.
// Lists all operators with masked phone, tier, active state, and MFA state.
// Allows inviting new operators, promoting/demoting tiers, and
// deactivating/reactivating operators. Self-changes and last-admin
// changes are refused with clear errors.

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchOperators,
  inviteOperator,
  updateOperatorTier,
  updateOperatorActive,
  type OperatorSummary,
} from "@/lib/operator/api";
import { usePanelRead } from "@/lib/operator/usePanelRead";
import type { AuditEventView } from "@/lib/audit/api";
import * as auditApi from "@/lib/audit/api";
import * as operatorApi from "@/lib/operator/api";

import { CollapsibleSettingsSection } from "./CollapsibleSettingsSection";

type UsersStrings = OperatorSettingsStrings["users"];
type SaveStatus = "idle" | "saving" | "saved" | "error";

function mfaLabel(enabled: boolean, t: UsersStrings): string {
  return enabled ? t.mfaEnabled : t.mfaDisabled;
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

function UsersHistory({
  entries,
  t,
  status,
  errorMessage,
  onRetry,
}: {
  entries: AuditEventView[];
  t: UsersStrings;
  status: "loading" | "ready" | "error";
  errorMessage: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="mt-5 border-t border-hairline pt-4"
      data-testid="settings-users-history"
    >
      <h3
        className="text-sm font-medium text-txt-sub"
        data-testid="settings-users-history-title"
      >
        {t.historyTitle}
      </h3>
      <p className="mt-0.5 text-xs text-txt-muted">{t.historyDescription}</p>

      {status === "loading" && (
        <div className="mt-2" data-testid="settings-users-history-loading">
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="mt-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
          data-testid="settings-users-history-error"
        >
          <p className="text-sm text-danger">{errorMessage}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex min-h-9 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
            data-testid="settings-users-history-retry"
          >
            {t.historyRetry}
          </button>
        </div>
      )}

      {status === "ready" && entries.length === 0 && (
        <p
          className="mt-2 text-sm text-txt-muted"
          data-testid="settings-users-history-empty"
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
                  {t.historyEvent}
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
                  key={entry.id}
                  className="border-b border-hairline last:border-0"
                  data-testid={`settings-users-history-row-${entry.id}`}
                >
                  <th
                    scope="row"
                    className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                  >
                    {entry.event_type}
                  </th>
                  <td className="py-2 pr-3 text-txt">
                    {entry.actor_id ?? t.historyUnknownActor}
                  </td>
                  <td className="py-2 text-txt">
                    {formatTimestamp(entry.timestamp)}
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

export function UsersSettingsSection({ t }: { t: OperatorSettingsStrings }) {
  const u = t.users;
  const operatorsRead = usePanelRead(() => fetchOperators());
  const historyRead = usePanelRead<AuditEventView[]>(() => {
    const auditResult = auditApi.fetchOperatorChangeHistory?.();
    if (
      auditResult &&
      typeof (auditResult as Promise<unknown>).then === "function"
    ) {
      return auditResult as Promise<AuditEventView[]>;
    }
    const operatorResult = operatorApi.fetchOperatorChangeHistory?.();
    if (
      operatorResult &&
      typeof (operatorResult as Promise<unknown>).then === "function"
    ) {
      return operatorResult as Promise<AuditEventView[]>;
    }
    return Promise.resolve([] as AuditEventView[]);
  });
  const [saveStates, setSaveStates] = useState<Record<number, SaveStatus>>({});
  const [saveErrors, setSaveErrors] = useState<Record<number, string>>({});
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [invitePhone, setInvitePhone] = useState("");
  const [inviteTier, setInviteTier] = useState<"admin" | "operator">(
    "operator",
  );
  const [inviteState, setInviteState] = useState<SaveStatus>("idle");
  const [inviteError, setInviteError] = useState<string | null>(null);

  async function handleTierSave(
    operator: OperatorSummary,
    newTier: "admin" | "operator",
  ) {
    setSaveErrors((current) => {
      if (!(operator.identity_id in current)) return current;
      const next = { ...current };
      delete next[operator.identity_id];
      return next;
    });

    const tier = newTier;

    setSaveStates((current) => ({
      ...current,
      [operator.identity_id]: "saving",
    }));
    try {
      await updateOperatorTier(operator.identity_id, { tier });
      setSaveStates((current) => ({
        ...current,
        [operator.identity_id]: "saved",
      }));
      operatorsRead.reload();
      historyRead.reload();
    } catch (error) {
      setSaveStates((current) => ({
        ...current,
        [operator.identity_id]: "error",
      }));
      setSaveErrors((current) => ({
        ...current,
        [operator.identity_id]:
          error instanceof ApiError
            ? error.message || t.users.editErrorExpected
            : t.users.editError,
      }));
    }
  }

  async function handleActiveSave(
    operator: OperatorSummary,
    isActive: boolean,
  ) {
    setSaveErrors((current) => {
      if (!(operator.identity_id in current)) return current;
      const next = { ...current };
      delete next[operator.identity_id];
      return next;
    });

    setSaveStates((current) => ({
      ...current,
      [operator.identity_id]: "saving",
    }));
    try {
      await updateOperatorActive(operator.identity_id, { is_active: isActive });
      setSaveStates((current) => ({
        ...current,
        [operator.identity_id]: "saved",
      }));
      operatorsRead.reload();
      historyRead.reload();
    } catch (error) {
      setSaveStates((current) => ({
        ...current,
        [operator.identity_id]: "error",
      }));
      setSaveErrors((current) => ({
        ...current,
        [operator.identity_id]:
          error instanceof ApiError
            ? error.message || t.users.editErrorExpected
            : t.users.editError,
      }));
    }
  }

  async function handleInvite() {
    setInviteError(null);
    setInviteState("saving");
    try {
      await inviteOperator({ phone: invitePhone, tier: inviteTier });
      setInviteState("saved");
      setInvitePhone("");
      setInviteTier("operator");
      operatorsRead.reload();
      historyRead.reload();
      setTimeout(() => {
        setShowInviteModal(false);
        setInviteState("idle");
      }, 1500);
    } catch (error) {
      setInviteState("error");
      setInviteError(
        error instanceof ApiError
          ? error.message || t.users.inviteErrorExpected
          : t.users.inviteError,
      );
    }
  }

  return (
    <CollapsibleSettingsSection
      sectionKey="users"
      testId="settings-users"
      title={t.sections.users}
      description={t.users.description}
    >
      <div className="flex items-center justify-between mb-4">
        <p
          className="text-xs text-txt-muted"
          data-testid="settings-users-takeaway"
        >
          {u.operatorCount(operatorsRead.data?.length ?? 0)}
        </p>
        <Button
          type="button"
          onClick={() => setShowInviteModal(true)}
          data-testid="settings-users-invite-button"
        >
          {t.users.inviteButton}
        </Button>
      </div>

      {operatorsRead.status === "loading" && (
        <div data-testid="settings-users-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {operatorsRead.status === "error" && (
        <div
          role="alert"
          data-testid="settings-users-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {operatorsRead.error?.expected
              ? t.users.editErrorExpected
              : t.users.editError}
          </p>
          {operatorsRead.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid="settings-users-error-trace-id"
            >
              {t.users.editErrorExpected}: {operatorsRead.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid="settings-users-error-no-trace"
            >
              {t.users.editError}
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={operatorsRead.reload}
            data-testid="settings-users-retry"
          >
            {t.retry}
          </Button>
        </div>
      )}

      {operatorsRead.status === "ready" && operatorsRead.data?.length === 0 && (
        <EmptyState title={t.users.emptyTitle} body={t.users.emptyBody} />
      )}

      {operatorsRead.status === "ready" &&
        operatorsRead.data &&
        operatorsRead.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t.users.description}</caption>
              <thead>
                <tr className="border-b border-hairline text-xs text-txt-muted">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.users.columns.phone}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.users.columns.tier}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.users.columns.active}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.users.columns.mfa}
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t.users.columns.created}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    {t.users.columns.actions}
                  </th>
                </tr>
              </thead>
              <tbody>
                {operatorsRead.data.map((operator) => {
                  const status = saveStates[operator.identity_id] ?? "idle";
                  const error = saveErrors[operator.identity_id];
                  const tier = operator.tier as "admin" | "operator";
                  const isActive = operator.is_active;
                  return (
                    <tr
                      key={operator.identity_id}
                      data-testid={`settings-users-row-${operator.identity_id}`}
                      className="border-b border-hairline align-top last:border-0"
                    >
                      <th
                        scope="row"
                        className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                      >
                        {operator.phone_masked}
                      </th>
                      <td className="py-2 pr-3">
                        <select
                          value={tier}
                          disabled={status === "saving"}
                          onChange={(e) =>
                            void handleTierSave(
                              operator,
                              e.target.value as "admin" | "operator",
                            )
                          }
                          className="text-sm border border-hairline rounded px-2 py-1 bg-surface focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          data-testid={`settings-users-tier-${operator.identity_id}`}
                        >
                          <option value="operator">{u.tierOperator}</option>
                          <option value="admin">{u.tierAdmin}</option>
                        </select>
                      </td>
                      <td className="py-2 pr-3">
                        <label className="inline-flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={isActive}
                            disabled={status === "saving"}
                            onChange={(e) =>
                              void handleActiveSave(operator, e.target.checked)
                            }
                            data-testid={`settings-users-active-${operator.identity_id}`}
                          />
                          <span className="text-xs text-txt-muted">
                            {isActive ? u.active : u.inactive}
                          </span>
                        </label>
                      </td>
                      <td className="py-2 pr-3">
                        <Badge
                          variant={
                            operator.mfa_enabled ? "default" : "secondary"
                          }
                          data-testid={`settings-users-mfa-${operator.identity_id}`}
                        >
                          {mfaLabel(operator.mfa_enabled, t.users)}
                        </Badge>
                      </td>
                      <td className="py-2 pr-3 text-xs text-txt-muted">
                        {new Date(operator.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-col gap-1">
                          {status === "saving" && (
                            <span
                              className="text-xs text-txt-muted"
                              data-testid={`settings-users-saving-${operator.identity_id}`}
                            >
                              {u.saving}
                            </span>
                          )}
                          {status === "saved" && (
                            <span
                              className="text-xs text-success"
                              data-testid={`settings-users-save-status-${operator.identity_id}`}
                            >
                              {u.saved}
                            </span>
                          )}
                          {status === "error" && (
                            <span
                              role="alert"
                              className="text-xs text-danger"
                              data-testid={`settings-users-save-error-${operator.identity_id}`}
                            >
                              {error}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

      <UsersHistory
        entries={(historyRead.data ?? []) as AuditEventView[]}
        t={u}
        status={historyRead.status}
        errorMessage={
          historyRead.error?.expected
            ? t.users.historyErrorExpected
            : t.users.historyError
        }
        onRetry={historyRead.reload}
      />

      {showInviteModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          data-testid="settings-users-invite-modal"
          onClick={() => setShowInviteModal(false)}
        >
          <div
            className="rounded-lg border border-hairline bg-surface p-4 w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-txt mb-4">
              {t.users.inviteTitle}
            </h3>
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="invite-phone"
                  className="block text-sm font-medium text-txt mb-1"
                >
                  {t.users.invitePhoneLabel}
                </label>
                <input
                  type="tel"
                  id="invite-phone"
                  value={invitePhone}
                  onChange={(e) => setInvitePhone(e.target.value)}
                  placeholder="9876543210"
                  className="w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  data-testid="settings-users-invite-phone-input"
                  disabled={inviteState === "saving"}
                />
              </div>
              <div>
                <label
                  htmlFor="invite-tier"
                  className="block text-sm font-medium text-txt mb-1"
                >
                  {t.users.inviteTierLabel}
                </label>
                <select
                  id="invite-tier"
                  value={inviteTier}
                  onChange={(e) =>
                    setInviteTier(e.target.value as "admin" | "operator")
                  }
                  className="w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  data-testid="settings-users-invite-tier-select"
                  disabled={inviteState === "saving"}
                >
                  <option value="operator">{u.tierOperator}</option>
                  <option value="admin">{u.tierAdmin}</option>
                </select>
              </div>
              {inviteError && (
                <p
                  role="alert"
                  className="text-sm text-danger"
                  data-testid="settings-users-invite-error"
                >
                  {inviteError}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowInviteModal(false)}
                  disabled={inviteState === "saving"}
                  data-testid="settings-users-invite-cancel"
                >
                  {t.users.cancel}
                </Button>
                <Button
                  type="button"
                  onClick={handleInvite}
                  disabled={inviteState === "saving" || !invitePhone.trim()}
                  data-testid="settings-users-invite-submit"
                >
                  {inviteState === "saving" ? u.saving : u.inviteButton}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </CollapsibleSettingsSection>
  );
}
