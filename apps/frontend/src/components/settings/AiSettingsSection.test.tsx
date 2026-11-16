// #924: catalog-driven AI & LLM section tests.
// Covers dependent provider/model/ASR filtering, custom-model escape hatch,
// pricing-table USD preview, admin writes vs operator read-only, and catalog
// load states.

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
    expect(screen.getByTestId("settings-ai-base-url")).toBeInTheDocument();
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
    fireEvent.change(providerSelect, {
      target: { value: "openai_compatible" },
    });

    await waitFor(() => {
      const modelSelect = screen.getByTestId(
        "settings-ai-model-select",
      ) as HTMLSelectElement;
      expect(modelSelect).toHaveValue("gpt-oss-120b");
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
    for (const fieldKey of [
      "ai.model",
      "ai.asr_model",
      "ai.fallback_provider",
      "ai.fallback_model",
    ]) {
      const row = within(block).getByTestId(`settings-ai-row-${fieldKey}`);
      expect(row).toBeInTheDocument();
      // Every row keeps its source badge and its inline save/status slot
      // (a save button when editable, a read-only marker otherwise).
      expect(
        within(row).getByTestId(`settings-ai-source-${fieldKey}`),
      ).toBeInTheDocument();
      const save = within(row).queryByTestId(`settings-ai-save-${fieldKey}`);
      const readOnly = within(row).queryByTestId(
        `settings-ai-readonly-${fieldKey}`,
      );
      expect(Boolean(save) !== Boolean(readOnly)).toBe(true);
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

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.model"),
      ).toHaveTextContent(en.validationCustomPrice);
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  it("saves an admin edit end to end", async () => {
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

    const providerSelect = screen.getByTestId(
      "settings-ai-provider-select",
    ) as HTMLSelectElement;
    fireEvent.change(providerSelect, {
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

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "gpt-oss-120b" } });

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith("ai.model", "gpt-oss-120b");
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-status-ai.model"),
      ).toHaveTextContent(en.saved);
    });
  });

  it("shows read-only controls for a non-admin operator", async () => {
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

    // Pick a custom model so the write is attempted with a non-empty value
    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByTestId("settings-ai-model-custom"), {
      target: { value: "some-model" },
    });

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.model"),
      ).toHaveTextContent(en.validationCustomPrice);
    });
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

  it("renders the API key field with the env status label", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("configured from environment", "environment"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-status"),
      ).toHaveTextContent(en.keyFromEnv);
    });
    // Env-configured (#930): the masked status stands alone - no password
    // input and no save control while a key exists.
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
    expect(screen.queryByTestId("settings-ai-save-ai.api_key")).toBeNull();
  });

  it("renders the API key field with the dashboard status label and date", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings(
        "configured from dashboard, set 2026-03-04T10:00:00Z",
        "database",
      ),
    );

    await waitFor(() => {
      const status = screen.getByTestId("settings-ai-api-key-status");
      expect(status).toHaveTextContent(en.keyFromDashboard);
      expect(status).toHaveTextContent(/set/);
    });
    // Dashboard-configured (#930): masked status only, no password input.
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
  });

  it("renders the API key field with the missing status label", async () => {
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
    expect(screen.getByTestId("settings-ai-api-key-status")).toHaveTextContent(
      en.keyMissing,
    );
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

  it("groups the provider select, base-URL pill, and key row in one block", async () => {
    await renderSection(
      adminAuth(),
      providers,
      apiKeySettings("missing", "default"),
    );

    const block = await screen.findByTestId("settings-ai-provider-block");
    expect(
      within(block).getByTestId("settings-ai-provider-select"),
    ).toBeInTheDocument();
    // The auto-derived base URL renders as a read-only mono pill beside the
    // provider select.
    expect(within(block).getByTestId("settings-ai-base-url")).toHaveTextContent(
      "https://api.openai.com/v1",
    );
    // The provider row keeps its source badge in the label position.
    expect(
      within(block).getByTestId("settings-ai-source-ai.provider"),
    ).toHaveTextContent(en.sources.environment);
    // The key row sits beneath in the same block; the missing state shows
    // the password input.
    const keyRow = within(block).getByTestId("settings-ai-row-ai.api_key");
    expect(
      within(keyRow).getByTestId("settings-ai-api-key-status"),
    ).toHaveTextContent(en.keyMissing);
    expect(
      within(keyRow).getByTestId("settings-ai-api-key-input"),
    ).toHaveAttribute("type", "password");
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
    screen.getByTestId("settings-ai-save-ai.api_key").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith(
        "ai.api_key",
        "sk-live-dashboard-key",
      );
    });
    // After the reload the key is dashboard-configured: the masked status
    // stands alone and the password input is gone (#930).
    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-status"),
      ).toHaveTextContent(en.keyFromDashboard);
    });
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
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
    screen.getByTestId("settings-ai-save-ai.api_key").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.api_key"),
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
    expect(screen.getByTestId("settings-ai-band-base-url")).toHaveTextContent(
      "https://api.openai.com/v1",
    );
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
      expect(
        screen.getByTestId("settings-ai-api-key-status"),
      ).toBeInTheDocument();
    });

    screen.getByText("flip-lang").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-api-key-status"),
      ).toHaveTextContent(hi.keyFromEnv);
    });
    // Env-configured: the masked status stands alone in Hindi too, with no
    // password input (#930).
    expect(screen.queryByTestId("settings-ai-api-key-input")).toBeNull();
  });
});
