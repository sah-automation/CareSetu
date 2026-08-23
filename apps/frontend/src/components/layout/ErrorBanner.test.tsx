// PHASE-2.6 T08 (#199): suite for the page-scoped error banner (blueprint
// §9.1) - dismissible, Retry action, and a short trace id for support
// correlation (client-generated per instance unless the API supplied one).

import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

import { ErrorBanner } from "./ErrorBanner";

afterEach(() => {
  cleanup();
});

describe("ErrorBanner", () => {
  it("renders as an alert with the failure message", () => {
    render(<ErrorBanner message="Could not load your queue" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not load your queue",
    );
  });

  it("carries a short client-generated trace id for support correlation", () => {
    render(<ErrorBanner message="Failed" />);

    const trace = screen.getByTestId("error-banner-trace-id").textContent ?? "";
    expect(trace).toMatch(/^Trace: [a-z0-9]{8}$/);
  });

  it("prefers an API-provided trace id over the generated one", () => {
    render(<ErrorBanner message="Failed" traceId="api42id9" />);

    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "Trace: api42id9",
    );
  });

  it("offers Retry when a retry handler is given", () => {
    const onRetry = vi.fn();
    render(<ErrorBanner message="Failed" onRetry={onRetry} />);

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("is dismissible via its dismiss button", () => {
    const onDismiss = vi.fn();
    render(<ErrorBanner message="Failed" onDismiss={onDismiss} />);

    fireEvent.click(screen.getByTestId("error-banner-dismiss"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("omits the retry and dismiss affordances when no handlers are given", () => {
    render(<ErrorBanner message="Failed" />);

    expect(screen.queryByTestId("error-banner-retry")).toBeNull();
    expect(screen.queryByTestId("error-banner-dismiss")).toBeNull();
  });
});
