// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// #583: provider suite for the doctor console's shared profile source. The
// doctor client is mocked at the module boundary, so what is pinned here is the
// discipline the read itself has to keep now that the chrome and the Profile page
// both render from it: one read per visit, an identity-scoped state, an explicit
// retry, a degrade that is silent to the chrome but carries the trace id to the
// page, and one adopt seam that takes a whole projection.
//
// The surfaces' own rendering is not re-tested here - the chrome's suite covers
// the disc, the page's covers the form, and the cross-surface suite covers the
// two agreeing on one read. What no surface can see is this file.

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
  DoctorProfileProvider,
  useDoctorProfile,
  useOptionalDoctorProfile,
} from "./DoctorProfileContext";
import { ApiError } from "@/lib/api-errors";
import type { DoctorProfileView } from "./api";

const state = vi.hoisted<{
  getProfile: ReturnType<typeof vi.fn>;
  user: { id: number; phone: string; roles: string[] } | null;
}>(() => ({
  getProfile: vi.fn(),
  user: { id: 7, phone: "+911234567890", roles: ["partner"] },
}));

vi.mock("./api", () => ({ fetchDoctorProfile: state.getProfile }));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: state.user,
    selectedRole: state.user === null ? null : "partner",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: state.user !== null,
    isLoading: false,
  }),
}));

function view(overrides: Partial<DoctorProfileView> = {}): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: "doctor/7/photo-1.enc",
    practice_name: "Sunrise Clinic",
    clinic_name: null,
    specialties: ["General Physician"],
    verified: true,
    practice_address: "Main Road, Daltonganj",
    address_line: "Main Road, Daltonganj",
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "822001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["Hindi", "English"],
    experience_years: 12,
    about: "Twelve years of primary care.",
    consultation_fee: 40000,
    consulting_days: ["mon", "tue", "wed", "thu", "fri", "sat"],
    consulting_hours: "Mon-Sat, 9am-1pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2027-04-01T00:00:00Z",
      },
    ],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

