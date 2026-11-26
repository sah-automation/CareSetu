// FEAT-015 (operator console) / #868: the cross-surface seam for the operator
// profile source. A defect that only exists as a divergence between the chrome
// and the page is invisible to either surface's own suite, so this mounts both
// in one tree under the shared provider the (operator) layout mounts, drives the
// page's real edits, and asserts what the account menu renders.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
import { AccountMenu } from "@/components/dashboard/AccountMenu";
import { OperatorProfileProvider } from "@/lib/operator/OperatorProfileContext";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import {
  deleteOperatorProfilePhoto,
  fetchOperatorProfile,
  fetchOperatorProfilePhoto,
  updateOperatorProfile,
  uploadOperatorProfilePhoto,
  type OperatorProfileView,
} from "@/lib/operator/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/operator/profile",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  },
}));

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
    () => "blob:http://localhost/operator-shared-photo",
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

async function renderBoth() {
  render(
    <OperatorProfileProvider>
      <AccountMenu shellRole="operator" />
      <OperatorProfilePage />
    </OperatorProfileProvider>,
  );
  await waitFor(() => screen.getByTestId("operator-profile-page"));
  await waitFor(() =>
    expect(screen.getByTestId("profile-name")).toHaveValue("Asha Admin"),
  );
}

async function openMenu() {
  fireEvent.keyDown(screen.getByTestId("account-menu"), { key: "Enter" });
  await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
}

describe("operator profile cross-surface agreement (#868)", () => {
  it("a name saved on the page reaches the account menu header", async () => {
    await renderBoth();
    await openMenu();
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Asha Admin",
    );

    fireEvent.change(screen.getByTestId("profile-name"), {
      target: { value: "Asha Rao" },
    });
    fireEvent.click(screen.getByTestId("profile-identity-save"));

    await waitFor(() =>
      expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
        "Asha Rao",
      ),
    );
    expect(getProfile).toHaveBeenCalledTimes(1);
  });

  it("a photo uploaded on the page reaches the account menu trigger", async () => {
    await renderBoth();
    const trigger = screen.getByTestId("account-menu");
    expect(trigger.querySelector("img")).toBeNull();

    const file = new File(["bytes"], "me.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByTestId("operator-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(uploadPhoto).toHaveBeenCalled());
    await waitFor(() => {
      expect(trigger.querySelector("img")).not.toBeNull();
    });
    expect(getPhoto).toHaveBeenCalled();
  });

  it("a photo removed on the page drops out of the account menu trigger", async () => {
    getProfile.mockResolvedValue(
      profile({ photo_ref: "operator/42/photo-1.enc" }),
    );
    await renderBoth();
    const trigger = screen.getByTestId("account-menu");
    await waitFor(() => {
      expect(trigger.querySelector("img")).not.toBeNull();
    });

    fireEvent.click(screen.getByTestId("operator-photo-remove"));

    await waitFor(() => expect(deletePhoto).toHaveBeenCalled());
    await waitFor(() => {
      expect(trigger.querySelector("img")).toBeNull();
    });
  });
});
