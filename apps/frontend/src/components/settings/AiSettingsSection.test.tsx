// #924: catalog-driven AI & LLM section tests.
// Covers dependent provider/model/ASR filtering, custom-model escape hatch,
// pricing-table USD preview, the single "Save changes" flow (#939), admin
// writes vs operator read-only, and catalog load states.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchAiProviderCatalog,
  fetchEffectiveSettings,
  fetchSettingHistory,
  writeSetting,
  type AiProviderCatalogEntry,
  type EffectiveSetting,
  type SettingHistoryEntry,
  type SettingSource,
} from "@/lib/operator/settings";

import { AiSettingsSection } from "@/components/settings/AiSettingsSection";

vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/operator/settings");

const mockUseAuth = vi.mocked(useAuth);
const mockFetchEffectiveSettings = vi.mocked(fetchEffectiveSettings);
const mockFetchAiProviderCatalog = vi.mocked(fetchAiProviderCatalog);
const mockFetchSettingHistory = vi.mocked(fetchSettingHistory);
const mockWriteSetting = vi.mocked(writeSetting);

const en = STRINGS.en.operatorSettings.ai;

const providers: AiProviderCatalogEntry[] = [
  {
    id: "mock",
    provider: "mock",
    provider_id: "mock",
    display_name: "Mock (offline)",
    base_url: "",
    chat_models: ["mock-model"],
    asr_models: [],
    api_key_env: "",
  },
  {
    id: "openai_compatible",
    provider: "openai_compatible",
    provider_id: "openai_compatible",
    display_name: "OpenAI-compatible",
    base_url: "https://api.openai.com/v1",
    chat_models: ["gpt-oss-120b", "gemini-3.6-flash", "mock-model"],
    asr_models: ["whisper-large-v3-turbo", "whisper-large-v3"],
    api_key_env: "AI_API_KEY",
  },
];

const settings: EffectiveSetting[] = [
  {
    key: "ai.provider",
    value: "mock",
    source: "environment",
    editable: true,
    restart_required: false,
  },
  {
    key: "ai.model",
    value: "mock-model",
    source: "environment",
    editable: true,
    restart_required: false,
  },
  {
    key: "ai.asr_model",
    value: "whisper-large-v3-turbo",
    source: "default",
    editable: true,
    restart_required: false,
  },
  {
    key: "ai.fallback_provider",
    value: "mock",
    source: "environment",
    editable: false,
    restart_required: false,
  },
  {
    key: "ai.fallback_model",
    value: "mock-model",
    source: "environment",
    editable: false,
    restart_required: false,
  },
  {
    key: "ai.pricing_table",
    value: "mock-model:0:0",
    source: "environment",
    editable: true,
    restart_required: false,
  },
];

function adminAuth() {
  return {
    user: { id: 1, phone: "+910000000000", roles: ["operator"], tier: "admin" },
  } as ReturnType<typeof useAuth>;
}

function operatorAuth() {
  return {
    user: {
      id: 2,
      phone: "+910000000001",
      roles: ["operator"],
      tier: "operator",
    },
  } as ReturnType<typeof useAuth>;
}

async function renderSection(
  auth = adminAuth(),
  catalog = providers,
  settingsRows = settings,
) {
  mockUseAuth.mockReturnValue(auth);
  mockFetchEffectiveSettings.mockResolvedValue(settingsRows);
  mockFetchAiProviderCatalog.mockResolvedValue(catalog);

  render(
    <AiSettingsSection
      t={STRINGS.en.operatorSettings}
      isAdmin={auth.user?.tier === "admin"}
    />,
  );
}

