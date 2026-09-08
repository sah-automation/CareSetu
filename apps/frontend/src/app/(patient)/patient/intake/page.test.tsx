// PHASE-7 T15 (#359): intake-start mode chooser suite - renders the two
// oversized first-class mode buttons (voice default-highlighted, text equally
// first-class), bilingual EN/HI parity, and lives in the patient shell with
// the Start nav active.

import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IntakeStartPage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/intake",
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

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["patient"] },
    selectedRole: "patient",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

beforeEach(() => {
  __resetLangForTests();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function langFlip() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

function LangFlipHost() {
  return (
    <>
      {langFlip()}
      <IntakeStartPage />
    </>
  );
}

describe("IntakeStartPage (inside the patient shell)", () => {
  it("mounts within the patient AppShell", () => {
    render(
      <PatientGroupLayout>
        <IntakeStartPage />
      </PatientGroupLayout>,
    );

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
  });

  it("renders the page header with bilingual title and description", () => {
    render(<IntakeStartPage />);

    expect(
      screen.getByRole("heading", { name: "Tell us what's bothering you" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No forms, no typing. This helps your doctor understand you faster.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the breadcrumb trail with Home and Start visit", () => {
    render(<IntakeStartPage />);

    const back = screen.getByTestId("breadcrumb-back");
    expect(back).toHaveTextContent("Home");
    expect(back).toHaveAttribute("href", "/patient");

    const current = screen.getByTestId("breadcrumb-current");
    expect(current).toHaveTextContent("Start visit");
  });
});

describe("IntakeStartPage mode buttons", () => {
  it("renders two mode buttons with voice default-highlighted", () => {
    render(<IntakeStartPage />);

    const voice = screen.getByTestId("mode-voice");
    const text = screen.getByTestId("mode-text");

    expect(voice).toBeInTheDocument();
    expect(text).toBeInTheDocument();

    // Voice has the accent-soft background highlight (unique to voice)
    expect(voice.className).toContain("bg-accent-soft");

    // Text does not have the accent-soft background
    expect(text.className).not.toContain("bg-accent-soft");
  });

  it("voice button has the correct label, sub-label, and link", () => {
    render(<IntakeStartPage />);

    const voice = screen.getByTestId("mode-voice");
    expect(voice).toHaveTextContent("Speak");
    expect(voice).toHaveTextContent("Record in Hindi or English");
    expect(voice).toHaveAttribute("href", "/patient/intake/voice");
  });

  it("text button has the correct label, sub-label, and link", () => {
    render(<IntakeStartPage />);

    const text = screen.getByTestId("mode-text");
    expect(text).toHaveTextContent("Type");
    expect(text).toHaveTextContent("Type your symptoms");
    expect(text).toHaveAttribute("href", "/patient/intake/text");
  });

  it("both buttons are equal size (same min-height)", () => {
    render(<IntakeStartPage />);

    const voice = screen.getByTestId("mode-voice");
    const text = screen.getByTestId("mode-text");

    expect(voice.className).toContain("min-h-[104px]");
    expect(text.className).toContain("min-h-[104px]");
  });
});

describe("IntakeStartPage bilingual EN/HI (REQ-006)", () => {
  it("switches all visible copy to Hindi when the locale flips", () => {
    render(<LangFlipHost />);

    fireEvent.click(screen.getByText("flip-lang"));

    expect(
      screen.getByRole("heading", { name: STRINGS.hi.intake.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(STRINGS.hi.intake.reassure)).toBeInTheDocument();
    expect(screen.getByTestId("mode-voice")).toHaveTextContent(
      STRINGS.hi.intake.modeVoice,
    );
    expect(screen.getByTestId("mode-voice")).toHaveTextContent(
      STRINGS.hi.intake.modeVoiceSub,
    );
    expect(screen.getByTestId("mode-text")).toHaveTextContent(
      STRINGS.hi.intake.modeText,
    );
    expect(screen.getByTestId("mode-text")).toHaveTextContent(
      STRINGS.hi.intake.modeTextSub,
    );
    expect(screen.getByTestId("breadcrumb-back")).toHaveTextContent(
      STRINGS.hi.nav.home,
    );
    expect(screen.getByTestId("breadcrumb-current")).toHaveTextContent(
      STRINGS.hi.intake.breadcrumb,
    );
  });

  it("starts in English with the correct EN strings", () => {
    render(<IntakeStartPage />);

    expect(
      screen.getByRole("heading", { name: STRINGS.en.intake.title }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("mode-voice")).toHaveTextContent(
      STRINGS.en.intake.modeVoice,
    );
    expect(screen.getByTestId("mode-text")).toHaveTextContent(
      STRINGS.en.intake.modeText,
    );
  });
});
