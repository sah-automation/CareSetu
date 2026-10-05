// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
  uploadDoctorProfilePhoto,
  type DoctorProfileView,
} from "@/lib/doctor/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPathname = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
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

// A production-shaped doctor session: the grants table issues only
// patient|partner|operator, so a doctor signs in with `["partner"]` and is a
// doctor by partner *type*. The shell's own role - not the session's - is what
// decides doctor-ness.
vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["partner"] },
    selectedRole: "partner",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

// The shell's Cases count pill rides the existing open-cases feed; the whole
// care module is mocked so this suite stays unit scoped.
vi.mock("@/lib/care/api", () => ({
  listOpenCases: vi.fn(),
}));

vi.mock("@/lib/doctor/api", () => ({
  fetchDoctorProfile: vi.fn(),
  // #617, #623: the practice write the practice card makes, and the only one this
  // suite exercises. The whole-form PUT used to sit above it mocked and unused - a
  // fake standing in for a route that 405s. #623 deleted it with the client export
  // it stood in for, so this suite now mocks exactly what it calls.
  updateDoctorProfilePractice: vi.fn(),
  uploadDoctorProfilePhoto: vi.fn(),
  fetchDoctorProfilePhoto: vi.fn(),
  deleteDoctorProfilePhoto: vi.fn(),
}));

// The fee editor inherited from the landing still runs its own PATCH route.
vi.mock("@/lib/partner/api", () => ({
  updateConsultationFee: vi.fn(),
}));

const getProfile = vi.mocked(fetchDoctorProfile);
// #623: the whole-form `saveProfile` mock went with the export it stubbed; #611
// removed the route and every section writes its own. What is left is the
// practice-section writer, which is the only one this suite exercises.
const savePractice = vi.mocked(updateDoctorProfilePractice);
const uploadPhoto = vi.mocked(uploadDoctorProfilePhoto);
const getPhoto = vi.mocked(fetchDoctorProfilePhoto);
const deletePhoto = vi.mocked(deleteDoctorProfilePhoto);
const getOpenCases = vi.mocked(listOpenCases);
const t = STRINGS.en.doctorProfile;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const STORED_REF = "doctor/7/photo-1.enc";
const UPLOADED_REF = "doctor/7/photo-2.enc";

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: STORED_REF,
    practice_name: "Sunrise Clinic",
    clinic_name: "Sunrise Clinic",
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
    consulting_days: ["mon", "tue"],
    consulting_hours: "Mon-Sat, 9am-1pm",
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

// A section write touches only its own columns, and the reply is the whole
// projection with everything the write did not touch carried through - including
// the photo ref, which no section write body can even mention. The projection
// names the doctor's practice as `practice_name` while the practice write names
// the column it owns `full_name`, so the rename happens here rather than by
// spreading a body whose keys are not the projection's.
function saveEchoesTheStoredRef() {
  savePractice.mockImplementation(async (update) => {
    const current = getStored();
    return {
      ...current,
      practice_name: update.full_name,
      clinic_name: update.clinic_name,
      specialties: update.specialties,
      experience_years: update.experience_years,
      photo_ref: current.photo_ref,
      verified: current.verified,
      area: current.area,
      credentials: current.credentials,
      consultation_fee: current.consultation_fee,
    };
  });
}

/** The projection the mocked backend would now answer with, per endpoint. */
let stored: DoctorProfileView;

function getStored(): DoctorProfileView {
  return stored;
}

// ---------------------------------------------------------------------------
// The tree production builds: the shared source above the shell, the shell
// above the page. Nothing here is a prop the shell would not really pass.
// ---------------------------------------------------------------------------

function renderConsoleAndProfilePage() {
  return render(
    <DoctorProfileProvider>
      <AppShell role="doctor">
        <DoctorProfilePage />
      </AppShell>
    </DoctorProfileProvider>,
  );
}

async function renderBothSurfaces(view: DoctorProfileView = profile()) {
  stored = view;
  getProfile.mockResolvedValue(view);
  mockPathname.mockReturnValue("/doctor/profile");
  const result = renderConsoleAndProfilePage();
  // The page is the page's own readiness signal, so waiting on it is waiting
  // on the shared read having answered.
  await waitFor(() => screen.getByTestId("profile-declared-band"));
  return result;
}

const accountTrigger = () => screen.getByTestId("account-menu");

async function openIdentityHeader() {
  const trigger = accountTrigger();
  fireEvent.keyDown(trigger, { key: "Enter" });
  await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
  return screen.getByRole("menu");
}

