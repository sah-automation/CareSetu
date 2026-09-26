// PHASE-2.6 T08 (#199): dedicated accessibility suite for the §2.6 account
// menu - trigger semantics, keyboard open/close with focus return, menu-item
// roles, the stale-session phone-missing degrade, and both shell densities.
// #521: patient avatar trigger (precedence chain, Devanagari initial, phone
// hidden until open) and the staff-role regression pinning the old phone-
// digit trigger/dropdown verbatim.
// #526: the patient dropdown as a real account menu - identity header (name or
// masked phone, full E.164), live Profile & Settings, the basics-gated
// Complete-your-profile CTA, role switching kept for multi-role accounts and
// absent for single-role, a red dictionary-driven Log out, bilingual copy, the
// stale-session Subject #id degrade with Log out still working, and an axe
// scan of the opened menu.

import {
  render,
  screen,
  act,
  fireEvent,
  cleanup,
  waitFor,
  within,
} from "@testing-library/react";
import {
  describe,
  it,
  expect,
  vi,
  beforeAll,
  beforeEach,
  afterEach,
} from "vitest";
import * as axe from "axe-core";

import { AccountMenu } from "./AccountMenu";
import { AuthProvider } from "@/lib/auth/AuthContext";
import type { StoredSession } from "@/lib/auth/session";
import {
  ProfileProvider,
  useOptionalProfile,
} from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { maskedPhone } from "./BottomTabs";

// Profile client mocked at the module boundary (ProfileContext.test prior
// art) so the patient trigger can hydrate a saved name/photo without HTTP.
const profileApi = vi.hoisted(() => ({
  getProfile: vi.fn(),
  saveProfile: vi.fn(),
  fetchPatientPhoto: vi.fn(),
}));

vi.mock("@/lib/profile/api", () => ({
  getProfile: profileApi.getProfile,
  saveProfile: profileApi.saveProfile,
  fetchPatientPhoto: profileApi.fetchPatientPhoto,
}));

const VALID_SESSION: StoredSession = {
  jwt: "test-jwt-token",
  refresh_token: "test-refresh-token",
  jti: "jti-1",
  scope: "patient",
  identity_id: 42,
  phone: "+911234567890",
};

const ME_RESPONSE_SINGLE_ROLE = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["patient"],
};

// #521 staff regression: a doctor session keeps the generic account avatar
// entry since #538 (person-icon fallback until the doctor profile seam).
const ME_RESPONSE_DOCTOR = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["doctor"],
};

// #538: partner/operator staff sessions keep the phone-digit trigger verbatim.
const ME_RESPONSE_PARTNER = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["partner"],
};

// A stale session payload predating T05's additive phone field.
const ME_RESPONSE_NO_PHONE = {
  subject_id: "42",
  roles: ["patient"],
};

const NAMED_PROFILE: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: null,
  emergency_contact: null,
  photo_ref: null,
};

const DEVANAGARI_PROFILE: StoredPatientProfile = {
  ...NAMED_PROFILE,
  name: "अंकिता शर्मा",
};

const PHOTO_PROFILE: StoredPatientProfile = {
  ...NAMED_PROFILE,
  photo_ref: "https://cdn.example.test/me.jpg",
};

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

function renderAccountMenu() {
  return render(
    <AuthProvider>
      <AccountMenu />
    </AuthProvider>,
  );
}

function mockMeResponse(payload: unknown) {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(payload), { status: 200 }),
  );
}

// #521: the patient trigger reads name/photo through the shared profile
// seam. When `profile` is given, wrap in the real ProfileProvider so
// hydration ordering is exercised (name/photo arrive async).
async function renderClosedTrigger(
  mePayload: unknown,
  profile?: StoredPatientProfile | null,
) {
  setStoredSession(VALID_SESSION);
  const app = (
    <AuthProvider>
      {profile !== undefined ? (
        <ProfileProvider>
          <AccountMenu />
        </ProfileProvider>
      ) : (
        <AccountMenu />
      )}
    </AuthProvider>
  );
  if (profile !== undefined) {
    profileApi.getProfile.mockResolvedValue({
      set: profile !== null,
      profile,
    });
  }
  mockMeResponse(mePayload);
  render(app);
  const trigger = await waitFor(() =>
    expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
  ).then(() => screen.getByTestId("account-menu"));
  if (profile !== undefined) {
    await waitFor(() => expect(profileApi.getProfile).toHaveBeenCalled());
  }
  return trigger;
}

