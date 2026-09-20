// PHASE-8.1 T11 (#485): patient Find Care page suite. The shared
// DirectoryBrowser surface is exercised through its own seams here - verified
// directory cards render from the directory-client fixture, filter commits
// stay on the patient route (never the public /directory, so the patient
// never leaves the shell), and the "Book consultation" deep link appears only
// when the intake flow signals an in-progress intake via ?intake=<id>,
// pointing at that intake's pick step.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FindPage from "./page";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import type { DirectoryEntry } from "@/lib/directory/search";

const state = vi.hoisted(() => ({
  params: new URLSearchParams(),
  searchDirectory: vi.fn(),
  mockReplace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => state.params,
  useRouter: () => ({ replace: state.mockReplace, push: vi.fn() }),
  usePathname: () => "/patient/find",
}));

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: React.ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/directory/search", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/directory/search")>();
  return { ...original, searchDirectory: state.searchDirectory };
});

const t = STRINGS.en.findCare;
const search = vi.mocked(state.searchDirectory);
const replace = vi.mocked(state.mockReplace);

function doctor(
  id: number,
  name: string,
  overrides: Partial<DirectoryEntry> = {},
): DirectoryEntry {
  return {
    partner_id: id,
    practice_name: name,
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: id,
    verified: true,
    consultation_fee: 40000,
    ...overrides,
  };
}

async function flush() {
  await act(async () => {});
}

async function renderPage() {
  render(<FindPage />);
  await flush();
}

beforeEach(() => {
  __resetLangForTests();
  state.params = new URLSearchParams();
  state.searchDirectory.mockReset();
  state.mockReplace.mockReset();
  state.searchDirectory.mockResolvedValue({
    items: [doctor(1, "Dr. A. Kumar")],
    fell_back: false,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FindCareBrowser verified directory browse", () => {
  it("renders verified provider cards from the directory client fixture", async () => {
    state.searchDirectory.mockResolvedValue({
      items: [doctor(1, "Dr. A. Kumar")],
      fell_back: false,
    });
    await renderPage();
    await waitFor(() => screen.getByTestId("directory-cards"));

    expect(screen.getByTestId("directory-card")).toHaveAttribute(
      "href",
      "/providers/1",
    );
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(
      screen.getByText(
        "General Physician \u00B7 Doctors \u00B7 Medininagar Rd",
      ),
    ).toBeInTheDocument();
  });

  it("keeps filter commits on the patient route, preserving the intake param", async () => {
    state.params.set("intake", "42");
    state.params.set("type", "doctor");
    await renderPage();
    await waitFor(() => screen.getByTestId("directory-cards"));

    fireEvent.click(screen.getAllByTestId("type-chip")[0]);

    // Commits stay under the patient shell (/patient/find), never the public
    // /directory, and the in-progress intake param survives the commit.
    expect(replace).toHaveBeenCalledWith("/patient/find?intake=42");
  });
});

describe("FindCareBrowser booking deep link", () => {
  it("deep-links Book consultation into the intake pick step when an intake is in progress", async () => {
    state.params.set("intake", "42");
    state.searchDirectory.mockResolvedValue({
      items: [doctor(1, "Dr. A. Kumar")],
      fell_back: false,
    });
    await renderPage();
    await waitFor(() => screen.getByTestId("find-care-book"));

    expect(screen.getByTestId("resume-consult")).toHaveTextContent(
      t.resumeTitle,
    );
    expect(screen.getByTestId("find-care-book")).toHaveAttribute(
      "href",
      "/patient/intake/42/pick",
    );
  });

  it("hides the booking deep link without an in-progress intake", async () => {
    await renderPage();
    await waitFor(() => screen.getByTestId("directory-cards"));

    expect(screen.queryByTestId("find-care-book")).not.toBeInTheDocument();
    expect(screen.queryByTestId("resume-consult")).not.toBeInTheDocument();
  });

  it("ignores a malformed intake param - no fabricated deep link", async () => {
    state.params.set("intake", "not-a-number");
    await renderPage();
    await waitFor(() => screen.getByTestId("directory-cards"));

    expect(screen.queryByTestId("find-care-book")).not.toBeInTheDocument();
  });
});

describe("FindCareBrowser bilingual parity (REQ-006)", () => {
  it("renders the resume copy in Hindi when the locale flips", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    state.params.set("intake", "42");
    await renderPage();
    await waitFor(() => screen.getByTestId("find-care-book"));

    expect(screen.getByTestId("resume-consult")).toHaveTextContent(
      STRINGS.hi.findCare.resumeTitle,
    );
    expect(screen.getByTestId("find-care-book")).toHaveTextContent(
      STRINGS.hi.findCare.bookCta,
    );
  });
});
