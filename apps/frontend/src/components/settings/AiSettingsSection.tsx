"use client";

// #924: the catalog-driven "AI & LLM" section of the operator Settings page.
// The section renders selects populated from the AI provider catalog endpoint,
// with per-provider dependent model / ASR-model filtering, a marked "custom
// model name" free-text escape hatch on the model selects, fallback
// provider / model selects, a pricing-table textarea (one `model:price_in:
// price_out` entry per line) with a USD-per-1M price preview alongside the
// stored paise unit, and the provider's auto-derived base URL shown read-only.
// Writes go through the settings client's string-value write support
// (`writeSetting`). Non-admin operators see every control read-only.

import React, { useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import type { OperatorSettingsStrings } from "@/lib/i18n/dictionaries";
import {
  fetchAiProviderCatalog,
  fetchEffectiveSettings,
  fetchSettingHistory,
  writeSetting,
  type AiProviderCatalogEntry,
  type EffectiveSetting,
  type SettingHistoryEntry,
  type SettingSource,
  type SettingWriteValue,
} from "@/lib/operator/settings";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { CollapsibleSettingsSection } from "./CollapsibleSettingsSection";

type AiStrings = OperatorSettingsStrings["ai"];
type SaveStatus = "idle" | "saving" | "saved" | "error";

// ~₹88.5/USD (#917): FX rate for the USD-per-1M price preview, from config.
// USD per 1M tokens = paise-per-token * 1e6 / PAISE_PER_USD.
const PAISE_PER_USD =
  Number(process.env.NEXT_PUBLIC_PAISE_PER_USD ?? "8850") || 8850;

const AI_FIELD_KEYS = [
  "ai.provider",
  "ai.model",
  "ai.asr_model",
  "ai.fallback_provider",
  "ai.fallback_model",
  "ai.pricing_table",
] as const;
type AiFieldKey = (typeof AI_FIELD_KEYS)[number];

// #930: the shared surfaced frame for standalone rows and grouped blocks -
// the block adds the row padding inside, the card rows add it here.
const CARD_FRAME = "mt-4 rounded-lg border border-hairline bg-surface";

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

function dashboardDate(value: string): string {
  const match = value.match(/set (.+)$/);
  if (!match) return "";
  try {
    return new Date(match[1]).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return match[1];
  }
}

// #930: the one source->key-state mapping, shared by the status label and
// the input's visibility, so a new source cannot desync the two.
type ApiKeyState = "env" | "dashboard" | "missing";

function apiKeyState(source: SettingSource | undefined): ApiKeyState {
  if (source === "environment") return "env";
  if (source === "database") return "dashboard";
  return "missing";
}

function apiKeyStatusLabel(
  value: unknown,
  source: SettingSource | undefined,
  t: AiStrings,
): string {
  const state = apiKeyState(source);
  if (state === "env") return t.keyFromEnv;
  if (state === "dashboard") {
    const v = value === null || value === undefined ? "" : String(value);
    const date = dashboardDate(v);
    return date ? `${t.keyFromDashboard}, set ${date}` : t.keyFromDashboard;
  }
  return t.keyMissing;
}

function usdPer1M(paisePerToken: number): string {
  const usd = (paisePerToken * 1_000_000) / PAISE_PER_USD;
  return usd.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

interface ParsedPrice {
  model: string;
  priceIn: number;
  priceOut: number;
  usdIn: string;
  usdOut: string;
  valid: boolean;
  error?: string;
}

function parsePricingTable(text: string | undefined): ParsedPrice[] {
  const rows: ParsedPrice[] = [];
  const value = text ?? "";
  for (const rawLine of value.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const parts = line.split(":");
    if (parts.length !== 3 || !parts[0]) {
      rows.push({
        model: line,
        priceIn: NaN,
        priceOut: NaN,
        usdIn: "",
        usdOut: "",
        valid: false,
        error: "expected 'model:price_in:price_out'",
      });
      continue;
    }
    const [model, inRaw, outRaw] = parts;
    const priceIn = Number(inRaw.trim());
    const priceOut = Number(outRaw.trim());
    if (
      !Number.isFinite(priceIn) ||
      !Number.isFinite(priceOut) ||
      priceIn < 0 ||
      priceOut < 0
    ) {
      rows.push({
        model: model.trim(),
        priceIn,
        priceOut,
        usdIn: "",
        usdOut: "",
        valid: false,
        error: "rates must be non-negative numbers",
      });
      continue;
    }
    rows.push({
      model: model.trim(),
      priceIn,
      priceOut,
      usdIn: usdPer1M(priceIn),
      usdOut: usdPer1M(priceOut),
      valid: true,
    });
  }
  return rows;
}

function currentValueOf(settings: EffectiveSetting[], key: string): string {
  const row = settings.find((s) => s.key === key);
  const value = row?.value;
  return value === null || value === undefined ? "" : String(value);
}

function providerById(
  providers: AiProviderCatalogEntry[],
  id: string,
): AiProviderCatalogEntry | undefined {
  return providers.find((p) => p.id === id);
}

function optionsWithCurrent(options: string[], current: string): string[] {
  if (current && !options.includes(current)) return [...options, current];
  return options;
}

// #929: the static status band at the top of the AI section - one glance at
// which provider, which models, the auto-derived base URL, how many pricing
// entries metering has, and when the config was last loaded. Presentation
// only: every value derives from the effective settings and the provider
// catalog the section already fetches (no new requests, no live metering).
// The accent chips reuse the patient/doctor surfaces' chip idiom
// (bg-accent-soft/text-accent-strong pill) so the pattern lifts into the
// other settings sections later.
function AiStatusBand({
  providerName,
  model,
  asrModel,
  baseUrl,
  pricingEntries,
  refreshedAt,
  t,
}: {
  providerName: string;
  model: string;
  asrModel: string;
  baseUrl: string;
  pricingEntries: number;
  refreshedAt: string | null;
  t: AiStrings;
}) {
  const chipClassName =
    "inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong";
  return (
    <div
      data-testid="settings-ai-band"
      className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-surface p-3"
    >
      <span className={chipClassName} data-testid="settings-ai-band-provider">
        {t.provider}: {providerName || "-"}
      </span>
      <span className={chipClassName} data-testid="settings-ai-band-model">
        {t.model}: {model || "-"}
      </span>
      <span className={chipClassName} data-testid="settings-ai-band-asr">
        {t.asrModel}: {asrModel || "-"}
      </span>
      <span className="inline-flex items-center gap-1 text-xs text-txt-muted">
        <span>{t.baseUrl}</span>
        <span
          className="max-w-64 truncate rounded-full border border-hairline px-2 py-0.5 font-mono text-txt"
          data-testid="settings-ai-band-base-url"
        >
          {baseUrl || "-"}
        </span>
      </span>
      <span
        className={chipClassName}
        data-testid="settings-ai-band-pricing-count"
      >
        {t.bandPricingEntries(pricingEntries)}
      </span>
      <span
        className="text-xs text-txt-muted"
        data-testid="settings-ai-band-refresh"
      >
        {refreshedAt
          ? `${t.bandRefreshed} ${formatTimestamp(refreshedAt)}`
          : ""}
      </span>
    </div>
  );
}

function AiFieldRow({
  fieldKey,
  label,
  value,
  source,
  editable,
  control,
  saveStatus,
  saveError,
  onDraft,
  onSave,
  isAdmin,
  t,
  variant = "card",
}: {
  fieldKey: string;
  label: string;
  value: string;
  source: SettingSource | undefined;
  editable: boolean;
  control: React.ReactNode;
  saveStatus: SaveStatus;
  saveError: string | undefined;
  onDraft: (value: string) => void;
  onSave: () => void;
  isAdmin: boolean;
  t: AiStrings;
  // #930: "block" rows sit inside a grouped block (the wrapper supplies the
  // card frame and the dividers); "card" rows keep the standalone frame.
  variant?: "card" | "block";
}) {
  const canEdit = editable && isAdmin;
  const status = saveStatus;
  const error = saveError;
  return (
    <div
      key={fieldKey}
      data-testid={`settings-ai-row-${fieldKey}`}
      className={variant === "block" ? "p-3" : `${CARD_FRAME} p-3`}
    >
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-sm font-medium text-txt">{label}</span>
        {source !== undefined ? (
          <Badge
            variant="secondary"
            className="text-xs"
            data-testid={`settings-ai-source-${fieldKey}`}
          >
            {sourceLabel(source, t)}
          </Badge>
        ) : null}
      </div>
      <div className="mb-2">{control}</div>
      <div className="flex flex-col gap-1">
        {canEdit ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={status === "saving"}
              onClick={onSave}
              className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
              data-testid={`settings-ai-save-${fieldKey}`}
            >
              {status === "saving" ? t.saving : t.save}
            </button>
            {status === "saved" && (
              <span
                className="text-xs text-success"
                data-testid={`settings-ai-save-status-${fieldKey}`}
              >
                {t.saved}
              </span>
            )}
            {status === "error" && error && (
              <span
                role="alert"
                className="text-xs text-danger"
                data-testid={`settings-ai-save-error-${fieldKey}`}
              >
                {error}
              </span>
            )}
          </div>
        ) : (
          <span
            className="text-xs text-txt-muted"
            data-testid={`settings-ai-readonly-${fieldKey}`}
          >
            {t.readOnly}
          </span>
        )}
      </div>
    </div>
  );
}

interface AiSectionProps {
  t: OperatorSettingsStrings;
  isAdmin: boolean;
}

export function AiSettingsSection({ t, isAdmin }: AiSectionProps) {
  const ai = t.ai;
  const settingsRead = usePanelRead(() => fetchEffectiveSettings());
  const catalogRead = usePanelRead(() => fetchAiProviderCatalog());
  const historyRead = usePanelRead(() => fetchSettingHistory());

  // #929: when the band's data last landed (both reads together). A
  // presentation stamp only - it never drives a fetch.
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);
  useEffect(() => {
    if (settingsRead.status === "ready" && catalogRead.status === "ready") {
      setRefreshedAt(new Date().toISOString());
    }
  }, [
    settingsRead.status,
    settingsRead.data,
    catalogRead.status,
    catalogRead.data,
  ]);

  const settings = settingsRead.data ?? [];
  const providers = catalogRead.data ?? [];
  const current: Record<AiFieldKey, string> = {} as Record<AiFieldKey, string>;
  for (const key of AI_FIELD_KEYS) {
    current[key] = currentValueOf(settings, key);
  }
  const currentSource: Record<AiFieldKey, SettingSource | undefined> =
    {} as Record<AiFieldKey, SettingSource | undefined>;
  const currentEditable: Record<AiFieldKey, boolean> = {} as Record<
    AiFieldKey,
    boolean
  >;
  for (const key of AI_FIELD_KEYS) {
    const row = settings.find((s) => s.key === key);
    currentSource[key] = row?.source;
    currentEditable[key] = row?.editable ?? false;
  }

  const [drafts, setDrafts] = useState<Record<AiFieldKey, string>>(current);
  const [customText, setCustomText] = useState<Record<AiFieldKey, string>>(
    Object.fromEntries(AI_FIELD_KEYS.map((k) => [k, ""])) as Record<
      AiFieldKey,
      string
    >,
  );
  const [saveStates, setSaveStates] = useState<Record<AiFieldKey, SaveStatus>>(
    Object.fromEntries(AI_FIELD_KEYS.map((k) => [k, "idle"])) as Record<
      AiFieldKey,
      SaveStatus
    >,
  );
  const [saveErrors, setSaveErrors] = useState<Record<AiFieldKey, string>>(
    Object.fromEntries(AI_FIELD_KEYS.map((k) => [k, ""])) as Record<
      AiFieldKey,
      string
    >,
  );
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [apiKeySaveStatus, setApiKeySaveStatus] = useState<SaveStatus>("idle");
  const [apiKeySaveError, setApiKeySaveError] = useState<string | undefined>(
    undefined,
  );

  const apiKeyRow = settings.find((s) => s.key === "ai.api_key");
  const currentEditableApiKey = apiKeyRow?.editable ?? false;
  // The provider the provider block is about: the draft selection while it
  // is unsaved, else the effective value. Drives the key-row visibility and
  // the base-URL pill (#930).
  const selectedProviderEntry = providerById(
    providers,
    drafts["ai.provider"] || current["ai.provider"],
  );
  const providerRequiresKey = Boolean(
    selectedProviderEntry?.api_key_env &&
      String(selectedProviderEntry.api_key_env).trim() !== "",
  );
  // #930: the masked status text stands alone whenever a key exists; only
  // the missing state shows the password input.
  const apiKeyConfigured = apiKeyState(apiKeyRow?.source) !== "missing";
  // The model lists stay bound to the raw draft selection (no effective
  // fallback): an unsaved provider pick re-filters its own model lists.
  const draftProviderEntry = providerById(providers, drafts["ai.provider"]);
  const fallbackProviderEntry = providerById(
    providers,
    drafts["ai.fallback_provider"],
  );
  const chatModels = optionsWithCurrent(
    draftProviderEntry?.chat_models ?? [],
    drafts["ai.model"],
  );
  const asrModels = optionsWithCurrent(
    draftProviderEntry?.asr_models ?? [],
    drafts["ai.asr_model"],
  );
  const fallbackChatModels = optionsWithCurrent(
    fallbackProviderEntry?.chat_models ?? [],
    drafts["ai.fallback_model"],
  );

  function handleDraft(key: AiFieldKey, value: string) {
    setDrafts((cur) => ({ ...cur, [key]: value }));
    setSaveStates((cur) => ({ ...cur, [key]: "idle" }));
    setSaveErrors((cur) => {
      const next = { ...cur };
      delete next[key];
      return next;
    });
  }

  function handleCustomDraft(key: AiFieldKey, value: string) {
    setCustomText((cur) => ({ ...cur, [key]: value }));
  }

  async function handleSave(key: AiFieldKey) {
    setSaveErrors((cur) => {
      const next = { ...cur };
      delete next[key];
      return next;
    });

    let value = drafts[key];
    if (key === "ai.model" || key === "ai.fallback_model") {
      // When a custom model name is typed, prefer it over the select choice.
      const custom = customText[key];
      if (custom.trim()) value = custom.trim();
    }

    if (value === "") {
      setSaveStates((cur) => ({ ...cur, [key]: "error" }));
      setSaveErrors((cur) => ({ ...cur, [key]: ai.validationRequired }));
      return;
    }

    // Client-side guard: a custom model requires a pricing-table entry.
    if (key === "ai.model" || key === "ai.fallback_model") {
      const entry = providerById(
        providers,
        key === "ai.model"
          ? drafts["ai.provider"]
          : drafts["ai.fallback_provider"],
      );
      const known = new Set([
        ...(entry?.chat_models ?? []),
        ...(entry?.asr_models ?? []),
      ]);
      if (!known.has(value)) {
        const pricing = parsePricingTable(drafts["ai.pricing_table"]);
        if (!pricing.some((row) => row.valid && row.model === value)) {
          setSaveStates((cur) => ({ ...cur, [key]: "error" }));
          setSaveErrors((cur) => ({ ...cur, [key]: ai.validationCustomPrice }));
          return;
        }
      }
    }

    setSaveStates((cur) => ({ ...cur, [key]: "saving" }));
    try {
      await writeSetting(key, value as SettingWriteValue);
      setSaveStates((cur) => ({ ...cur, [key]: "saved" }));
      setDrafts((cur) => {
        if (!(key in cur)) return cur;
        const next = { ...cur };
        delete next[key];
        return next;
      });
      settingsRead.reload();
    } catch (error) {
      setSaveStates((cur) => ({ ...cur, [key]: "error" }));
      setSaveErrors((cur) => ({
        ...cur,
        [key]:
          error instanceof ApiError
            ? error.message || ai.saveErrorExpected
            : ai.saveError,
      }));
    }
  }

  async function handleSaveApiKey() {
    setApiKeySaveError(undefined);
    const value = apiKeyDraft;
    if (value === "") {
      setApiKeySaveStatus("error");
      setApiKeySaveError(ai.validationRequired);
      return;
    }

    setApiKeySaveStatus("saving");
    try {
      await writeSetting("ai.api_key", value as SettingWriteValue);
      setApiKeySaveStatus("saved");
      setApiKeyDraft("");
      settingsRead.reload();
    } catch (error) {
      setApiKeySaveStatus("error");
      setApiKeySaveError(
        error instanceof ApiError
          ? error.message || ai.saveErrorExpected
          : ai.saveError,
      );
    }
  }

  const pricingRows = parsePricingTable(drafts["ai.pricing_table"]);
  const bandProviderEntry = providerById(providers, current["ai.provider"]);

  return (
    <CollapsibleSettingsSection
      sectionKey="ai"
      testId="settings-ai"
      title={t.sections.ai}
      description={ai.description}
    >
      {(settingsRead.status === "loading" ||
        catalogRead.status === "loading") && (
        <div data-testid="settings-ai-loading">
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {settingsRead.status === "error" && (
        <div
          role="alert"
          data-testid="settings-ai-error"
          className="rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">
            {settingsRead.error?.expected ? ai.errorExpected : ai.error}
          </p>
          <button
            type="button"
            onClick={settingsRead.reload}
            data-testid="settings-ai-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.retry}
          </button>
        </div>
      )}

      {catalogRead.status === "error" && (
        <div
          role="alert"
          data-testid="settings-ai-catalog-error"
          className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">{ai.catalogError}</p>
          <button
            type="button"
            onClick={catalogRead.reload}
            data-testid="settings-ai-catalog-retry"
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            {t.retry}
          </button>
        </div>
      )}

      {settingsRead.status === "ready" &&
        catalogRead.status === "ready" &&
        providers.length === 0 && (
          <EmptyState title={ai.catalogEmpty} body={ai.catalogError} />
        )}

      {settingsRead.status === "ready" &&
        catalogRead.status === "ready" &&
        providers.length > 0 && (
          <>
            <AiStatusBand
              providerName={
                bandProviderEntry?.display_name ?? current["ai.provider"]
              }
              model={current["ai.model"]}
              asrModel={current["ai.asr_model"]}
              baseUrl={bandProviderEntry?.base_url ?? ""}
              pricingEntries={
                parsePricingTable(current["ai.pricing_table"]).filter(
                  (row) => row.valid,
                ).length
              }
              refreshedAt={refreshedAt}
              t={ai}
            />

            <p
              className="mb-2 text-xs text-txt-muted"
              data-testid="settings-ai-takeaway"
            >
              {ai.takeaway ? ai.takeaway(6) : "6 effective settings"}
            </p>

            <div
              data-testid="settings-ai-provider-block"
              className={CARD_FRAME}
            >
              <div className="divide-y divide-hairline">
                <AiFieldRow
                  variant="block"
                  fieldKey="ai.provider"
                  label={ai.provider}
                  value={drafts["ai.provider"]}
                  source={currentSource["ai.provider"]}
                  editable={currentEditable["ai.provider"]}
                  control={
                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={drafts["ai.provider"]}
                        onChange={(event) => {
                          handleDraft("ai.provider", event.target.value);
                          setApiKeyDraft("");
                          setApiKeySaveStatus("idle");
                          setApiKeySaveError(undefined);
                        }}
                        disabled={!isAdmin || !currentEditable["ai.provider"]}
                        className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                        data-testid="settings-ai-provider-select"
                      >
                        {providers.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.display_name}
                          </option>
                        ))}
                      </select>
                      <span className="inline-flex items-center gap-1 text-xs text-txt-muted">
                        <span>{ai.baseUrl}</span>
                        <span
                          className="max-w-64 truncate rounded-full border border-hairline px-2 py-0.5 font-mono text-txt"
                          data-testid="settings-ai-base-url"
                        >
                          {selectedProviderEntry?.base_url || "-"}
                        </span>
                      </span>
                    </div>
                  }
                  saveStatus={saveStates["ai.provider"] ?? "idle"}
                  saveError={saveErrors["ai.provider"]}
                  onDraft={(v) => handleDraft("ai.provider", v)}
                  onSave={() => void handleSave("ai.provider")}
                  isAdmin={isAdmin}
                  t={ai}
                />

                {providerRequiresKey && (
                  <div
                    key="ai.api_key"
                    data-testid="settings-ai-row-ai.api_key"
                    className="p-3"
                  >
                    <div className="flex items-baseline gap-2 mb-1">
                      <span className="text-sm font-medium text-txt">
                        {ai.apiKeyLabel}
                      </span>
                      <Badge
                        variant="secondary"
                        className="text-xs"
                        data-testid="settings-ai-api-key-status"
                      >
                        {apiKeyStatusLabel(
                          apiKeyRow?.value,
                          apiKeyRow?.source,
                          ai,
                        )}
                      </Badge>
                    </div>
                    {!apiKeyConfigured && (
                      <>
                        <div className="mb-2">
                          <input
                            type="password"
                            value={apiKeyDraft}
                            onChange={(event) =>
                              setApiKeyDraft(event.target.value)
                            }
                            disabled={!isAdmin || !currentEditableApiKey}
                            placeholder={ai.apiKeyPlaceholder}
                            className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                            data-testid="settings-ai-api-key-input"
                          />
                        </div>
                        <div className="flex flex-col gap-1">
                          {isAdmin && currentEditableApiKey ? (
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                disabled={apiKeySaveStatus === "saving"}
                                onClick={handleSaveApiKey}
                                className="inline-flex min-h-9 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                                data-testid="settings-ai-save-ai.api_key"
                              >
                                {apiKeySaveStatus === "saving"
                                  ? ai.saving
                                  : ai.save}
                              </button>
                              {apiKeySaveStatus === "saved" && (
                                <span
                                  className="text-xs text-success"
                                  data-testid="settings-ai-save-status-ai.api_key"
                                >
                                  {ai.saved}
                                </span>
                              )}
                              {apiKeySaveStatus === "error" &&
                                apiKeySaveError && (
                                  <span
                                    role="alert"
                                    className="text-xs text-danger"
                                    data-testid="settings-ai-save-error-ai.api_key"
                                  >
                                    {apiKeySaveError}
                                  </span>
                                )}
                            </div>
                          ) : (
                            <span
                              className="text-xs text-txt-muted"
                              data-testid="settings-ai-readonly-ai.api_key"
                            >
                              {ai.readOnly}
                            </span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>

            <AiFieldRow
              fieldKey="ai.model"
              label={ai.model}
              value={drafts["ai.model"]}
              source={currentSource["ai.model"]}
              editable={currentEditable["ai.model"]}
              control={
                <div className="flex flex-col gap-1">
                  <select
                    value={drafts["ai.model"]}
                    onChange={(event) =>
                      handleDraft("ai.model", event.target.value)
                    }
                    disabled={!isAdmin || !currentEditable["ai.model"]}
                    className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                    data-testid="settings-ai-model-select"
                  >
                    {chatModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                    <option key="__custom__" value="__custom__">
                      {ai.customModelOption}
                    </option>
                  </select>
                  {drafts["ai.model"] === "__custom__" && (
                    <input
                      type="text"
                      value={customText["ai.model"]}
                      onChange={(event) =>
                        handleCustomDraft("ai.model", event.target.value)
                      }
                      placeholder={ai.customModel}
                      disabled={!isAdmin || !currentEditable["ai.model"]}
                      className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input mt-1"
                      data-testid="settings-ai-model-custom"
                    />
                  )}
                  <span
                    className="text-xs text-txt-muted"
                    data-testid="settings-ai-model-hint"
                  >
                    {drafts["ai.model"] === "__custom__"
                      ? `${ai.customModelMarked} ${ai.customModel}`
                      : ""}
                  </span>
                </div>
              }
              saveStatus={saveStates["ai.model"] ?? "idle"}
              saveError={saveErrors["ai.model"]}
              onDraft={(v) => handleDraft("ai.model", v)}
              onSave={() => void handleSave("ai.model")}
              isAdmin={isAdmin}
              t={ai}
            />

            <AiFieldRow
              fieldKey="ai.asr_model"
              label={ai.asrModel}
              value={drafts["ai.asr_model"]}
              source={currentSource["ai.asr_model"]}
              editable={currentEditable["ai.asr_model"]}
              control={
                <select
                  value={drafts["ai.asr_model"]}
                  onChange={(event) =>
                    handleDraft("ai.asr_model", event.target.value)
                  }
                  disabled={!isAdmin || !currentEditable["ai.asr_model"]}
                  className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                  data-testid="settings-ai-asr-select"
                >
                  {asrModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              }
              saveStatus={saveStates["ai.asr_model"] ?? "idle"}
              saveError={saveErrors["ai.asr_model"]}
              onDraft={(v) => handleDraft("ai.asr_model", v)}
              onSave={() => void handleSave("ai.asr_model")}
              isAdmin={isAdmin}
              t={ai}
            />

            <AiFieldRow
              fieldKey="ai.fallback_provider"
              label={ai.fallbackProvider}
              value={drafts["ai.fallback_provider"]}
              source={currentSource["ai.fallback_provider"]}
              editable={currentEditable["ai.fallback_provider"]}
              control={
                <select
                  value={drafts["ai.fallback_provider"]}
                  onChange={(event) =>
                    handleDraft("ai.fallback_provider", event.target.value)
                  }
                  disabled={
                    !isAdmin || !currentEditable["ai.fallback_provider"]
                  }
                  className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                  data-testid="settings-ai-fallback-provider-select"
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </select>
              }
              saveStatus={saveStates["ai.fallback_provider"] ?? "idle"}
              saveError={saveErrors["ai.fallback_provider"]}
              onDraft={(v) => handleDraft("ai.fallback_provider", v)}
              onSave={() => void handleSave("ai.fallback_provider")}
              isAdmin={isAdmin}
              t={ai}
            />

            <AiFieldRow
              fieldKey="ai.fallback_model"
              label={ai.fallbackModel}
              value={drafts["ai.fallback_model"]}
              source={currentSource["ai.fallback_model"]}
              editable={currentEditable["ai.fallback_model"]}
              control={
                <div className="flex flex-col gap-1">
                  <select
                    value={drafts["ai.fallback_model"]}
                    onChange={(event) =>
                      handleDraft("ai.fallback_model", event.target.value)
                    }
                    disabled={!isAdmin || !currentEditable["ai.fallback_model"]}
                    className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input"
                    data-testid="settings-ai-fallback-model-select"
                  >
                    {fallbackChatModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                    <option key="__custom__" value="__custom__">
                      {ai.customModelOption}
                    </option>
                  </select>
                  {drafts["ai.fallback_model"] === "__custom__" && (
                    <input
                      type="text"
                      value={customText["ai.fallback_model"]}
                      onChange={(event) =>
                        handleCustomDraft(
                          "ai.fallback_model",
                          event.target.value,
                        )
                      }
                      placeholder={ai.customModel}
                      disabled={
                        !isAdmin || !currentEditable["ai.fallback_model"]
                      }
                      className="w-48 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input mt-1"
                      data-testid="settings-ai-fallback-model-custom"
                    />
                  )}
                </div>
              }
              saveStatus={saveStates["ai.fallback_model"] ?? "idle"}
              saveError={saveErrors["ai.fallback_model"]}
              onDraft={(v) => handleDraft("ai.fallback_model", v)}
              onSave={() => void handleSave("ai.fallback_model")}
              isAdmin={isAdmin}
              t={ai}
            />

            <AiFieldRow
              fieldKey="ai.pricing_table"
              label={ai.pricingTable}
              value={drafts["ai.pricing_table"]}
              source={currentSource["ai.pricing_table"]}
              editable={currentEditable["ai.pricing_table"]}
              control={
                <div className="flex flex-col gap-1">
                  <textarea
                    value={drafts["ai.pricing_table"]}
                    onChange={(event) =>
                      handleDraft("ai.pricing_table", event.target.value)
                    }
                    disabled={!isAdmin || !currentEditable["ai.pricing_table"]}
                    rows={4}
                    className="w-64 rounded-md border border-hairline px-2 py-1 text-sm text-txt bg-input font-mono"
                    placeholder={ai.pricingPlaceholder}
                    data-testid="settings-ai-pricing-table"
                  />
                  <span className="text-xs text-txt-muted">
                    {ai.pricingHint}
                  </span>
                  {pricingRows.length > 0 && (
                    <div className="mt-1 text-xs text-txt-sub">
                      {pricingRows.map((row, i) => (
                        <span
                          key={i}
                          className="mr-3"
                          data-testid={`settings-ai-pricing-preview-${row.model}`}
                        >
                          {row.valid
                            ? `${row.model}: ${ai.usdInput} $${row.usdIn} · ${ai.usdOutput} $${row.usdOut} ${ai.usdPer1M}`
                            : `${row.model}: ${row.error}`}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              }
              saveStatus={saveStates["ai.pricing_table"] ?? "idle"}
              saveError={saveErrors["ai.pricing_table"]}
              onDraft={(v) => handleDraft("ai.pricing_table", v)}
              onSave={() => void handleSave("ai.pricing_table")}
              isAdmin={isAdmin}
              t={ai}
            />
          </>
        )}

      {settingsRead.status === "ready" &&
        catalogRead.status === "ready" &&
        historyRead.status === "ready" && (
          <AiHistory
            entries={(historyRead.data ?? []).filter((e) =>
              AI_FIELD_KEYS.includes(e.setting_key as AiFieldKey),
            )}
            t={ai}
            status={historyRead.status}
            errorMessage={
              historyRead.error?.expected
                ? ai.historyErrorExpected
                : ai.historyError
            }
            onRetry={historyRead.reload}
          />
        )}
    </CollapsibleSettingsSection>
  );
}

function AiHistory({
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
      data-testid="settings-ai-history"
    >
      <h3
        className="text-sm font-medium text-txt-sub"
        data-testid="settings-ai-history-title"
      >
        {t.historyTitle}
      </h3>
      <p className="mt-0.5 text-xs text-txt-muted">{t.historyDescription}</p>

      {status === "loading" && (
        <div className="mt-2" data-testid="settings-ai-history-loading">
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="mt-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
          data-testid="settings-ai-history-error"
        >
          <p className="text-sm text-danger">{errorMessage}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex min-h-9 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
            data-testid="settings-ai-history-retry"
          >
            {t.historyRetry}
          </button>
        </div>
      )}

      {status === "ready" && entries.length === 0 && (
        <p
          className="mt-2 text-sm text-txt-muted"
          data-testid="settings-ai-history-empty"
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
                  data-testid={`settings-ai-history-row-${entry.setting_key}-${entry.version}`}
                >
                  <th
                    scope="row"
                    className="py-2 pr-3 font-mono text-xs font-normal text-txt"
                  >
                    {entry.setting_key}
                  </th>
                  <td className="py-2 pr-3 text-txt">
                    {typeof entry.value === "string"
                      ? entry.value
                      : String(entry.value)}
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