function renderPatientWithProfile(profile: StoredPatientProfile | null) {
  return renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE, profile);
}

// #557: the only thing that moves a stored photo ref is the profile context's
// syncPhotoRef, so the replace/clear path is driven through the real context
// rather than a faked setter.
function PhotoRefControls() {
  const profile = useOptionalProfile();
  return (
    <div>
      <button
        type="button"
        data-testid="replace-photo"
        onClick={() => profile?.syncPhotoRef("patient/7/photo-2.enc")}
      >
        replace
      </button>
      <button
        type="button"
        data-testid="clear-photo"
        onClick={() => profile?.syncPhotoRef(null)}
      >
        clear
      </button>
    </div>
  );
}

async function openViaKeyboard() {
  await waitFor(() =>
    expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
  );
  const trigger = screen.getByTestId("account-menu");
  fireEvent.keyDown(trigger, { key: "Enter" });
  await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
  return trigger;
}

// Radix popper relies on ResizeObserver and opens menus on real pointer
// events, neither of which jsdom implements fully. Vitest isolates each test
// file in its own jsdom environment, so these stubs cannot leak elsewhere.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

const mockReplace = vi.fn();
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
  usePathname: () => "/patient",
}));

// next/link reads its own app-router context (not the mocked useRouter), so
// clicks on the menu's asChild links fall through to jsdom navigation. Mock
// it as a click-aware anchor that composes the incoming handler (Radix's
// select/close) and then records the same router.push(next/link) would
// perform, exercising the activation path of both profile entries.
vi.mock("next/link", () => ({
  default({
    href,
    children,
    onClick,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
    [key: string]: unknown;
  }) {
    return (
      <a
        href={href}
        {...props}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) {
            event.preventDefault();
            mockPush(href);
          }
        }}
      >
        {children}
      </a>
    );
  },
}));

// #557: the <img> a surface ends up showing. Asserting inside waitFor is what
// makes it retry - a bare querySelector returns null and resolves immediately.
async function imageIn(root: ParentNode): Promise<HTMLImageElement> {
  return waitFor(() => {
    const img = root.querySelector("img");
    expect(img).not.toBeNull();
    return img;
  }).then((el) => el as HTMLImageElement);
}

