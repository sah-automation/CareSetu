import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "./dropdown-menu";

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
    // Minimal stand-in so dispatched pointerdown carries button/ctrlKey.
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

afterEach(() => {
  cleanup();
});

type SetupOptions = {
  onAction?: () => void;
};

function setup({ onAction }: SetupOptions = {}) {
  render(
    <DropdownMenu>
      <DropdownMenuTrigger data-testid="trigger">Actions</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Record actions</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => onAction?.()}>
          Download
        </DropdownMenuItem>
        <DropdownMenuItem disabled onSelect={() => onAction?.()}>
          Share
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem checked>
          Show summaries
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

describe("DropdownMenu", () => {
  it("renders the trigger but no content when closed", () => {
    setup();

    expect(screen.getByTestId("trigger")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens the menu with its items when the trigger is pressed", () => {
    setup();

    fireEvent.pointerDown(screen.getByTestId("trigger"));
    fireEvent.click(screen.getByTestId("trigger"));

    const menu = screen.getByRole("menu");
    expect(menu).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Download" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Record actions")).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Show summaries" }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("closes on Escape", () => {
    setup();

    fireEvent.pointerDown(screen.getByTestId("trigger"));
    fireEvent.click(screen.getByTestId("trigger"));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("runs onSelect and closes when an item is chosen", () => {
    const onAction = vi.fn();
    setup({ onAction });

    fireEvent.pointerDown(screen.getByTestId("trigger"));
    fireEvent.click(screen.getByTestId("trigger"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Download" }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("does not run onSelect for a disabled item and keeps the menu open", () => {
    const onAction = vi.fn();
    setup({ onAction });

    fireEvent.pointerDown(screen.getByTestId("trigger"));
    fireEvent.click(screen.getByTestId("trigger"));
    const share = screen.getByRole("menuitem", { name: "Share" });
    expect(share).toHaveAttribute("data-disabled");

    fireEvent.click(share);
    expect(onAction).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("marks the trigger with state attributes for styling hooks", () => {
    setup();

    const trigger = screen.getByTestId("trigger");
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);
    expect(trigger.getAttribute("data-state")).toBe("open");
  });
});
