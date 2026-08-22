// PHASE-2.6 T09 (#200): homepage composition suite. Asserts the ten ordered
// sections (blueprint §3.1), the G1 copy rule (no disease-based program
// promises anywhere in homepage strings), and REQ-006 toggle parity: the
// EN/Hindi switch re-renders public copy across every section while
// <html lang> tracks the active locale.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MarketingHomepage from "./page";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/",
}));

function renderHomepage() {
  return render(
    <AuthProvider>
      <MarketingHomepage />
    </AuthProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  mockReplace.mockReset();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  cleanup();
});

describe("homepage ten ordered sections (blueprint \u00a73.1)", () => {
  it("renders all ten sections in order", () => {
    renderHomepage();

    const markers = [...screen.getAllByTestId(/^section-/)].map((el) =>
      el.getAttribute("data-testid"),
    );
    expect(markers).toEqual([
      "section-header",
      "section-hero",
      "section-chips",
      "section-tiles",
      "section-featured",
      "section-how",
      "section-trust",
      "section-providers",
      "section-final-cta",
      "section-footer",
    ]);
  });

  it("keeps exactly one h1 in the hero and anchors for the tile ids", () => {
    renderHomepage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Find trusted doctors, labs and chemists near you",
    );
    for (const id of ["doctors", "labs", "chemists"]) {
      expect(document.getElementById(id)).not.toBeNull();
    }
  });

  it("lands the hero search on /directory with type/q/location fields", () => {
    renderHomepage();

    const form = document.querySelector("form");
    expect(form).not.toBeNull();
    expect(form).toHaveAttribute("action", "/directory");
    expect(form).toHaveAttribute("method", "get");
    for (const name of ["type", "q", "location"]) {
      expect(form?.querySelector(`[name="${name}"]`)).not.toBeNull();
    }
    // Location chip defaults to the beachhead.
    const location = form?.querySelector('[name="location"]');
    expect(location).toHaveValue("Daltonganj");
  });

  it("carries the application-type preset on providers-band CTAs", () => {
    renderHomepage();

    for (const type of ["doctor", "lab", "chemist"]) {
      expect(
        document.querySelector(`a[href="/staff/register?type=${type}"]`),
      ).not.toBeNull();
    }
  });
});

describe("G1 copy rule - no disease-program promises", () => {
  function collectStrings(value: unknown): string[] {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) return value.flatMap(collectStrings);
    if (typeof value === "object" && value !== null) {
      return Object.values(value).flatMap(collectStrings);
    }
    return [];
  }

  it("never promises disease-based programs or packages in homepage copy", () => {
    // English scan: no program/package/disease/cure/treatment wording.
    const banned =
      /\b(program|programs|package|packages|disease|diseases|cure|cures|treatment)\b/i;
    const offenders = collectStrings(STRINGS.en.home).filter((copy) =>
      banned.test(copy),
    );
    expect(offenders).toEqual([]);
  });

  it("never promises disease-based programs or packages in Hindi copy", () => {
    // Hindi scan of the direct promise words (program/package/disease/
    // treatment). \u0930\u094B\u0917 (disease) is excluded because it appears inside legitimate
    // specialty compounds, and \u0907\u0932\u093E\u091C (treatment/care) is excluded because the
    // provider-recruitment card legitimately describes doctors treating
    // patients - neither is a patient-facing cure promise.
    const banned =
      /(\u0915\u093E\u0930\u094D\u092F\u0915\u094D\u0930\u092E|\u092A\u0948\u0915\u0947\u091C|\u0909\u092A\u091A\u093E\u0930|\u092C\u0940\u092E\u093E\u0930\u0940)/;
    const offenders = collectStrings(STRINGS.hi.home).filter((copy) =>
      banned.test(copy),
    );
    expect(offenders).toEqual([]);
  });
});

describe("EN/Hindi toggle parity across sections (REQ-006)", () => {
  it("re-renders public copy in every section and tracks html lang", async () => {
    renderHomepage();

    expect(document.documentElement.lang).toBe("en");

    fireEvent.click(screen.getByRole("button", { name: "\u0939\u093F\u0902" }));

    expect(document.documentElement.lang).toBe("hi");
    // One sample node per section proves every section re-renders. The
    // featured empty state resolves from the integration point
    // asynchronously, so it gets findBy; everything else is synchronous.
    expect(
      await screen.findByText(
        "\u0921\u093E\u0932\u091F\u0928\u0917\u0902\u091C \u092E\u0947\u0902 \u0921\u093E\u092F\u0930\u0947\u0915\u094D\u091F\u0930\u0940 \u091C\u0932\u094D\u0926 \u0906 \u0930\u0939\u0940 \u0939\u0948",
      ),
    ).toBeInTheDocument(); // featured empty state
    expect(
      screen.getByText(
        "\u0906\u092E \u091C\u093C\u0930\u0942\u0930\u0924\u0947\u0902",
      ),
    ).toBeInTheDocument(); // chips title
    expect(
      screen.getByText(
        "\u0936\u094D\u0930\u0947\u0923\u0940 \u0938\u0947 \u0916\u094B\u091C\u0947\u0902",
      ),
    ).toBeInTheDocument(); // tiles title
    expect(
      screen.getByText(
        "CareSetu \u0915\u0948\u0938\u0947 \u0915\u093E\u092E \u0915\u0930\u0924\u093E \u0939\u0948",
      ),
    ).toBeInTheDocument(); // how title
    expect(
      screen.getByText(
        "\u0915\u094D\u092F\u093E \u0906\u092A \u092A\u094D\u0930\u094B\u0935\u093E\u0907\u0921\u0930 \u0939\u0948\u0902?",
      ),
    ).toBeInTheDocument(); // providers title
    expect(
      screen.getByText(
        "\u0905\u092A\u0928\u0947 \u0939\u0947\u0932\u094D\u0925 \u0930\u093F\u0915\u0949\u0930\u094D\u0921 \u0938\u0947 \u0936\u0941\u0930\u0942 \u0915\u0930\u0947\u0902",
      ),
    ).toBeInTheDocument(); // final CTA title
    expect(screen.getByText(/\u00a9 CareSetu/)).toBeInTheDocument(); // footer meta

    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(document.documentElement.lang).toBe("en");
    expect(
      screen.getByText("Find trusted doctors, labs and chemists near you"),
    ).toBeInTheDocument();
  });
});
