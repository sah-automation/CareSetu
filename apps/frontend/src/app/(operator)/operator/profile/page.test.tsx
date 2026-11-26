// FEAT-015 (operator console) / #868: operator profile page suite. Renders the
// three zones from the shared operator profile source, saves the editable name,
// drives photo upload and removal over the operator photo endpoints, shows the
// read-only account facts and security status, and covers the retryable load
// failure plus bilingual parity (REQ-006).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { ReactNode } from "react";

import OperatorProfilePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { OperatorProfileProvider } from "@/lib/operator/OperatorProfileContext";
import {
  deleteOperatorProfilePhoto,
  fetchOperatorProfile,
  fetchOperatorProfilePhoto,
  updateOperatorProfile,
  uploadOperatorProfilePhoto,
  type OperatorProfileView,
} from "@/lib/operator/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/operator/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/operator/api")>();
  return {
    ...mod,
    fetchOperatorProfile: vi.fn(),
    updateOperatorProfile: vi.fn(),
    uploadOperatorProfilePhoto: vi.fn(),
    fetchOperatorProfilePhoto: vi.fn(),
    deleteOperatorProfilePhoto: vi.fn(),
  };
});

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 42, phone: "+911234567890", roles: ["operator"] },
    selectedRole: "operator",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const t = STRINGS.en.operatorProfile;
const hiT = STRINGS.hi.operatorProfile;
const getProfile = vi.mocked(fetchOperatorProfile);
const saveProfile = vi.mocked(updateOperatorProfile);
const uploadPhoto = vi.mocked(uploadOperatorProfilePhoto);
const getPhoto = vi.mocked(fetchOperatorProfilePhoto);
const deletePhoto = vi.mocked(deleteOperatorProfilePhoto);

function profile(
  overrides: Partial<OperatorProfileView> = {},
): OperatorProfileView {
  return {
    identity_id: 42,
    name: "Asha Admin",
    phone: "+911234567890",
    tier: "operator",
    mfa_enabled: true,
    photo_ref: null,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
});

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;

beforeEach(() => {
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => "blob:http://localhost/operator-photo",
  ) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  getProfile.mockResolvedValue(profile());
  saveProfile.mockImplementation(async ({ name }) =>
    profile({ name: name ?? null }),
  );
  uploadPhoto.mockResolvedValue({ photo_ref: "operator/42/photo-1.enc" });
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/jpeg" }));
  deletePhoto.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

async function renderReady(view: OperatorProfileView = profile()) {
  getProfile.mockResolvedValue(view);
  render(
    <OperatorProfileProvider>
      <OperatorProfilePage />
    </OperatorProfileProvider>,
  );
  await waitFor(() => screen.getByTestId("operator-profile-page"));
}

describe("OperatorProfilePage zones (#868)", () => {
  it("renders identity, account and security from one shared projection", async () => {
    await renderReady();

    expect(screen.getByTestId("operator-profile-page")).toBeInTheDocument();
    expect(screen.getByTestId("profile-identity")).toBeInTheDocument();
    expect(screen.getByTestId("profile-account")).toBeInTheDocument();
    expect(screen.getByTestId("profile-security")).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByTestId("profile-name")).toHaveValue("Asha Admin"),
    );
    expect(screen.getByTestId("operator-phone")).toHaveValue("+911234567890");
    expect(screen.getByTestId("operator-tier-badge")).toHaveTextContent(
      t.tierOperator,
    );
    expect(screen.getByTestId("operator-mfa-status")).toHaveTextContent(
      t.mfaEnabled,
    );
    expect(
      screen.getByTestId("operator-mfa-status-security"),
    ).toHaveTextContent(t.mfaEnabled);
    expect(screen.getByTestId("operator-created-at")).toHaveTextContent("2025");
    expect(screen.getByTestId("operator-mfa-manage")).toHaveAttribute(
      "href",
      "/operator/security",
    );
  });

  it("offers an anchor index that points at each rendered section", async () => {
    await renderReady();

    for (const id of [
      "profile-section-identity",
      "profile-section-account",
      "profile-section-security",
    ]) {
      expect(screen.getByTestId(`profile-anchor-${id}`)).toHaveAttribute(
        "href",
        `#${id}`,
      );
      expect(document.getElementById(id)).not.toBeNull();
    }
  });

  it("shows Disabled when MFA is not enrolled", async () => {
    await renderReady(profile({ mfa_enabled: false }));

    expect(screen.getByTestId("operator-mfa-status")).toHaveTextContent(
      t.mfaDisabled,
    );
  });
});