async function closeIdentityHeader() {
  fireEvent.keyDown(accountTrigger(), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
}

/** The <img> a surface is showing. Asserting inside waitFor makes it retry. */
async function imageIn(root: ParentNode): Promise<HTMLImageElement> {
  return waitFor(() => {
    const img = root.querySelector("img");
    expect(img).not.toBeNull();
    return img;
  }).then((el) => el as HTMLImageElement);
}

function pickPhoto(name: string) {
  fireEvent.change(screen.getByTestId("profile-photo-input"), {
    target: { files: [new File(["bytes"], name, { type: "image/jpeg" })] },
  });
}

// ---------------------------------------------------------------------------
// jsdom plumbing
// ---------------------------------------------------------------------------

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

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let photoUrls: number;

beforeEach(() => {
  photoUrls = 0;
  __resetLangForTests();
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  // A distinct URL per call, so a test can tell WHICH generation of the photo a
  // surface is showing - which is the whole of a replace and a remove.
  URL.createObjectURL = vi.fn(
    () => `blob:http://localhost/photo-${(photoUrls += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;

  stored = profile();
  getOpenCases.mockReset();
  getOpenCases.mockResolvedValue([]);
  getProfile.mockReset();
  savePractice.mockReset();
  uploadPhoto.mockReset();
  getPhoto.mockReset();
  deletePhoto.mockReset();
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/jpeg" }));
  deletePhoto.mockResolvedValue(undefined);
  uploadPhoto.mockImplementation(async (file) => {
    stored = {
      ...stored,
      photo_ref: file.name === "me.jpg" ? UPLOADED_REF : STORED_REF,
    };
    return { photo_ref: stored.photo_ref ?? UPLOADED_REF };
  });
  deletePhoto.mockImplementation(async () => {
    stored = { ...stored, photo_ref: null };
  });
  saveEchoesTheStoredRef();
});

afterEach(() => {
  // Unmounting drops the photo resolver's cache entries, so it has to happen
  // before the stubs come back - otherwise a live entry survives into the next
  // test and a byte read is answered from a dead cache.
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

// ---------------------------------------------------------------------------

describe("the doctor account menu and the doctor Profile page share one profile source (#583)", () => {
  it("shows an uploaded photo in the chrome, with no reload", async () => {
    await renderBothSurfaces(profile({ photo_ref: null }));

    // Before the edit, the chrome shows the person icon: absence reads as
    // intentional rather than broken.
    const trigger = accountTrigger();
    expect(trigger.querySelector("img")).toBeNull();
    expect(trigger.querySelector("svg")).not.toBeNull();

    uploadPhoto.mockResolvedValue({ photo_ref: UPLOADED_REF });
    pickPhoto("me.jpg");

    // The page's own preview lands first, in the identity band's avatar (#615
    // moved the picker into the band, so the avatar is the page's surface)...
    const pageImg = await imageIn(screen.getByTestId("profile-identity"));
    // ...and so does the chrome's account avatar, off the same source. No
    // reload, no second read of the projection, no second read of the bytes.
    const triggerImg = await imageIn(trigger);
    expect(triggerImg.getAttribute("src")).toMatch(/^blob:/);
    // ADR-0020 D1/D2: the stored key is opaque and never browser-reachable, so
    // a src that carried it would be the whole defect back.
    expect(triggerImg.getAttribute("src")).not.toContain(UPLOADED_REF);
    // Both surfaces are showing the same stored photo, read once between them -
    // the two object URLs are per consumer, so the counted read is the claim.
    expect(pageImg.getAttribute("src")).toMatch(/^blob:/);
    expect(getProfile).toHaveBeenCalledTimes(1);
    expect(getPhoto).toHaveBeenCalledTimes(1);
  });

  it("replaces the chrome's photo the instant the photo is replaced", async () => {
    await renderBothSurfaces();

    const trigger = accountTrigger();
    const before = (await imageIn(trigger)).getAttribute("src");

    uploadPhoto.mockResolvedValue({ photo_ref: UPLOADED_REF });
    pickPhoto("me.jpg");

    await waitFor(() =>
      expect(
        accountTrigger().querySelector("img")?.getAttribute("src"),
      ).not.toBe(before),
    );
    const after = (await imageIn(accountTrigger())).getAttribute("src");
    // A new generation of the photo, not the revoked old one still on screen.
    expect(after).not.toBe(before);
    expect(after).not.toContain(STORED_REF);
  });

  it("drops a removed photo from the chrome, not just from the page", async () => {
    await renderBothSurfaces();

    const trigger = accountTrigger();
    await imageIn(trigger);
    // The dropdown's identity header is showing the same photo.
    await imageIn(await openIdentityHeader());
    await closeIdentityHeader();

    fireEvent.click(screen.getByTestId("profile-photo-remove"));
    await waitFor(() => expect(deletePhoto).toHaveBeenCalled());

    // The sharpest of the three. A photo the doctor has deleted must stop being
    // displayed in the product, chrome included - it used to keep rendering
    // there until a full reload, which is the worst of the three because the
    // doctor has just declared that picture should not be there.
    await waitFor(() =>
      expect(accountTrigger().querySelector("img")).toBeNull(),
    );
    expect(accountTrigger().querySelector("svg")).not.toBeNull();
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-identity").querySelector("img"),
      ).toBeNull(),
    );
    // The identity header's avatar agrees with the trigger rather than keeping
    // the removed photo's bytes alive.
    const reopened = await openIdentityHeader();
    expect(reopened.querySelector("img")).toBeNull();
    // Nothing is left pointing at the removed ref.
    expect(document.body.innerHTML).not.toContain(STORED_REF);
  });

  it("still shows the photo after a full console reload", async () => {
    const first = await renderBothSurfaces();
    await imageIn(accountTrigger());

    // A reload, as the browser does it: the whole console unmounts and mounts
    // again with the store unchanged. The photo must not be an artifact of the
    // mount that happened to load it.
    first.unmount();
    await renderBothSurfaces();

    const src = (await imageIn(accountTrigger())).getAttribute("src");
    expect(src).toBeTruthy();
    expect(src).not.toContain(STORED_REF);
    // The fresh mount read and resolved for itself - once, for both surfaces.
    expect(getProfile).toHaveBeenCalledTimes(2);
    expect(getPhoto).toHaveBeenCalledTimes(2);
  });

  it("shows a saved practice name in the identity header, with no reload", async () => {
    await renderBothSurfaces();

    await openIdentityHeader();
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Sunrise Clinic",
    );
    await closeIdentityHeader();

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 2" },
    });
    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-practice-saved")).toHaveTextContent(
        t.practiceSaved,
      ),
    );

    // The dropdown's identity header is the ONLY place anywhere in the doctor
    // console where the doctor is named, so a rename that does not land there is
    // a name that is out of date everywhere.
    await openIdentityHeader();
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Sunrise Clinic 2",
    );
    await closeIdentityHeader();
    // The practice write declared no photo ref, so it could not have detached the
    // stored photo; the reply carried it through and the chrome still shows it.
    expect(savePractice.mock.calls[0][0]).not.toHaveProperty("photo_ref");
    expect((await imageIn(accountTrigger())).getAttribute("src")).toMatch(
      /^blob:/,
    );
  });

  it("reads the projection once for both surfaces, and re-reads on neither", async () => {
    const { rerender } = await renderBothSurfaces();

    // Both surfaces are up at once, on one read: not one for the chrome and one
    // for the page. Counted, not inferred from a rendering that looked right.
    expect(getProfile).toHaveBeenCalledTimes(1);

    // Moving between console pages keeps the route-group layout mounted, so the
    // read does not re-run - which is exactly why the shell's own once-only read
    // used to leave the two surfaces silently diverged.
    rerender(
      <DoctorProfileProvider>
        <AppShell role="doctor">
          <DoctorProfilePage />
        </AppShell>
      </DoctorProfileProvider>,
    );
    await waitFor(() => screen.getByTestId("profile-declared-band"));
    expect(getProfile).toHaveBeenCalledTimes(1);

    // And the account menu makes no request of its own: opening it is instant.
    await openIdentityHeader();
    expect(getProfile).toHaveBeenCalledTimes(1);
    expect(getPhoto).toHaveBeenCalledTimes(1);
  });

  it("keeps the rest of the console usable when the profile read fails", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    getProfile.mockRejectedValue(new Error("profile read down"));
    stored = profile();
    mockPathname.mockReturnValue("/doctor/profile");
    renderConsoleAndProfilePage();

    // The page offers the failure and a retry, the chrome degrades to its icon,
    // and neither of them blocks navigation.
    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByTestId("app-shell")).toBeVisible();
    expect(screen.getByTestId("sidebar")).toBeVisible();
    expect(accountTrigger().querySelector("img")).toBeNull();
    expect(accountTrigger().querySelector("svg")).not.toBeNull();
    // A blip costs no byte read: there is no ref to ask for.
    expect(getPhoto).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();

    // And a retry that succeeds renders the profile, with no page reload.
    getProfile.mockResolvedValue(stored);
    await act(async () => {
      fireEvent.click(screen.getByTestId("error-banner-retry"));
    });
    await waitFor(() => screen.getByTestId("profile-declared-band"));
    expect(getProfile).toHaveBeenCalledTimes(2);
    const triggerImg = await imageIn(accountTrigger());
    expect(triggerImg.getAttribute("src")).not.toContain(STORED_REF);
  });
});
