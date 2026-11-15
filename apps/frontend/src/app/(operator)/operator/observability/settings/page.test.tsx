// #797: the admin Settings shell and its AI section.
// #798: the allowlisted AI knobs gain editable controls, save states,
// validation copy, and the append-only setting history beneath the table.
// #800: the Feature Flags section with runtime/restart-required flags and history.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchAiProviderCatalog,
  fetchEffectiveSettings,
  fetchFeatureFlags,
  fetchFeatureFlagHistory,
  fetchSettingHistory,
  fetchAlertDeliveries,
  writeFeatureFlag,
  writeSetting,
  type AiProviderCatalogEntry,
  type EffectiveSetting,
  type FeatureFlag,
  type FeatureFlagHistoryEntry,
  type SettingHistoryEntry,
} from "@/lib/operator/settings";

import ObservabilitySettingsPage from "./page";

vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/operator/settings");

const mockUseAuth = vi.mocked(useAuth);
const mockFetchEffectiveSettings = vi.mocked(fetchEffectiveSettings);
const mockFetchAiProviderCatalog = vi.mocked(fetchAiProviderCatalog);
const mockFetchFeatureFlags = vi.mocked(fetchFeatureFlags);
const mockFetchFeatureFlagHistory = vi.mocked(fetchFeatureFlagHistory);
const mockFetchSettingHistory = vi.mocked(fetchSettingHistory);
const mockFetchAlertDeliveries = vi.mocked(fetchAlertDeliveries);
const mockWriteFeatureFlag = vi.mocked(writeFeatureFlag);
const mockWriteSetting = vi.mocked(writeSetting);

const en = STRINGS.en.operatorSettings;
const hi = STRINGS.hi.operatorSettings;

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

const settings: EffectiveSetting[] = [
  {
    key: "ai.provider",
    value: "mock",
    source: "environment",
    editable: false,
    restart_required: false,
  },
  {
    key: "ai.model",
    value: null,
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
    value: null,
    source: "environment",
    editable: true,
    restart_required: false,
  },
  {
    key: "ai.pricing_table",
    value: "mock-model:0:0",
    source: "environment",
    editable: true,
    restart_required: false,
  },
  {
    key: "notification.channels.slack.enabled",
    value: false,
    source: "default",
    editable: true,
    restart_required: false,
  },
  {
    key: "notification.channels.email.enabled",
    value: false,
    source: "default",
    editable: true,
    restart_required: false,
  },
  {
    key: "notification.email.recipients",
    value: [],
    source: "default",
    editable: true,
    restart_required: false,
  },
  {
    key: "notification.routing.ai_budget",
    value: "none",
    source: "default",
    editable: true,
    restart_required: false,
  },
  {
    key: "notification.routing.provider_health_drop",
    value: "none",
    source: "default",
    editable: true,
    restart_required: false,
  },
];

const featureFlags: FeatureFlag[] = [
  {
    flag_key: "test.runtime_flag",
    enabled: true,
    flag_kind: "runtime",
    description: "A runtime flag",
    editable: true,
    updated_at: "2026-03-04T10:00:00Z",
  },
  {
    flag_key: "test.restart_flag",
    enabled: false,
    flag_kind: "restart_required",
    description: "A restart-required flag",
    editable: false,
    updated_at: "2026-03-03T10:00:00Z",
  },
];

const featureFlagHistory: FeatureFlagHistoryEntry[] = [
  {
    flag_key: "test.runtime_flag",
    enabled: true,
    flag_kind: "runtime",
    version: 2,
    changed_by: 7,
    changed_at: "2026-03-04T10:00:00Z",
  },
  {
    flag_key: "test.runtime_flag",
    enabled: false,
    flag_kind: "runtime",
    version: 1,
    changed_by: null,
    changed_at: "2026-03-03T09:00:00Z",
  },
];