describe("AiSettingsSection (#924)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    __resetLangForTests();
    mockUseAuth.mockReturnValue(adminAuth());
    mockFetchEffectiveSettings.mockResolvedValue(settings);
    mockFetchAiProviderCatalog.mockResolvedValue(providers);
    mockFetchSettingHistory.mockResolvedValue([]);
  });

  it("renders each AI field row from the catalog", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("settings-ai-model-select")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-asr-select")).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-ai-fallback-provider-select"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-ai-fallback-model-select"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-pricing-table")).toBeInTheDocument();
    // #939: the auto-derived base URL pill is gone from the section.
    expect(screen.queryByTestId("settings-ai-base-url")).toBeNull();
  });

  it("filters model options by the chosen provider", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    expect(modelSelect.options.length).toBeGreaterThanOrEqual(1);
  });

  it("filters ASR options by the chosen provider", async () => {
    await renderSection();

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-asr-select")).toBeInTheDocument();
    });

    // Mock provider has no ASR models; the select exists but may be empty.
    // Dependent filtering is verified by the provider-change test below.
    const asrSelect = screen.getByTestId(
      "settings-ai-asr-select",
    ) as HTMLSelectElement;
    expect(asrSelect).toBeInTheDocument();
  });

  it("re-filters models and ASR options when the provider changes", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-provider-select"),
      ).toBeInTheDocument();
    });

    const providerSelect = screen.getByTestId(
      "settings-ai-provider-select",
    ) as HTMLSelectElement;
    // Pre-change: the mock provider has no ASR models; only the carried-over
    // effective value shows as an option (#939: drafts track current).
    expect(
      (screen.getByTestId("settings-ai-asr-select") as HTMLSelectElement)
        .options.length,
    ).toBe(1);
    fireEvent.change(providerSelect, {
      target: { value: "openai_compatible" },
    });

    await waitFor(() => {
      const modelSelect = screen.getByTestId(
        "settings-ai-model-select",
      ) as HTMLSelectElement;
      // #939: drafts track current, so the selection carries over when the
      // new provider still offers the same model.
      expect(modelSelect).toHaveValue("mock-model");
      const modelValues = Array.from(modelSelect.options).map((o) => o.value);
      expect(modelValues).toEqual([
        "gpt-oss-120b",
        "gemini-3.6-flash",
        "mock-model",
        "__custom__",
      ]);
    });

    // #931: the ASR list follows the same provider switch.
    const asrSelect = screen.getByTestId(
      "settings-ai-asr-select",
    ) as HTMLSelectElement;
    const asrValues = Array.from(asrSelect.options).map((o) => o.value);
    expect(asrValues).toEqual(["whisper-large-v3-turbo", "whisper-large-v3"]);
  });

  it("#931: lays the four model selects out in one responsive grid block", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-models-block"),
      ).toBeInTheDocument();
    });

    const block = screen.getByTestId("settings-ai-models-block");
    for (const [fieldKey, editable] of [
      ["ai.model", true],
      ["ai.asr_model", true],
      ["ai.fallback_provider", false],
      ["ai.fallback_model", false],
    ] as Array<[string, boolean]>) {
      const row = within(block).getByTestId(`settings-ai-row-${fieldKey}`);
      expect(row).toBeInTheDocument();
      // Every row keeps its source badge; there is no per-row save control.
      expect(
        within(row).getByTestId(`settings-ai-source-${fieldKey}`),
      ).toBeInTheDocument();
      expect(
        within(row).queryByTestId(`settings-ai-save-${fieldKey}`),
      ).toBeNull();
      // The read-only marker appears exactly when the row is not editable.
      expect(
        Boolean(within(row).queryByTestId(`settings-ai-readonly-${fieldKey}`)),
      ).toBe(!editable);
    }
    // The pricing table stays outside the models block.
    expect(within(block).queryByTestId("settings-ai-pricing-table")).toBeNull();
  });

  it("#931: reveals the custom-model input directly beneath its select", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });

    const customInput = await screen.findByTestId("settings-ai-model-custom");
    expect(customInput.previousElementSibling).toBe(modelSelect);

    // The fallback-model select gets the same treatment.
    const fallbackSelect = screen.getByTestId(
      "settings-ai-fallback-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(fallbackSelect, { target: { value: "__custom__" } });

    const fallbackCustom = await screen.findByTestId(
      "settings-ai-fallback-model-custom",
    );
    expect(fallbackCustom.previousElementSibling).toBe(fallbackSelect);
  });

  it("shows the custom-model escape hatch and preview price", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-custom"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("settings-ai-model-custom"), {
      target: { value: "new-model" },
    });

    const pricing = screen.getByTestId(
      "settings-ai-pricing-table",
    ) as HTMLTextAreaElement;
    fireEvent.change(pricing, { target: { value: "new-model:100:200" } });

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-pricing-preview-new-model"),
      ).toHaveTextContent(/\$11,299/);
    });
  });

  it("rejects a custom model with no pricing entry", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });

    fireEvent.change(screen.getByTestId("settings-ai-model-custom"), {
      target: { value: "unpriced-model" },
    });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.model"),
      ).toHaveTextContent(en.validationCustomPrice);
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  // --- Pricing block reskin (#932): helper chips + inline validation ---

  it("#932: renders the pricing hint and the USD-per-1M preview as helper chips", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-pricing-table"),
      ).toBeInTheDocument();
    });

    // The paise-per-token hint line renders as a single helper chip.
    expect(screen.getByTestId("settings-ai-pricing-hint")).toHaveTextContent(
      en.pricingHint,
    );

    // The draft rows preview as USD-per-1M chips; 0 paise/token = $0.
    const pricing = screen.getByTestId(
      "settings-ai-pricing-table",
    ) as HTMLTextAreaElement;
    fireEvent.change(pricing, { target: { value: "mock-model:0:0" } });

    expect(
      screen.getByTestId("settings-ai-pricing-preview-mock-model"),
    ).toHaveTextContent(
      `mock-model: ${en.usdInput} $0.00 · ${en.usdOutput} $0.00 ${en.usdPer1M}`,
    );

    // A malformed line previews as an inline error chip near the field.
    fireEvent.change(pricing, {
      target: { value: "mock-model:0:0\nbad-line" },
    });

    expect(
      screen.getByTestId("settings-ai-pricing-preview-bad-line"),
    ).toHaveTextContent("bad-line: expected 'model:price_in:price_out'");
  });

  // #935: US2 - pricing is a distinct grouped block like provider/models/history.
  it("#935: wraps the pricing row in a settings-ai-pricing-block block", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-pricing-block"),
      ).toBeInTheDocument();
    });

    const block = screen.getByTestId("settings-ai-pricing-block");
    expect(
      within(block).getByTestId("settings-ai-pricing-table"),
    ).toBeInTheDocument();
    expect(
      within(block).getByTestId("settings-ai-pricing-hint"),
    ).toBeInTheDocument();
  });

  it("#932: shows the missing-value validation inline for an empty pricing table", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-pricing-table"),
      ).toBeInTheDocument();
    });

    const pricing = screen.getByTestId(
      "settings-ai-pricing-table",
    ) as HTMLTextAreaElement;
    fireEvent.change(pricing, { target: { value: "" } });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.pricing_table"),
      ).toHaveTextContent(en.validationRequired);
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  // --- Single "Save changes" flow (#939) ---

  it("#939: renders one primary save button and no per-row save buttons", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-changes"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("settings-ai-save-changes")).toHaveTextContent(
      en.saveChanges,
    );
    for (const key of [
      "ai.provider",
      "ai.model",
      "ai.asr_model",
      "ai.fallback_provider",
      "ai.fallback_model",
      "ai.pricing_table",
    ]) {
      expect(screen.queryByTestId(`settings-ai-save-${key}`)).toBeNull();
      expect(screen.queryByTestId(`settings-ai-save-status-${key}`)).toBeNull();
      expect(screen.queryByTestId(`settings-ai-save-error-${key}`)).toBeNull();
    }
  });

  it("#939: saves only the changed fields, in DOM order, on one click", async () => {
    mockWriteSetting.mockResolvedValue({
      setting_key: "ai.model",
      value: "gpt-oss-120b",
      version: 2,
    });

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("settings-ai-provider-select"), {
      target: { value: "openai_compatible" },
    });
    await waitFor(() => {
      const modelSelect = screen.getByTestId(
        "settings-ai-model-select",
      ) as HTMLSelectElement;
      expect(
        modelSelect.querySelector('option[value="gpt-oss-120b"]'),
      ).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId("settings-ai-model-select"), {
      target: { value: "gpt-oss-120b" },
    });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledTimes(2);
    });
    expect(mockWriteSetting.mock.calls[0]).toEqual([
      "ai.provider",
      "openai_compatible",
    ]);
    expect(mockWriteSetting.mock.calls[1]).toEqual([
      "ai.model",
      "gpt-oss-120b",
    ]);
  });

  it("#939: is a no-op when nothing changed", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-changes"),
      ).toBeInTheDocument();
    });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-save-banner")).toBeNull();
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  it("#939: stops on the first failed write and shows its field error", async () => {
    mockWriteSetting.mockRejectedValueOnce(
      new ApiError({
        code: "INVALID_SETTING_WRITE",
        message: "provider write refused",
        trace_id: "trace-939",
        details: {},
      }),
    );

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("settings-ai-provider-select"), {
      target: { value: "openai_compatible" },
    });
    await waitFor(() => {
      const modelSelect = screen.getByTestId(
        "settings-ai-model-select",
      ) as HTMLSelectElement;
      expect(
        modelSelect.querySelector('option[value="gpt-oss-120b"]'),
      ).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId("settings-ai-model-select"), {
      target: { value: "gpt-oss-120b" },
    });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.provider"),
      ).toHaveTextContent("provider write refused");
    });
    // The first write failed, so the second never fired.
    expect(mockWriteSetting).toHaveBeenCalledTimes(1);
    // The aggregate banner above the button carries the same refusal.
    expect(screen.getByTestId("settings-ai-save-banner")).toHaveTextContent(
      "provider write refused",
    );
    expect(screen.getByTestId("settings-ai-save-changes")).toBeEnabled();
  });

  it("#939: shows the aggregate banner's saving then saved states", async () => {
    let resolveWrite: ((value: unknown) => void) | undefined;
    mockWriteSetting.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveWrite = resolve;
        }),
    );

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("settings-ai-pricing-table"), {
      target: { value: "mock-model:100:200" },
    });
    fireEvent.click(screen.getByTestId("settings-ai-save-changes"));

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-save-banner")).toHaveTextContent(
        en.savingChanges,
      );
    });
    expect(screen.getByTestId("settings-ai-save-changes")).toBeDisabled();

    resolveWrite?.({
      setting_key: "ai.pricing_table",
      value: "mock-model:100:200",
      version: 2,
    });

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-save-banner")).toHaveTextContent(
        en.savedChanges,
      );
    });
    expect(mockWriteSetting).toHaveBeenCalledWith(
      "ai.pricing_table",
      "mock-model:100:200",
    );
  });

  it("#939: shows read-only controls for a non-admin operator", async () => {
    await renderSection(operatorAuth());

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId("settings-ai-model-select")).toBeDisabled();
    expect(screen.getByTestId("settings-ai-pricing-table")).toBeDisabled();
    expect(
      screen.getByTestId("settings-ai-readonly-ai.model"),
    ).toHaveTextContent(en.readOnly);
    expect(screen.queryByTestId("settings-ai-save-ai.model")).toBeNull();
    // The single save button is the one control the read-only surface
    // does not get.
    expect(screen.queryByTestId("settings-ai-save-changes")).toBeNull();
  });

  it("shows a retryable error when the catalog fails", async () => {
    mockFetchAiProviderCatalog
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(providers);

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-catalog-error"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(en.catalogError)).toBeInTheDocument();

    screen.getByTestId("settings-ai-catalog-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });
  });

  // #933: the section's load, error, and empty states.
  it("#933: shows skeleton placeholders while the section loads", async () => {
    mockUseAuth.mockReturnValue(adminAuth());
    mockFetchEffectiveSettings.mockReturnValue(new Promise(() => {}));
    mockFetchAiProviderCatalog.mockReturnValue(new Promise(() => {}));

    render(
      <AiSettingsSection t={STRINGS.en.operatorSettings} isAdmin={true} />,
    );

    expect(screen.getByTestId("settings-ai-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-ai-band")).toBeNull();
    expect(screen.queryByTestId("settings-ai-row-ai.provider")).toBeNull();
  });

  it("#933: shows the empty state when the provider catalog is empty", async () => {
    await renderSection(adminAuth(), []);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
    expect(screen.getByTestId("empty-state-title")).toHaveTextContent(
      en.catalogEmpty,
    );
    expect(screen.queryByTestId("settings-ai-band")).toBeNull();
    expect(screen.queryByTestId("settings-ai-model-select")).toBeNull();
  });

  it("#933: shows a retryable error when the effective settings fail", async () => {
    mockFetchEffectiveSettings
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(settings);

    await renderSection();

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-error")).toBeInTheDocument();
    });
    expect(screen.getByText(en.error)).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-error-no-trace")).toHaveTextContent(
      en.noTrace,
    );

    screen.getByTestId("settings-ai-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });
  });

  it("#933: shows the API's trace id on an expected settings error", async () => {
    mockFetchEffectiveSettings.mockRejectedValueOnce(
      new ApiError({
        code: "FORBIDDEN",
        message: "Operator admin role required",
        trace_id: "trace-933",
        details: {},
      }),
    );

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-error-trace-id"),
      ).toHaveTextContent("trace-933");
    });
    expect(screen.getByText(en.errorExpected)).toBeInTheDocument();
  });

  it("#933: shows a retryable error when the history read fails", async () => {
    mockFetchSettingHistory
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce([]);

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-error"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(en.historyError)).toBeInTheDocument();

    screen.getByTestId("settings-ai-history-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-empty"),
      ).toBeInTheDocument();
    });
  });

  it("renders the Hindi locale", async () => {
    const hi = STRINGS.hi.operatorSettings.ai;

    function LangFlipHost() {
      const { lang, setLang } = useLang();
      return (
        <>
          <button
            type="button"
            onClick={() => setLang(lang === "en" ? "hi" : "en")}
          >
            flip-lang
          </button>
          <AiSettingsSection
            t={STRINGS[lang].operatorSettings}
            isAdmin={true}
          />
        </>
      );
    }

    render(<LangFlipHost />);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });

    screen.getByText("flip-lang").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(hi.provider)).toBeInTheDocument();
    expect(screen.getByText(hi.model)).toBeInTheDocument();
  });

  it("shows history entries for AI keys", async () => {
    const history: SettingHistoryEntry[] = [
      {
        setting_key: "ai.model",
        value: "gpt-oss-120b",
        version: 2,
        changed_by: 7,
        changed_at: "2026-03-04T10:00:00Z",
      },
    ];
    mockFetchSettingHistory.mockResolvedValue(history);

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-row-ai.model-2"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("settings-ai-history-row-ai.model-2"),
    ).toHaveTextContent("gpt-oss-120b");
  });

  it("shows the API's refusal message for a failed write", async () => {
    mockWriteSetting.mockRejectedValue(
      new ApiError({
        code: "INVALID_SETTING_WRITE",
        message: "custom model needs a pricing entry",
        trace_id: "trace-924",
        details: {},
      }),
    );

    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    // Pick a custom model WITH a pricing entry so client-side validation
    // passes and the write reaches the API, which then rejects it.
    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByTestId("settings-ai-model-custom"), {
      target: { value: "some-model" },
    });
    fireEvent.change(screen.getByTestId("settings-ai-pricing-table"), {
      target: { value: "some-model:1:2" },
    });

    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.model"),
      ).toHaveTextContent("custom model needs a pricing entry");
    });
    expect(screen.getByTestId("settings-ai-save-banner")).toHaveTextContent(
      "custom model needs a pricing entry",
    );
  });

  // --- API key field: masked status states (#925, reskinned in #930) ---

  function apiKeySettings(
    apiKeyValue: string | null,
    source: SettingSource,
    provider = "openai_compatible",
  ): EffectiveSetting[] {
    return [
      {
        key: "ai.provider",
        value: provider,
        source: "environment",
        editable: true,
        restart_required: false,
      },
      {
        key: "ai.api_key",
        value: apiKeyValue,
        source,
        editable: true,
        restart_required: false,
      },
    ];
  }

  it("renders the API key field with the env status (no status badge)", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("configured from environment", "environment"),
    );

    // Env-configured: no password input, no status badge
    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });
  });

  it("renders the API key field with the dashboard status (no status badge)", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings(
        "configured from dashboard, set 2026-03-04T10:00:00Z",
        "database",
      ),
    );

    // Dashboard-configured: no password input, no status badge
    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });
  });

  it("renders the API key field with the missing state (shows input, no status badge)", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-input"),
      ).toBeInTheDocument();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });
  });

  it("hides the API key field for the mock provider (no key required)", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default", "mock"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-provider-select"),
      ).toBeInTheDocument();
    });
    // No key required: neither the key row nor its input renders (#930).
    expect(screen.queryByTestId("settings-ai-row-ai.api_key")).toBeNull();
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
  });

  it("#939: places the provider select and the API key input side by side in one block", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    const block = await screen.findByTestId("settings-ai-provider-block");
    const providerRow = within(block).getByTestId(
      "settings-ai-row-ai.provider",
    );
    expect(
      within(providerRow).getByTestId("settings-ai-provider-select"),
    ).toBeInTheDocument();
    // The key field is the provider select's side-by-side companion in the
    // same grid row; the base-URL pill is gone (#939).
    const keyRow = within(block).getByTestId("settings-ai-row-ai.api_key");
    const keyInput = within(keyRow).getByTestId("settings-ai-api-key-input");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(within(block).queryByTestId("settings-ai-base-url")).toBeNull();
    // The provider row keeps its source badge in the label position.
    expect(
      within(block).getByTestId("settings-ai-source-ai.provider"),
    ).toHaveTextContent(en.sources.environment);
    // The API key status badge is removed.
    expect(
      within(block).queryByTestId("settings-ai-api-key-status"),
    ).toBeNull();
  });

  it("saves an API key end to end and flips status to dashboard", async () => {
    mockWriteSetting.mockResolvedValue({
      setting_key: "ai.api_key",
      value: "sk-live-dashboard-key",
      version: 1,
    });

    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-input"),
      ).toBeInTheDocument();
    });
    // The reload after a successful write resolves to the dashboard state.
    mockFetchEffectiveSettings.mockResolvedValue(
      apiKeySettings(
        "configured from dashboard, set 2026-03-04T10:00:00Z",
        "database",
      ),
    );

    fireEvent.change(screen.getByTestId("settings-ai-api-key-input"), {
      target: { value: "sk-live-dashboard-key" },
    });
    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith(
        "ai.api_key",
        "sk-live-dashboard-key",
      );
    });
    // After the reload the key is dashboard-configured: no password input
    // and no status badge (#930).
    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });
    // Plaintext never renders anywhere.
    expect(screen.queryByText("sk-live-dashboard-key")).toBeNull();
  });

  it("shows the server's rejection message for a failed API key write", async () => {
    mockWriteSetting.mockRejectedValue(
      new ApiError({
        code: "INVALID_SETTING_WRITE",
        message: "non-mock provider requires a resolvable API key",
        trace_id: "trace-925",
        details: {},
      }),
    );

    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-input"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("settings-ai-api-key-input"), {
      target: { value: "sk-key" },
    });
    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.api_key"),
      ).toHaveTextContent("non-mock provider requires a resolvable API key");
    });
  });

  // --- Status band (#929) ---

  const bandSettings: EffectiveSetting[] = [
    {
      key: "ai.provider",
      value: "openai_compatible",
      source: "environment",
      editable: true,
      restart_required: false,
    },
    {
      key: "ai.model",
      value: "gpt-oss-120b",
      source: "environment",
      editable: true,
      restart_required: false,
    },
    {
      key: "ai.asr_model",
      value: "whisper-large-v3-turbo",
      source: "default",
      editable: true,
      restart_required: false,
    },
    {
      key: "ai.pricing_table",
      value: "gpt-oss-120b:100:200\nwhisper-large-v3-turbo:50:50\nbad-line",
      source: "environment",
      editable: true,
      restart_required: false,
    },
  ];

  it("renders the status band from effective settings and the catalog", async () => {
    await renderSection(adminAuth(), providers, bandSettings);

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-band")).toBeInTheDocument();
    });
    expect(screen.getByTestId("settings-ai-band-provider")).toHaveTextContent(
      "OpenAI-compatible",
    );
    expect(screen.getByTestId("settings-ai-band-model")).toHaveTextContent(
      "gpt-oss-120b",
    );
    expect(screen.getByTestId("settings-ai-band-asr")).toHaveTextContent(
      "whisper-large-v3-turbo",
    );
    // #939: the base-URL pill is gone from the band.
    expect(screen.queryByTestId("settings-ai-band-base-url")).toBeNull();
    // Only the two well-formed pricing lines count; "bad-line" does not.
    expect(
      screen.getByTestId("settings-ai-band-pricing-count"),
    ).toHaveTextContent(en.bandPricingEntries(2));
    // The refreshed stamp lands in an effect after the band commits - wait
    // for it instead of racing it.
    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-band-refresh")).toHaveTextContent(
        en.bandRefreshed,
      );
    });
  });

  it("derives the status band without new network requests", async () => {
    await renderSection(adminAuth(), providers, bandSettings);

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-band")).toBeInTheDocument();
    });
    expect(mockFetchEffectiveSettings).toHaveBeenCalledTimes(1);
    expect(mockFetchAiProviderCatalog).toHaveBeenCalledTimes(1);
    expect(mockFetchSettingHistory).toHaveBeenCalledTimes(1);
  });

  it("renders the API key field in Hindi", async () => {
    const hi = STRINGS.hi.operatorSettings.ai;
    mockFetchEffectiveSettings.mockResolvedValue(
      apiKeySettings("configured from environment", "environment"),
    );

    function LangFlipHost() {
      const { lang, setLang } = useLang();
      return (
        <>
          <button
            type="button"
            onClick={() => setLang(lang === "en" ? "hi" : "en")}
          >
            flip-lang
          </button>
          <AiSettingsSection
            t={STRINGS[lang].operatorSettings}
            isAdmin={true}
          />
        </>
      );
    }

    render(<LangFlipHost />);

    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });

    screen.getByText("flip-lang").click();

    await waitFor(() => {
      expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
      expect(screen.queryByTestId("settings-ai-api-key-status")).toBeNull();
    });
    // Env-configured: no password input, no status badge in Hindi either.
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
  });

  // #934: every visible label is programmatically tied to its control.
  it("associates every visible label with its control via htmlFor/id", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });

    const pairs: Array<{
      fieldKey: string;
      controlTestId: string;
      labelText: string;
    }> = [
      {
        fieldKey: "ai.provider",
        controlTestId: "settings-ai-provider-select",
        labelText: en.provider,
      },
      {
        fieldKey: "ai.model",
        controlTestId: "settings-ai-model-select",
        labelText: en.model,
      },
      {
        fieldKey: "ai.asr_model",
        controlTestId: "settings-ai-asr-select",
        labelText: en.asrModel,
      },
      {
        fieldKey: "ai.fallback_provider",
        controlTestId: "settings-ai-fallback-provider-select",
        labelText: en.fallbackProvider,
      },
      {
        fieldKey: "ai.fallback_model",
        controlTestId: "settings-ai-fallback-model-select",
        labelText: en.fallbackModel,
      },
      {
        fieldKey: "ai.pricing_table",
        controlTestId: "settings-ai-pricing-table",
        labelText: en.pricingTable,
      },
    ];

    for (const { fieldKey, controlTestId, labelText } of pairs) {
      const control = screen.getByTestId(controlTestId);
      expect(control).toHaveAttribute("id", fieldKey);
      const label = document.querySelector(`label[for="${fieldKey}"]`);
      expect(label).not.toBeNull();
      expect(label?.textContent).toBe(labelText);
    }
  });

  // #934: the API key row (rendered inline, not via AiFieldRow) keeps the same
  // label-to-control association when a key-requiring provider is selected.
  it("associates the API key label with its input", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-input"),
      ).toBeInTheDocument();
    });

    const apiKeyInput = screen.getByTestId("settings-ai-api-key-input");
    expect(apiKeyInput).toHaveAttribute("id", "ai.api_key");
    expect(document.querySelector('label[for="ai.api_key"]')).not.toBeNull();
  });

  // #934: error text is announced as an alert.
  it("renders save errors with role=alert", async () => {
    await renderSection();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByTestId("settings-ai-model-custom"), {
      target: { value: "unpriced-model" },
    });
    screen.getByTestId("settings-ai-save-changes").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-field-error-ai.model"),
      ).toHaveAttribute("role", "alert");
    });
  });
});