describe("OperatorProfilePage name save (#868)", () => {
  it("saves only the trimmed name and adopts the returned view", async () => {
    await renderReady();
    fireEvent.change(screen.getByTestId("profile-name"), {
      target: { value: "  Asha Rao  " },
    });
    fireEvent.click(screen.getByTestId("profile-identity-save"));

    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1));
    expect(saveProfile).toHaveBeenCalledWith(
      { name: "Asha Rao" },
      expect.any(String),
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-identity-saved")).toBeInTheDocument(),
    );
    // The buffer keeps the operator's literal keystrokes after a save (it does
    // not reseed while dirty), so the trimmed value lives in the request, not
    // in the input. The confirmation is the page-level proof of the save.
    expect(screen.getByTestId("profile-identity-saved")).toHaveTextContent(
      t.saved,
    );
  });

  it("clears the name to null when the field is emptied", async () => {
    await renderReady();
    fireEvent.change(screen.getByTestId("profile-name"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId("profile-identity-save"));

    await waitFor(() =>
      expect(saveProfile).toHaveBeenCalledWith(
        { name: null },
        expect.any(String),
      ),
    );
  });

  it("surfaces a save failure with its API trace id", async () => {
    saveProfile.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-868",
        details: {},
      }),
    );
    await renderReady();
    fireEvent.change(screen.getByTestId("profile-name"), {
      target: { value: "Asha Rao" },
    });
    fireEvent.click(screen.getByTestId("profile-identity-save"));

    await waitFor(() =>
      expect(screen.getByText(t.saveFailed)).toBeInTheDocument(),
    );
    expect(screen.getByText(/trace-868/)).toBeInTheDocument();
  });
});

describe("OperatorProfilePage photo (#868)", () => {
  it("uploads a picked photo and previews the returned ref", async () => {
    await renderReady();
    const input = screen.getByTestId("operator-photo-input");
    const file = new File(["bytes"], "me.jpg", { type: "image/jpeg" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(uploadPhoto).toHaveBeenCalledWith(file, expect.any(String)),
    );
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    await waitFor(() => {
      const photo = screen.getByTestId("operator-profile-photo");
      expect(photo.querySelector("img")).not.toBeNull();
    });
  });

  it("removes the photo and falls back to the avatar placeholder", async () => {
    await renderReady(profile({ photo_ref: "operator/42/photo-1.enc" }));
    await waitFor(() =>
      expect(screen.getByTestId("operator-photo-remove")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("operator-photo-remove"));

    await waitFor(() =>
      expect(deletePhoto).toHaveBeenCalledWith(expect.any(String)),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("operator-photo-remove")).toBeNull(),
    );
  });

  it("reports an upload failure with the API trace", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-photo",
        details: {},
      }),
    );
    await renderReady();
    const file = new File(["bytes"], "me.jpg", { type: "image/jpeg" });

    fireEvent.change(screen.getByTestId("operator-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByTestId("operator-photo-failed")).toHaveTextContent(
        t.photoFailed,
      ),
    );
    expect(screen.getByTestId("operator-photo-failed")).toHaveTextContent(
      "trace-photo",
    );
  });
});

describe("OperatorProfilePage load failure (#868)", () => {
  it("shows a retryable banner that re-reads the profile", async () => {
    getProfile.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-load",
        details: {},
      }),
    );
    render(
      <OperatorProfileProvider>
        <OperatorProfilePage />
      </OperatorProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText(t.loadFailed)).toBeInTheDocument(),
    );
    expect(screen.getByText(/trace-load/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(screen.getByTestId("operator-profile-page")).toBeInTheDocument(),
    );
    expect(getProfile).toHaveBeenCalledTimes(2);
  });
});

describe("OperatorProfilePage bilingual parity (REQ-006)", () => {
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
        <OperatorProfilePage />
      </>
    );
  }

  it("renders the operator copy in Hindi when the locale flips", async () => {
    render(
      <OperatorProfileProvider>
        <LangFlipHost />
      </OperatorProfileProvider>,
    );
    await waitFor(() => screen.getByTestId("operator-profile-page"));

    fireEvent.click(screen.getByText("flip-lang"));

    await waitFor(() =>
      expect(
        within(screen.getByTestId("profile-identity")).getByRole("heading", {
          name: hiT.identityHeading,
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("operator-tier-badge")).toHaveTextContent(
      hiT.tierOperator,
    );
    expect(screen.getByTestId("operator-mfa-status")).toHaveTextContent(
      hiT.mfaEnabled,
    );
  });
});