async function renderReady() {
  render(<ObservabilitySettingsPage />);
  await waitFor(() => {
    expect(
      screen.getByTestId("settings-ai-row-ai.provider"),
    ).toBeInTheDocument();
  });
}

async function renderFeatureFlagsReady() {
  render(<ObservabilitySettingsPage />);
  await waitFor(() => {
    expect(
      screen.getByTestId("settings-feature-flags-row-test.runtime_flag"),
    ).toBeInTheDocument();
  });
}

describe("ObservabilitySettingsPage (#797)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    __resetLangForTests();
    mockUseAuth.mockReturnValue(adminAuth());
    mockFetchSettingHistory.mockResolvedValue([]);
    mockFetchFeatureFlagHistory.mockResolvedValue([]);
    mockFetchAlertDeliveries.mockResolvedValue({
      deliveries: [],
      total_count: 0,
      page: 1,
      page_size: 25,
    });
    mockFetchAiProviderCatalog.mockResolvedValue([
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
    ]);
  });

  it("renders the four-section shell", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);
    mockFetchFeatureFlags.mockResolvedValue(featureFlags);

    render(<ObservabilitySettingsPage />);

    expect(screen.getByTestId("page-header")).toHaveTextContent(en.title);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.timeout_seconds"),
      ).toBeInTheDocument();
    });

    for (const [testId, title] of [
      ["settings-ai", en.sections.ai],
      ["settings-notifications", en.sections.notifications],
      ["settings-feature-flags", en.sections.featureFlags],
      ["settings-users", en.sections.users],
    ] as const) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
      expect(screen.getByTestId(`${testId}-title`)).toHaveTextContent(title);
    }
  });

  it("shows effective AI values from the catalog with source badges", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);
    mockFetchAiProviderCatalog.mockResolvedValue([
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
    ]);

    render(<ObservabilitySettingsPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.provider"),
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId("settings-ai-model-select")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-asr-select")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-pricing-table")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-base-url")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-source-ai.model")).toHaveTextContent(
      en.ai.sources.environment,
    );
    expect(screen.getByTestId("settings-ai-takeaway")).toHaveTextContent(
      en.ai.takeaway(6),
    );
    expect(
      screen.queryByTestId(
        "settings-ai-row-notification.channels.email.enabled",
      ),
    ).toBeNull();
  });

  it("hides the page from non-admin operators", () => {
    mockUseAuth.mockReturnValue(operatorAuth());

    render(<ObservabilitySettingsPage />);

    expect(
      screen.getByTestId("settings-permission-denied"),
    ).toBeInTheDocument();
    expect(screen.getByText(en.permissionDeniedTitle)).toBeInTheDocument();
    expect(screen.queryByTestId("settings-shell")).toBeNull();
    expect(mockFetchEffectiveSettings).not.toHaveBeenCalled();
  });

  it("hides the page when there is no session", () => {
    mockUseAuth.mockReturnValue({ user: null } as ReturnType<typeof useAuth>);

    render(<ObservabilitySettingsPage />);

    expect(
      screen.getByTestId("settings-permission-denied"),
    ).toBeInTheDocument();
    expect(mockFetchEffectiveSettings).not.toHaveBeenCalled();
  });

  it("shows a retryable error when the read fails", async () => {
    mockFetchEffectiveSettings
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(settings);

    render(<ObservabilitySettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-error")).toBeInTheDocument();
    });
    expect(screen.getByText(en.ai.error)).toBeInTheDocument();
    expect(screen.getByText(en.ai.noTrace)).toBeInTheDocument();

    screen.getByTestId("settings-ai-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.timeout_seconds"),
      ).toBeInTheDocument();
    });
    // Called 3 times: initial AI + Notifications, then retry for AI + Notifications
    expect(mockFetchEffectiveSettings).toHaveBeenCalledTimes(3);
  });

  it("shows the API rejection copy for an expected error", async () => {
    mockFetchEffectiveSettings.mockRejectedValue(
      new ApiError({
        code: "FORBIDDEN",
        message: "Operator admin role required",
        trace_id: "trace-797",
        details: {},
      }),
    );

    render(<ObservabilitySettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-error")).toBeInTheDocument();
    });
    expect(screen.getByText(en.ai.errorExpected)).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-error-trace-id")).toHaveTextContent(
      "trace-797",
    );
    expect(screen.queryByText(en.ai.error)).toBeNull();
  });

  it("renders in Hindi when the locale flips", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);

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
          <ObservabilitySettingsPage />
        </>
      );
    }

    render(<LangFlipHost />);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.model"),
      ).toBeInTheDocument();
    });

    screen.getByText("flip-lang").click();

    await waitFor(() => {
      expect(screen.getByTestId("page-header")).toHaveTextContent(hi.title);
    });
    expect(screen.getByTestId("settings-ai-title")).toHaveTextContent(
      hi.sections.ai,
    );
    expect(
      screen.getByTestId("settings-notifications-title"),
    ).toHaveTextContent(hi.sections.notifications);
    expect(screen.getByTestId("settings-ai-source-ai.model")).toHaveTextContent(
      hi.ai.sources.environment,
    );
    expect(screen.getByTestId("settings-ai-save-ai.model")).toHaveTextContent(
      hi.ai.save,
    );
    expect(screen.getByTestId("settings-ai-history-title")).toHaveTextContent(
      hi.ai.historyTitle,
    );
  });
});