function Probe() {
  const { profile, status, errorTraceId, reload, adoptProfile } =
    useDoctorProfile();
  return (
    <div>
      <span data-testid="probe-status">{status}</span>
      <span data-testid="probe-name">{profile?.practice_name ?? ""}</span>
      <span data-testid="probe-ref">{profile?.photo_ref ?? ""}</span>
      <span data-testid="probe-trace">{errorTraceId ?? ""}</span>
      <button data-testid="probe-reload" onClick={reload}>
        retry
      </button>
      <button
        data-testid="probe-adopt"
        onClick={() =>
          adoptProfile(
            view({ practice_name: "Evening Clinic", photo_ref: null }),
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
  state.user = { id: 7, phone: "+911234567890", roles: ["partner"] };
  state.getProfile.mockResolvedValue(view());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderReady() {
  const rendered = render(
    <DoctorProfileProvider>
      <Probe />
    </DoctorProfileProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
  );
  return rendered;
}

describe("DoctorProfileProvider read discipline (#583)", () => {
  it("reads once for a visit and hydrates the whole projection", async () => {
    await renderReady();

    expect(state.getProfile).toHaveBeenCalledTimes(1);
    // The name and the ref travel together: the identity header needs both, and
    // a second read for the second field is the request this source removes.
    expect(screen.getByTestId("probe-name").textContent).toBe("Sunrise Clinic");
    expect(screen.getByTestId("probe-ref").textContent).toBe(
      "doctor/7/photo-1.enc",
    );
  });

  it("does not re-read when a child re-renders", async () => {
    const { rerender } = await renderReady();

    // A re-render of the tree beneath the source is what a page navigation or a
    // parent state change looks like from here; the read is keyed on the
    // identity, so it must not repeat.
    rerender(
      <DoctorProfileProvider>
        <Probe />
        <span data-testid="sibling">elsewhere</span>
      </DoctorProfileProvider>,
    );
    expect(screen.getByTestId("sibling")).toBeInTheDocument();

    rerender(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );

    expect(screen.queryByTestId("sibling")).not.toBeInTheDocument();
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("reads nothing at all without a signed-in identity", async () => {
    state.user = null;
    render(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );

    // The doctor surfaces are unreachable without an identity, and this
    // freshly-keyed subtree already holds pristine state, so there is nothing to
    // hydrate - and nothing to ask the backend for.
    expect(state.getProfile).not.toHaveBeenCalled();
    expect(screen.getByTestId("probe-status").textContent).toBe("loading");
    expect(screen.getByTestId("probe-name").textContent).toBe("");
  });

  it("reads again on an explicit retry, and a successful retry clears the failure", async () => {
    state.getProfile.mockRejectedValueOnce(new Error("profile feed down"));
    render(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    fireEvent.click(screen.getByTestId("probe-reload"));

    // A retry that succeeds renders the profile with no reload of the console.
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    expect(state.getProfile).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("probe-name").textContent).toBe("Sunrise Clinic");
  });
});

describe("DoctorProfileProvider identity isolation (#583)", () => {
  it("remounts pristine and reads afresh when the identity changes", async () => {
    const tree = (id: number) => {
      state.user = { id, phone: "+911234567890", roles: ["partner"] };
      return (
        <DoctorProfileProvider>
          <Probe />
        </DoctorProfileProvider>
      );
    };
    const { rerender } = render(tree(7));
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    state.getProfile.mockClear();
    state.getProfile.mockResolvedValue(
      view({ partner_id: 8, practice_name: "Night Clinic" }),
    );

    // A second doctor on the same browser: the state is keyed on the identity,
    // so the very first commit already holds the new doctor's pristine state -
    // no render can show the previous one's profile.
    rerender(tree(8));

    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe("Night Clinic"),
    );
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("never shows the previous doctor's projection while the new read is in flight", async () => {
    state.getProfile.mockResolvedValue(
      view({ practice_name: "Sunrise Clinic" }),
    );
    const tree = (id: number) => {
      state.user = { id, phone: "+911234567890", roles: ["partner"] };
      return (
        <DoctorProfileProvider>
          <Probe />
        </DoctorProfileProvider>
      );
    };
    const { rerender } = render(tree(7));
    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe(
        "Sunrise Clinic",
      ),
    );

    // The new doctor's read hangs: the whole point is the window between the
    // identity switch and the answer, which is exactly when a stale name would
    // otherwise be on screen.
    let settle: (value: DoctorProfileView) => void = () => {};
    state.getProfile.mockReset();
    state.getProfile.mockImplementation(
      () =>
        new Promise<DoctorProfileView>((resolve) => {
          settle = resolve;
        }),
    );

    rerender(tree(8));

    // Between the identity switch and the new read's answer there is nothing to
    // show: the old name is gone rather than stale, and the read is one.
    expect(screen.getByTestId("probe-name").textContent).toBe("");
    expect(state.getProfile).toHaveBeenCalledTimes(1);
    settle(view({ partner_id: 8, practice_name: "Night Clinic" }));
    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe("Night Clinic"),
    );
  });
});

describe("DoctorProfileProvider failed read (#583)", () => {
  it("degrades silently to the chrome but carries the trace id to the page", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-583",
        details: {},
      }),
    );
    render(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    // Chrome identity is a bonus, never a blocker: no projection, no trace to a
    // component that would render a name. The page gets both, so the one place a
    // doctor is named can say what happened and offer the retry.
    expect(screen.getByTestId("probe-name").textContent).toBe("");
    expect(screen.getByTestId("probe-trace").textContent).toBe("trace-583");
    // A silent feed is still logged, under the prefix of the module that owns it.
    expect(warn).toHaveBeenCalledWith(
      "[doctor-profile] failed to load:",
      expect.any(ApiError),
    );
  });

  it("reports no trace id for a failure that carries none", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValue(new Error("connection reset"));
    render(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    // A transport failure has no server trace to quote, and inventing one would
    // send a doctor looking for an id that does not exist.
    expect(screen.getByTestId("probe-trace").textContent).toBe("");
  });
});

describe("DoctorProfileProvider adoptProfile (#583)", () => {
  it("takes a whole projection, so a moved practice name reaches the chrome", async () => {
    await renderReady();

    fireEvent.click(screen.getByTestId("probe-adopt"));

    // A save reply, an upload's ref and a removal's null ref all arrive here, and
    // the name comes with them: a ref-only seam would fix the avatar and leave
    // the only place the doctor is named showing yesterday's clinic.
    await waitFor(() =>
      expect(screen.getByTestId("probe-name").textContent).toBe(
        "Evening Clinic",
      ),
    );
    expect(screen.getByTestId("probe-ref").textContent).toBe("");
    // An adopted answer is a ready one, and it costs no read.
    expect(screen.getByTestId("probe-status").textContent).toBe("ready");
    expect(state.getProfile).toHaveBeenCalledTimes(1);
  });

  it("clears a failed read's trace when an answer is adopted after it", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    state.getProfile.mockRejectedValueOnce(new Error("profile feed down"));
    render(
      <DoctorProfileProvider>
        <Probe />
      </DoctorProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );

    fireEvent.click(screen.getByTestId("probe-adopt"));

    // An upload or a save that succeeds after a failed read leaves nothing to
    // retry, so the banner has nothing left to quote.
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("probe-trace").textContent).toBe("");
  });
});

