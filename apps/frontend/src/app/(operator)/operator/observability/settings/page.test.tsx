// #797: the admin Settings shell and its read-only AI section. These tests pin
// the four-section shell, effective values with source and restart badges, the
// admin-only guard, and the bilingual strings.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchEffectiveSettings,
  type EffectiveSetting,
} from "@/lib/operator/settings";

import ObservabilitySettingsPage from "./page";

vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/operator/settings");

const mockUseAuth = vi.mocked(useAuth);
const mockFetchEffectiveSettings = vi.mocked(fetchEffectiveSettings);

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
    key: "notification.channels.email.enabled",
    value: false,
    source: "default",
    editable: true,
    restart_required: false,
  },
];

describe("ObservabilitySettingsPage (#797)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    __resetLangForTests();
    mockUseAuth.mockReturnValue(adminAuth());
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
      screen.getByTestId("settings-ai-value-ai.timeout_seconds"),
    ).toHaveTextContent("30");
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
    expect(mockFetchEffectiveSettings).toHaveBeenCalledTimes(2);
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
  });
});