describe("AiSettingsSection writes and history (#798)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    __resetLangForTests();
    mockUseAuth.mockReturnValue(adminAuth());
    mockFetchEffectiveSettings.mockResolvedValue(settings);
    mockFetchSettingHistory.mockResolvedValue([]);
    mockFetchAiProviderCatalog.mockResolvedValue([
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
    ]);
  });

  it("only gives editable rows a control", async () => {
    await renderReady();

    expect(screen.getByTestId("settings-ai-model-select")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-asr-select")).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-pricing-table")).toBeInTheDocument();
    // ai.provider is not editable in the fixture
    expect(
      screen.getByTestId("settings-ai-readonly-ai.provider"),
    ).toHaveTextContent(en.ai.readOnly);
    // ai.pricing_table is editable, so it has a save button
    expect(
      screen.getByTestId("settings-ai-save-ai.pricing_table"),
    ).toBeInTheDocument();
  });

  it("saves an edited value and refreshes effective values and history", async () => {
    mockWriteSetting.mockResolvedValue({
      setting_key: "ai.model",
      value: "gpt-oss-120b",
      version: 2,
    });

    await renderReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    // Switch to a provider that offers gpt-oss-120b, then select it
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

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith("ai.model", "gpt-oss-120b");
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-status-ai.model"),
      ).toHaveTextContent(en.ai.saved);
    });
    expect(mockFetchEffectiveSettings).toHaveBeenCalledTimes(3);
    expect(mockFetchSettingHistory).toHaveBeenCalledTimes(3);
  });

  it("refuses an empty value before calling the API", async () => {
    await renderReady();

    const modelSelect = screen.getByTestId(
      "settings-ai-model-select",
    ) as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "" } });
    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.model"),
      ).toHaveTextContent(en.ai.validationRequired);
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  it("shows the API's refusal message for a failed write", async () => {
    mockWriteSetting.mockRejectedValue(
      new ApiError({
        code: "INVALID_SETTING_WRITE",
        message: "custom model needs a pricing entry",
        trace_id: "trace-798",
        details: {},
      }),
    );

    await renderReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    // Switch to openai_compatible so gpt-oss-120b passes the custom-model guard
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

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.model"),
      ).toHaveTextContent("custom model needs a pricing entry");
    });
    expect(screen.getByTestId("settings-ai-save-ai.model")).toBeEnabled();
  });

  it("shows the fallback copy for an unexpected write failure", async () => {
    mockWriteSetting.mockRejectedValue(new Error("network down"));

    await renderReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-model-select"),
      ).toBeInTheDocument();
    });

    // Switch to openai_compatible so gpt-oss-120b passes the custom-model guard
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

    screen.getByTestId("settings-ai-save-ai.model").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.model"),
      ).toHaveTextContent(en.ai.saveError);
    });
  });

  it("lists AI history newest first and hides non-AI rows", async () => {
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

    await renderReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-row-ai.model-2"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId(
        "settings-ai-history-row-notification.channels.email.enabled-1",
      ),
    ).toBeNull();
    expect(
      screen.getByTestId("settings-ai-history-row-ai.model-2"),
    ).toHaveTextContent("gpt-oss-120b");
  });

  it("says so when there is no history", async () => {
    await renderReady();

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-history-empty")).toHaveTextContent(
        en.ai.historyEmpty,
      );
    });
  });

  it("retries a failed history read", async () => {
    mockFetchSettingHistory
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce([]);

    await renderReady();

    await waitFor(() => {
      expect(screen.getByTestId("settings-ai-history-error")).toHaveTextContent(
        en.ai.historyError,
      );
    });

    screen.getByTestId("settings-ai-history-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-empty"),
      ).toBeInTheDocument();
    });
  });
});

