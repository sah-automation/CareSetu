// PHASE-2.6 T03 (#194): component-seam coverage for the language engine -
// default locale, persisted-choice adoption across reloads (D1), <html lang>
// tracking, and the provider-less fallback the pre-existing suites rely on
// when rendering surfaces bare.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { __resetLangForTests, LangProvider, useLang } from "./LangContext";

function Probe() {
  const { lang, setLang } = useLang();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <button type="button" onClick={() => setLang("hi")}>
        to-hi
      </button>
      <button type="button" onClick={() => setLang("en")}>
        to-en
      </button>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
  __resetLangForTests();
  document.documentElement.lang = "";
});

afterEach(() => {
  cleanup();
});

describe("LangProvider", () => {
  it("defaults to en until a choice exists", async () => {
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );

    expect(await screen.findByText(/^en$/)).toBeInTheDocument();
  });

  it("adopts the persisted choice on mount (reload persistence)", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );

    expect(await screen.findByText(/^hi$/)).toBeInTheDocument();
  });

  it("persists a new choice for the next visit", async () => {
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );
    await screen.findByText(/^en$/);

    fireEvent.click(screen.getByRole("button", { name: "to-hi" }));

    expect(await screen.findByText(/^hi$/)).toBeInTheDocument();
    // Simulate a reload: a fresh tree adopts what was stored.
    expect(localStorage.getItem("caresetu.lang")).toBe("hi");
    cleanup();
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );
    expect(await screen.findByText(/^hi$/)).toBeInTheDocument();
  });

  it("ignores an invalid stored value", async () => {
    localStorage.setItem("caresetu.lang", "fr");
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );

    expect(await screen.findByText(/^en$/)).toBeInTheDocument();
  });

  it("keeps <html lang> tracking the active locale", async () => {
    render(
      <LangProvider>
        <Probe />
      </LangProvider>,
    );
    await screen.findByText(/^en$/);

    fireEvent.click(screen.getByRole("button", { name: "to-hi" }));
    await screen.findByText(/^hi$/);
    expect(document.documentElement.lang).toBe("hi");

    fireEvent.click(screen.getByRole("button", { name: "to-en" }));
    await screen.findByText(/^en$/);
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("useLang without a provider", () => {
  it("still switches and persists (bare-render fallback)", async () => {
    render(<Probe />);
    await screen.findByText(/^en$/);

    fireEvent.click(screen.getByRole("button", { name: "to-hi" }));

    expect(await screen.findByText(/^hi$/)).toBeInTheDocument();
    expect(localStorage.getItem("caresetu.lang")).toBe("hi");
    expect(document.documentElement.lang).toBe("hi");
  });
});
