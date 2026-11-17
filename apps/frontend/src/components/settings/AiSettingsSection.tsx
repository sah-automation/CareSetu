"use client";

// #924: the catalog-driven "AI & LLM" section of the operator Settings page.
// The section renders selects populated from the AI provider catalog endpoint,
// with per-provider dependent model / ASR-model filtering, a marked "custom
// model name" free-text escape hatch on the model selects, and a pricing-table
// textarea (one `model:price_in:price_out` entry per line) with a USD-per-1M
// price preview alongside the stored paise unit. One primary "Save changes"
// button writes every field whose draft differs from the effective value,
// sequentially, stopping on the first error (#939); failures render as an
// aggregate banner plus inline errors under the failing fields. Writes go
// through the settings client's string-value write support (`writeSetting`).
// Non-admin operators see every control read-only.

import React, { useEffect, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
type FormStatus = "idle" | "saving" | "saved" | "error";

// ~₹88.5/USD (#917): FX rate for the USD-per-1M price preview, from config.
// USD per 1M tokens = paise-per-token * 1e6 / PAISE_PER_USD.
// Env-driven: NEXT_PUBLIC_PAISE_PER_USD must be set at deploy time.
const PAISE_PER_USD = Number(process.env.NEXT_PUBLIC_PAISE_PER_USD);
if (!Number.isFinite(PAISE_PER_USD)) {
  throw new Error(
    "NEXT_PUBLIC_PAISE_PER_USD must be set and be a valid number",
  );
}

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

// #939: fields sit on the default white background - border only.
const FIELD_CLASS =
  "rounded-md border border-hairline px-2 py-1 text-sm text-txt";

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

// #930: the one source->key-state mapping used for the input's visibility,
// so a new source cannot desync the two.
type ApiKeyState = "env" | "dashboard" | "missing";

function apiKeyState(source: SettingSource | undefined): ApiKeyState {
  if (source === "environment") return "env";
  if (source === "database") return "dashboard";
  return "missing";
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
// which provider, which models, how many pricing entries metering has, and
// when the config was last loaded. Presentation only: every value derives
// from the effective settings and the provider catalog the section already
// fetches (no new requests, no live metering). The accent chips reuse the
// patient/doctor surfaces' chip idiom (bg-accent-soft/text-accent-strong
// pill) so the pattern lifts into the other settings sections later.
function AiStatusBand({
  providerName,
  model,
  asrModel,
  pricingEntries,
  refreshedAt,
  t,
}: {
  providerName: string;
  model: string;
  asrModel: string;
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

// #939: a row is label + source badge + control, with a field-level error
// under the control when a save failed. There is no per-row save control -
// the section saves through its one primary button.
function AiFieldRow({
  fieldKey,
  label,
  source,
  editable,
  isAdmin,
  control,
  error,
  t,
  variant = "card",
}: {
  fieldKey: string;
  label: string;
  source: SettingSource | undefined;
  editable: boolean;
  isAdmin: boolean;
  control: React.ReactNode;
  error?: string;
  t: AiStrings;
  // #930: "block" rows sit inside a grouped block (the wrapper supplies the
  // card frame and the dividers); "card" rows keep the standalone frame.
  variant?: "card" | "block";
}) {
  const canEdit = editable && isAdmin;
  return (
    <div
      data-testid={`settings-ai-row-${fieldKey}`}
      className={variant === "block" ? "p-3" : `${CARD_FRAME} p-3`}
    >
      <div className="flex items-baseline gap-2 mb-1">
        <label htmlFor={fieldKey} className="text-sm font-medium text-txt">
          {label}
        </label>
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
      {error ? (
        <span
          role="alert"
          className="text-xs text-danger"
          data-testid={`settings-ai-field-error-${fieldKey}`}
        >
          {error}
        </span>
      ) : null}
      {!canEdit ? (
        <span
          className="text-xs text-txt-muted"
          data-testid={`settings-ai-readonly-${fieldKey}`}
        >
          {t.readOnly}
        </span>
      ) : null}
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

  // #939: drafts are overrides over the effective values, so a field the
  // operator never touched is never dirty and never written by Save changes.
  const [draftOverrides, setDraftOverrides] = useState<
    Partial<Record<AiFieldKey, string>>
  >({});
  const drafts = { ...current, ...draftOverrides };
  const [customText, setCustomText] = useState<Record<AiFieldKey, string>>(
    Object.fromEntries(AI_FIELD_KEYS.map((k) => [k, ""])) as Record<
      AiFieldKey,
      string
    >,
  );
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formStatus, setFormStatus] = useState<FormStatus>("idle");
  const [formError, setFormError] = useState<string | undefined>(undefined);
  const [apiKeyDraft, setApiKeyDraft] = useState("");

  const apiKeyRow = settings.find((s) => s.key === "ai.api_key");
  const currentEditableApiKey = apiKeyRow?.editable ?? false;
  // The provider the provider block is about: the draft selection while it
  // is unsaved, else the effective value. Drives the key-row visibility.
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

  function clearFormFeedback() {
    setFormStatus("idle");
    setFormError(undefined);
  }

  function clearFieldError(key: string) {
    setFieldErrors((cur) => {
      if (!(key in cur)) return cur;
      const next = { ...cur };
      delete next[key];
      return next;
    });
  }

  function handleDraft(key: AiFieldKey, value: string) {
    setDraftOverrides((cur) => ({ ...cur, [key]: value }));
    clearFormFeedback();
    clearFieldError(key);
  }

  function handleApiKeyDraft(value: string) {
    setApiKeyDraft(value);
    clearFormFeedback();
    clearFieldError("ai.api_key");
  }

  function handleCustomDraft(key: AiFieldKey, value: string) {
    setCustomText((cur) => ({ ...cur, [key]: value }));
  }

  function resolveSaveValue(key: AiFieldKey): string {
    let value = drafts[key];
    if (key === "ai.model" || key === "ai.fallback_model") {
      // When a custom model name is typed, prefer it over the select choice.
      const custom = customText[key];
      if (custom.trim()) value = custom.trim();
    }
    return value;
  }

  function validateValue(
    key: AiFieldKey,
    value: string,
    entriesBeingSaved: Array<{ key: string; value: string }>,
  ): string | undefined {
    if (value === "") return ai.validationRequired;

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
        // Check if pricing table is also being saved in this batch; if so,
        // use the new value for validation instead of the stale draft.
        const pricingEntry = entriesBeingSaved.find(
          (e) => e.key === "ai.pricing_table",
        );
        const pricingText = pricingEntry?.value ?? drafts["ai.pricing_table"];
        const pricing = parsePricingTable(pricingText);
        if (!pricing.some((row) => row.valid && row.model === value)) {
          return ai.validationCustomPrice;
        }
      }
    }
    return undefined;
  }

  async function handleSaveChanges() {
    clearFormFeedback();
    setFieldErrors({});

    const apiKeyChanged =
      providerRequiresKey && !apiKeyConfigured && apiKeyDraft !== "";

    // Write order follows the DOM: provider, then its API key, then the
    // model/fallback fields, then the pricing table.
    const entries: Array<{ key: AiFieldKey | "ai.api_key"; value: string }> =
      [];
    const providerDirty = drafts["ai.provider"] !== current["ai.provider"];

    if (providerDirty) {
      entries.push({
        key: "ai.provider",
        value: resolveSaveValue("ai.provider"),
      });
      if (apiKeyChanged) {
        entries.push({ key: "ai.api_key", value: apiKeyDraft });
      }
    } else if (apiKeyChanged) {
      // Provider not dirty but key is: key still writes before model fields
      entries.push({ key: "ai.api_key", value: apiKeyDraft });
    }

    for (const key of AI_FIELD_KEYS) {
      if (key === "ai.provider") continue;
      if (drafts[key] === current[key]) continue;
      entries.push({ key, value: resolveSaveValue(key) });
    }
    if (entries.length === 0) return;

    // Client-side validation first: every failing field shows its own
    // inline error and nothing reaches the API (ui-blueprint §9.5).
    const errors: Record<string, string> = {};
    for (const entry of entries) {
      // The key draft cannot be empty: apiKeyChanged already requires a
      // non-empty draft, so there is nothing to validate for it.
      if (entry.key === "ai.api_key") continue;
      const validationError = validateValue(entry.key, entry.value, entries);
      if (validationError) errors[entry.key] = validationError;
    }
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormStatus("error");
      setFormError(Object.values(errors)[0]);
      return;
    }

    setFormStatus("saving");
    let savedAny = false;
    for (const entry of entries) {
      try {
        await writeSetting(entry.key, entry.value);
        if (entry.key === "ai.api_key") {
          setApiKeyDraft("");
        } else {
          // The write landed: the override drops and the draft falls back to
          // the reloaded effective value.
          setDraftOverrides((cur) => {
            const next = { ...cur };
            delete next[entry.key as AiFieldKey];
            return next;
          });
        }
        savedAny = true;
      } catch (error) {
        const isApiError = error instanceof ApiError;
        const traceId = isApiError ? error.traceId : "";
        const status = isApiError ? error.status : undefined;
        const message = isApiError
          ? error.message || ai.saveErrorExpected
          : ai.saveError;

        // Structured error logging with trace_id correlation (coding-standards §8.4)
        console.error("AI settings save failed", {
          key: entry.key,
          traceId,
          status,
          code: isApiError ? error.code : "UNKNOWN",
          message,
        });

        // For display: always show the backend refusal message when we have one.
        // The 4xx/5xx distinction (api-standards §2) is used for retry logic:
        // 4xx = don't retry (client error), 5xx/unknown = retryable (server error).
        const isClientError =
          status !== undefined && status >= 400 && status < 500;
        setFieldErrors((cur) => ({ ...cur, [entry.key]: message }));
        setFormStatus("error");
        setFormError(message);
        // Earlier writes in this run landed on the server: refresh the
        // effective values so saved fields stop looking dirty.
        if (savedAny) {
          settingsRead.reload();
          historyRead.reload();
        }
        return;
      }
    }
    setFormStatus("saved");
    settingsRead.reload();
    historyRead.reload();
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
        <div
          data-testid="settings-ai-loading"
          className="flex flex-col gap-3"
          aria-hidden="true"
        >
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-36 w-full rounded-lg" />
          <Skeleton className="h-36 w-full rounded-lg" />
          <Skeleton className="h-20 w-full rounded-lg" />
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
          {settingsRead.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid="settings-ai-error-trace-id"
            >
              {ai.traceLabel}: {settingsRead.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid="settings-ai-error-no-trace"
            >
              {ai.noTrace}
            </p>
          )}
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
              <div className="grid grid-cols-1 gap-x-6 p-2 md:grid-cols-2">
                <AiFieldRow
                  variant="block"
                  fieldKey="ai.provider"
                  label={ai.provider}
                  source={currentSource["ai.provider"]}
                  editable={currentEditable["ai.provider"]}
                  isAdmin={isAdmin}
                  t={ai}
                  error={fieldErrors["ai.provider"]}
                  control={
                    <select
                      value={drafts["ai.provider"]}
                      onChange={(event) => {
                        handleDraft("ai.provider", event.target.value);
                        setApiKeyDraft("");
                      }}
                      disabled={!isAdmin || !currentEditable["ai.provider"]}
                      className={`${FIELD_CLASS} w-full md:w-48`}
                      id="ai.provider"
                      data-testid="settings-ai-provider-select"
                    >
                      {providers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name}
                        </option>
                      ))}
                    </select>
                  }
                />
                {providerRequiresKey && (
                  <AiFieldRow
                    variant="block"
                    fieldKey="ai.api_key"
                    label={ai.apiKeyLabel}
                    source={apiKeyRow?.source}
                    editable={currentEditableApiKey}
                    isAdmin={isAdmin}
                    t={ai}
                    error={fieldErrors["ai.api_key"]}
                    control={
                      <div className="flex flex-col gap-1">
                        {!apiKeyConfigured && (
                          <>
                            <input
                              type="password"
                              value={apiKeyDraft}
                              onChange={(event) =>
                                handleApiKeyDraft(event.target.value)
                              }
                              disabled={!isAdmin || !currentEditableApiKey}
                              placeholder={ai.apiKeyPlaceholder}
                              className={`${FIELD_CLASS} w-full md:w-64`}
                              id="ai.api_key"
                              data-testid="settings-ai-api-key-input"
                            />
                            {!isAdmin || !currentEditableApiKey ? (
                              <span
                                className="text-xs text-txt-muted"
                                data-testid="settings-ai-readonly-ai.api_key"
                              >
                                {ai.readOnly}
                              </span>
                            ) : null}
                          </>
                        )}
                      </div>
                    }
                  />
                )}
              </div>
            </div>

            {/* #931: the four model selects share one responsive block -
                multi-column at the standard breakpoint, stacked on mobile. */}
            <div data-testid="settings-ai-models-block" className={CARD_FRAME}>
              <div className="grid grid-cols-1 gap-x-6 p-2 md:grid-cols-2">
                <AiFieldRow
                  variant="block"
                  fieldKey="ai.model"
                  label={ai.model}
                  source={currentSource["ai.model"]}
                  editable={currentEditable["ai.model"]}
                  isAdmin={isAdmin}
                  t={ai}
                  error={fieldErrors["ai.model"]}
                  control={
                    <div className="flex flex-col gap-1">
                      <select
                        value={drafts["ai.model"]}
                        onChange={(event) =>
                          handleDraft("ai.model", event.target.value)
                        }
                        disabled={!isAdmin || !currentEditable["ai.model"]}
                        className={`${FIELD_CLASS} w-full md:w-48`}
                        id="ai.model"
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
                          className={`${FIELD_CLASS} w-full md:w-48 mt-1`}
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
                />

                <AiFieldRow
                  variant="block"
                  fieldKey="ai.asr_model"
                  label={ai.asrModel}
                  source={currentSource["ai.asr_model"]}
                  editable={currentEditable["ai.asr_model"]}
                  isAdmin={isAdmin}
                  t={ai}
                  error={fieldErrors["ai.asr_model"]}
                  control={
                    <select
                      value={drafts["ai.asr_model"]}
                      onChange={(event) =>
                        handleDraft("ai.asr_model", event.target.value)
                      }
                      disabled={!isAdmin || !currentEditable["ai.asr_model"]}
                      className={`${FIELD_CLASS} w-full md:w-48`}
                      id="ai.asr_model"
                      data-testid="settings-ai-asr-select"
                    >
                      {asrModels.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  }
                />

                <AiFieldRow
                  variant="block"
                  fieldKey="ai.fallback_provider"
                  label={ai.fallbackProvider}
                  source={currentSource["ai.fallback_provider"]}
                  editable={currentEditable["ai.fallback_provider"]}
                  isAdmin={isAdmin}
                  t={ai}
                  error={fieldErrors["ai.fallback_provider"]}
                  control={
                    <select
                      value={drafts["ai.fallback_provider"]}
                      onChange={(event) =>
                        handleDraft("ai.fallback_provider", event.target.value)
                      }
                      disabled={
                        !isAdmin || !currentEditable["ai.fallback_provider"]
                      }
                      className={`${FIELD_CLASS} w-full md:w-48`}
                      id="ai.fallback_provider"
                      data-testid="settings-ai-fallback-provider-select"
                    >
                      {providers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name}
                        </option>
                      ))}
                    </select>
                  }
                />

                <AiFieldRow
                  variant="block"
                  fieldKey="ai.fallback_model"
                  label={ai.fallbackModel}
                  source={currentSource["ai.fallback_model"]}
                  editable={currentEditable["ai.fallback_model"]}
                  isAdmin={isAdmin}
                  t={ai}
                  error={fieldErrors["ai.fallback_model"]}
                  control={
                    <div className="flex flex-col gap-1">
                      <select
                        value={drafts["ai.fallback_model"]}
                        onChange={(event) =>
                          handleDraft("ai.fallback_model", event.target.value)
                        }
                        disabled={
                          !isAdmin || !currentEditable["ai.fallback_model"]
                        }
                        className={`${FIELD_CLASS} w-full md:w-48`}
                        id="ai.fallback_model"
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
                          className={`${FIELD_CLASS} w-full md:w-48 mt-1`}
                          data-testid="settings-ai-fallback-model-custom"
                        />
                      )}
                    </div>
                  }
                />
              </div>
            </div>

            <div data-testid="settings-ai-pricing-block" className={CARD_FRAME}>
              <AiFieldRow
                variant="block"
                fieldKey="ai.pricing_table"
                label={ai.pricingTable}
                source={currentSource["ai.pricing_table"]}
                editable={currentEditable["ai.pricing_table"]}
                isAdmin={isAdmin}
                t={ai}
                error={fieldErrors["ai.pricing_table"]}
                control={
                  // #932: prettified, not rebuilt - the raw textarea stays the
                  // editor (mono typeface, comfortable width/height) and the
                  // paise hint plus USD-per-1M preview render as tidy helper
                  // chips beneath it. Validation logic is untouched.
                  <div className="flex flex-col gap-1.5">
                    <textarea
                      value={drafts["ai.pricing_table"]}
                      onChange={(event) =>
                        handleDraft("ai.pricing_table", event.target.value)
                      }
                      disabled={
                        !isAdmin || !currentEditable["ai.pricing_table"]
                      }
                      rows={6}
                      className={`${FIELD_CLASS} w-full max-w-md px-2 py-1.5 leading-relaxed font-mono`}
                      placeholder={ai.pricingPlaceholder}
                      id="ai.pricing_table"
                      data-testid="settings-ai-pricing-table"
                    />
                    <Badge
                      variant="outline"
                      className="w-fit border-hairline font-medium text-xs text-txt-muted"
                      data-testid="settings-ai-pricing-hint"
                    >
                      {ai.pricingHint}
                    </Badge>
                    {pricingRows.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {pricingRows.map((row, i) => {
                          const chipClass =
                            "max-w-full font-mono font-medium text-xs";
                          return (
                            <Badge
                              key={i}
                              variant={row.valid ? "secondary" : "outline"}
                              className={
                                row.valid
                                  ? chipClass
                                  : `${chipClass} border-danger-border bg-danger-soft text-danger`
                              }
                              data-testid={`settings-ai-pricing-preview-${row.model}`}
                            >
                              {row.valid
                                ? `${row.model}: ${ai.usdInput} $${row.usdIn} · ${ai.usdOutput} $${row.usdOut} ${ai.usdPer1M}`
                                : `${row.model}: ${row.error}`}
                            </Badge>
                          );
                        })}
                      </div>
                    )}
                  </div>
                }
              />
            </div>

            {isAdmin && (
              <div
                className="mt-4 flex flex-col items-start gap-2"
                data-testid="settings-ai-save-area"
              >
                {formStatus === "saving" && (
                  <div
                    role="status"
                    data-testid="settings-ai-save-banner"
                    className="rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt-muted"
                  >
                    {ai.savingChanges}
                  </div>
                )}
                {formStatus === "saved" && (
                  <div
                    role="status"
                    data-testid="settings-ai-save-banner"
                    className="rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text"
                  >
                    {ai.savedChanges}
                  </div>
                )}
                {formStatus === "error" && (
                  <div
                    role="alert"
                    data-testid="settings-ai-save-banner"
                    className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
                  >
                    {formError ?? ai.saveError}
                  </div>
                )}
                <Button
                  type="button"
                  loading={formStatus === "saving"}
                  disabled={formStatus === "saving"}
                  onClick={() => void handleSaveChanges()}
                  data-testid="settings-ai-save-changes"
                >
                  {formStatus === "saving" ? ai.savingChanges : ai.saveChanges}
                </Button>
              </div>
            )}
          </>
        )}
      {settingsRead.status === "ready" && catalogRead.status === "ready" && (
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
      className="mt-5 rounded-lg border border-hairline bg-surface p-4"
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
