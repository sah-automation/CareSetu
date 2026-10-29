// #797: the admin Settings shell and its AI section.
// #798: the allowlisted AI knobs gain editable controls, save states,
// validation copy, and the append-only setting history beneath the table.

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
  fetchEffectiveSettings,
  fetchSettingHistory,
  fetchAlertDeliveries,
  writeSetting,
  type EffectiveSetting,
  type SettingHistoryEntry,
} from "@/lib/operator/settings";

import ObservabilitySettingsPage from "./page";

vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/operator/settings");

const mockUseAuth = vi.mocked(useAuth);
const mockFetchEffectiveSettings = vi.mocked(fetchEffectiveSettings);
const mockFetchSettingHistory = vi.mocked(fetchSettingHistory);
const mockFetchAlertDeliveries = vi.mocked(fetchAlertDeliveries);
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
    key: "ai.model",
    value: null,
    source: "environment",
    editable: false,
    restart_required: true,
  },
  {
    key: "ai.timeout_seconds",
    value: 30,
    source: "database",
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

const editableSettings: EffectiveSetting[] = [
  {
    key: "ai.timeout_seconds",
    value: 30,
    source: "database",
    editable: true,
    restart_required: false,
  },
  {
    key: "ai.fallback_enabled",
    value: false,
    source: "default",
    editable: true,
    restart_required: false,
  },
];

const historyEntries: SettingHistoryEntry[] = [
  {
    setting_key: "ai.timeout_seconds",
    value: 20,
    version: 2,
    changed_by: 7,
    changed_at: "2026-03-04T10:00:00Z",
  },
  {
    setting_key: "notification.channels.email.enabled",
    value: true,
    version: 1,
    changed_by: null,
    changed_at: "2026-03-03T09:00:00Z",
  },
];

async function renderReady() {
  render(<ObservabilitySettingsPage />);
  await waitFor(() => {
    expect(
      screen.getByTestId("settings-ai-row-ai.timeout_seconds"),
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
    mockFetchAlertDeliveries.mockResolvedValue({
      deliveries: [],
      total_count: 0,
      page: 1,
      page_size: 25,
    });
  });

  it("renders the four-section shell", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);

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

  it("shows effective AI values with source and restart-required badges", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);

    render(<ObservabilitySettingsPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-row-ai.model"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
    ).toHaveValue(30);
    expect(
      screen.getByTestId("settings-ai-source-ai.timeout_seconds"),
    ).toHaveTextContent(en.ai.sources.database);
    expect(
      screen.getByTestId("settings-ai-restart-ai.model"),
    ).toHaveTextContent(en.ai.restartRequired);
    expect(
      screen.getByTestId("settings-ai-no-restart-ai.timeout_seconds"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("settings-ai-value-ai.model")).toHaveTextContent(
      en.ai.notReturned,
    );
    expect(screen.getByTestId("settings-ai-takeaway")).toHaveTextContent(
      en.ai.takeaway(2),
    );
    // Only the AI section reads this endpoint in #797.
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
    expect(
      screen.getByTestId("settings-ai-source-ai.timeout_seconds"),
    ).toHaveTextContent(hi.ai.sources.database);
    expect(
      screen.getByTestId("settings-ai-save-ai.timeout_seconds"),
    ).toHaveTextContent(hi.ai.save);
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
    mockFetchEffectiveSettings.mockResolvedValue(editableSettings);
    mockFetchSettingHistory.mockResolvedValue([]);
  });

  it("only gives editable rows a control", async () => {
    mockFetchEffectiveSettings.mockResolvedValue(settings);

    await renderReady();

    expect(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("settings-ai-input-ai.model")).toBeNull();
    expect(
      screen.getByTestId("settings-ai-readonly-ai.model"),
    ).toHaveTextContent(en.ai.readOnly);
  });

  it("saves an edited value and refreshes effective values and history", async () => {
    mockWriteSetting.mockResolvedValue({
      setting_key: "ai.timeout_seconds",
      value: 20,
      version: 2,
    });

    await renderReady();

    fireEvent.change(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
      {
        target: { value: "20" },
      },
    );
    screen.getByTestId("settings-ai-save-ai.timeout_seconds").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith("ai.timeout_seconds", 20);
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-status-ai.timeout_seconds"),
      ).toHaveTextContent(en.ai.saved);
    });
    // Called 3 times: initial AI + Notifications, then after save for AI + Notifications
    expect(mockFetchEffectiveSettings).toHaveBeenCalledTimes(3);
    expect(mockFetchSettingHistory).toHaveBeenCalledTimes(2);
  });

  it("saves a boolean with the checkbox value", async () => {
    mockWriteSetting.mockResolvedValue({
      setting_key: "ai.fallback_enabled",
      value: true,
      version: 1,
    });

    await renderReady();

    fireEvent.click(
      screen.getByTestId("settings-ai-input-ai.fallback_enabled"),
    );
    screen.getByTestId("settings-ai-save-ai.fallback_enabled").click();

    await waitFor(() => {
      expect(mockWriteSetting).toHaveBeenCalledWith(
        "ai.fallback_enabled",
        true,
      );
    });
  });

  it("refuses an empty value before calling the API", async () => {
    await renderReady();

    fireEvent.change(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
      {
        target: { value: "" },
      },
    );
    screen.getByTestId("settings-ai-save-ai.timeout_seconds").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.timeout_seconds"),
      ).toHaveTextContent(en.ai.validationRequired);
    });
    expect(mockWriteSetting).not.toHaveBeenCalled();
  });

  it("shows the API's refusal message and keeps the row editable", async () => {
    mockWriteSetting.mockRejectedValue(
      new ApiError({
        code: "INVALID_SETTING_WRITE",
        message: "AI timeout must be a number of seconds in (0, 30]",
        trace_id: "trace-798",
        details: {},
      }),
    );

    await renderReady();

    fireEvent.change(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
      {
        target: { value: "45" },
      },
    );
    screen.getByTestId("settings-ai-save-ai.timeout_seconds").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.timeout_seconds"),
      ).toHaveTextContent("AI timeout must be a number of seconds in (0, 30]");
    });
    expect(
      screen.getByTestId("settings-ai-save-ai.timeout_seconds"),
    ).toBeEnabled();
    expect(
      screen.getByTestId("settings-ai-input-ai.timeout_seconds"),
    ).toHaveValue(45);
  });

  it("shows the fallback copy for an unexpected write failure", async () => {
    mockWriteSetting.mockRejectedValue(new Error("network down"));

    await renderReady();

    screen.getByTestId("settings-ai-save-ai.timeout_seconds").click();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-save-error-ai.timeout_seconds"),
      ).toHaveTextContent(en.ai.saveError);
    });
  });

  it("lists AI history newest first and hides non-AI rows", async () => {
    mockFetchSettingHistory.mockResolvedValue(historyEntries);

    await renderReady();

    await waitFor(() => {
      expect(
        screen.getByTestId("settings-ai-history-row-ai.timeout_seconds-2"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId(
        "settings-ai-history-row-notification.channels.email.enabled-1",
      ),
    ).toBeNull();
    expect(
      screen.getByTestId("settings-ai-history-row-ai.timeout_seconds-2"),
    ).toHaveTextContent("20");
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
