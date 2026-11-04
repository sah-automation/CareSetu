// FEAT-015 (operator console) / #868: provider suite for the operator console's
// shared profile source. The operator client is mocked at the module boundary,
// so what is pinned here is the read discipline the chrome and the profile page
// both depend on: one read per visit, identity-scoped state, an explicit retry,
// a silent degrade that still carries the trace id to the page, and one adopt
// seam that takes a whole view. Mirrors DoctorProfileContext.test.tsx.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  OperatorProfileProvider,
  useOperatorProfile,
  useOptionalOperatorProfile,
} from "./OperatorProfileContext";
import { ApiError } from "@/lib/api-errors";
import type { OperatorProfileView } from "./api";

const state = vi.hoisted<{
  getProfile: ReturnType<typeof vi.fn>;
  user: { id: number; phone: string; roles: string[] } | null;
}>(() => ({
  getProfile: vi.fn(),
  user: { id: 42, phone: "+911234567890", roles: ["operator"] },
}));

vi.mock("./api", () => ({ fetchOperatorProfile: state.getProfile }));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: state.user,
    selectedRole: state.user === null ? null : "operator",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: state.user !== null,
    isLoading: false,
  }),
}));

function view(
  overrides: Partial<OperatorProfileView> = {},
): OperatorProfileView {
  return {
    identity_id: 42,
    name: "Asha Admin",
    phone: "+911234567890",
    tier: "operator",
    mfa_enabled: true,
    photo_ref: "operator/42/photo-1.enc",
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function Probe() {
  const { profile, status, errorTraceId, reload, adoptProfile } =
    useOperatorProfile();
  return (
    <div>
      <span data-testid="probe-status">{status}</span>
      <span data-testid="probe-name">{profile?.name ?? ""}</span>
      <span data-testid="probe-tier">{profile?.tier ?? ""}</span>
      <span data-testid="probe-ref">{profile?.photo_ref ?? ""}</span>
      <span data-testid="probe-trace">{errorTraceId ?? ""}</span>
      <button data-testid="probe-reload" onClick={reload}>
        retry
      </button>
      <button
        data-testid="probe-adopt"
        onClick={() =>
          adoptProfile(
            view({ name: "Night Operator", photo_ref: null, tier: "admin" }),
          )
        }
      >
        adopt
      </button>
    </div>
  );
}

beforeEach(() => {
  state.getProfile.mockReset();
  state.getProfile.mockResolvedValue(view());
  state.user = { id: 42, phone: "+911234567890", roles: ["operator"] };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderReady() {
  const rendered = render(
    <OperatorProfileProvider>
      <Probe />
    </OperatorProfileProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
  );
  return rendered;
}

describe("OperatorProfileProvider read discipline (#868)", () => {
  it("reads once for a visit and hydrates the whole projection", async () => {
    await renderReady();

    expect(state.getProfile).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("probe-name").textContent).toBe("Asha Admin");
    expect(screen.getByTestId("probe-tier").textContent).toBe("operator");
    expect(screen.getByTestId("probe-ref").textContent).toBe(
      "operator/42/photo-1.enc",
    );
  });

  it("does not re-read when a child re-renders", async () => {
    const { rerender } = await renderReady();

    rerender(
      <OperatorProfileProvider>
        <Probe />
        <span data-testid="sibling">elsewhere</span>
      </OperatorProfileProvider>,
    );
    expect(screen.getByTestId("sibling")).toBeInTheDocument();

    rerender(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );

    expect(screen.queryByTestId("sibling")).not.toBeInTheDocument();
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("reads nothing at all without a signed-in identity", () => {
    state.user = null;
    render(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );

    expect(state.getProfile).not.toHaveBeenCalled();
    expect(screen.getByTestId("probe-status").textContent).toBe("loading");
    expect(screen.getByTestId("probe-name").textContent).toBe("");
  });

  it("reads again on an explicit retry, and a successful retry clears the failure", async () => {
    state.getProfile.mockRejectedValueOnce(new Error("profile feed down"));
    render(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    fireEvent.click(screen.getByTestId("probe-reload"));

    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    expect(state.getProfile).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("probe-name").textContent).toBe("Asha Admin");
  });
});

describe("OperatorProfileProvider identity isolation (#868)", () => {
  it("remounts pristine and reads afresh when the identity changes", async () => {
    const tree = (id: number) => {
      state.user = { id, phone: "+911234567890", roles: ["operator"] };
      return (
        <OperatorProfileProvider>
          <Probe />
        </OperatorProfileProvider>
      );
    };
    const { rerender } = render(tree(42));
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    state.getProfile.mockClear();
    state.getProfile.mockResolvedValue(
      view({ identity_id: 43, name: "Second Operator" }),
    );

    rerender(tree(43));

    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe(
        "Second Operator",
      ),
    );
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("never shows the previous operator's profile while the new read is in flight", async () => {
    state.getProfile.mockResolvedValue(view({ name: "Asha Admin" }));
    const tree = (id: number) => {
      state.user = { id, phone: "+911234567890", roles: ["operator"] };
      return (
        <OperatorProfileProvider>
          <Probe />
        </OperatorProfileProvider>
      );
    };
    const { rerender } = render(tree(42));
    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe("Asha Admin"),
    );

    let settle: (value: OperatorProfileView) => void = () => {};
    state.getProfile.mockReset();
    state.getProfile.mockImplementation(
      () =>
        new Promise<OperatorProfileView>((resolve) => {
          settle = resolve;
        }),
    );

    rerender(tree(43));

    expect(screen.getByTestId("probe-name").textContent).toBe("");
    expect(state.getProfile).toHaveBeenCalledTimes(1);
    settle(view({ identity_id: 43, name: "Second Operator" }));
    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe(
        "Second Operator",
      ),
    );
  });
});

describe("OperatorProfileProvider failed read (#868)", () => {
  it("degrades silently to the chrome but carries the trace id to the page", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-868",
        details: {},
      }),
    );
    render(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    expect(screen.getByTestId("probe-name").textContent).toBe("");
    expect(screen.getByTestId("probe-trace").textContent).toBe("trace-868");
    expect(warn).toHaveBeenCalledWith("[operator-profile] failed to load:", {
      code: "INTERNAL_ERROR",
      traceId: "trace-868",
    });
  });

  it("reports no trace id for a failure that carries none", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValue(new Error("connection reset"));
    render(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    expect(screen.getByTestId("probe-trace").textContent).toBe("");
  });
});

describe("OperatorProfileProvider adoptProfile (#868)", () => {
  it("takes a whole view, so a moved name and tier reach the chrome", async () => {
    await renderReady();

    fireEvent.click(screen.getByTestId("probe-adopt"));

    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe(
        "Night Operator",
      ),
    );
    expect(screen.getByTestId("probe-tier").textContent).toBe("admin");
    expect(screen.getByTestId("probe-ref").textContent).toBe("");
    expect(screen.getByTestId("probe-status").textContent).toBe("ready");
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("clears a failed read's trace when an answer is adopted after it", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValueOnce(new Error("profile feed down"));
    render(
      <OperatorProfileProvider>
        <Probe />
      </OperatorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    fireEvent.click(screen.getByTestId("probe-adopt"));

    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("probe-trace").textContent).toBe("");
  });
});

describe("OperatorProfileProvider optional accessor (#868)", () => {
  function OptionalProbe() {
    const operator = useOptionalOperatorProfile();
    return (
      <span data-testid="probe-optional">
        {operator === null ? "none" : "some"}
      </span>
    );
  }

  it("yields null in a shell that mounts no provider", () => {
    render(<OptionalProbe />);

    expect(screen.getByTestId("probe-optional").textContent).toBe("none");
    expect(state.getProfile).not.toHaveBeenCalled();
  });

  it("yields the source where one is mounted", () => {
    render(
      <OperatorProfileProvider>
        <OptionalProbe />
      </OperatorProfileProvider>,
    );

    expect(screen.getByTestId("probe-optional").textContent).toBe("some");
  });
});

describe("the operator profile read has one home (#868)", () => {
  const moduleDir = join(__dirname);

  it("is read in this module and nowhere else", () => {
    const source = readFileSync(
      join(moduleDir, "OperatorProfileContext.tsx"),
      "utf8",
    );
    expect(source.match(/fetchOperatorProfile\(/g)).toHaveLength(1);

    for (const file of [
      join(moduleDir, "..", "..", "components", "dashboard", "AppShell.tsx"),
      join(moduleDir, "..", "..", "components", "dashboard", "Topbar.tsx"),
      join(moduleDir, "..", "..", "components", "dashboard", "AccountMenu.tsx"),
    ]) {
      expect(readFileSync(file, "utf8")).not.toMatch(/fetchOperatorProfile\(/);
    }
  });
});