describe("FeatureFlagsSettingsSection (#800)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    __resetLangForTests();
    mockUseAuth.mockReturnValue(adminAuth());
    mockFetchSettingHistory.mockResolvedValue([]);
    mockFetchFeatureFlagHistory.mockResolvedValue([]);
    mockFetchAlertDeliveries.mockResolvedValue({
      deliveries: [],
      total_count: 0,
      page: 1,
      page_size: 25,
    });
    mockFetchEffectiveSettings.mockResolvedValue(settings);
    mockFetchFeatureFlags.mockResolvedValue(featureFlags);
  });

  it("renders all flags with their type and editability", async () => {
    await renderFeatureFlagsReady();

    expect(
      screen.getByTestId("settings-feature-flags-row-test.runtime_flag"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-feature-flags-row-test.restart_flag"),
    ).toBeInTheDocument();

    expect(
      screen.getByTestId("settings-feature-flags-type-test.runtime_flag"),
    ).toHaveTextContent(en.featureFlags.runtime);
    expect(
      screen.getByTestId("settings-feature-flags-type-test.restart_flag"),
    ).toHaveTextContent(en.featureFlags.restartRequired);

    // Runtime flag has a toggle control
    expect(
      screen.getByTestId("settings-feature-flags-input-test.runtime_flag"),
    ).toBeInTheDocument();
    // Restart-required flag is read-only with explanation
    expect(
      screen.getByTestId("settings-feature-flags-readonly-test.restart_flag"),
    ).toHaveTextContent(en.featureFlags.readOnly);
    expect(
      screen.getByTestId(
        "settings-feature-flags-restart-explanation-test.restart_flag",
      ),
    ).toHaveTextContent(en.featureFlags.restartExplanation);
  });

  it("saves an edited runtime flag and refreshes flags and history", async () => {
    mockWriteFeatureFlag.mockResolvedValue({
      flag_key: "test.runtime_flag",
      enabled: false,
      flag_kind: "runtime",
      version: 3,
    });

    await renderFeatureFlagsReady();

    fireEvent.click(
      screen.getByTestId("settings-feature-flags-input-test.runtime_flag"),
    );
    screen.getByTestId("settings-feature-flags-save-test.runtime_flag").click();

    await waitFor(() => {
      expect(mockWriteFeatureFlag).toHaveBeenCalledWith(
        "test.runtime_flag",
        false,
      );
    });
    await waitFor(() => {
      expect(
        screen.getByTestId(
          "settings-feature-flags-save-status-test.runtime_flag",
        ),
      ).toHaveTextContent(en.featureFlags.saved);
    });
    expect(mockFetchFeatureFlags).toHaveBeenCalledTimes(2);
    expect(mockFetchFeatureFlagHistory).toHaveBeenCalledTimes(2);
  });

  it("shows the API's refusal message for a failed write", async () => {
    mockWriteFeatureFlag.mockRejectedValue(
      new ApiError({
        code: "INVALID_FEATURE_FLAG_WRITE",
        message: "flag is restart-required and cannot be edited at runtime",
        trace_id: "trace-800",
        details: {},
      }),
    );

    await renderFeatureFlagsReady();

    fireEvent.click(
      screen.getByTestId("settings-feature-flags-input-test.runtime_flag"),
    );
    screen.getByTestId("settings-feature-flags-save-test.runtime_flag").click();

    await waitFor(() => {
      expect(
        screen.getByTestId(
          "settings-feature-flags-save-error-test.runtime_flag",
        ),
      ).toHaveTextContent(
        "flag is restart-required and cannot be edited at runtime",
      );
    });
    expect(
      screen.getByTestId("settings-feature-flags-save-test.runtime_flag"),
    ).toBeEnabled();
  });

  it("shows the fallback copy for an unexpected write failure", async () => {
    mockWriteFeatureFlag.mockRejectedValue(new Error("network down"));

    await renderFeatureFlagsReady();

    fireEvent.click(
      screen.getByTestId("settings-feature-flags-input-test.runtime_flag"),
    );
    screen.getByTestId("settings-feature-flags-save-test.runtime_flag").click();

    await waitFor(() => {
      expect(
        screen.getByTestId(
          "settings-feature-flags-save-error-test.runtime_flag",
        ),
      ).toHaveTextContent(en.featureFlags.editError);
    });
  });

  it("lists flag history newest first", async () => {
    mockFetchFeatureFlagHistory.mockResolvedValue(featureFlagHistory);

    await renderFeatureFlagsReady();

    await waitFor(() => {
      expect(
        screen.getByTestId(
          "settings-feature-flags-history-row-test.runtime_flag-2",
        ),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId(
        "settings-feature-flags-history-row-test.runtime_flag-2",
      ),
    ).toHaveTextContent(en.featureFlags.toggleOn);
    expect(
      screen.getByTestId(
        "settings-feature-flags-history-row-test.runtime_flag-1",
      ),
    ).toHaveTextContent(en.featureFlags.toggleOff);
  });

  it("says so when there is no history", async () => {
    await renderFeatureFlagsReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-feature-flags-history-empty"),
      ).toHaveTextContent(en.featureFlags.historyEmpty);
    });
  });

  it("retries a failed history read", async () => {
    mockFetchFeatureFlagHistory
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce([]);

    await renderFeatureFlagsReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-feature-flags-history-error"),
      ).toHaveTextContent(en.featureFlags.historyError);
    });

    screen.getByTestId("settings-feature-flags-history-retry").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-feature-flags-history-empty"),
      ).toBeInTheDocument();
    });
  });

  it("renders in Hindi when the locale flips", async () => {
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
          <ObservabilitySettingsPage />
        </>
      );
    }

    render(<LangFlipHost />);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-feature-flags-row-test.runtime_flag"),
      ).toBeInTheDocument();
    });

    screen.getByText("flip-lang").click();

    await waitFor(() => {
      expect(screen.getByTestId("page-header")).toHaveTextContent(hi.title);
    });
    expect(
      screen.getByTestId("settings-feature-flags-title"),
    ).toHaveTextContent(hi.sections.featureFlags);
    expect(
      screen.getByTestId("settings-feature-flags-type-test.runtime_flag"),
    ).toHaveTextContent(hi.featureFlags.runtime);
    expect(
      screen.getByTestId("settings-feature-flags-save-test.runtime_flag"),
    ).toHaveTextContent(hi.featureFlags.save);
    expect(
      screen.getByTestId("settings-feature-flags-history-title"),
    ).toHaveTextContent(hi.featureFlags.historyTitle);
  });
});