// #557: object-URL plumbing for the shared photo resolver. jsdom implements
// neither, so the suite supplies them and restores whatever the host has.
let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let photoUrls: number;

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  __resetLangForTests();
  mockReplace.mockReset();
  mockPush.mockReset();
  // restoreAllMocks clears the hoisted module-mock implementations too;
  // re-seed the default "no saved profile" answer every test starts from.
  profileApi.getProfile.mockResolvedValue({ set: false, profile: null });
  // #557: the stored photo ref resolves to an object URL, and jsdom has no
  // createObjectURL of its own. A distinct URL per call so a test can tell
  // *which* generation of the photo a surface is showing.
  photoUrls = 0;
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => `blob:http://localhost/photo-${(photoUrls += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  profileApi.fetchPatientPhoto.mockResolvedValue(
    new Blob(["photo-bytes"], { type: "image/png" }),
  );
});

afterEach(() => {
  // Unmounting is what drops the hook's cache entry, so it has to happen before
  // the stubs come back - otherwise a live entry survives into the next test.
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

describe("AccountMenu accessibility", () => {
  it("trigger announces itself as a menu opener (aria-haspopup)", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("Account menu");
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  });

  it("opens via Enter key into a role=menu with role=menuitem entries", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    const trigger = await openViaKeyboard();

    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(trigger);
  });

  it("consolidates phone, role badge, and logout - no standalone controls", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Patient",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });
});

describe("AccountMenu patient avatar trigger (#521)", () => {
  it("falls back to the person icon when no profile is saved", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE);

    // No digit text and no name: just the icon branch of the chain.
    expect(trigger).toHaveTextContent("");
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    await waitFor(() =>
      expect(trigger).toHaveAttribute("data-session-resolved", "true"),
    );
  });

  it("shows the first letter of the saved name, no icon", async () => {
    const trigger = await renderPatientWithProfile(NAMED_PROFILE);

    await waitFor(() => expect(trigger).toHaveTextContent("A"));
    expect(trigger.querySelector("svg")).toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    // No stored photo means nothing to ask the backend for, so the bytes
    // endpoint is never touched.
    expect(profileApi.fetchPatientPhoto).not.toHaveBeenCalled();
  });

  it("renders a Devanagari initial intact", async () => {
    const trigger = await renderPatientWithProfile(DEVANAGARI_PROFILE);

    await waitFor(() => expect(trigger).toHaveTextContent("अ"));
  });

  // #557: the ref is an opaque object key, so the primitive can no longer be
  // handed it directly. The trigger shows the bytes the backend streams back,
  // never the stored ref as a browser-reachable URL (ADR-0020 D2).
  it("photo_ref resolves to a renderable source, never the ref itself", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      PHOTO_PROFILE,
    );

    const img = await imageIn(trigger);
    expect(img.getAttribute("src")).toBe("blob:http://localhost/photo-1");
    expect(img.getAttribute("src")).not.toContain("cdn.example.test");
    expect(trigger).not.toHaveTextContent("A");
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);
  });

  it("a stored photo ref renders an image in the trigger and in the identity header", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE, {
      ...NAMED_PROFILE,
      photo_ref: "patient/7/photo-1.enc",
    });

    const triggerImg = await imageIn(trigger);
    expect(triggerImg.getAttribute("src")).toMatch(/^blob:/);

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const headerImg = await imageIn(screen.getByRole("menu"));
    expect(headerImg.getAttribute("src")).toBe(triggerImg.getAttribute("src"));
    // Two avatars, one ref, one request: the menu header reads the same
    // resolution the trigger is already showing.
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);
  });

  it("a photo ref that fails to resolve degrades to the initial, not a broken image", async () => {
    profileApi.fetchPatientPhoto.mockRejectedValue(new Error("network down"));

    const trigger = await renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE, {
      ...NAMED_PROFILE,
      photo_ref: "patient/7/photo-1.enc",
    });
    await waitFor(() =>
      expect(profileApi.fetchPatientPhoto).toHaveBeenCalled(),
    );
    await waitFor(() => expect(trigger).toHaveTextContent("A"));

    // A blip is not a photo failure notice: the chrome avatar shows the initial
    // and nothing else, and no <img> is left pointing at nothing.
    expect(trigger.querySelector("img")).toBeNull();
    expect(trigger).toHaveTextContent("A");
  });

  // The cache is keyed by the ref, so syncPhotoRef is what invalidates it. A
  // replace or a clear moves every surface at once and never answers from the
  // bytes the previous ref produced.
  it("a replaced photo ref re-reads the bytes, and a cleared one falls back to the initial", async () => {
    setStoredSession(VALID_SESSION);
    profileApi.getProfile.mockResolvedValue({
      set: true,
      profile: { ...NAMED_PROFILE, photo_ref: "patient/7/photo-1.enc" },
    });
    mockMeResponse(ME_RESPONSE_SINGLE_ROLE);
    render(
      <AuthProvider>
        <ProfileProvider>
          <AccountMenu />
          <PhotoRefControls />
        </ProfileProvider>
      </AuthProvider>,
    );
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    const first = await imageIn(trigger);
    expect(first.getAttribute("src")).toBe("blob:http://localhost/photo-1");

    fireEvent.click(screen.getByTestId("replace-photo"));
    // The new ref is a new cache key: a second read, a new object URL, and the
    // bytes the previous ref produced are no longer in any view.
    await waitFor(() =>
      expect(trigger.querySelector("img")?.getAttribute("src")).toBe(
        "blob:http://localhost/photo-2",
      ),
    );
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(2);

    // The header behind the trigger moves with it, not one commit behind.
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(
      screen.getByRole("menu").querySelector("img")?.getAttribute("src"),
    ).toBe("blob:http://localhost/photo-2");

    fireEvent.click(screen.getByTestId("clear-photo"));
    await waitFor(() => expect(trigger).toHaveTextContent("A"));
    expect(trigger.querySelector("img")).toBeNull();
  });

  it("patient branch keeps the name off the trigger and the phone hidden until the menu opens", async () => {
    const trigger = await renderPatientWithProfile(NAMED_PROFILE);

    // No name label beside the circle; no full phone while closed.
    expect(trigger).not.toHaveTextContent("Asha");
    expect(screen.queryByText("Asha Devi")).toBeNull();
    expect(screen.queryByText("+911234567890")).toBeNull();

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("#538 shows the doctor a person-icon account avatar instead of phone digits", async () => {
    // #557: seeded with a photo ref on purpose. The doctor disc is deliberately
    // un-hydrated (that is later work), and this is the assertion that keeps it
    // that way: a stored photo must not cost a doctor an authed read for bytes
    // no surface renders.
    const trigger = await renderClosedTrigger(ME_RESPONSE_DOCTOR, {
      ...NAMED_PROFILE,
      photo_ref: "patient/7/photo-1.enc",
    });

    // The generic person icon entry point - no digit text, and no saved photo
    // on the chrome disc (the doctor photo lives on the Profile page, #543).
    expect(trigger).not.toHaveTextContent("90");
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    // Let hydration settle first: a read that arrives a tick late is still a
    // read, so this has to be an assertion about the branch, not about timing.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(profileApi.fetchPatientPhoto).not.toHaveBeenCalled();

    // The dropdown behind the avatar still carries the full phone, role badge
    // and dictionary-driven Log out.
    await openViaKeyboard();
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Doctor",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });

  it("#543 opens the doctor Profile page from the avatar dropdown", async () => {
    await renderClosedTrigger(ME_RESPONSE_DOCTOR);
    await openViaKeyboard();

    const profileItem = screen.getByTestId("account-menu-doctor-profile");
    expect(profileItem).toHaveAttribute("href", "/doctor/profile");
    expect(profileItem).toHaveTextContent("Profile");
  });

  it("#543 keeps the Profile row off non-doctor staff menus", async () => {
    await renderClosedTrigger(ME_RESPONSE_PARTNER);
    await openViaKeyboard();

    expect(screen.queryByTestId("account-menu-doctor-profile")).toBeNull();
  });

  it("non-doctor staff keeps the phone-digit trigger and dropdown verbatim", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_PARTNER);

    expect(trigger).toHaveTextContent("90");
    expect(trigger.querySelector("svg")).toBeNull();
    expect(trigger.querySelector("img")).toBeNull();

    await openViaKeyboard();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Partner",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });
});

describe("AccountMenu mobile placement (#525)", () => {
  it("hides the patient trigger below lg so the phone account lives only in the More sheet", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE);

    expect(trigger.className).toContain("hidden");
    expect(trigger.className).toContain("lg:inline-flex");
    // The shared Avatar still resolves to the patient person icon.
    expect(trigger.querySelector("svg")).not.toBeNull();
  });

  it("keeps the non-doctor staff phone-digit trigger fully visible at every width", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_PARTNER);

    expect(trigger).toHaveTextContent("90");
    expect(trigger.className).toContain("flex");
    expect(trigger.className).not.toContain("hidden");
  });
});

describe("AccountMenu desktop identity dropdown (#526)", () => {
  function openPatientMenu() {
    return renderPatientWithProfile(NAMED_PROFILE).then((trigger) => {
      fireEvent.keyDown(trigger, { key: "Enter" });
      return waitFor(() =>
        expect(screen.getByRole("menu")).toBeInTheDocument(),
      );
    });
  }

  it("identity header shows the saved name, full E.164 phone and avatar initial", async () => {
    await openPatientMenu();

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Asha Devi",
    );
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    // The header avatar owns the named initial inside the open menu.
    expect(within(screen.getByRole("menu")).getByText("A")).toBeInTheDocument();
  });

  it("falls back to the masked phone and still shows the full E.164 without a saved name", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      maskedPhone("+911234567890"),
    );
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "+91 XXXXXX7890",
    );
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("renders a live Profile & Settings entry pointing at the profile page", async () => {
    await openPatientMenu();

    const entry = screen.getByRole("menuitem", {
      name: "Profile & Settings",
    });
    expect(entry.tagName).toBe("A");
    expect(entry).toHaveAttribute("href", "/patient/profile");
  });

  it("navigates to the profile page when the Profile & Settings entry is activated", async () => {
    await openPatientMenu();

    fireEvent.click(
      screen.getByRole("menuitem", { name: "Profile & Settings" }),
    );

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/patient/profile"),
    );
  });

  it("shows the Complete your profile CTA only while basics are missing", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const cta = screen.getByTestId("account-menu-complete-profile");
    expect(cta).toHaveTextContent("Complete your profile");
    expect(cta).toHaveAttribute("href", "/patient/profile");
  });

  it("navigates to the profile page when the CTA is activated", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => screen.getByRole("menu"));

    fireEvent.click(screen.getByTestId("account-menu-complete-profile"));

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/patient/profile"),
    );
  });

  it("keeps the CTA when a saved profile is missing a basic field", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE, {
      ...NAMED_PROFILE,
      name: "  ",
    });
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByTestId("account-menu-complete-profile"),
    ).toBeInTheDocument();
  });

  it("hides the CTA once basics (name, age, gender) are saved", async () => {
    await openPatientMenu();

    expect(
      screen.queryByTestId("account-menu-complete-profile"),
    ).not.toBeInTheDocument();
  });

  it("keeps role switching for multi-role accounts", async () => {
    const trigger = await renderClosedTrigger(
      {
        subject_id: "42",
        phone: "+911234567890",
        roles: ["patient", "doctor"],
      },
      NAMED_PROFILE,
    );
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByRole("menuitem", { name: "Switch to Doctor" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Doctor" }));
    // Radix closes on select; reopening shows the role did switch.
    fireEvent.keyDown(screen.getByTestId("account-menu"), { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Doctor",
    );
  });

  it("keeps the single-role patient menu free of role-switch clutter", async () => {
    await openPatientMenu();

    expect(screen.queryByText(/Switch to/)).not.toBeInTheDocument();
  });

  it("renders a red dictionary-driven Log out that ends the session", async () => {
    await openPatientMenu();

    const logoutItem = screen.getByRole("menuitem", { name: "Log out" });
    expect(logoutItem.className).toContain("text-danger");

    fireEvent.click(logoutItem);
    expect(mockReplace).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });

  it("renders the account menu strings bilingually", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("अकाउंट मेन्यू");

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByRole("menuitem", { name: "लॉग आउट" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "प्रोफ़ाइल और सेटिंग" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "अपनी प्रोफ़ाइल पूरी करें" }),
    ).toBeInTheDocument();
  });

  it("keeps the patient dropdown axe-clean", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const { violations } = await axe.run(screen.getByRole("menu"));
    expect(violations).toEqual([]);
  });
});

describe("AccountMenu stale sessions", () => {
  it("degrades to subject-id-only when /me carries no phone field", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_NO_PHONE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(screen.getByText("Subject #42")).toBeInTheDocument();
    expect(screen.queryByText("+911234567890")).toBeNull();
  });

  it("renders Subject #id in the identity header and Log out still works", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_NO_PHONE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Subject #42",
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(mockReplace).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });
});