describe("DoctorProfileProvider optional accessor (#583)", () => {
  function OptionalProbe() {
    const doctor = useOptionalDoctorProfile();
    return (
      <span data-testid="probe-optional">
        {doctor === null ? "none" : "some"}
      </span>
    );
  }

  it("yields null in a shell that mounts no provider", () => {
    render(<OptionalProbe />);

    // The account menu is shared across roles, and the partner and operator
    // shells mount no doctor source at all. Reading through the required hook
    // there would throw a doctor's whole console away; this is the shape the
    // patient chrome already uses.
    expect(screen.getByTestId("probe-optional").textContent).toBe("none");
    expect(state.getProfile).not.toHaveBeenCalled();
  });

  it("yields the source where one is mounted", async () => {
    render(
      <DoctorProfileProvider>
        <OptionalProbe />
      </DoctorProfileProvider>,
    );

    expect(screen.getByTestId("probe-optional").textContent).toBe("some");
  });
});

// #583: the read has exactly one home. This pin moved here from the shell suite
// with the read it asserted on, because it reads this module's own source text
// and no surface can see it: a second `fetchDoctorProfile` call site anywhere in
// the console would be invisible to every behavioural test here - each would
// still see its own copy answer, which is exactly how the two-copy defect this
// ticket fixes looked from every single-surface test that passed with it.
// Source-scoped, like the shell suite's nav-config and #567 scans.
describe("the doctor profile read has one home (#583)", () => {
  const moduleDir = join(__dirname);

  it("is read in this module and nowhere else in the console", () => {
    const source = readFileSync(
      join(moduleDir, "DoctorProfileContext.tsx"),
      "utf8",
    );
    // One projection read, and it is this one.
    expect(source.match(/fetchDoctorProfile\(/g)).toHaveLength(1);

    // And the chrome holds no read at all: a shell, a top bar and an account
    // menu that each read the projection for themselves would put the two copies
    // straight back, and the pin that catches it is the one above.
    for (const file of [
      join(moduleDir, "..", "..", "components", "dashboard", "AppShell.tsx"),
      join(moduleDir, "..", "..", "components", "dashboard", "Topbar.tsx"),
      join(moduleDir, "..", "..", "components", "dashboard", "AccountMenu.tsx"),
    ]) {
      expect(readFileSync(file, "utf8")).not.toMatch(/fetchDoctorProfile\(/);
    }
  });
});
