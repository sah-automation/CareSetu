import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";

import {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
} from "./sheet";

afterEach(() => {
  cleanup();
});

function ControlledSheet({
  onOpenChange,
}: {
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        onOpenChange?.(next);
      }}
    >
      <SheetTrigger data-testid="trigger">Open menu</SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Patient records</SheetTitle>
          <SheetDescription>Choose a record to review.</SheetDescription>
        </SheetHeader>
        <SheetFooter>
          <SheetClose data-testid="footer-close">Done</SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

describe("Sheet", () => {
  it("renders nothing but the trigger when closed", () => {
    render(<ControlledSheet />);

    expect(screen.getByTestId("trigger")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens via the trigger and shows title and description", async () => {
    render(<ControlledSheet />);

    fireEvent.click(screen.getByTestId("trigger"));

    await waitFor(() => {
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(dialog.getAttribute("data-state")).toBe("open");
    });
    expect(screen.getByText("Patient records")).toBeInTheDocument();
    expect(screen.getByText("Choose a record to review.")).toBeInTheDocument();
  });

  it("closes via the close button", async () => {
    const onOpenChange = vi.fn();
    render(<ControlledSheet onOpenChange={onOpenChange} />);

    fireEvent.click(screen.getByTestId("trigger"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("footer-close"));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("closes on Escape", async () => {
    render(<ControlledSheet />);

    fireEvent.click(screen.getByTestId("trigger"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("renders a labelled close affordance inside the content", async () => {
    render(<ControlledSheet />);

    fireEvent.click(screen.getByTestId("trigger"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    // The primitive ships an sr-only "Close" label on the X button.
    expect(screen.getByText("Close")).toHaveClass("sr-only");
  });
});
